#!/usr/bin/env python3
"""
githubfetch.py - Show a GitHub user's avatar + profile details + top-5 repos
A neofetch-like program for GitHub profiles.
"""

import os
import sys
import io
import textwrap
import shutil
from datetime import datetime
import requests
from PIL import Image


# ─────────────────────────────────────────── Colors ──────────────────────────
class Color:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    @staticmethod
    def paint(code, text):
        return f"{code}{text}{Color.RESET}"


# ───────────────────────────── Enable ANSI colors on Windows ────────────────
def enable_ansi_colors():
    if os.name == "nt":
        try:
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.SetConsoleMode(k32.GetStdHandle(-11), 7)
        except Exception:
            os.system("color")


# ───────────────────────────────── Avatar → true-color ASCII ────────────────
def download_avatar(url, size=18):
    """Download and resize avatar image."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        print(Color.paint(Color.RED, f"Avatar download failed: {e}"))
        return None


def image_to_ascii(img, reset):
    """Convert image to true-color ASCII art rows."""
    if not img:
        return []

    rows = []
    width, height = img.size
    for y in range(height):
        line = []
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            line.append(f"\033[38;2;{r};{g};{b}m██{reset}")
        rows.append("".join(line))
    return rows


# ─────────────────────────────────── GitHub API ─────────────────────────────
def fetch_github_data(username):
    """Fetch user data and repos from GitHub API."""
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "GitHubFetch"}

    try:
        # User info
        user_resp = requests.get(
            f"https://api.github.com/users/{username}", headers=headers, timeout=10
        )

        if user_resp.status_code == 404:
            print(Color.paint(Color.RED, f"Error: user '{username}' not found."))
            sys.exit(1)

        user_resp.raise_for_status()
        user_data = user_resp.json()

        # Repositories
        repos_resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=headers,
            params={"type": "public", "per_page": 100},
            timeout=10,
        )
        repos_resp.raise_for_status()
        repos_data = repos_resp.json()

        return user_data, repos_data

    except requests.exceptions.Timeout:
        print(Color.paint(Color.RED, "Error: Request timed out!"))
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(Color.paint(Color.RED, f"GitHub API error: {e}"))
        sys.exit(1)
    except Exception as e:
        print(Color.paint(Color.RED, f"Unexpected error: {e}"))
        sys.exit(1)


# ─────────────────────────────────── Helpers ────────────────────────────────
def format_date(date_string):
    """Format ISO date string to readable format."""
    if not date_string:
        return "N/A"
    date = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
    return date.strftime("%d %B %Y")


def get_top_repos(repos, count=5):
    """Get top repositories sorted by stars."""
    sorted_repos = sorted(
        repos, key=lambda x: x.get("stargazers_count", 0), reverse=True
    )
    return sorted_repos[:count]


def wrap_text(text, width=50):
    """Wrap long text to specified width."""
    if not text:
        return []
    return textwrap.wrap(text, width=width)


# ──────────────────────────────────── MAIN ──────────────────────────────────
def main():
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <github-username>")

    username = sys.argv[1]
    enable_ansi_colors()

    print(f"Fetching GitHub profile for: {username}")

    # Fetch data
    user_data, repos_data = fetch_github_data(username)

    # Layout dimensions — compute available width so long text never
    # wraps in the terminal and splits the avatar image.
    SEP = " │ "
    # Prefer COLUMNS env var (set by most shells), fall back to TTY size.
    try:
        terminal_width = int(os.environ.get("COLUMNS", 0)) or shutil.get_terminal_size().columns
    except (ValueError, OSError):
        terminal_width = shutil.get_terminal_size().columns

    # Shrink avatar if terminal is too narrow to fit avatar + separator + info
    AVATAR_SIZE = 18  # pixels, each renders as 2 terminal columns
    MIN_INFO = 20
    if terminal_width < AVATAR_SIZE * 2 + len(SEP) + MIN_INFO:
        AVATAR_SIZE = max(6, (terminal_width - len(SEP) - MIN_INFO) // 2)
    AVATAR_W = AVATAR_SIZE * 2  # chars
    INFO_WIDTH = max(10, terminal_width - AVATAR_W - len(SEP))

    # Avatar processing — download at the size determined by terminal width
    avatar_url = user_data.get("avatar_url", "")
    avatar_img = download_avatar(avatar_url, size=AVATAR_SIZE)
    avatar_rows = image_to_ascii(avatar_img, Color.RESET)

    # Build profile info lines
    info_lines = []

    def add_field(label, value, color):
        raw = str(value).replace("\n", " ")
        wrap_w = max(1, INFO_WIDTH - len(label) - 1)
        wrapped = wrap_text(raw, wrap_w) or [""]
        info_lines.append(Color.paint(color, f"{label} {wrapped[0]}".rstrip()))
        indent = " " * (len(label) + 1)
        for w in wrapped[1:]:
            info_lines.append(f"{indent}{w}")

    add_field("Username:", user_data.get("login", "N/A"), Color.CYAN)
    add_field("Name:", user_data.get("name") or "N/A", Color.YELLOW)
    add_field("Bio:", user_data.get("bio") or "N/A", Color.GREEN)
    add_field("Location:", user_data.get("location") or "Not Provided", Color.RED)
    add_field("Public Repos:", user_data.get("public_repos", 0), Color.MAGENTA)
    add_field("Followers:", user_data.get("followers", 0), Color.BLUE)
    add_field("Following:", user_data.get("following", 0), Color.CYAN)
    add_field("Created:", format_date(user_data.get("created_at")), Color.YELLOW)
    add_field("Profile:", user_data.get("html_url", "N/A"), Color.GREEN)

    # Top repos
    top_repos = get_top_repos(repos_data, 5)
    if top_repos:
        info_lines.append("")
        repos_title = "Top Repositories:"
        if len(repos_title) > INFO_WIDTH:
            repos_title = repos_title[:INFO_WIDTH]
        info_lines.append(Color.paint(Color.MAGENTA, repos_title))
        for repo in top_repos:
            stars = repo.get("stargazers_count", 0)
            name = repo.get("name", "N/A")
            desc = repo.get("description") or "No description"

            # ⭐ emoji is 1 Python char but renders as 2 terminal columns
            header = f"⭐ {name} ({stars})"
            header_width = len(header) + 1  # +1 for emoji double-width

            if header_width >= INFO_WIDTH:
                # Header itself is too long — truncate name to fit
                fixed_w = 3 + 2 + len(str(stars)) + 1  # "⭐ " + " (" + stars + ")"
                name_avail = INFO_WIDTH - fixed_w
                if name_avail > 3:
                    name = name[:name_avail - 3] + "..."
                else:
                    name = "..."
                info_lines.append(f"{Color.YELLOW}⭐ {name} ({stars}){Color.RESET}")
            else:
                sep_str = " — "
                desc_avail = INFO_WIDTH - header_width - len(sep_str)
                if desc_avail <= 0:
                    # No room for description at all — just show header
                    info_lines.append(
                        f"{Color.YELLOW}⭐ {name} ({stars}){Color.RESET}"
                    )
                elif desc_avail <= 3:
                    # Very little room — show what fits, no ellipsis
                    info_lines.append(
                        f"{Color.YELLOW}⭐ {name} ({stars}){Color.RESET}"
                        f"{sep_str}{desc[:desc_avail]}"
                    )
                elif len(desc) > desc_avail:
                    info_lines.append(
                        f"{Color.YELLOW}⭐ {name} ({stars}){Color.RESET}"
                        f"{sep_str}{desc[:desc_avail - 3]}..."
                    )
                else:
                    info_lines.append(
                        f"{Color.YELLOW}⭐ {name} ({stars}){Color.RESET}"
                        f"{sep_str}{desc}"
                    )

    # Print side-by-side
    BLANK_AVTR = " " * AVATAR_W
    total_width = AVATAR_W + len(SEP) + INFO_WIDTH

    print()
    print("=" * total_width)
    card_title = f"GitHub Profile Card - @{username}"
    if len(card_title) > total_width:
        card_title = card_title[:total_width]
    print(Color.paint(Color.CYAN, card_title))
    print("=" * total_width)
    print()

    max_lines = max(len(avatar_rows), len(info_lines))
    for i in range(max_lines):
        left = avatar_rows[i] if i < len(avatar_rows) else BLANK_AVTR
        right = info_lines[i] if i < len(info_lines) else ""
        print(f"{left}{SEP}{right}")

    print()
    print("=" * total_width)
    print()


if __name__ == "__main__":
    main()
