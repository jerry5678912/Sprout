#!/usr/bin/env python3
"""Tests for Sprout package/project/release foundations."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "sprout.py"), *args], cwd=cwd, text=True, capture_output=True, check=check)


def test_pkg_lifecycle_and_resolution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app = root / "app"
        lib = root / "pixelgarden"
        app.mkdir()
        lib.mkdir()

        run(["pkg", "init"], app)
        run(["pkg", "init"], lib)
        (lib / "pixel.sprout").write_text('def name():\n  return "local-package"\n', encoding="utf-8")

        added = run(["pkg", "add", str(lib)], app).stdout
        assert "added pixelgarden" in added
        listed = run(["pkg", "list"], app).stdout
        assert "pixelgarden" in listed
        info = run(["pkg", "info", "pixelgarden"], app).stdout
        assert "packages/pixelgarden" not in info

        (app / "src" / "main.sprout").write_text('import "pixel.sprout" as pixel\nsay pixel.name()\n', encoding="utf-8")
        assert run(["run", "."], app).stdout.strip() == "local-package"

        removed = run(["pkg", "remove", "pixelgarden"], app).stdout
        assert "removed pixelgarden" in removed


def test_templates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for template in ["cli", "game2d", "game3d", "library"]:
            name = f"{template}_demo"
            run(["new", template, name], root)
            project = root / name
            assert (project / "sprout.toml").exists()
            assert (project / "src" / "main.sprout").exists()
            assert (project / "README.md").exists()
            run(["check", "."], project)
            run(["run", "."], project)
            formatted = run(["fmt", "."], project).stdout
            assert "src/main.sprout" in formatted
            run(["fmt", ".", "--write"], project)
            if template == "library":
                tests = run(["test"], project).stdout
                assert "2 tests: 2 passed, 0 failed" in tests


def test_doctor_and_release_docs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        release_root = Path(tmp)
        for item in ["sprout.py", "install.py", "sprout_core", "README.md", "docs", "editor", "tests", "examples", "tools", ".github", "sprout.toml"]:
            source = ROOT / item
            dest = release_root / item
            if source.is_dir():
                shutil.copytree(source, dest)
            else:
                shutil.copy2(source, dest)
        run(["release-docs"], release_root)
        for path in ["LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "CHANGELOG.md", "ROADMAP.md", ".github/pull_request_template.md"]:
            assert (release_root / path).exists()
        doctor = run(["doctor"], release_root).stdout
        assert "ok python >= 3.9" in doctor


def main() -> int:
    test_pkg_lifecycle_and_resolution()
    test_templates()
    test_doctor_and_release_docs()
    print("sprout package tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
