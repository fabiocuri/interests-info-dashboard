"""FastAPI app: a single-page dashboard plus an on-demand refresh endpoint.

There is no background scheduler. A run happens only when POST /api/refresh is
called — the login/boot script triggers exactly one run per computer start, so
API cost is one batch of calls per boot and nothing while idle.
"""
import logging
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import claude_client, storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

# Tracks the most recent refresh attempt so the UI can show status.
_state = {"running": False, "last_started": None, "last_error": None}


def refresh() -> None:
    """Run all three tasks and persist a new run."""
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
        },
    )


@app.get("/api/runs")
def api_runs():
    return JSONResponse(storage.load_runs())


@app.post("/api/refresh")
def api_refresh():
    """Trigger a refresh now (runs in a background thread, returns immediately)."""
    if _state["running"]:
        return JSONResponse({"status": "already_running"}, status_code=409)
    threading.Thread(target=refresh, daemon=True).start()
    return JSONResponse({"status": "started"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "running": _state["running"]}
