"""Rendering: avatar to true-color blocks, profile fields, side-by-side layout."""

from __future__ import annotations

import io
import os
import shutil
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

from .sanitize import (
    MAX_BIO,
    MAX_LOCATION,
    MAX_NAME,
    MAX_REPO_DESC,
    MAX_REPO_NAME,
    MAX_URL,
    MAX_USERNAME,
    display_width,
    sanitize_text,
    truncate_display,
    wrap_display,
)

SEP = " │ "
SEP_ASCII = " | "
DEFAULT_AVATAR_SIZE = 18
MIN_AVATAR_SIZE = 6
MIN_INFO_WIDTH = 20
FALLBACK_TERMINAL_WIDTH = 80

# Glyphs that a legacy Windows code page (cp1252, cp437) cannot encode.
_UNICODE_PROBE = "│⭐—██░▒▓"


def configure_stdout() -> None:
    """Ask stdout for UTF-8 so box characters survive a legacy console.

    Windows terminals still default to a legacy code page, where printing the
    separator or the star emoji raises ``UnicodeEncodeError``. Reconfiguring is
    best-effort; :func:`output_is_unicode_safe` decides the fallback if it fails.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: S110 - best-effort; fallback handles failure
            # Some consoles and wrapped streams refuse reconfiguration. That is
            # fine: output_is_unicode_safe() then selects the ASCII fallback.
            pass


def output_is_unicode_safe(stream: Any = None) -> bool:
    """True if *stream* can encode the glyphs the card is drawn with."""
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        _UNICODE_PROBE.encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


class Palette:
    """ANSI colors, or empty strings when color is disabled."""

    RESET: str
    RED: str
    GREEN: str
    YELLOW: str
    BLUE: str
    MAGENTA: str
    CYAN: str
    WHITE: str

    _CODES = {
        "RESET": "\033[0m",
        "RED": "\033[91m",
        "GREEN": "\033[92m",
        "YELLOW": "\033[93m",
        "BLUE": "\033[94m",
        "MAGENTA": "\033[95m",
        "CYAN": "\033[96m",
        "WHITE": "\033[97m",
    }

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        for name, code in self._CODES.items():
            setattr(self, name, code if enabled else "")

    def paint(self, code: str, text: str) -> str:
        if not self.enabled or not code:
            return text
        return f"{code}{text}{self.RESET}"

    def truecolor(self, r: int, g: int, b: int) -> str:
        if not self.enabled:
            return ""
        return f"\033[38;2;{r};{g};{b}m"


def color_enabled(force_off: bool = False, stream: Any = None) -> bool:
    """Respect ``--no-color``, ``NO_COLOR``, ``TERM=dumb`` and non-TTY output."""
    if force_off:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def enable_ansi_colors() -> None:
    """Turn on VT processing in legacy Windows consoles."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        os.system("color")  # noqa: S605, S607 - legacy Windows console fallback


def terminal_width() -> int:
    """Best-effort terminal width; ``COLUMNS`` wins because shells keep it fresh."""
    raw = os.environ.get("COLUMNS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    try:
        return shutil.get_terminal_size(
            (FALLBACK_TERMINAL_WIDTH, 24)
        ).columns or FALLBACK_TERMINAL_WIDTH
    except OSError:
        return FALLBACK_TERMINAL_WIDTH


def compute_layout(
    width: int, avatar_size: int = DEFAULT_AVATAR_SIZE, show_avatar: bool = True
) -> tuple[int, int]:
    """Return ``(avatar_size_in_pixels, info_width_in_columns)``.

    Each avatar pixel renders as two terminal columns.
    """
    width = max(1, width)
    sep_w = display_width(SEP)

    if not show_avatar or avatar_size <= 0:
        return 0, max(10, width)

    # Below this the smallest useful avatar plus the info column cannot both
    # fit, so drop the avatar rather than overflow the terminal.
    if width < MIN_AVATAR_SIZE * 2 + sep_w + MIN_INFO_WIDTH:
        return 0, max(10, width)

    if width < avatar_size * 2 + sep_w + MIN_INFO_WIDTH:
        avatar_size = max(MIN_AVATAR_SIZE, (width - sep_w - MIN_INFO_WIDTH) // 2)
    avatar_cols = avatar_size * 2
    info_width = max(10, width - avatar_cols - sep_w)
    return avatar_size, info_width


def load_avatar(data: bytes, size: int):
    """Decode avatar bytes into a square RGB image, or ``None`` on failure."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard requirement
        return None
    try:
        with Image.open(io.BytesIO(data)) as raw:
            raw.load()
            return raw.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        return None


def image_to_rows(img: Any, palette: Palette, unicode_ok: bool = True) -> list[str]:
    """Render an image as rows of double-width blocks."""
    if img is None:
        return []
    # Shade ramp for monochrome output, darkest to lightest.
    ramp = ("  ", "░░", "▒▒", "▓▓", "██") if unicode_ok else ("  ", "..", "::", "oo", "##")
    block = "██" if unicode_ok else "##"

    rows: list[str] = []
    width, height = img.size
    pixels = img.load()
    for y in range(height):
        parts: list[str] = []
        for x in range(width):
            r, g, b = pixels[x, y][:3]
            if palette.enabled:
                parts.append(f"{palette.truecolor(r, g, b)}{block}{palette.RESET}")
            else:
                lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
                parts.append(ramp[min(4, int(lum * 5))])
        rows.append("".join(parts))
    return rows


def format_date(value: object) -> str:
    if not value or not isinstance(value, str):
        return "N/A"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "N/A"
    return parsed.strftime("%d %B %Y")


def top_repos(repos: Iterable[dict], count: int = 5) -> list[dict]:
    def stars(repo: dict) -> int:
        value = repo.get("stargazers_count", 0)
        return value if isinstance(value, int) else 0

    ranked = sorted(
        (r for r in repos if isinstance(r, dict)),
        key=lambda r: (stars(r), str(r.get("name", ""))),
        reverse=True,
    )
    return ranked[: max(0, count)]


def build_info_lines(
    user: dict,
    repos: Sequence[dict],
    info_width: int,
    palette: Palette,
    repo_count: int = 5,
    unicode_ok: bool = True,
) -> list[str]:
    """Every value here is sanitized: nothing remote is emitted verbatim."""
    lines: list[str] = []

    def add_field(label: str, value: object, color: str, cap: int | None = None) -> None:
        text = sanitize_text(value, cap)
        label_w = display_width(label)

        # Very narrow info column: the label alone can overflow, so give it its
        # own truncated line and wrap the value underneath at full width.
        if label_w + 2 > info_width:
            lines.append(palette.paint(color, truncate_display(label, info_width)))
            lines.extend(wrap_display(text, info_width))
            return

        wrap_w = max(1, info_width - label_w - 1)
        wrapped = wrap_display(text, wrap_w) or [""]
        lines.append(palette.paint(color, f"{label} {wrapped[0]}".rstrip()))
        indent = " " * (label_w + 1)
        for extra in wrapped[1:]:
            lines.append(f"{indent}{extra}")

    add_field("Username:", user.get("login") or "N/A", palette.CYAN, MAX_USERNAME)
    add_field("Name:", user.get("name") or "N/A", palette.YELLOW, MAX_NAME)
    add_field("Bio:", user.get("bio") or "N/A", palette.GREEN, MAX_BIO)
    add_field("Location:", user.get("location") or "Not Provided", palette.RED, MAX_LOCATION)
    add_field("Public Repos:", user.get("public_repos", 0), palette.MAGENTA, 12)
    add_field("Followers:", user.get("followers", 0), palette.BLUE, 12)
    add_field("Following:", user.get("following", 0), palette.CYAN, 12)
    add_field("Created:", format_date(user.get("created_at")), palette.YELLOW, 32)
    add_field("Profile:", user.get("html_url") or "N/A", palette.GREEN, MAX_URL)

    selected = top_repos(repos, repo_count)
    if selected:
        lines.append("")
        lines.append(
            palette.paint(palette.MAGENTA, truncate_display("Top Repositories:", info_width))
        )
        for repo in selected:
            lines.append(_repo_line(repo, info_width, palette, unicode_ok))
    return lines


def _repo_line(
    repo: dict, info_width: int, palette: Palette, unicode_ok: bool = True
) -> str:
    stars = repo.get("stargazers_count", 0)
    stars = stars if isinstance(stars, int) else 0
    name = sanitize_text(repo.get("name") or "N/A", MAX_REPO_NAME)
    desc = sanitize_text(repo.get("description") or "", MAX_REPO_DESC)

    prefix = "⭐ " if unicode_ok else "* "
    suffix = f" ({stars})"
    fixed_w = display_width(prefix) + display_width(suffix)

    if fixed_w + display_width(name) > info_width:
        # Truncate the name first; if the fixed parts alone still overflow
        # (huge star counts in a very narrow column) clip the whole header.
        name = truncate_display(name, max(0, info_width - fixed_w))
        header = truncate_display(f"{prefix}{name}{suffix}", info_width)
        return palette.paint(palette.YELLOW, header)

    header = f"{prefix}{name}{suffix}"
    painted = palette.paint(palette.YELLOW, header)
    if not desc:
        return painted

    sep = " — " if unicode_ok else " - "
    remaining = info_width - display_width(header) - display_width(sep)
    if remaining <= 0:
        return painted
    return f"{painted}{sep}{truncate_display(desc, remaining)}"


def render_card(
    user: dict,
    repos: Sequence[dict],
    avatar_rows: Sequence[str],
    info_lines: Sequence[str],
    avatar_cols: int,
    info_width: int,
    palette: Palette,
    unicode_ok: bool = True,
) -> str:
    """Compose the final card. Returns the whole thing as one string."""
    sep = (SEP if unicode_ok else SEP_ASCII) if avatar_cols else ""
    total = avatar_cols + display_width(sep) + info_width
    blank_avatar = " " * avatar_cols

    username = sanitize_text(user.get("login") or "unknown", MAX_USERNAME)
    title = truncate_display(f"GitHub Profile Card - @{username}", total)

    out: list[str] = ["", "=" * total, palette.paint(palette.CYAN, title), "=" * total, ""]
    for i in range(max(len(avatar_rows), len(info_lines))):
        left = avatar_rows[i] if i < len(avatar_rows) else blank_avatar
        right = info_lines[i] if i < len(info_lines) else ""
        out.append(f"{left}{sep}{right}".rstrip())
    out.extend(["", "=" * total, ""])
    return "\n".join(out)


def build_json_payload(user: dict, repos: Sequence[dict], repo_count: int = 5) -> dict:
    """Machine-readable output; still sanitized so piping into a pager is safe."""
    return {
        "username": sanitize_text(user.get("login"), MAX_USERNAME),
        "name": sanitize_text(user.get("name"), MAX_NAME),
        "bio": sanitize_text(user.get("bio"), MAX_BIO),
        "location": sanitize_text(user.get("location"), MAX_LOCATION),
        "public_repos": user.get("public_repos", 0),
        "followers": user.get("followers", 0),
        "following": user.get("following", 0),
        "created_at": user.get("created_at"),
        "profile_url": sanitize_text(user.get("html_url"), MAX_URL),
        "top_repositories": [
            {
                "name": sanitize_text(repo.get("name"), MAX_REPO_NAME),
                "description": sanitize_text(repo.get("description"), MAX_REPO_DESC),
                "stars": repo.get("stargazers_count", 0),
                "language": sanitize_text(repo.get("language"), 40),
                "url": sanitize_text(repo.get("html_url"), MAX_URL),
            }
            for repo in top_repos(repos, repo_count)
        ],
    }
