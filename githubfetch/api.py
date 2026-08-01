"""GitHub REST API access: auth, retries, rate limiting and pagination."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__

API_ROOT = "https://api.github.com"
USER_AGENT = f"githubfetch/{__version__}"

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 15.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_REPO_PAGES = 10  # 10 x 100 repos is plenty and bounds a hostile response
MAX_AVATAR_BYTES = 8 * 1024 * 1024

TOKEN_ENV_VARS = ("GITHUB_TOKEN", "GH_TOKEN")

_TOKEN_PATTERN = re.compile(
    r"\b(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b"
)


class GitHubError(RuntimeError):
    """A user-facing failure while talking to the GitHub API."""


class RateLimitError(GitHubError):
    """The request was rejected because the rate limit is exhausted."""


def get_token() -> str | None:
    """Read a token from the environment only.

    Never accepted as a CLI argument: argv is world-readable in the process
    list on most systems.
    """
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def redact(text: object, token: str | None = None) -> str:
    """Strip any token material out of *text* before it is shown to a user."""
    out = str(text)
    if token:
        out = out.replace(token, "***REDACTED***")
    out = _TOKEN_PATTERN.sub("***REDACTED***", out)
    # Never echo an Authorization header value back to the terminal.
    out = re.sub(
        r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(bearer|token)?\s*\S+",
        r"\1***REDACTED***",
        out,
    )
    return out


def build_session(token: str | None = None, retries: int = 3) -> requests.Session:
    """A session with sane headers and exponential backoff on transient errors."""
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
    )
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _reset_in_words(reset_epoch: str | None) -> str:
    if not reset_epoch:
        return "unknown time"
    try:
        reset_at = datetime.fromtimestamp(int(reset_epoch), tz=timezone.utc)
    except (TypeError, ValueError):
        return "unknown time"
    seconds = max(0, int(reset_at.timestamp() - time.time()))
    minutes, secs = divmod(seconds, 60)
    local = reset_at.astimezone()
    when = local.strftime("%H:%M:%S")
    if minutes:
        return f"{minutes}m {secs}s (at {when})"
    return f"{secs}s (at {when})"


def _check_rate_limit(resp: requests.Response, authenticated: bool) -> None:
    """Raise :class:`RateLimitError` when GitHub says we are out of quota."""
    if resp.status_code not in (403, 429):
        return

    remaining = resp.headers.get("X-RateLimit-Remaining")
    retry_after = resp.headers.get("Retry-After")
    is_limited = remaining == "0" or resp.status_code == 429 or retry_after is not None
    if not is_limited:
        return

    limit = resp.headers.get("X-RateLimit-Limit", "?")
    if retry_after:
        wait = f"{retry_after}s (Retry-After)"
    else:
        wait = _reset_in_words(resp.headers.get("X-RateLimit-Reset"))

    hint = (
        ""
        if authenticated
        else "\nSet GITHUB_TOKEN to raise the limit from 60 to 5,000 requests/hour."
    )
    raise RateLimitError(
        f"GitHub rate limit reached (limit {limit}/hour). Try again in {wait}.{hint}"
    )


def _get(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    authenticated: bool = False,
) -> requests.Response:
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT)
    except requests.exceptions.Timeout as exc:
        raise GitHubError(f"Request timed out: {redact(exc)}") from exc
    except requests.exceptions.SSLError as exc:
        raise GitHubError(f"TLS verification failed: {redact(exc)}") from exc
    except requests.exceptions.RequestException as exc:
        raise GitHubError(f"Network error: {redact(exc)}") from exc

    _check_rate_limit(resp, authenticated)
    return resp


def _next_link(resp: requests.Response) -> str | None:
    """Parse the ``Link`` header and return the ``rel="next"`` URL, if any."""
    link = resp.headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        segments = part.split(";")
        if len(segments) < 2:
            continue
        url = segments[0].strip()
        if not (url.startswith("<") and url.endswith(">")):
            continue
        for attr in segments[1:]:
            key, _, value = attr.strip().partition("=")
            if key.strip().lower() == "rel" and value.strip(" \"'") == "next":
                candidate = url[1:-1]
                if candidate.startswith(API_ROOT):
                    return candidate
                return None
    return None


def fetch_user(session: requests.Session, username: str, *, authenticated: bool = False) -> dict:
    resp = _get(
        session, f"{API_ROOT}/users/{quote(username, safe='')}",
        authenticated=authenticated,
    )
    if resp.status_code == 404:
        raise GitHubError(f"User '{username}' not found.")
    if resp.status_code == 401:
        raise GitHubError("GitHub rejected the token (401). Check GITHUB_TOKEN.")
    if resp.status_code >= 400:
        raise GitHubError(f"GitHub API error {resp.status_code} while fetching the user.")
    try:
        data = resp.json()
    except ValueError as exc:
        raise GitHubError("GitHub returned a malformed user response.") from exc
    if not isinstance(data, dict):
        raise GitHubError("GitHub returned an unexpected user payload.")
    return data


def fetch_repos(
    session: requests.Session,
    username: str,
    *,
    authenticated: bool = False,
    max_pages: int = MAX_REPO_PAGES,
) -> list[dict]:
    """Fetch every public repo, following ``Link`` pagination up to *max_pages*."""
    url: str | None = f"{API_ROOT}/users/{quote(username, safe='')}/repos"
    params: dict[str, Any] | None = {"type": "owner", "per_page": 100, "sort": "pushed"}
    repos: list[dict] = []

    for _ in range(max(1, max_pages)):
        if url is None:
            break
        resp = _get(session, url, params=params, authenticated=authenticated)
        if resp.status_code == 404:
            raise GitHubError(f"User '{username}' not found.")
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub API error {resp.status_code} while fetching repositories."
            )
        try:
            page = resp.json()
        except ValueError as exc:
            raise GitHubError("GitHub returned a malformed repository response.") from exc
        if not isinstance(page, list):
            raise GitHubError("GitHub returned an unexpected repository payload.")
        repos.extend(item for item in page if isinstance(item, dict))

        url = _next_link(resp)
        params = None  # the next link already carries the query string
    return repos


def download_avatar_bytes(session: requests.Session, url: str) -> bytes:
    """Stream an avatar with a hard size cap, so a huge file cannot exhaust RAM."""
    try:
        with session.get(url, timeout=TIMEOUT, stream=True) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_AVATAR_BYTES:
                raise GitHubError("Avatar is larger than the 8 MiB limit.")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_AVATAR_BYTES:
                    raise GitHubError("Avatar is larger than the 8 MiB limit.")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.exceptions.RequestException as exc:
        raise GitHubError(f"Avatar download failed: {redact(exc)}") from exc
