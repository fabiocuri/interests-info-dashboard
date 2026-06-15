"""FastAPI app: scheduler that refreshes answers + a single-page dashboard."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import claude_client, config, storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

# Tracks the most recent refresh attempt so the UI can show status.
_state = {"running": False, "last_started": None, "last_error": None}


def refresh() -> None:
    """Run all three tasks and persist a new run. Safe to call from scheduler."""
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler(timezone="UTC")
    # Run on startup (only if we have no data yet) + every REFRESH_HOURS.
    if not storage.load_runs():
        scheduler.add_job(refresh, next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(
        refresh,
        "interval",
        hours=config.REFRESH_HOURS,
        id="refresh",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    log.info("Scheduler started (every %s h)", config.REFRESH_HOURS)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Interests Info Dashboard", lifespan=lifespan)


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
            "refresh_hours": config.REFRESH_HOURS,
            "page_refresh": config.PAGE_REFRESH_SECONDS,
        },
    )


@app.get("/api/runs")
def api_runs():
    return JSONResponse(storage.load_runs())


@app.post("/api/refresh")
def api_refresh():
    """Trigger a refresh now (runs in the background scheduler thread)."""
    if _state["running"]:
        return JSONResponse({"status": "already_running"}, status_code=409)
    # Run inline in a thread so the request returns immediately.
    import threading

    threading.Thread(target=refresh, daemon=True).start()
    return JSONResponse({"status": "started"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "running": _state["running"]}
