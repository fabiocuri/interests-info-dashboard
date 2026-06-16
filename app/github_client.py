"""Read-only GitHub panel via the REST API.

Shows pull requests awaiting your review, your own open PRs, and the unread
notification count. Token-authenticated; never raises (errors surface as data).
"""
import json
import logging
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
_API = "https://api.github.com"


def _get(path: str):
    req = urllib.request.Request(
        _API + path,
        headers={
            "Authorization": "Bearer " + config.GITHUB_TOKEN,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "interests-dashboard",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as r:
        return json.load(r)


def _login() -> str:
    if config.GITHUB_LOGIN:
        return config.GITHUB_LOGIN
    return _get("/user").get("login", "")


def _pr_item(it: dict) -> dict:
    repo_url = it.get("repository_url", "")
    repo = "/".join(repo_url.split("/")[-2:]) if repo_url else ""
    return {
        "repo": repo,
        "title": it.get("title", ""),
        "number": it.get("number"),
        "url": it.get("html_url", ""),
        "updated": it.get("updated_at", ""),
        "draft": bool(it.get("draft", False)),
    }


def _search_prs(query: str) -> list:
    path = "/search/issues?per_page=10&q=" + urllib.parse.quote(query)
    return [_pr_item(i) for i in _get(path).get("items", [])]


def fetch_github() -> dict:
    """Return {configured, login, review_requests, my_prs, notifications, error}."""
    if not config.GITHUB_TOKEN:
        return {"configured": False}

    result = {
        "configured": True,
        "login": "",
        "review_requests": [],
        "my_prs": [],
        "notifications": 0,
        "error": None,
    }
    try:
        login = _login()
        result["login"] = login
        result["review_requests"] = _search_prs(f"is:open is:pr review-requested:{login}")
        result["my_prs"] = _search_prs(f"is:open is:pr author:{login}")
        try:
            notif = _get("/notifications")  # unread only, by default
            result["notifications"] = len(notif) if isinstance(notif, list) else 0
        except Exception:  # noqa: BLE001 - notifications are best-effort
            log.exception("GitHub notifications fetch failed")
    except Exception as exc:  # noqa: BLE001 - surface as data, not a 500
        log.exception("GitHub fetch failed")
        result["error"] = str(exc)
    return result
