"""End-to-end attack test.

Unit tests can be fooled by a mock; this drives the real CLI as a subprocess
against a local HTTP server serving a hostile profile, then inspects the raw
bytes that would have reached a terminal.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

HOSTILE = (
    "\x1b[2J\x1b[H PWNED "  # clear screen + home
    "\x9b31m "  # one-byte CSI
    "\x07 "  # bell
    "\x1b]0;window-title\x07 "  # OSC title change
    "\x1b]8;;https://evil.example\x1b\\link\x1b]8;;\x1b\\ "  # OSC 8 hyperlink
    "\x1b[200~paste\x1b[201~ "  # bracketed-paste injection
    "\u202ereversed"  # bidi override
)

USER = {
    "login": "victim",
    "name": HOSTILE,
    "bio": HOSTILE,
    "location": HOSTILE,
    "public_repos": 1,
    "followers": 1,
    "following": 0,
    "created_at": "2011-01-25T18:44:36Z",
    "html_url": "https://github.com/victim",
    "avatar_url": "https://evil.example/steal.png",
}
REPOS = [{"name": "repo" + HOSTILE, "description": HOSTILE, "stargazers_count": 5}]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        payload = REPOS if "/repos" in self.path else USER
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def hostile_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_hostile_profile_is_inert_end_to_end(hostile_server):
    code = (
        f"import githubfetch.api as a; a.API_ROOT={hostile_server!r};"
        "from githubfetch.cli import run; import sys; sys.exit(run(['victim','--width','80']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, cwd=ROOT, timeout=120
    )
    raw = result.stdout
    err = result.stderr.decode(errors="replace")
    out = raw.decode(errors="replace")

    # Nothing executable reaches the terminal.
    assert b"\x1b" not in raw, "ESC leaked to stdout"
    assert b"\xc2\x9b" not in raw, "C1 CSI leaked to stdout"
    assert b"\x07" not in raw, "BEL leaked to stdout"
    assert b"\x0d" not in raw, "CR leaked to stdout"
    assert b"\x00" not in raw
    assert "\u202e".encode() not in raw, "bidi override leaked to stdout"

    # The off-host avatar is refused and never requested.
    assert "not on a GitHub host" in err

    # And the tool still succeeds with a usable card.
    assert result.returncode == 0
    assert "GitHub Profile Card - @victim" in out
    assert "PWNED" in out  # shown as inert literal text, which is the point
