"""Spotify track lookup via the Client Credentials flow (no user login).

Used to turn a country's recommended artist + song into a Spotify track so the
dashboard can embed a player. Free, app-level auth; requires a Spotify app's
client id + secret. Never raises — returns None when unconfigured or on error.
"""
import base64
import json
import logging
import re
import time
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
_token_cache = {"token": None, "exp": 0.0}


def _get_token() -> str | None:
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        return None
    if _token_cache["token"] and time.time() < _token_cache["exp"] - 30:
        return _token_cache["token"]
    creds = base64.b64encode(
        f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Authorization": "Basic " + creds,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as r:
            tok = json.load(r)
        _token_cache["token"] = tok["access_token"]
        _token_cache["exp"] = time.time() + tok.get("expires_in", 3600)
        return _token_cache["token"]
    except Exception:  # noqa: BLE001
        log.exception("Spotify token request failed")
        return None


def _clean(s: str) -> str:
    """Drop bracketed/parenthetical noise (e.g. '[ver. 2.0]', '(Live)') and trim."""
    return re.sub(r"[\[(].*?[\])]", "", s or "").strip()


def _search(token: str, query: str) -> list:
    url = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode(
        {"q": query, "type": "track", "limit": 3}
    )
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as r:
            return json.load(r).get("tracks", {}).get("items", [])
    except Exception:  # noqa: BLE001
        log.exception("Spotify search failed for %r", query)
        return []


def _fmt(t: dict) -> dict:
    return {
        "id": t["id"],
        "url": t.get("external_urls", {}).get("spotify", ""),
        "name": t.get("name", ""),
        "artist": ", ".join(a["name"] for a in t.get("artists", [])),
    }


def find_track(artist: str, track: str) -> dict | None:
    """Find the recommended song on Spotify; return {id, url, name, artist} or None.

    Tries a precise field-filtered query first, then a looser one — but only
    accepts a loose hit if its artist matches, so we never embed a wrong song.
    """
    token = _get_token()
    if not token:
        return None
    track, artist = _clean(track), _clean(artist)
    if not track and not artist:
        return None

    a_lower = artist.lower()
    attempts = []
    if track and artist:
        attempts.append((f"track:{track} artist:{artist}", False))
        attempts.append((f"{track} {artist}", True))
    else:
        attempts.append((track or artist, True))

    for query, verify in attempts:
        for cand in _search(token, query):
            if verify and a_lower:
                names = " ".join(a["name"].lower() for a in cand.get("artists", []))
                if a_lower not in names:
                    continue
            return _fmt(cand)
    return None
