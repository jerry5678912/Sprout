#!/usr/bin/env python3
"""Dogfood project tests for real Sprout apps."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def assert_project_ok(path: str) -> None:
    run(["check", path])
    run(["lint", path])
    run(["fmt", path])


def main() -> int:
    assert_project_ok("examples/dogfood/cli_tool")
    cli = run(["run", "examples/dogfood/cli_tool", "add", "docs:2", "tests:3", "release:5"])
    assert "plan items: 3" in cli
    assert "total effort: 10" in cli

    assert_project_ok("examples/dogfood/game2d")
    game = run(["run", "examples/dogfood/game2d"])
    assert "final: 3 4 score 1 coins_left 2" in game
    assert "############" in game

    assert_project_ok("examples/dogfood/math_utility")
    math = run(["run", "examples/dogfood/math_utility"])
    assert "beam reactions: 9.8 6.2" in math
    assert "max moment: 19.6 at 2.0" in math

    assert_project_ok("examples/dogfood/python_interop")
    py = run(["run", "examples/dogfood/python_interop"])
    assert "python interop stats" in py
    assert '"spread": 10.28' in py

    assert_project_ok("examples/dogfood/package_app")
    package = run(["run", "examples/dogfood/package_app"])
    assert "SPROUT DOGFOOD REPORT" in package
    assert "local-package-works" in package
    listing = run(["pkg", "list"], ROOT / "examples/dogfood/package_app")
    assert "textforge" in listing

    quoted = run(["check", "examples/dogfood/python_interop", "--json"])
    assert '"ok": true' in quoted
    print("sprout dogfood tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
