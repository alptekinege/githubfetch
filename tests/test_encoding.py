"""Legacy-console encoding tests.

Windows terminals still default to a legacy code page (cp1252 / cp437) that
cannot encode the glyphs the card is drawn with. Printing them there raises
``UnicodeEncodeError`` and the tool dies. These tests pin the fallback.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

import pytest

from githubfetch.render import (
    SEP,
    SEP_ASCII,
    Palette,
    build_info_lines,
    configure_stdout,
    image_to_rows,
    output_is_unicode_safe,
    render_card,
)
from githubfetch.sanitize import display_width

LEGACY_ENCODINGS = ["cp1252", "cp437", "ascii", "latin-1"]
UNICODE_ENCODINGS = ["utf-8", "utf-16", "UTF-8"]


class FakeStream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


@pytest.mark.parametrize("encoding", LEGACY_ENCODINGS)
def test_legacy_encodings_are_not_unicode_safe(encoding):
    assert not output_is_unicode_safe(FakeStream(encoding))


@pytest.mark.parametrize("encoding", UNICODE_ENCODINGS)
def test_utf_encodings_are_unicode_safe(encoding):
    assert output_is_unicode_safe(FakeStream(encoding))


def test_unknown_encoding_is_treated_as_unsafe():
    assert not output_is_unicode_safe(FakeStream("not-a-real-codec"))


def test_missing_encoding_attribute_is_unsafe():
    class NoEncoding:
        pass

    assert not output_is_unicode_safe(NoEncoding())


def test_configure_stdout_is_safe_on_streams_without_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    configure_stdout()  # must not raise


# ───────────────────────── ASCII fallback rendering ─────────────────────────
def test_separator_fallback_is_same_width():
    """Layout math assumes a 3-column separator either way."""
    assert display_width(SEP) == display_width(SEP_ASCII) == 3


def test_card_uses_ascii_separator_when_unsafe(user_payload, repos_payload):
    palette = Palette(False)
    lines = build_info_lines(user_payload, repos_payload, 40, palette, 5, False)
    card = render_card(
        user_payload, repos_payload, ["##" * 6] * 6, lines, 12, 40, palette, False
    )
    assert SEP_ASCII in card
    assert SEP not in card


def test_ascii_card_encodes_to_cp1252(user_payload, repos_payload):
    """The whole rendered card must survive a legacy code page."""
    palette = Palette(False)
    lines = build_info_lines(user_payload, repos_payload, 40, palette, 5, False)
    card = render_card(
        user_payload, repos_payload, ["##" * 6] * 6, lines, 12, 40, palette, False
    )
    card.encode("cp1252")  # raises if any glyph is unencodable


def test_ascii_repo_line_has_no_star_emoji(user_payload, repos_payload):
    lines = build_info_lines(user_payload, repos_payload, 60, Palette(False), 5, False)
    joined = "\n".join(lines)
    assert "⭐" not in joined
    assert "—" not in joined
    assert "* spoon-knife" in joined


def test_unicode_repo_line_keeps_star_emoji(user_payload, repos_payload):
    joined = "\n".join(build_info_lines(user_payload, repos_payload, 60, Palette(False), 5, True))
    assert "⭐" in joined


def test_ascii_avatar_ramp_is_encodable():
    class FakeImage:
        size = (4, 4)

        def load(self):
            return {(x, y): (x * 60, y * 60, 120) for x in range(4) for y in range(4)}

    rows = image_to_rows(FakeImage(), Palette(False), False)
    "\n".join(rows).encode("cp1252")
    assert all("░" not in row and "█" not in row for row in rows)


def test_unicode_avatar_ramp_uses_blocks():
    class FakeImage:
        size = (4, 4)

        def load(self):
            return {(x, y): (250, 250, 250) for x in range(4) for y in range(4)}

    rows = image_to_rows(FakeImage(), Palette(False), True)
    assert any("█" in row for row in rows)


def test_ascii_and_unicode_rows_have_identical_widths():
    """The fallback must not shift the layout by a single column."""

    class FakeImage:
        size = (6, 3)

        def load(self):
            return {(x, y): (x * 40, y * 80, 90) for x in range(6) for y in range(3)}

    uni = image_to_rows(FakeImage(), Palette(False), True)
    asc = image_to_rows(FakeImage(), Palette(False), False)
    assert [display_width(r) for r in uni] == [display_width(r) for r in asc]


# ───────────────────────────── end-to-end ───────────────────────────────────
@pytest.mark.parametrize("encoding", ["cp1252", "cp437"])
def test_cli_survives_legacy_console_encoding(encoding, hostile_server_factory):
    """Drive the real CLI with a legacy stdout encoding; it must not crash."""
    base = hostile_server_factory()
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    env.pop("PYTHONPATH", None)
    code = (
        f"import githubfetch.api as a; a.API_ROOT={base!r};"
        "from githubfetch.cli import run; import sys;"
        "sys.exit(run(['victim','--width','70','--no-color']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"UnicodeEncodeError" not in result.stderr
    assert b"GitHub Profile Card" in result.stdout


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_cli_json_survives_legacy_console_encoding(encoding, hostile_server_factory):
    base = hostile_server_factory()
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    env.pop("PYTHONPATH", None)
    code = (
        f"import githubfetch.api as a; a.API_ROOT={base!r};"
        "from githubfetch.cli import run; import sys; sys.exit(run(['victim','--json']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"UnicodeEncodeError" not in result.stderr

    import json

    payload = json.loads(result.stdout.decode(errors="replace"))
    assert payload["username"] == "victim"
