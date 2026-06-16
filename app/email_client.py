"""Read-only Gmail inbox access over IMAP.

Uses the standard library only (imaplib + email). Credentials come from the
environment (a Gmail address + an app password), supplied via the k8s Secret.
The inbox is opened read-only so viewing it never marks mail as read, and a
short socket timeout keeps a slow/unreachable server from hanging the page.
"""
import email
import imaplib
import logging
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from . import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10


def _decode(value: str | None) -> str:
    """Decode an RFC 2047 encoded header (e.g. =?UTF-8?...?=) to plain text."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # noqa: BLE001 - never let a bad header break the inbox
        return value.strip()


def _parse_message(prefix: bytes, raw_headers: bytes) -> dict:
    msg = email.message_from_bytes(raw_headers)
    name, addr = parseaddr(_decode(msg.get("From")))

    date_iso = None
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        if dt is not None:
            date_iso = dt.isoformat()
    except (TypeError, ValueError):
        pass

    flags = imaplib.ParseFlags(prefix)
    unread = b"\\Seen" not in flags

    return {
        "from_name": name or addr,
        "from_email": addr,
        "subject": _decode(msg.get("Subject")) or "(no subject)",
        "date_iso": date_iso,
        "unread": unread,
    }


def fetch_inbox() -> dict:
    """Return a snapshot of the inbox, or an error/unconfigured marker.

    Shape: {configured, address, total, unread, messages: [...], error}.
    Never raises — failures are reported in the `error` field so the rest of
    the dashboard keeps rendering.
    """
    if not config.GMAIL_ADDRESS or not config.GMAIL_APP_PASSWORD:
        return {"configured": False}

    result = {
        "configured": True,
        "address": config.GMAIL_ADDRESS,
        "total": 0,
        "unread": 0,
        "messages": [],
        "error": None,
    }

    imap = None
    try:
        imap = imaplib.IMAP4_SSL(config.IMAP_HOST, timeout=_TIMEOUT_SECONDS)
        imap.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        imap.select("INBOX", readonly=True)

        _, all_data = imap.search(None, "ALL")
        ids = all_data[0].split()
        result["total"] = len(ids)

        _, unseen_data = imap.search(None, "UNSEEN")
        result["unread"] = len(unseen_data[0].split())

        # Newest mail has the highest sequence number; take the last N, newest first.
        latest = list(reversed(ids[-config.INBOX_FETCH_COUNT:]))
        for num in latest:
            _, msg_data = imap.fetch(num, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            prefix, raw_headers = msg_data[0]
            result["messages"].append(_parse_message(prefix, raw_headers))
    except Exception as exc:  # noqa: BLE001 - surface as data, not a 500
        log.exception("Inbox fetch failed")
        result["error"] = str(exc)
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:  # noqa: BLE001
                pass

    return result
