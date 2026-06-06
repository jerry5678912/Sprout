#!/usr/bin/env python3
"""Regression tests for optional Sprout typed abstractions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run_source(source: str, *args: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(source, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), *args, str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )


def test_typed_program_runs_in_both_engines() -> None:
    path = ROOT / "examples" / "typed_abstractions.sprout"
    checked = subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), "typecheck", str(path), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(checked.stdout)
    assert checked.returncode == 0, payload
    assert payload["ok"] is True

    stable = subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), "run", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    vm = subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), "run", "--vm", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert stable.stdout.splitlines() == ["hello Mina", "42"]
    assert vm.stdout == stable.stdout


def test_assignment_return_and_argument_errors() -> None:
    result = run_source(
        "def add(value: Int) -> Int:\n"
        '  return "wrong"\n\n'
        "class Counter:\n"
        "  def init(self, start: Int):\n"
        "    self.start = start\n"
        "  def increase(self, amount: Int) -> Int:\n"
        "    return self.start + amount\n\n"
        'let count: Int = "many"\n'
        'say add("bad")\n'
        'Counter("bad").increase("wrong")\n',
        "typecheck",
    )
    assert result.returncode == 1
    assert "Return expects Int, got String" in result.stdout
    assert "Variable 'count' expects Int, got String" in result.stdout
    assert "Argument 'value' expects Int, got String" in result.stdout
    assert "Argument 'start' expects Int, got String" in result.stdout
    assert "Argument 'amount' expects Int, got String" in result.stdout


def test_interfaces_generics_and_unknown_types() -> None:
    result = run_source(
        "interface Named:\n"
        "  def name(self) -> String\n\n"
        "class Missing implements Named:\n"
        "  def other(self):\n"
        "    return 1\n\n"
        "class Pair[T, U]:\n"
        "  def init(self, left: T, right: U):\n"
        "    self.left = left\n"
        "    self.right = right\n\n"
        "let item: Pair[Int] = Pair(1, 2)\n"
        "let mystery: NeverKnown = nil\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    messages = [item["message"] for item in payload["diagnostics"]]
    assert result.returncode == 1
    assert any("missing interface method 'name'" in message for message in messages)
    assert any("expects 2 type argument(s), got 1" in message for message in messages)
    assert any("Unknown type 'NeverKnown'" in message for message in messages)


def test_editor_diagnostics_include_type_errors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "typed.sprout"
        path.write_text('let count: Int = "wrong"\n', encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "sprout.py"),
                "intel",
                str(path),
                "--kind",
                "diagnostics",
                "--line",
                "1",
                "--col",
                "5",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    payload = json.loads(result.stdout)
    assert any(item["code"] == "SPROUT_ASSIGNMENT_TYPE" for item in payload["diagnostics"])


def main() -> int:
    test_typed_program_runs_in_both_engines()
    test_assignment_return_and_argument_errors()
    test_interfaces_generics_and_unknown_types()
    test_editor_diagnostics_include_type_errors()
    print("sprout type system tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
