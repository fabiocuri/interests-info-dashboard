"""Thin wrapper over the Anthropic SDK for the three personal-interest tasks.

Each task is a separate API call so we can:
  - enable the web_search tool only where it's needed (task 2),
  - give each task its own anti-repeat context, and
  - keep one failing task from blanking the others.
"""
import logging
from datetime import datetime, timedelta, timezone

import anthropic

from . import config

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
            "I'm an AI Engineer who wants to master many skills, tools, and "
            "frameworks across the AI engineering, DevOps, and software development "
            "world. Pick any one worthwhile technical topic from that universe and "
            "teach it to me concretely. Structure the answer with exactly these "
            "sections, each as a plain-text header on its own line:\n"
            "Title\nIntroduction\nProblem Statement\nTools Out There\nExample Scenario\n"
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
            "to find it, then answer in max 2 short paragraphs. No preamble."
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


def run_task(task: dict, prior_answers: list[str]) -> str:
    """Run one task and return its answer text. Raises on API failure."""
    client = _client()
    system = _anti_repeat_note(prior_answers) or None
    tools = [WEB_SEARCH_TOOL] if task["needs_web"] else None
    max_tokens = task.get("max_tokens", config.MAX_OUTPUT_TOKENS)

    prompt = task["prompt"]
    if "{yesterday}" in prompt:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%A, %B %d, %Y")
        prompt = prompt.format(yesterday=yesterday)

    messages = [{"role": "user", "content": prompt}]

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
        if resp.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": resp.content}]
            continue
        break

    return _extract_text(resp.content)


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
            entry["text"] = run_task(task, prior)
            entry["error"] = None
        except Exception as exc:  # noqa: BLE001 - keep other tasks alive
            log.exception("Task %s failed", task["key"])
            entry["text"] = ""
            entry["error"] = str(exc)
        results[task["key"]] = entry
    return results
