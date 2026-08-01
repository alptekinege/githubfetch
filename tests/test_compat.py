"""Compatibility guards.

The package claims ``requires-python = ">=3.9"`` but CI cannot always run every
old interpreter, so these tests assert the two things that actually break on
3.9: syntax the parser rejects, and PEP 604 / PEP 585 annotations evaluated at
runtime without ``from __future__ import annotations``.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES = sorted((ROOT / "githubfetch").glob("*.py")) + [ROOT / "githubfetch.py"]


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
@pytest.mark.parametrize("minor", [9, 10, 11])
def test_parses_on_old_python(path: pathlib.Path, minor: int):
    ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, minor))


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_modern_annotations_are_deferred(path: pathlib.Path):
    """``int | None`` in a signature is a TypeError on 3.9 unless deferred."""
    source = path.read_text(encoding="utf-8")
    uses_modern = any(
        token in source for token in ("| None", "list[", "dict[", "tuple[", "set[")
    )
    if not uses_modern:
        pytest.skip("no modern annotation syntax in this module")

    tree = ast.parse(source)
    has_future = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    assert has_future, f"{path.name} needs `from __future__ import annotations`"


def test_shim_still_runs_as_a_script():
    """``python githubfetch.py --version`` must keep working."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "githubfetch.py"), "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "githubfetch" in (result.stdout + result.stderr)


def test_console_entry_point_is_importable():
    from githubfetch.cli import main

    assert callable(main)
