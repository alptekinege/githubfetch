# githubfetch

A neofetch-like CLI for GitHub profiles. Renders a user's avatar as true-color
ASCII art next to their profile details and top repositories.

![example image](screenshot.png)

## Features
- True-color ASCII avatar (graceful monochrome fallback when color is off)
- Profile information: name, bio, location, stats, join date
- Top repositories sorted by stars
- **Safe by default** — every remote string is sanitized, so a hostile bio
  cannot clear your screen, retitle your window, or spoof text direction
- Responsive layout: width-aware wrapping and truncation that handles CJK,
  emoji and combining marks without breaking alignment
- Optional token auth for a 5,000/hour rate limit
- JSON output for scripting
- Cross-platform (Linux, macOS, Windows)

## Requirements
- Python 3.9+
- requests, Pillow

## Installation

```bash
git clone https://github.com/alptekinege/githubfetch.git
cd githubfetch
pip install -e .
```

Or just install the dependencies and run the script directly:

```bash
pip install -r requirements.txt
python githubfetch.py <username>
```

For a byte-for-byte reproducible install:

```bash
pip install --require-hashes -r requirements.lock
```

## Usage

```bash
githubfetch <username>
# or
python githubfetch.py <username>
```

### Options

| Flag | Description |
|---|---|
| `--repos N` | Number of top repositories to show (default 5) |
| `--avatar-size N` | Avatar height in pixels, 6–64 (default 18) |
| `--no-avatar` | Skip the avatar entirely |
| `--no-color` / `--color-off` | Disable ANSI colors |
| `--json` | Emit machine-readable JSON instead of the card |
| `--width N` | Override the detected terminal width |
| `--timeout-retries N` | Retries for transient network failures (default 3) |
| `--version` | Print the version |

Examples:

```bash
githubfetch torvalds
githubfetch torvalds --repos 10 --avatar-size 24
githubfetch torvalds --json | jq '.top_repositories[0]'
githubfetch torvalds --no-avatar --no-color
```

## Authentication

Unauthenticated requests are limited to 60/hour. Set a token to raise that to
5,000/hour:

```bash
export GITHUB_TOKEN=ghp_your_token_here
githubfetch torvalds
```

`GH_TOKEN` also works. The token is **only** read from the environment — it is
deliberately not accepted as a command-line argument, because arguments are
visible to any other user via the process list. It is never logged, and it is
redacted from error messages.

When the rate limit is hit, the tool prints how long until it resets instead of
crashing, and honors `Retry-After`.

## Security

`githubfetch` prints data controlled by strangers, so it treats every remote
string as hostile:

- **Terminal escape injection is blocked.** C0/C1 control bytes (including
  `ESC`, the one-byte `CSI`, and `BEL`), zero-width characters and bidi
  overrides are stripped from all API-sourced text before it is printed. A bio
  containing `\x1b[2J` renders as inert literal text.
- **Field lengths are capped** in the renderer (bio ≤ 200, name ≤ 50, …)
  independent of terminal width, so a huge profile cannot flood your scrollback.
- **Avatar URLs are allowlisted** to `*.githubusercontent.com` / `github.com`
  over HTTPS; anything else is refused and never requested. Downloads are capped
  at 8 MiB.
- **Colors are disabled automatically** when output is not a TTY, or when
  `NO_COLOR` / `TERM=dumb` is set.
- Dependencies are pinned, hash-locked in `requirements.lock`, and tracked by
  Dependabot.

These properties are enforced by tests, including a fuzz suite over adversarial
unicode and an end-to-end test that serves a hostile profile from a local server
and asserts the raw output bytes are inert.

## Terminal Alias (optional)

```bash
echo "alias githubfetch='python3 $(pwd)/githubfetch.py'" >> ~/.bashrc
source ~/.bashrc
```

Use `~/.zshrc` for Zsh.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q       # tests
ruff check .    # lint
mypy            # type-check
```

Project layout:

```
githubfetch/
  sanitize.py   # control-char stripping, width math, URL allowlist
  api.py        # auth, retries, rate limiting, pagination
  render.py     # avatar → ASCII, layout, JSON payload
  cli.py        # argparse entry point
githubfetch.py  # shim so `python githubfetch.py` still works
```

See `FUTURE.md` for the roadmap.

## License
Public domain under the [Unlicense](LICENSE). See [unlicense.org](https://unlicense.org).
