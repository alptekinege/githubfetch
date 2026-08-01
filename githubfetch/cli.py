"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .api import (
    GitHubError,
    build_session,
    download_avatar_bytes,
    fetch_repos,
    fetch_user,
    get_token,
    redact,
)
from .render import (
    DEFAULT_AVATAR_SIZE,
    MIN_AVATAR_SIZE,
    Palette,
    build_info_lines,
    build_json_payload,
    color_enabled,
    compute_layout,
    configure_stdout,
    enable_ansi_colors,
    image_to_rows,
    load_avatar,
    output_is_unicode_safe,
    render_card,
    terminal_width,
)
from .sanitize import is_allowed_avatar_url

MAX_AVATAR_SIZE = 64


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="githubfetch",
        description="Show a GitHub profile in the terminal, neofetch style.",
        epilog=(
            "Authentication: set GITHUB_TOKEN (or GH_TOKEN) in the environment to "
            "raise the API rate limit from 60 to 5,000 requests/hour. Tokens are "
            "never accepted as command-line arguments."
        ),
    )
    parser.add_argument("username", help="GitHub username to display")
    parser.add_argument(
        "--avatar-size",
        type=int,
        default=DEFAULT_AVATAR_SIZE,
        metavar="N",
        help=f"avatar height in pixels ({MIN_AVATAR_SIZE}-{MAX_AVATAR_SIZE}, "
        f"default {DEFAULT_AVATAR_SIZE}); each pixel is 2 terminal columns",
    )
    parser.add_argument(
        "--repos", type=int, default=5, metavar="N", help="number of top repos (default 5)"
    )
    parser.add_argument("--no-avatar", action="store_true", help="skip the avatar entirely")
    parser.add_argument(
        "--no-color",
        "--color-off",
        dest="no_color",
        action="store_true",
        help="disable ANSI colors (NO_COLOR is honored automatically)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the card")
    parser.add_argument(
        "--width", type=int, default=0, metavar="N", help="override the detected terminal width"
    )
    parser.add_argument(
        "--timeout-retries",
        type=int,
        default=3,
        metavar="N",
        help="retries for transient network failures (default 3)",
    )
    parser.add_argument("--version", action="version", version=f"githubfetch {__version__}")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_stdout()

    username = args.username.strip()
    if not username or len(username) > 39 or not all(
        ch.isalnum() or ch == "-" for ch in username
    ):
        print("Error: invalid GitHub username.", file=sys.stderr)
        return 2

    repo_count = max(0, min(args.repos, 100))
    avatar_size = max(MIN_AVATAR_SIZE, min(args.avatar_size, MAX_AVATAR_SIZE))
    retries = max(0, min(args.timeout_retries, 10))

    token = get_token()
    session = build_session(token, retries=retries)

    try:
        user = fetch_user(session, username, authenticated=bool(token))
        repos = fetch_repos(session, username, authenticated=bool(token))
    except GitHubError as exc:
        print(f"Error: {redact(exc, token)}", file=sys.stderr)
        return 1
    except Exception as exc:  # defensive: never leak a traceback with a token in it
        print(f"Unexpected error: {redact(exc, token)}", file=sys.stderr)
        return 1
    finally:
        session.close()

    if args.json:
        payload = build_json_payload(user, repos, repo_count)
        # ensure_ascii only when the console cannot encode the real characters.
        print(json.dumps(payload, indent=2, ensure_ascii=not output_is_unicode_safe()))
        return 0

    use_color = color_enabled(force_off=args.no_color)
    if use_color:
        enable_ansi_colors()
    palette = Palette(use_color)
    # A legacy Windows code page cannot encode the box/star glyphs.
    unicode_ok = output_is_unicode_safe()

    width = args.width if args.width > 0 else terminal_width()
    show_avatar = not args.no_avatar
    avatar_size, info_width = compute_layout(width, avatar_size, show_avatar)

    avatar_rows: list[str] = []
    if show_avatar and avatar_size > 0:
        avatar_url = user.get("avatar_url", "")
        if not is_allowed_avatar_url(avatar_url):
            if avatar_url:
                print(
                    "Warning: avatar URL is not on a GitHub host, skipping it.",
                    file=sys.stderr,
                )
        else:
            avatar_session = build_session(None, retries=retries)
            try:
                data = download_avatar_bytes(avatar_session, avatar_url)
                avatar_rows = image_to_rows(
                    load_avatar(data, avatar_size), palette, unicode_ok
                )
            except GitHubError as exc:
                print(f"Warning: {redact(exc, token)}", file=sys.stderr)
            finally:
                avatar_session.close()

    avatar_cols = avatar_size * 2 if avatar_rows else 0
    if not avatar_rows:
        _, info_width = compute_layout(width, 0, False)

    info_lines = build_info_lines(user, repos, info_width, palette, repo_count, unicode_ok)
    print(
        render_card(
            user, repos, avatar_rows, info_lines, avatar_cols, info_width, palette, unicode_ok
        )
    )
    return 0


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
