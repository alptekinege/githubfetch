"""Shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def user_payload() -> dict:
    return {
        "login": "octocat",
        "name": "The Octocat",
        "bio": "A friendly cat.",
        "location": "San Francisco",
        "public_repos": 8,
        "followers": 1234,
        "following": 9,
        "created_at": "2011-01-25T18:44:36Z",
        "html_url": "https://github.com/octocat",
        "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4",
    }


@pytest.fixture
def repos_payload() -> list[dict]:
    return [
        {
            "name": "hello-world",
            "description": "My first repository.",
            "stargazers_count": 2100,
            "language": "Python",
            "html_url": "https://github.com/octocat/hello-world",
        },
        {
            "name": "spoon-knife",
            "description": "Fork me.",
            "stargazers_count": 12000,
            "language": None,
            "html_url": "https://github.com/octocat/spoon-knife",
        },
        {
            "name": "no-desc",
            "description": None,
            "stargazers_count": 3,
            "language": "C",
            "html_url": "https://github.com/octocat/no-desc",
        },
    ]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "NO_COLOR", "COLUMNS", "TERM"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def hostile_server_factory(user_payload, repos_payload):
    """Serve a profile over local HTTP and return its base URL.

    Used by tests that need to drive the real CLI as a subprocess. Defaults to
    a benign profile; pass overrides to make it hostile.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    servers = []

    def factory(user: dict | None = None, repos: list | None = None) -> str:
        served_user = dict(user_payload)
        served_user["login"] = "victim"
        if user:
            served_user.update(user)
        served_repos = repos if repos is not None else repos_payload

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                payload = served_repos if "/repos" in self.path else served_user
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield factory

    for server in servers:
        server.shutdown()
        server.server_close()
