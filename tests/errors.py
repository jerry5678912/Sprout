#!/usr/bin/env python3
"""Regression tests for user-facing Sprout error reports."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run_source(source: str, *, vm: bool = False) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write(source)
        path = fh.name
    args = ["run", "--vm", path] if vm else [path]
    return subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_clean_failure(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 1
    assert "Traceback (most recent call last)" not in result.stderr
    assert "sprout_core/" not in result.stderr


def test_syntax_context() -> None:
    result = run_source('say "hello" say "again"\n')
    assert_clean_failure(result)
    assert "error: SyntaxError: Expected a line ending after say" in result.stderr
    assert '1 | say "hello" say "again"' in result.stderr
    assert "^" in result.stderr
    assert "= hint: End the statement" in result.stderr


def test_runtime_math_error() -> None:
    result = run_source("say 10 / 0\n")
    assert_clean_failure(result)
    assert "error: MathError: Division by zero" in result.stderr
    assert "divisor is not zero" in result.stderr


def test_python_bridge_error() -> None:
    result = run_source('importpython math\nsay math.sqrt("leaf")\n')
    assert_clean_failure(result)
    assert "error: InteropError: Python bridge call 'math.sqrt' failed" in result.stderr
    assert ":2:" in result.stderr
    assert '2 | say math.sqrt("leaf")' in result.stderr


def test_vm_error_context() -> None:
    result = run_source("def crash():\n  return missing_name\n\ncrash()\n", vm=True)
    assert_clean_failure(result)
    assert "error: NameError: Undefined variable 'missing_name'" in result.stderr
    assert "2 |   return missing_name" in result.stderr
    assert "stack:" in result.stderr


def main() -> int:
    test_syntax_context()
    test_runtime_math_error()
    test_python_bridge_error()
    test_vm_error_context()
    print("sprout error reporting tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
