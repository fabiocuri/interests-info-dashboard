"""FastAPI app: a single-page dashboard plus an on-demand refresh endpoint.

There is no background scheduler. A run happens only when POST /api/refresh is
called — the login/boot script triggers exactly one run per computer start, so
API cost is one batch of calls per boot and nothing while idle.
"""
import html
import logging
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.requests import Request

from . import calendar_client, claude_client, config, email_client, storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

# Section labels emitted by the AI deep-dive task; rendered as bold sub-heads.
_SUBHEADS = {"Title", "Introduction", "Problem Statement", "Tools Out There", "Example Scenario"}


def _article(text: str, rtl: bool = False) -> Markup:
    """Render answer text as clean HTML.

    - RTL (the Arabic dialogue): one turn per line, so every line break is kept.
    - Otherwise: group lines into <p> paragraphs (a blank line or a recognised
      section header starts a new block), so prose wraps naturally instead of
      breaking mid-sentence. Recognised section headers become bold sub-heads.
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
            para.append(html.escape(line))
    flush()
    return Markup("\n".join(blocks))


templates.env.filters["article"] = _article

# Tracks the most recent all-refresh so the UI can show status.
_state = {"running": False, "last_started": None, "last_error": None}

# Per-task refresh state: {task_key: {"running": bool, "error": str | None}}.
_tasks_state: dict[str, dict] = {t["key"]: {"running": False, "error": None} for t in claude_client.TASKS}

# Human labels for the spend breakdown (TASKS plus the ad-hoc globe lookups).
_TASK_LABELS = {t["key"]: t["title"] for t in claude_client.TASKS}
_TASK_LABELS["country_brief"] = "Globe explorer"


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


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    runs = storage.load_runs()
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
            "spend": storage.spend_summary(),
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


@app.get("/api/country")
def api_country(name: str, force: bool = False):
    """Globe explorer: interesting fact + music pick for a country.

    Results are cached on the PVC, so re-clicking a country is free; only the
    first lookup (or `?force=true`) calls Claude.
    """
    name = (name or "").strip()
    if not name:
        return JSONResponse({"error": "missing country name"}, status_code=400)
    if not force:
        cached = storage.get_country(name)
        if cached:
            return JSONResponse({"country": name, "cached": True, **cached})
    try:
        data = claude_client.country_brief(name)
    except Exception as exc:  # noqa: BLE001 - report as data
        return JSONResponse({"country": name, "error": str(exc)})
    storage.set_country(name, data)
    return JSONResponse({"country": name, "cached": False, **data})


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
