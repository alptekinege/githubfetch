"""Layout, width math and fuzz tests for adversarial unicode."""

from __future__ import annotations

import random
import string

import pytest

from githubfetch.render import (
    SEP,
    Palette,
    build_info_lines,
    compute_layout,
    format_date,
    render_card,
    terminal_width,
    top_repos,
)
from githubfetch.sanitize import (
    display_width,
    sanitize_text,
    truncate_display,
    wrap_display,
)


def strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ───────────────────────────── display width ────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("abc", 3),
        ("日本語", 6),
        ("⭐", 2),
        ("🎉🎉", 4),
        ("a日b", 4),
        ("café", 4),
    ],
)
def test_display_width(text, expected):
    assert display_width(text) == expected


def test_combining_marks_are_zero_width():
    assert display_width("e\u0301") == 1


# ───────────────────────────── truncation ───────────────────────────────────
def test_truncate_noop_when_it_fits():
    assert truncate_display("hello", 10) == "hello"


def test_truncate_adds_ellipsis():
    out = truncate_display("hello world", 8)
    assert display_width(out) <= 8
    assert out.endswith("...")


def test_truncate_never_splits_a_wide_char():
    out = truncate_display("日本語日本語", 5)
    assert display_width(out) <= 5


def test_truncate_zero_width():
    assert truncate_display("anything", 0) == ""


def test_truncate_tiny_widths():
    for width in range(1, 5):
        assert display_width(truncate_display("hello world", width)) <= width


# ───────────────────────────── wrapping ─────────────────────────────────────
def test_wrap_respects_columns_not_len():
    lines = wrap_display("日本語 日本語 日本語", 6)
    assert all(display_width(line) <= 6 for line in lines)


def test_wrap_hard_splits_long_word():
    lines = wrap_display("x" * 50, 10)
    assert all(display_width(line) <= 10 for line in lines)
    assert "".join(lines) == "x" * 50


def test_wrap_empty_and_zero():
    assert wrap_display("", 10) == []
    assert wrap_display("text", 0) == []


# ───────────────────────────── layout ───────────────────────────────────────
@pytest.mark.parametrize("width", [20, 40, 60, 80, 120, 200, 400])
def test_layout_fits_terminal(width):
    size, info = compute_layout(width, 18, True)
    sep_w = display_width(SEP) if size else 0
    assert size * 2 + sep_w + info <= width
    assert info >= 10


def test_layout_shrinks_avatar_on_narrow_terminal():
    size, _ = compute_layout(40, 18, True)
    assert 0 < size < 18


def test_layout_drops_avatar_when_terminal_is_tiny():
    size, info = compute_layout(20, 18, True)
    assert size == 0
    assert info == 20


def test_layout_without_avatar_uses_full_width():
    size, info = compute_layout(100, 18, False)
    assert size == 0
    assert info == 100


def test_terminal_width_prefers_columns(monkeypatch):
    monkeypatch.setenv("COLUMNS", "137")
    assert terminal_width() == 137


def test_terminal_width_ignores_garbage_columns(monkeypatch):
    monkeypatch.setenv("COLUMNS", "not-a-number")
    assert terminal_width() > 0


# ───────────────────────────── card rendering ───────────────────────────────
@pytest.mark.parametrize("width", [24, 40, 80, 120, 200])
def test_card_lines_never_exceed_terminal_width(user_payload, repos_payload, width):
    palette = Palette(False)
    size, info = compute_layout(width, 18, True)
    rows = ["█" * (size * 2)] * size
    lines = build_info_lines(user_payload, repos_payload, info, palette)
    card = render_card(user_payload, repos_payload, rows, lines, size * 2, info, palette)
    for line in card.splitlines():
        assert display_width(strip_ansi(line)) <= max(width, size * 2 + info + 3)


def test_card_has_no_avatar_when_rows_empty(user_payload, repos_payload):
    palette = Palette(False)
    lines = build_info_lines(user_payload, repos_payload, 60, palette)
    card = render_card(user_payload, repos_payload, [], lines, 0, 60, palette)
    assert SEP not in card


def test_repo_line_shows_stars_and_name(user_payload, repos_payload):
    lines = build_info_lines(user_payload, repos_payload, 80, Palette(False))
    joined = "\n".join(lines)
    assert "spoon-knife" in joined
    assert "12000" in joined


def test_top_repos_sorted_by_stars(repos_payload):
    ranked = top_repos(repos_payload, 3)
    assert [r["name"] for r in ranked] == ["spoon-knife", "hello-world", "no-desc"]


def test_top_repos_handles_missing_stars():
    ranked = top_repos([{"name": "a"}, {"name": "b", "stargazers_count": 5}], 2)
    assert ranked[0]["name"] == "b"


def test_top_repos_ignores_non_dicts():
    assert top_repos(["junk", None, {"name": "ok", "stargazers_count": 1}], 5) == [
        {"name": "ok", "stargazers_count": 1}
    ]


def test_zero_repos(user_payload):
    lines = build_info_lines(user_payload, [], 60, Palette(False))
    assert not any("Top Repositories" in line for line in lines)


def test_empty_bio_and_name(user_payload, repos_payload):
    user_payload["bio"] = None
    user_payload["name"] = None
    user_payload["location"] = None
    lines = build_info_lines(user_payload, repos_payload, 60, Palette(False))
    joined = "\n".join(lines)
    assert "Bio: N/A" in joined
    assert "Name: N/A" in joined
    assert "Location: Not Provided" in joined


# ───────────────────────────── dates ────────────────────────────────────────
def test_format_date():
    assert format_date("2011-01-25T18:44:36Z") == "25 January 2011"


@pytest.mark.parametrize("value", [None, "", "garbage", 12345, "2011-13-45T99:99:99Z"])
def test_format_date_bad_input(value):
    assert format_date(value) == "N/A"


# ───────────────────────────── fuzz ─────────────────────────────────────────
ADVERSARIAL_ALPHABET = (
    string.printable
    + "日本語中文한국어"
    + "🎉🚀⭐🐍🔥"
    + "\x1b\x9b\x07\x00\r\n\t"
    + "\u202e\u200b\u0301\ufeff"
    + "àéîõü"
)


@pytest.mark.parametrize("seed", range(80))
def test_fuzz_layout_never_crashes_or_overflows(seed, user_payload):
    rng = random.Random(seed)

    def noise(max_len: int) -> str:
        return "".join(rng.choice(ADVERSARIAL_ALPHABET) for _ in range(rng.randint(0, max_len)))

    user = dict(user_payload)
    user["name"] = noise(120)
    user["bio"] = noise(600)
    user["location"] = noise(90)
    user["login"] = noise(45)
    user["public_repos"] = rng.randint(0, 10**9)
    user["followers"] = rng.randint(0, 10**9)
    user["html_url"] = "https://github.com/" + noise(80)
    repos = [
        {
            "name": noise(120),
            "description": noise(400),
            "stargazers_count": rng.randint(0, 10**9),
        }
        for _ in range(rng.randint(0, 8))
    ]

    width = rng.choice([10, 14, 20, 24, 31, 40, 63, 80, 100, 137, 200])
    palette = Palette(rng.choice([True, False]))
    size, info = compute_layout(width, 18, True)
    avatar_rows = ["█" * (size * 2)] * size
    lines = build_info_lines(user, repos, info, palette)
    card = render_card(user, repos, avatar_rows, lines, size * 2, info, palette)

    total = size * 2 + (display_width(SEP) if size else 0) + info
    assert total <= max(width, 10)

    for line in card.splitlines():
        plain = strip_ansi(line)
        assert "\x1b" not in plain
        assert "\x9b" not in plain
        assert "\x07" not in plain
        # Exact bound: nothing may spill past the card, at any terminal width.
        assert display_width(plain) <= total, f"overflow at width={width}: {plain!r}"


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_sanitize_output_is_always_safe(seed):
    rng = random.Random(seed + 1000)
    raw = "".join(rng.choice(ADVERSARIAL_ALPHABET) for _ in range(rng.randint(0, 300)))
    cleaned = sanitize_text(raw, 200)
    assert len(cleaned) <= 200
    assert all(ord(ch) >= 0x20 and ord(ch) != 0x7F for ch in cleaned)
    assert "\n" not in cleaned
