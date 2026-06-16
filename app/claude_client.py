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
        "title": "Engineering — learn a tool",
        "kicker": "Engineering",
        "needs_web": False,
        "max_tokens": 1200,
        "prompt": (
            "I'm a software / AI engineer who wants to get broadly strong across "
            "technical engineering. Teach me ONE concrete, specific, named tool, "
            "technology, protocol, or concept I can add to my toolbox. Rotate widely "
            "across these domains and pick something different each time: networking "
            "and firewalls, Linux and security (TLS, certificates, auth, secrets), "
            "DevOps and CI/CD, infrastructure-as-code, observability and logging, "
            "containers and Kubernetes, databases and caching, message queues, and web "
            "protocols. Do NOT pick GPU / CUDA / NVIDIA or hardware topics — strongly "
            "favor security, networking, and DevOps. Keep it brief and practical. Use "
            "exactly these two sections, each as a plain-text header on its own line:\n"
            "Example Scenario\nTools Out There\n"
            "Under 'Example Scenario': a short, concrete real-world situation in 3-5 "
            "sentences that motivates the topic. Under 'Tools Out There': list 3-5 "
            "specific real tools or standards; write EACH as its own short paragraph "
            "separated by a blank line, starting with the tool name, then one line on "
            "what it does, then a real https:// homepage or docs link. Always include a "
            "working link for every tool. Begin with the 'Example Scenario' line and do "
            "not restate or mention these instructions."
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


def _parse_json_obj(text: str) -> dict:
    """Parse a JSON object from the model reply, tolerating code fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = re.sub(r"^json", "", t.strip(), flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}


def _one_call(prompt: str, task_key: str, max_tokens: int = 500) -> dict:
    """Single Claude call returning a parsed JSON object; records spend."""
    client = _client()
    resp = client.messages.create(
        model=config.MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = {"input_tokens": 0, "output_tokens": 0, "web_searches": 0}
    _accumulate_usage(usage, resp)
    storage.record_spend(task_key, usage)
    return _parse_json_obj(_extract_text(resp.content))


def country_fact(country: str, prior: list[str] | None = None) -> dict:
    """One interesting fact about a country. `prior` facts are avoided. Returns {fact}."""
    prior = prior or []
    avoid = ""
    seen = " | ".join(p for p in prior if p)
    if seen:
        avoid = (
            " Do NOT repeat any of these facts you already gave — give a genuinely "
            f"different one: {seen}."
        )
    prompt = (
        f"Give ONE genuinely interesting, lesser-known fact about {country} in 2-3 "
        'sentences. Respond with ONLY a JSON object (no markdown) with one string key '
        '"fact".' + avoid
    )
    obj = _one_call(prompt, "country_fact")
    return {"fact": str(obj.get("fact", "")).strip()}


def country_music(country: str, era: str = "Nowadays", prior: list[dict] | None = None) -> dict:
    """A music pick from a country, scoped to `era`. Prior picks are avoided.

    Returns {music, artist, track}; artist/track feed the Spotify lookup.
    """
    prior = prior or []
    if era.strip().lower().startswith("now"):
        era_phrase = "the last few years (current / recent music)"
    else:
        era_phrase = f"the {era.strip()}"

    avoid = ""
    seen = "; ".join(
        f"{p.get('artist', '')} - {p.get('track', '')}".strip(" -")
        for p in prior
        if p.get("artist") or p.get("track")
    )
    if seen:
        avoid = (
            " You already suggested these — do NOT repeat them, pick a genuinely "
            f"different artist and song: {seen}."
        )
    prompt = (
        f"Recommend one piece of music from {country} from {era_phrase}. Respond with "
        'ONLY a JSON object (no markdown) with string keys "music", "artist", "track". '
        '"music": name the artist and a specific song from that era, then one short '
        "sentence on why it captures the country's sound then. \"artist\": artist/band "
        f'name only. "track": song title only (a real, findable song from {era_phrase}).'
        + avoid
    )
    obj = _one_call(prompt, "country_music")
    return {
        "music": str(obj.get("music", "")).strip(),
        "artist": str(obj.get("artist", "")).strip(),
        "track": str(obj.get("track", "")).strip(),
    }


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
