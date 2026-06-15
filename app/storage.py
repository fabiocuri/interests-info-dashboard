"""JSON-file persistence for run history.

A "run" is one refresh cycle holding the three task answers plus a timestamp.
Runs are stored newest-first and capped at MAX_RUNS.
"""
import json
import os
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _path() -> str:
    return os.path.join(config.DATA_DIR, "runs.json")


def _ensure_dir() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)


def load_runs() -> list[dict]:
    """Return all stored runs, newest first. Missing/corrupt file -> []."""
    with _lock:
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    return data if isinstance(data, list) else []


def add_run(answers: dict) -> dict:
    """Persist a new run built from `answers` and return it."""
    run = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
    }
    with _lock:
        _ensure_dir()
        try:
            with open(_path(), encoding="utf-8") as f:
                runs = json.load(f)
            if not isinstance(runs, list):
                runs = []
        except (FileNotFoundError, json.JSONDecodeError):
            runs = []

        runs.insert(0, run)
        runs = runs[: config.MAX_RUNS]

        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _path())  # atomic write

    return run
