"""CLI tests: argument handling, exit codes, JSON output, color policy."""

from __future__ import annotations

import json

import pytest
import responses

from githubfetch.api import API_ROOT
from githubfetch.cli import build_parser, run
from githubfetch.render import color_enabled


def register(user_payload, repos_payload, avatar: bool = True):
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json=user_payload, status=200)
    responses.add(
        responses.GET, f"{API_ROOT}/users/octocat/repos", json=repos_payload, status=200
    )
    if avatar:
        responses.add(
            responses.GET,
            user_payload["avatar_url"],
            body=_tiny_png(),
            status=200,
            content_type="image/png",
        )


def _tiny_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


# ───────────────────────────── argument parsing ─────────────────────────────
def test_parser_defaults():
    args = build_parser().parse_args(["octocat"])
    assert args.username == "octocat"
    assert args.repos == 5
    assert args.avatar_size == 18
    assert not args.no_avatar
    assert not args.json


def test_parser_flags():
    args = build_parser().parse_args(
        ["octocat", "--repos", "10", "--no-avatar", "--no-color", "--json", "--avatar-size", "24"]
    )
    assert args.repos == 10
    assert args.no_avatar and args.no_color and args.json
    assert args.avatar_size == 24


def test_color_off_alias():
    assert build_parser().parse_args(["octocat", "--color-off"]).no_color


def test_parser_has_no_token_option():
    """A token must never be passable on the command line (process-list leak)."""
    text = build_parser().format_help()
    assert "--token" not in text
    assert "GITHUB_TOKEN" in text


@pytest.mark.parametrize("bad", ["", "  ", "a" * 40, "bad name", "evil;rm -rf", "../etc"])
def test_invalid_username_exits_2(bad, capsys):
    assert run([bad]) == 2
    assert "invalid" in capsys.readouterr().err.lower()


# ───────────────────────────── happy paths ──────────────────────────────────
@responses.activate
def test_run_renders_card(user_payload, repos_payload, capsys):
    register(user_payload, repos_payload)
    assert run(["octocat", "--no-color", "--width", "80"]) == 0
    out = capsys.readouterr().out
    assert "GitHub Profile Card - @octocat" in out
    assert "The Octocat" in out
    assert "spoon-knife" in out


@responses.activate
def test_run_no_avatar(user_payload, repos_payload, capsys):
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--no-avatar", "--no-color", "--width", "80"]) == 0
    assert "Username: octocat" in capsys.readouterr().out


@responses.activate
def test_json_output_is_valid(user_payload, repos_payload, capsys):
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["username"] == "octocat"
    assert data["top_repositories"][0]["name"] == "spoon-knife"


@responses.activate
def test_repos_flag_limits_output(user_payload, repos_payload, capsys):
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--json", "--repos", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["top_repositories"]) == 1


@responses.activate
def test_zero_repos_flag(user_payload, repos_payload, capsys):
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--json", "--repos", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["top_repositories"] == []


# ───────────────────────────── failure paths ────────────────────────────────
@responses.activate
def test_missing_user_exits_1(capsys):
    responses.add(responses.GET, f"{API_ROOT}/users/ghost", json={}, status=404)
    assert run(["ghost", "--no-color"]) == 1
    assert "not found" in capsys.readouterr().err


@responses.activate
def test_rate_limited_exits_1(capsys):
    responses.add(
        responses.GET,
        f"{API_ROOT}/users/octocat",
        json={},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "60"},
    )
    assert run(["octocat", "--no-color"]) == 1
    assert "rate limit" in capsys.readouterr().err.lower()


@responses.activate
def test_bad_avatar_host_is_skipped_not_fatal(user_payload, repos_payload, capsys):
    user_payload["avatar_url"] = "https://evil.example/pwn.png"
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--no-color", "--width", "80"]) == 0
    captured = capsys.readouterr()
    assert "not on a GitHub host" in captured.err
    assert "GitHub Profile Card" in captured.out
    # The off-host URL must never have been requested.
    assert all("evil.example" not in call.request.url for call in responses.calls)


@responses.activate
def test_avatar_failure_is_a_warning_not_a_crash(user_payload, repos_payload, capsys):
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json=user_payload, status=200)
    responses.add(
        responses.GET, f"{API_ROOT}/users/octocat/repos", json=repos_payload, status=200
    )
    responses.add(responses.GET, user_payload["avatar_url"], status=500)
    assert run(["octocat", "--no-color", "--width", "80", "--timeout-retries", "0"]) == 0
    assert "GitHub Profile Card" in capsys.readouterr().out


@responses.activate
def test_token_never_printed_on_error(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "z" * 36)
    responses.add(responses.GET, f"{API_ROOT}/users/octocat", json={}, status=401)
    assert run(["octocat", "--no-color"]) == 1
    assert "ghp_" not in capsys.readouterr().err


# ───────────────────────────── color policy ─────────────────────────────────
def test_no_color_env_disables_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert not color_enabled()


def test_dumb_term_disables_color(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert not color_enabled()


def test_non_tty_disables_color():
    class NotATty:
        def isatty(self):
            return False

    assert not color_enabled(stream=NotATty())


def test_tty_enables_color():
    class IsATty:
        def isatty(self):
            return True

    assert color_enabled(stream=IsATty())


@responses.activate
def test_piped_output_has_no_ansi(user_payload, repos_payload, capsys):
    """capsys is not a TTY, so the card must come out plain."""
    register(user_payload, repos_payload, avatar=False)
    assert run(["octocat", "--no-avatar", "--width", "80"]) == 0
    assert "\x1b" not in capsys.readouterr().out
