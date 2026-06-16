"""Read-only Google Calendar agenda from a secret ICS feed.

Fetches the calendar's "secret address in iCal format" URL (no OAuth), expands
recurring events for the look-ahead window, and returns upcoming events with
ISO timestamps. The browser groups them into Today / Upcoming in local time, so
the server stays timezone-agnostic.
"""
import logging
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def _to_iso(value) -> str | None:
    """Normalise an icalendar date/datetime to an ISO string (UTC-aware)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value.isoformat()  # a date (all-day event)


def fetch_agenda() -> dict:
    """Return upcoming calendar events, or an error/unconfigured marker.

    Shape: {configured, events: [{summary, location, start, end, all_day}], error}.
    Never raises — failures surface in `error` so the dashboard keeps rendering.
    """
    if not config.CALENDAR_ICS_URL:
        return {"configured": False}

    result = {"configured": True, "events": [], "error": None}
    try:
        import icalendar
        import recurring_ical_events

        req = urllib.request.Request(config.CALENDAR_ICS_URL, headers={"User-Agent": "interests-dashboard"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            raw = resp.read()

        cal = icalendar.Calendar.from_ical(raw)
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=12)
        end = now + timedelta(days=config.AGENDA_DAYS)

        events = recurring_ical_events.of(cal).between(start, end)
        items = []
        for e in events:
            dtstart = e.get("DTSTART")
            if dtstart is None:
                continue
            dtstart = dtstart.dt
            dtend = e.get("DTEND")
            items.append({
                "summary": str(e.get("SUMMARY", "(no title)")),
                "location": (str(e.get("LOCATION")) or None) if e.get("LOCATION") else None,
                "start": _to_iso(dtstart),
                "end": _to_iso(dtend.dt) if dtend is not None else None,
                "all_day": not isinstance(dtstart, datetime),
            })

        items.sort(key=lambda x: x["start"] or "")
        result["events"] = items[: config.AGENDA_MAX]
    except Exception as exc:  # noqa: BLE001 - surface as data, not a 500
        log.exception("Agenda fetch failed")
        result["error"] = str(exc)

    return result
