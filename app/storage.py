"""JSON-file persistence for run history.

A "run" is one refresh cycle holding the three task answers plus a timestamp.
Runs are stored newest-first and capped at MAX_RUNS.
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

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
        _write(runs)

    return run


def update_answer(task_key: str, entry: dict) -> dict:
    """Patch a single task's answer in the latest run (amend the current edition).

    Stamps the answer with its own `updated` time. If there are no runs yet, a
    new run is created holding just this one answer. Used by per-section refresh.
    """
    entry = {**entry, "updated": datetime.now(timezone.utc).isoformat()}
    with _lock:
        _ensure_dir()
        try:
            with open(_path(), encoding="utf-8") as f:
                runs = json.load(f)
            if not isinstance(runs, list):
                runs = []
        except (FileNotFoundError, json.JSONDecodeError):
            runs = []

        if runs:
            runs[0].setdefault("answers", {})[task_key] = entry
        else:
            runs = [{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "answers": {task_key: entry},
            }]
        _write(runs)

    return runs[0]


def _write(runs: list[dict]) -> None:
    """Atomically write the run list. Caller must hold the lock."""
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(runs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path())


# ── API spend tracking ──────────────────────────────────────────────────────

_spend_lock = threading.Lock()


def _spend_path() -> str:
    return os.path.join(config.DATA_DIR, "spend.json")


def record_spend(task_key: str, usage: dict) -> None:
    """Append one Claude-call usage record (tokens + web searches)."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": config.MODEL,
        "task": task_key,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "web_searches": usage.get("web_searches", 0),
    }
    with _spend_lock:
        _ensure_dir()
        try:
            with open(_spend_path(), encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                records = []
        except (FileNotFoundError, json.JSONDecodeError):
            records = []

        records.append(record)
        records = records[-config.MAX_SPEND_RECORDS:]

        tmp = _spend_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _spend_path())


def _cost(rec: dict) -> float:
    """Estimated USD cost of one usage record at the configured prices."""
    return (
        rec.get("input_tokens", 0) / 1_000_000 * config.PRICE_INPUT_PER_MTOK
        + rec.get("output_tokens", 0) / 1_000_000 * config.PRICE_OUTPUT_PER_MTOK
        + rec.get("web_searches", 0) / 1_000 * config.PRICE_WEB_SEARCH_PER_1K
    )


def spend_summary() -> dict:
    """Aggregate recorded spend into today / 7-day / month / all-time windows."""
    with _spend_lock:
        try:
            with open(_spend_path(), encoding="utf-8") as f:
                records = json.load(f)
            if not isinstance(records, list):
                records = []
        except (FileNotFoundError, json.JSONDecodeError):
            records = []

    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    windows = {
        "today": {"cost": 0.0, "calls": 0},
        "week": {"cost": 0.0, "calls": 0},
        "month": {"cost": 0.0, "calls": 0},
        "all": {"cost": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "web_searches": 0},
    }
    by_task: dict[str, dict] = {}
    for rec in records:
        try:
            ts = datetime.fromisoformat(rec["timestamp"])
        except (KeyError, ValueError):
            continue
        c = _cost(rec)
        a = windows["all"]
        a["cost"] += c
        a["calls"] += 1
        a["input_tokens"] += rec.get("input_tokens", 0)
        a["output_tokens"] += rec.get("output_tokens", 0)
        a["web_searches"] += rec.get("web_searches", 0)
        if ts >= midnight:
            windows["today"]["cost"] += c
            windows["today"]["calls"] += 1
        if ts >= week_ago:
            windows["week"]["cost"] += c
            windows["week"]["calls"] += 1
        if ts >= month_start:
            windows["month"]["cost"] += c
            windows["month"]["calls"] += 1

        t = by_task.setdefault(
            rec.get("task", "?"),
            {"cost": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0},
        )
        t["cost"] += c
        t["calls"] += 1
        t["input_tokens"] += rec.get("input_tokens", 0)
        t["output_tokens"] += rec.get("output_tokens", 0)

    # Largest cost first, so the card reads like a "what's driving spend" list.
    windows["by_task"] = dict(sorted(by_task.items(), key=lambda kv: kv[1]["cost"], reverse=True))
    windows["currency"] = config.CURRENCY_SYMBOL
    return windows


# ── Country music history (globe explorer) ──────────────────────────────────
# Keyed by "country|era" → list of past {artist, track} suggestions. Used as
# anti-repeat context so each click yields a new recommendation (not a cache).

_country_lock = threading.Lock()
_HISTORY_KEEP = 12


def _country_path() -> str:
    return os.path.join(config.DATA_DIR, "countries.json")


def _load_countries() -> dict:
    try:
        with open(_country_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _country_key(name: str, era: str) -> str:
    return f"{name.strip().lower()}|{era.strip().lower()}"


def country_history(name: str, era: str) -> list[dict]:
    """Recent past suggestions for this country+era (for anti-repeat)."""
    with _country_lock:
        value = _load_countries().get(_country_key(name, era))
        return list(value) if isinstance(value, list) else []


def add_country_history(name: str, era: str, entry: dict) -> None:
    """Append a suggestion to this country+era's history (capped)."""
    with _country_lock:
        _ensure_dir()
        countries = _load_countries()
        key = _country_key(name, era)
        history = countries.get(key)
        if not isinstance(history, list):
            history = []
        history.append({
            "artist": entry.get("artist", ""),
            "track": entry.get("track", ""),
            "updated": datetime.now(timezone.utc).isoformat(),
        })
        countries[key] = history[-_HISTORY_KEEP:]
        tmp = _country_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(countries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _country_path())
