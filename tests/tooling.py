#!/usr/bin/env python3
"""Structured tests for Sprout tooling commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SPROUT = ROOT / "sprout.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(SPROUT), *args], cwd=ROOT, text=True, capture_output=True, check=check)


def test_check_json_ok() -> None:
    result = run("check", "examples/fibonacci.sprout", "--json")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["diagnostics"] == []
    assert any(symbol["name"] == "fib" for symbol in payload["symbols"])


def test_check_json_error() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("def bad(:\n")
        path = fh.name
    result = run("check", path, "--json", check=False)
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["severity"] == "error"
    assert payload["diagnostics"][0]["line"] is not None


def test_project_run() -> None:
    result = run("run", "examples/project")
    assert "project: Mina 2 3" in result.stdout


def test_fmt_safe_output() -> None:
    result = run("fmt", "examples/seedfn.sprout")
    assert "double = seedfn x: x * 2" in result.stdout
    assert result.stdout.endswith("\n")


def main() -> int:
    test_check_json_ok()
    test_check_json_error()
    test_project_run()
    test_fmt_safe_output()
    print("sprout tooling tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
