"""API tests: auth, rate limiting, pagination, retries, redaction."""

from __future__ import annotations

import time

import pytest
import requests
import responses

from githubfetch.api import (
    API_ROOT,
    GitHubError,
    RateLimitError,
    build_session,
    download_avatar_bytes,
    fetch_repos,
    fetch_user,
    get_token,
    redact,
)


# ───────────────────────────── token handling ───────────────────────────────
def test_token_read_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    assert get_token() == "ghp_" + "a" * 36


def test_token_falls_back_to_gh_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "secret-value")
    assert get_token() == "secret-value"


def test_no_token_returns_none():
    assert get_token() is None


def test_blank_token_is_ignored(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    assert get_token() is None


def test_session_sets_authorization_header():
    session = build_session("tok123")
    assert session.headers["Authorization"] == "Bearer tok123"
    session.close()


def test_session_without_token_has_no_auth_header():
    session = build_session(None)
    assert "Authorization" not in session.headers
    session.close()


def test_redact_removes_known_token():
    assert "supersecret" not in redact("failed with supersecret", "supersecret")


def test_redact_matches_token_patterns():
    text = "error: ghp_" + "b" * 36 + " rejected"
    assert "ghp_" not in redact(text)


def test_redact_scrubs_authorization_header():
    out = redact("Authorization: Bearer abc123xyz")
    assert "abc123xyz" not in out


# ───────────────────────────── user fetch ───────────────────────────────────
@responses.activate
def test_fetch_user_ok(user_payload):
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json=user_payload, status=200)
    session = build_session(None)
    assert fetch_user(session, "octocat")["login"] == "octocat"


@responses.activate
def test_fetch_user_404():
    responses.add(responses.GET, f"{API_ROOT}/users/ghost", json={}, status=404)
    session = build_session(None)
    with pytest.raises(GitHubError, match="not found"):
        fetch_user(session, "ghost")


@responses.activate
def test_fetch_user_401_mentions_token():
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json={}, status=401)
    session = build_session("bad")
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        fetch_user(session, "octocat")


@responses.activate
def test_fetch_user_malformed_json():
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", body="not json", status=200)
    session = build_session(None)
    with pytest.raises(GitHubError, match="malformed"):
        fetch_user(session, "octocat")


@responses.activate
def test_fetch_user_unexpected_payload_type():
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json=[1, 2, 3], status=200)
    session = build_session(None)
    with pytest.raises(GitHubError, match="unexpected"):
        fetch_user(session, "octocat")


# ───────────────────────────── rate limiting ────────────────────────────────
@responses.activate
def test_rate_limit_403_raises_readable_error():
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat",
        json={"message": "API rate limit exceeded"},
        status=403,
        headers={
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Limit": "60",
            "X-RateLimit-Reset": str(int(time.time()) + 125),
        },
    )
    session = build_session(None)
    with pytest.raises(RateLimitError) as exc:
        fetch_user(session, "octocat")
    message = str(exc.value)
    assert "rate limit" in message.lower()
    assert "GITHUB_TOKEN" in message  # hint shown to unauthenticated users


@responses.activate
def test_rate_limit_hint_absent_when_authenticated():
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat",
        json={},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "5000"},
    )
    session = build_session("tok")
    with pytest.raises(RateLimitError) as exc:
        fetch_user(session, "octocat", authenticated=True)
    assert "GITHUB_TOKEN" not in str(exc.value)


@responses.activate
def test_retry_after_is_honored_in_message():
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat",
        json={},
        status=429,
        headers={"Retry-After": "42"},
    )
    session = build_session(None)
    with pytest.raises(RateLimitError, match="42s"):
        fetch_user(session, "octocat")


@responses.activate
def test_403_without_rate_limit_headers_is_plain_error():
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json={}, status=403)
    session = build_session(None)
    with pytest.raises(GitHubError) as exc:
        fetch_user(session, "octocat")
    assert not isinstance(exc.value, RateLimitError)


# ───────────────────────────── pagination ───────────────────────────────────
@responses.activate
def test_repo_pagination_follows_link_header():
    page1 = [{"name": f"r{i}", "stargazers_count": i} for i in range(100)]
    page2 = [{"name": "r100", "stargazers_count": 999}]
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat/repos",
        json=page1,
        status=200,
        headers={"Link": f'<{API_ROOT}/users/octocat/repos?page=2>; rel="next"'},
    )
    responses.add(responses.GET, f"{API_ROOT}/users/octocat/repos", json=page2, status=200)

    session = build_session(None)
    repos = fetch_repos(session, "octocat")
    assert len(repos) == 101
    assert repos[-1]["name"] == "r100"


@responses.activate
def test_pagination_stops_at_max_pages():
    page = [{"name": "r", "stargazers_count": 1}]
    for _ in range(5):
        responses.add(
            responses.GET,
            f"{API_ROOT}/users/octocat/repos",
            json=page,
            status=200,
            headers={"Link": f'<{API_ROOT}/users/octocat/repos?page=9>; rel="next"'},
        )
    session = build_session(None)
    repos = fetch_repos(session, "octocat", max_pages=3)
    assert len(repos) == 3


@responses.activate
def test_pagination_refuses_offsite_next_link():
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat/repos",
        json=[{"name": "r"}],
        status=200,
        headers={"Link": '<https://evil.example/repos>; rel="next"'},
    )
    session = build_session(None)
    assert len(fetch_repos(session, "octocat")) == 1


@responses.activate
def test_repos_filters_non_dict_entries():
    responses.add(
        responses.GET, f"{API_ROOT}/users/octocat/repos", json=["junk", {"name": "ok"}], status=200
    )
    session = build_session(None)
    assert fetch_repos(session, "octocat") == [{"name": "ok"}]


@responses.activate
def test_repos_bad_payload_type():
    responses.add(responses.GET, f"{API_ROOT}/users/octocat/repos", json={"a": 1}, status=200)
    session = build_session(None)
    with pytest.raises(GitHubError, match="unexpected"):
        fetch_repos(session, "octocat")


# ───────────────────────────── network errors ───────────────────────────────
@responses.activate
def test_timeout_becomes_github_error():
    responses.add(
        responses.GET, f"{API_ROOT}/users/octocat", body=requests.exceptions.Timeout("slow")
    )
    session = build_session(None, retries=0)
    with pytest.raises(GitHubError, match="timed out"):
        fetch_user(session, "octocat")


@responses.activate
def test_connection_error_becomes_github_error():
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat",
        body=requests.exceptions.ConnectionError("boom"),
    )
    session = build_session(None, retries=0)
    with pytest.raises(GitHubError, match="Network error"):
        fetch_user(session, "octocat")


# ───────────────────────────── avatar download ──────────────────────────────
@responses.activate
def test_avatar_download_returns_bytes():
    url = "https://avatars.githubusercontent.com/u/1"
    responses.add(responses.GET, url, body=b"\x89PNG\r\n", status=200)
    session = build_session(None)
    assert download_avatar_bytes(session, url).startswith(b"\x89PNG")


@responses.activate
def test_avatar_rejects_oversized_content_length():
    url = "https://avatars.githubusercontent.com/u/1"
    responses.add(
        responses.GET,
        url,
        body=b"x",
        status=200,
        headers={"Content-Length": str(50 * 1024 * 1024)},
    )
    session = build_session(None)
    with pytest.raises(GitHubError, match="8 MiB"):
        download_avatar_bytes(session, url)


@responses.activate
def test_avatar_http_error():
    url = "https://avatars.githubusercontent.com/u/1"
    responses.add(responses.GET, url, status=404)
    session = build_session(None, retries=0)
    with pytest.raises(GitHubError, match="Avatar download failed"):
        download_avatar_bytes(session, url)
