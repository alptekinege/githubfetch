"""Sanitization and terminal-width helpers.

Every string that originates from the GitHub API is untrusted: a user can put
ANSI escape sequences, bidi overrides or zero-width characters into their name,
bio, location or repository description.  Printing those raw lets a remote
profile clear the victim's screen, move the cursor, emit OSC sequences or spoof
text direction.  Nothing from the network reaches ``print`` without passing
through :func:`sanitize_text` first.
"""

from __future__ import annotations

import unicodedata
from urllib.parse import urlparse

# ─────────────────────────────── Length caps ────────────────────────────────
# Applied before wrapping, regardless of terminal width.
MAX_USERNAME = 39  # GitHub's own hard limit
MAX_NAME = 50
MAX_BIO = 200
MAX_LOCATION = 60
MAX_URL = 120
MAX_REPO_NAME = 100
MAX_REPO_DESC = 200

# Hosts allowed for avatar downloads.
ALLOWED_AVATAR_HOSTS = ("githubusercontent.com", "github.com")

# Characters removed outright.
#   C0 controls (except tab/newline, which are folded to a space first)
#   DEL, C1 controls (0x80-0x9f) - \x9b is a one-byte CSI introducer
#   zero-width & bidi control characters (spoofing / invisible text)
_ZERO_WIDTH_AND_BIDI = frozenset(
    "\u200b\u200c\u200d\u200e\u200f"  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    "\u202a\u202b\u202c\u202d\u202e"  # LRE, RLE, PDF, LRO, RLO
    "\u2060\u2061\u2062\u2063\u2064"  # word joiner + invisible operators
    "\u2066\u2067\u2068\u2069"  # LRI, RLI, FSI, PDI
    "\ufeff"  # BOM / ZWNBSP
)

_FOLD_TO_SPACE = frozenset("\t\n\r\v\f\u0085\u2028\u2029")


def sanitize_text(value: object, max_length: int | None = None) -> str:
    """Return *value* as a single-line string that is inert in a terminal.

    Control characters are dropped, line breaks and tabs become spaces, runs of
    whitespace collapse, and the result is truncated to ``max_length``
    characters (an ellipsis marks the cut).
    """
    if value is None:
        return ""

    text = value if isinstance(value, str) else str(value)

    out: list[str] = []
    for ch in text:
        if ch in _FOLD_TO_SPACE:
            out.append(" ")
            continue
        if ch in _ZERO_WIDTH_AND_BIDI:
            continue
        code = ord(ch)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            continue  # C0, DEL, C1 - includes \x1b ESC and \x9b CSI
        if unicodedata.category(ch) in ("Cs", "Co", "Cn"):
            continue  # surrogates, private use, unassigned
        out.append(ch)

    cleaned = " ".join("".join(out).split())

    if max_length is not None and len(cleaned) > max_length:
        cleaned = cleaned[: max(0, max_length - 1)].rstrip() + "…"
    return cleaned


def char_width(ch: str) -> int:
    """Terminal columns occupied by a single character."""
    if unicodedata.combining(ch):
        return 0
    category = unicodedata.category(ch)
    if category in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    # Emoji outside the East-Asian "wide" tables still render double-width in
    # every modern terminal (misc symbols, pictographs, transport, flags…).
    code = ord(ch)
    if (
        0x1F300 <= code <= 0x1FAFF
        or 0x1F000 <= code <= 0x1F0FF
        or 0x2600 <= code <= 0x27BF
    ):
        return 2
    return 1


def display_width(text: str) -> int:
    """Terminal columns occupied by *text* (assumes it is already sanitized)."""
    return sum(char_width(ch) for ch in text)


def truncate_display(text: str, width: int, ellipsis: str = "...") -> str:
    """Truncate *text* so it renders in at most *width* terminal columns."""
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text

    ell_w = display_width(ellipsis)
    if width <= ell_w:
        # No room for text plus marker - emit as much of the marker as fits.
        out, used = "", 0
        for ch in ellipsis:
            w = char_width(ch)
            if used + w > width:
                break
            out += ch
            used += w
        return out

    budget = width - ell_w
    out, used = "", 0
    for ch in text:
        w = char_width(ch)
        if used + w > budget:
            break
        out += ch
        used += w
    return out.rstrip() + ellipsis


def wrap_display(text: str, width: int) -> list[str]:
    """Word-wrap *text* to *width* terminal columns (width-aware, not len-aware)."""
    if width <= 0:
        return []
    if not text:
        return []

    lines: list[str] = []
    current, current_w = "", 0

    for word in text.split():
        word_w = display_width(word)

        if word_w > width:
            # A single word longer than the line: hard-split it by columns.
            if current:
                lines.append(current)
                current, current_w = "", 0
            chunk, chunk_w = "", 0
            for ch in word:
                cw = char_width(ch)
                if cw > width:
                    # A wide glyph that cannot fit the column at all; emitting
                    # it would overflow the layout, so it is dropped.
                    continue
                if chunk_w + cw > width:
                    if chunk:
                        lines.append(chunk)
                    chunk, chunk_w = "", 0
                chunk += ch
                chunk_w += cw
            current, current_w = chunk, chunk_w
            continue

        extra = word_w if not current else word_w + 1
        if current_w + extra > width:
            lines.append(current)
            current, current_w = word, word_w
        else:
            current = word if not current else f"{current} {word}"
            current_w += extra

    if current:
        lines.append(current)
    return lines


def is_allowed_avatar_url(url: str) -> bool:
    """True if *url* is an HTTPS URL on a GitHub-controlled host."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_AVATAR_HOSTS
    )
