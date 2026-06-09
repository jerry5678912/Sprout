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


def test_keyword_argument_diagnostics() -> None:
    result = run_source(
        "def spawn(name: String, hp: Int = 10) -> String:\n"
        "  return name\n\n"
        'spawn(name="Mina", health=10)\n'
        'spawn("Mina", name="Ada")\n'
        "spawn()\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    codes = [item["code"] for item in payload["diagnostics"]]
    assert result.returncode == 1
    assert "SPROUT_UNKNOWN_ARGUMENT" in codes
    assert "SPROUT_DUPLICATE_ARGUMENT" in codes
    assert "SPROUT_ARGUMENT_COUNT" in codes


def test_argument_diagnostics_include_fix_data() -> None:
    result = run_source(
        "def hello(count: Int, mood: String):\n"
        "  return count\n\n"
        "hello()\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    argument_count = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_ARGUMENT_COUNT")
    assert argument_count["data"]["kind"] == "missing-arguments"
    assert argument_count["data"]["function"] == "hello"
    assert argument_count["data"]["missing"] == ["count", "mood"]
    assert argument_count["data"]["signature"] == "hello(count, mood)"


def test_override_and_unreachable_diagnostics() -> None:
    result = run_source(
        "class Base:\n"
        "  def value(self, amount: Int) -> Int:\n"
        "    return amount\n\n"
        "class Child extends Base:\n"
        "  def value(self, amount: String) -> String:\n"
        "    return amount\n\n"
        "def early() -> Int:\n"
        "  return 1\n"
        "  say 2\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    codes = [item["code"] for item in payload["diagnostics"]]
    assert result.returncode == 1
    assert "SPROUT_OVERRIDE_SIGNATURE" in codes
    assert "SPROUT_UNREACHABLE" in codes


def test_nil_narrowing_and_branch_merge_reduce_false_positives() -> None:
    result = run_source(
        "def use(maybe: String | Nil) -> String:\n"
        "  if maybe != nil:\n"
        "    return maybe\n"
        "  return \"fallback\"\n\n"
        "def branch(flag: Bool):\n"
        "  if flag:\n"
        "    value = 1\n"
        "  else:\n"
        "    value = 2.5\n"
        "  return value\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    codes = [item["code"] for item in payload["diagnostics"]]
    assert "SPROUT_RETURN_TYPE" not in codes
    assert result.returncode == 0


def test_truthy_nil_narrowing_and_keyword_fix_data() -> None:
    result = run_source(
        "def greet(name: String | Nil, mood: String = \"ok\") -> String:\n"
        "  if name:\n"
        "    return name\n"
        "  return \"fallback\"\n\n"
        'greet(name="Ada", modd="happy")\n',
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    unknown = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_UNKNOWN_ARGUMENT")
    assert unknown["data"]["parameter"] == "modd"
    assert unknown["data"]["replacement"] == "mood"
    assert "Did you mean 'mood'?" in unknown["message"]


def test_get_builtin_preserves_value_type_with_default() -> None:
    result = run_source(
        "def read_name(state: Dict[String, String]) -> String:\n"
        '  value = get(state, "name", "fallback")\n'
        "  return value\n",
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    codes = [item["code"] for item in payload["diagnostics"]]
    assert "SPROUT_RETURN_TYPE" not in codes
    assert result.returncode == 0


def main() -> int:
    test_typed_program_runs_in_both_engines()
    test_assignment_return_and_argument_errors()
    test_interfaces_generics_and_unknown_types()
    test_editor_diagnostics_include_type_errors()
    test_keyword_argument_diagnostics()
    test_argument_diagnostics_include_fix_data()
    test_override_and_unreachable_diagnostics()
    test_nil_narrowing_and_branch_merge_reduce_false_positives()
    test_truthy_nil_narrowing_and_keyword_fix_data()
    test_get_builtin_preserves_value_type_with_default()
    print("sprout type system tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
