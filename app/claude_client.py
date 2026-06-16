"""Thin wrapper over the Anthropic SDK for the three personal-interest tasks.

Each task is a separate API call so we can:
  - enable the web_search tool only where it's needed (task 2),
  - give each task its own anti-repeat context, and
  - keep one failing task from blanking the others.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import anthropic

from . import config, storage

log = logging.getLogger(__name__)

# Three tasks. `needs_web` flags the one that depends on live information.
TASKS = [
    {
        "key": "ai_engineer_tip",
        "title": "AI Engineer — technical deep-dive",
        "kicker": "Engineering",
        "needs_web": False,
        "max_tokens": 2000,
        "prompt": (
            "I'm an AI engineer and DevOps engineer. I work daily with "
            "infrastructure-as-code, performance optimization, monitoring and "
            "observability, GPUs, networking, security, and AI systems. Teach me ONE "
            "concrete, specific, named tool, technology, protocol, or building block "
            "from that world that I can add to my toolbox — not an abstract theme. "
            "Favor concrete 'what is X and how does it work' things, for example: what "
            "an SMTP server is, what a firewall is and the types of firewalls, how a "
            "GPU executes work (CUDA cores, VRAM, kernels), what an MCP server is, what "
            "a reverse proxy is, Terraform state and locking, Prometheus and metrics "
            "scraping, eBPF, what a load balancer does, DNS resolution, OAuth flows. "
            "Pick a different one each time and explain it concretely and practically, "
            "with real numbers, commands, or config where useful. Structure the answer "
            "with exactly these sections, each as a plain-text header on its own line:\n"
            "Title\nIntroduction\nProblem Statement\nTools Out There\nExample Scenario\n"
            "Under 'Tools Out There' name the real tools, standards, and vendors. "
            "Write at most 10 paragraphs in total. Begin with the Title line and stop "
            "after the Example Scenario. Do not restate or mention these instructions."
        ),
    },
    {
        "key": "world_topic",
        "title": "Most talked-about event yesterday",
        "kicker": "World",
        "needs_web": True,
        "prompt": (
            "Today is the day after {yesterday}. Summarise the single most "
            "talked-about news event in the world from {yesterday}. Do a web search "
            "to find it, then answer in one or two short paragraphs of flowing prose. "
            "Separate paragraphs with a single blank line. Do NOT insert line breaks "
            "within a paragraph and do not use bullet points or headings. No preamble."
        ),
    },
    {
        "key": "lebanese_arabic",
        "title": "Short conversation in Lebanese Arabic",
        "kicker": "Language",
        "needs_web": False,
        "prompt": (
            "Write a short conversation in Lebanese Arabic between two people, in the "
            "Arabic alphabet. Max 10 lines. Output only the dialogue, no preamble."
        ),
    },
]

TASKS_BY_KEY = {t["key"]: t for t in TASKS}

# Older web-search tool version (works on Haiku); capped to bound search cost.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": config.WEB_SEARCH_MAX_USES,
}


def _client() -> anthropic.Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _extract_text(content) -> str:
    return "\n".join(b.text for b in content if b.type == "text").strip()


def _anti_repeat_note(prior_answers: list[str]) -> str:
    """Build a system note asking Claude to avoid repeating recent answers."""
    prior = [a for a in prior_answers if a]
    if not prior:
        return ""
    bullets = "\n\n".join(f"--- Previous answer {i + 1} ---\n{a}" for i, a in enumerate(prior))
    return (
        "Here are your most recent answers to this same question. "
        "Give a genuinely fresh, different response — do not repeat these themes, "
        "examples, or phrasing:\n\n" + bullets
    )


def _accumulate_usage(usage: dict, resp) -> None:
    """Add one API response's token/search usage into the running tally."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
    usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0
    stu = getattr(u, "server_tool_use", None)
    if stu is not None:
        usage["web_searches"] += getattr(stu, "web_search_requests", 0) or 0


def run_task(task: dict, prior_answers: list[str]) -> tuple[str, dict]:
    """Run one task. Returns (answer_text, usage). Raises on API failure.

    `usage` totals input/output tokens and web searches across every API call
    made for this task (including web-search pause_turn continuations).
    """
    client = _client()
    system = _anti_repeat_note(prior_answers) or None
    tools = [WEB_SEARCH_TOOL] if task["needs_web"] else None
    max_tokens = task.get("max_tokens", config.MAX_OUTPUT_TOKENS)

    prompt = task["prompt"]
    if "{yesterday}" in prompt:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%A, %B %d, %Y")
        prompt = prompt.format(yesterday=yesterday)

    messages = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "web_searches": 0}

    # Server-side tools run their own loop; on pause_turn we resume by re-sending.
    resp = None
    for _ in range(6):
        kwargs = {
            "model": config.MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        resp = client.messages.create(**kwargs)
        _accumulate_usage(usage, resp)
        if resp.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": resp.content}]
            continue
        break

    return _extract_text(resp.content), usage


def run_single_task(task_key: str, history: list[dict]) -> dict:
    """Run one task by key and return its answer entry. Raises on API failure.

    `history` is recent runs (newest first) used for anti-repeat context.
    """
    task = TASKS_BY_KEY[task_key]
    prior = [
        run.get("answers", {}).get(task_key, {}).get("text", "")
        for run in history[: config.HISTORY_FEEDBACK]
    ]
    text, usage = run_task(task, prior)
    storage.record_spend(task_key, usage)
    return {
        "title": task["title"],
        "rtl": task_key == "lebanese_arabic",
        "text": text,
        "error": None,
    }


def _parse_country_json(text: str) -> dict:
    """Parse the model's country reply into {fact, music}, tolerating fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = re.sub(r"^json", "", t.strip(), flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(t)
        return {"fact": str(obj.get("fact", "")).strip(), "music": str(obj.get("music", "")).strip()}
    except (ValueError, AttributeError):
        return {"fact": text.strip(), "music": ""}


def country_brief(country: str) -> dict:
    """Ask Claude for an interesting fact + a music recommendation for a country.

    Returns {fact, music}. Records its own spend under the "country_brief" task.
    """
    client = _client()
    prompt = (
        f"For the country {country}, respond with ONLY a JSON object (no markdown, no "
        f'code fences) with exactly two string keys: "fact" and "music". '
        f'"fact": one genuinely interesting, lesser-known fact about {country}, in 2-3 '
        f'sentences. "music": one musical recommendation from {country} — name a specific '
        f"artist and a specific song or album, then one short sentence on why it represents "
        f"the country's sound."
    )
    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"input_tokens": 0, "output_tokens": 0, "web_searches": 0}
    _accumulate_usage(usage, resp)
    storage.record_spend("country_brief", usage)
    return _parse_country_json(_extract_text(resp.content))


def run_all_tasks(history: list[dict]) -> dict:
    """Run all three tasks. Returns {task_key: {title, text, error}}.

    `history` is the recent runs (newest first) used for anti-repeat context.
    """
    results: dict[str, dict] = {}
    for task in TASKS:
        prior = [
            run.get("answers", {}).get(task["key"], {}).get("text", "")
            for run in history[: config.HISTORY_FEEDBACK]
        ]
        entry = {"title": task["title"], "rtl": task["key"] == "lebanese_arabic"}
        try:
            text, usage = run_task(task, prior)
            storage.record_spend(task["key"], usage)
            entry["text"] = text
            entry["error"] = None
        except Exception as exc:  # noqa: BLE001 - keep other tasks alive
            log.exception("Task %s failed", task["key"])
            entry["text"] = ""
            entry["error"] = str(exc)
        results[task["key"]] = entry
    return results
