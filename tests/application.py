#!/usr/bin/env python3
"""Tests for Sprout application-layer foundations."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.application import RouteHttpServer  # noqa: E402


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), *args],
        cwd=cwd or ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def test_language_tests() -> None:
    result = run(["test", "tests/application_test.sprout", "--verbose"])
    assert "6 tests: 6 passed, 0 failed" in result.stdout
    assert "PASS sqlite rows and transactions" in result.stdout


def test_failure_exit_code() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "failure.sprout"
        path.write_text('test "failure":\n  expect(2).to_equal(3)\n', encoding="utf-8")
        result = run(["test", str(path)], check=False)
        assert result.returncode == 1
        assert "1 tests: 0 passed, 1 failed" in result.stdout
        assert "expected 2 to equal 3" in result.stdout


def test_application_examples() -> None:
    assert "task results: [16, 25]" in run(["run", "examples/application/async_demo.sprout"]).stdout
    assert "2 ship app" in run(["run", "examples/application/sqlite_demo.sprout"]).stdout
    assert "magnitude: 5.0" in run(["run", "examples/application/engineering_demo.sprout"]).stdout
    assert "finished: 3" in run(["run", "examples/application/game_app_demo.sprout"]).stdout


def test_docs_command() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        (project / "src").mkdir()
        (project / "sprout.toml").write_text(
            '[project]\nname = "docs_demo"\nversion = "0.1.0"\nmain = "src/main.sprout"\n'
            'description = "Docs demo"\nlicense = "MIT"\n\n[paths]\nsource = ["src"]\nmodules = []\n',
            encoding="utf-8",
        )
        (project / "src/main.sprout").write_text(
            "## Returns a greeting.\ndef greet(name):\n  return \"hello \" + name\n",
            encoding="utf-8",
        )
        run(["docs", str(project), "--html"])
        markdown = (project / "docs/API.md").read_text(encoding="utf-8")
        assert "Returns a greeting." in markdown
        assert "`greet(name)`" in markdown
        assert (project / "docs/API.html").exists()


def test_http_server_resource_without_socket() -> None:
    class FakeServer:
        server_address = ("127.0.0.1", 4321)

        def __init__(self, *_args: object, **_kwargs: object):
            pass

        def serve_forever(self) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    with patch("sprout_core.application.http.server.ThreadingHTTPServer", FakeServer):
        server = RouteHttpServer({"/": "ok"})
        assert server.url == "http://127.0.0.1:4321"


def main() -> int:
    test_language_tests()
    test_failure_exit_code()
    test_application_examples()
    test_docs_command()
    test_http_server_resource_without_socket()
    print("sprout application tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
