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
