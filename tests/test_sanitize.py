"""Security regression tests: nothing remote may reach the terminal verbatim."""

from __future__ import annotations

import pytest

from githubfetch.render import Palette, build_info_lines, build_json_payload, render_card
from githubfetch.sanitize import (
    is_allowed_avatar_url,
    sanitize_text,
)

# Every one of these must be rendered inert.
HOSTILE_STRINGS = [
    "\x1b[2J\x1b[H wiped your screen",
    "\x9b31m one-byte CSI",
    "\x1b]0;window title\x07",
    "\x1b]8;;https://evil.example\x1b\\clickable\x1b]8;;\x1b\\",
    "bell\x07bell",
    "carriage\rreturn overwrite",
    "\x0f shift-in charset switch",
    "back\x08space",
    "null\x00byte",
    "\x1bPtmux;\x1b\x1b[2J\x1b\\",
    "paste\x1b[200~injection\x1b[201~",
    "\u202egnisrever fdp\u202c",
    "zero\u200bwidth\u200djoiner",
]

CONTROL_CHARS = "".join(chr(c) for c in list(range(0x00, 0x20)) + [0x7F] + list(range(0x80, 0xA0)))


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_sanitize_removes_escape_sequences(hostile):
    cleaned = sanitize_text(hostile)
    assert "\x1b" not in cleaned
    assert "\x9b" not in cleaned
    assert "\x07" not in cleaned
    assert "\r" not in cleaned
    assert "\x00" not in cleaned
    assert "\u202e" not in cleaned
    assert "\u200b" not in cleaned


def test_sanitize_strips_every_control_character():
    assert sanitize_text(CONTROL_CHARS) == ""


def test_sanitize_preserves_normal_text():
    assert sanitize_text("Hello, World! 123 — ok") == "Hello, World! 123 — ok"


def test_sanitize_folds_newlines_to_spaces():
    assert sanitize_text("line one\nline two\ttab") == "line one line two tab"


def test_sanitize_collapses_whitespace_runs():
    assert sanitize_text("a     b\n\n\nc") == "a b c"


def test_sanitize_none_and_numbers():
    assert sanitize_text(None) == ""
    assert sanitize_text(42) == "42"


def test_sanitize_enforces_length_cap():
    out = sanitize_text("x" * 500, 200)
    assert len(out) == 200
    assert out.endswith("…")


def test_sanitize_keeps_emoji_and_cjk():
    assert sanitize_text("日本語 🎉 café") == "日本語 🎉 café"


def test_rendered_card_contains_no_raw_escapes_when_color_off(user_payload, repos_payload):
    user_payload["bio"] = "\x1b[2J destroy \x9b31m"
    user_payload["name"] = "\x1b]0;pwned\x07"
    user_payload["location"] = "\u202eevil"
    user_payload["login"] = "octocat"
    repos_payload[0]["description"] = "\x1b[31mred\x1b[0m"
    repos_payload[0]["name"] = "repo\x1b[1m"

    palette = Palette(False)
    lines = build_info_lines(user_payload, repos_payload, 60, palette)
    card = render_card(user_payload, repos_payload, [], lines, 0, 60, palette)

    for bad in ("\x1b", "\x9b", "\x07", "\u202e", "\x00"):
        assert bad not in card


def test_rendered_card_with_color_only_emits_own_escapes(user_payload, repos_payload):
    user_payload["bio"] = "\x1b[2Jhostile"
    palette = Palette(True)
    lines = build_info_lines(user_payload, repos_payload, 60, palette)
    card = render_card(user_payload, repos_payload, [], lines, 0, 60, palette)

    # Only SGR sequences that we generated ourselves may appear.
    import re

    for seq in re.findall(r"\x1b\[[0-9;]*[A-Za-z]", card):
        assert seq.endswith("m"), f"non-SGR escape leaked: {seq!r}"
    # The literal text "[2J" may survive; without a preceding ESC it is inert.
    assert "\x1b[2J" not in card


def test_json_output_is_sanitized(user_payload, repos_payload):
    user_payload["bio"] = "\x1b[2Jhostile\u202e"
    payload = build_json_payload(user_payload, repos_payload)
    assert "\x1b" not in payload["bio"]
    assert "\u202e" not in payload["bio"]


@pytest.mark.parametrize(
    "url",
    [
        "https://avatars.githubusercontent.com/u/1?v=4",
        "https://avatars3.githubusercontent.com/u/1",
        "https://github.com/images/error/octocat.gif",
    ],
)
def test_avatar_allowlist_accepts_github(url):
    assert is_allowed_avatar_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://avatars.githubusercontent.com/u/1",  # not https
        "https://evil.example/avatar.png",
        "https://githubusercontent.com.evil.example/a.png",
        "https://notgithub.com/a.png",
        "file:///etc/passwd",
        "https://127.0.0.1/a.png",
        "https://[::1]:8080/a.png",
        "https://localhost/a.png",
        "",
        None,
        "javascript:alert(1)",
        "https://user:pass@evil.example/a.png",
    ],
)
def test_avatar_allowlist_rejects_everything_else(url):
    assert not is_allowed_avatar_url(url)


def test_avatar_allowlist_rejects_userinfo_spoof():
    # A classic trick: the real host is evil.example, not githubusercontent.com.
    assert not is_allowed_avatar_url("https://avatars.githubusercontent.com@evil.example/a.png")


def test_field_caps_survive_a_wide_terminal(user_payload, repos_payload):
    user_payload["bio"] = "b" * 5000
    lines = build_info_lines(user_payload, repos_payload, 4000, Palette(False))
    bio_line = next(line for line in lines if line.startswith("Bio:"))
    assert len(bio_line) < 260  # cap (200) + label, not 5000
