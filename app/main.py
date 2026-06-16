"""FastAPI app: a single-page dashboard plus an on-demand refresh endpoint.

There is no background scheduler. A run happens only when POST /api/refresh is
called — the login/boot script triggers exactly one run per computer start, so
API cost is one batch of calls per boot and nothing while idle.
"""
import html
import logging
import re
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.requests import Request

from . import calendar_client, claude_client, config, email_client, spotify_client, storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

# Section labels emitted by the engineering task; rendered as bold sub-heads.
_SUBHEADS = {"Example Scenario", "Tools Out There"}

# Markdown links [text](url) and bare http(s) URLs, for making links clickable.
_MD_OR_URL = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)]+)\)"
    r"|(https?://[^\s<>()]+[^\s<>().,;:!?'\"])"
)


def _linkify(text: str) -> str:
    """HTML-escape a line and turn markdown/bare links into clickable anchors."""
    out: list[str] = []
    i = 0
    for m in _MD_OR_URL.finditer(text):
        out.append(html.escape(text[i:m.start()]))
        if m.group(2):  # [label](url)
            href = html.escape(m.group(2), quote=True)
            out.append(f'<a href="{href}" target="_blank" rel="noopener">{html.escape(m.group(1))}</a>')
        else:  # bare url
            url = m.group(3)
            href = html.escape(url, quote=True)
            out.append(f'<a href="{href}" target="_blank" rel="noopener">{html.escape(url)}</a>')
        i = m.end()
    out.append(html.escape(text[i:]))
    return "".join(out)


def _article(text: str, rtl: bool = False) -> Markup:
    """Render answer text as clean HTML.

    - RTL (the Arabic dialogue): one turn per line, so every line break is kept.
    - Otherwise: group lines into <p> paragraphs (a blank line or a recognised
      section header starts a new block), so prose wraps naturally instead of
      breaking mid-sentence. Section headers become bold sub-heads, and any
      links in the body are made clickable.
    """
    text = text or ""
    if rtl:
        return Markup("<br>".join(html.escape(line) for line in text.split("\n")))

    blocks: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            flush()
        elif line in _SUBHEADS:
            flush()
            blocks.append(f'<strong class="subhead">{html.escape(line)}</strong>')
        else:
            para.append(_linkify(line))
    flush()
    return Markup("\n".join(blocks))


templates.env.filters["article"] = _article

# Tracks the most recent all-refresh so the UI can show status.
_state = {"running": False, "last_started": None, "last_error": None}

# Per-task refresh state: {task_key: {"running": bool, "error": str | None}}.
_tasks_state: dict[str, dict] = {t["key"]: {"running": False, "error": None} for t in claude_client.TASKS}

# Human labels for the spend breakdown (TASKS plus the ad-hoc globe lookups).
_TASK_LABELS = {t["key"]: t["title"] for t in claude_client.TASKS}
_TASK_LABELS["country_brief"] = "Globe explorer"  # legacy records
_TASK_LABELS["country_fact"] = "Map · fact"
_TASK_LABELS["country_music"] = "Map · music"


def refresh() -> None:
    """Run all three tasks and persist a new run (a fresh edition)."""
    if _state["running"]:
        log.info("Refresh already in progress; skipping")
        return
    _state["running"] = True
    _state["last_started"] = datetime.now(timezone.utc).isoformat()
    _state["last_error"] = None
    try:
        history = storage.load_runs()
        answers = claude_client.run_all_tasks(history)
        storage.add_run(answers)
        log.info("Refresh complete")
    except Exception as exc:  # noqa: BLE001
        log.exception("Refresh failed")
        _state["last_error"] = str(exc)
    finally:
        _state["running"] = False


def refresh_task(task_key: str) -> None:
    """Regenerate a single task and amend it into the current edition."""
    st = _tasks_state[task_key]
    if st["running"]:
        log.info("Task %s refresh already in progress; skipping", task_key)
        return
    st["running"] = True
    st["error"] = None
    try:
        history = storage.load_runs()
        entry = claude_client.run_single_task(task_key, history)
        storage.update_answer(task_key, entry)
        log.info("Task %s refresh complete", task_key)
    except Exception as exc:  # noqa: BLE001
        log.exception("Task %s refresh failed", task_key)
        st["error"] = str(exc)
    finally:
        st["running"] = False


def _any_running() -> bool:
    return _state["running"] or any(s["running"] for s in _tasks_state.values())


app = FastAPI(title="Interests Info Dashboard")


def _balance(spend: dict) -> dict | None:
    """Build the manual-balance figure: entered balance minus tracked spend."""
    if not config.CLAUDE_API_BALANCE:
        return None
    try:
        entered = float(config.CLAUDE_API_BALANCE)
    except ValueError:
        return None
    return {
        "entered": entered,
        "remaining": entered - spend["all"]["cost"],
        "tracked": spend["all"]["cost"],
        "currency": spend["currency"],
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    runs = storage.load_runs()
    spend = storage.spend_summary()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "runs": runs,
            "tasks": claude_client.TASKS,
            "state": _state,
            "tasks_state": _tasks_state,
            "email_configured": bool(config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD),
            "agenda_configured": bool(config.CALENDAR_ICS_URL),
            "spend": spend,
            "balance": _balance(spend),
            "task_labels": _TASK_LABELS,
        },
    )


@app.get("/api/runs")
def api_runs():
    return JSONResponse(storage.load_runs())


@app.get("/api/inbox")
def api_inbox():
    """Live, read-only Gmail inbox snapshot. Fetched client-side so it never
    blocks page render and a mail outage can't take the dashboard down."""
    return JSONResponse(email_client.fetch_inbox())


@app.get("/api/agenda")
def api_agenda():
    """Upcoming calendar events from the secret ICS feed. Fetched client-side
    (free, no Claude) so a calendar outage can't take the dashboard down."""
    return JSONResponse(calendar_client.fetch_agenda())


@app.get("/api/country/fact")
def api_country_fact(name: str):
    """One interesting fact about a country. Fresh each call (anti-repeat)."""
    name = (name or "").strip()
    if not name:
        return JSONResponse({"error": "missing country name"}, status_code=400)
    prior = [e.get("fact", "") for e in storage.fact_history(name)]
    try:
        data = claude_client.country_fact(name, prior)
    except Exception as exc:  # noqa: BLE001 - report as data
        return JSONResponse({"country": name, "error": str(exc)})
    storage.add_fact(name, data["fact"])
    return JSONResponse({"country": name, **data})


@app.get("/api/country/music")
def api_country_music(name: str, decade: str = "Nowadays"):
    """An era-scoped music pick (+ Spotify track) for a country. Fresh each call."""
    name = (name or "").strip()
    if not name:
        return JSONResponse({"error": "missing country name"}, status_code=400)
    prior = storage.country_history(name, decade)
    try:
        data = claude_client.country_music(name, decade, prior)
    except Exception as exc:  # noqa: BLE001 - report as data
        return JSONResponse({"country": name, "decade": decade, "error": str(exc)})
    data["spotify"] = spotify_client.find_track(data.get("artist", ""), data.get("track", ""))
    storage.add_country_history(name, decade, data)
    return JSONResponse({"country": name, "decade": decade, **data})


@app.post("/api/refresh")
def api_refresh():
    """Refresh all three tasks now (background thread, returns immediately)."""
    if _state["running"]:
        return JSONResponse({"status": "already_running"}, status_code=409)
    threading.Thread(target=refresh, daemon=True).start()
    return JSONResponse({"status": "started"})


@app.post("/api/refresh/{task_key}")
def api_refresh_task(task_key: str):
    """Refresh a single task (background thread, returns immediately)."""
    if task_key not in _tasks_state:
        return JSONResponse({"status": "unknown_task"}, status_code=404)
    if _tasks_state[task_key]["running"]:
        return JSONResponse({"status": "already_running"}, status_code=409)
    threading.Thread(target=refresh_task, args=(task_key,), daemon=True).start()
    return JSONResponse({"status": "started"})


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "running": _any_running(),
        "tasks": {k: v["running"] for k, v in _tasks_state.items()},
    }
