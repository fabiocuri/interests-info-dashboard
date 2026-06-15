"""Thin wrapper over the Anthropic SDK for the three personal-interest tasks.

Each task is a separate API call so we can:
  - enable the web_search tool only where it's needed (task 2),
  - give each task its own anti-repeat context, and
  - keep one failing task from blanking the others.
"""
import logging

import anthropic

from . import config

log = logging.getLogger(__name__)

# Three tasks. `needs_web` flags the one that depends on live information.
TASKS = [
    {
        "key": "ai_engineer_tip",
        "title": "AI Engineer — something to know",
        "needs_web": False,
        "prompt": (
            "I am an AI Engineer. Tell me something that I should know as an AI "
            "Engineer. I want to be top talent in the field. Explain this shortly, "
            "with maximum 2 paragraphs."
        ),
    },
    {
        "key": "world_topic",
        "title": "Most spoken-about topic in the world right now",
        "needs_web": True,
        "prompt": (
            "Tell me what is the most spoken topic about in the world right now. "
            "Explain this shortly, with maximum 2 paragraphs."
        ),
    },
    {
        "key": "lebanese_arabic",
        "title": "Short conversation in Lebanese Arabic",
        "needs_web": False,
        "prompt": (
            "Tell me a short conversation in Lebanese Arabic, between two people. "
            "Max 10 lines of conversation. I want it written in the Arabic alphabet."
        ),
    },
]

# Server-side web search tool (dynamic filtering built in) — see claude-api skill.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


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

    messages = [{"role": "user", "content": task["prompt"]}]

    # Server-side tools run their own loop; on pause_turn we resume by re-sending.
    resp = None
    for _ in range(6):
        kwargs = {
            "model": config.MODEL,
            "max_tokens": 2000,
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
