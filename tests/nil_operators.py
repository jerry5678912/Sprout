#!/usr/bin/env python3
"""Regression tests for safe navigation and nil coalescing."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.lexer import Lexer  # noqa: E402
from sprout_core.parser import Parser  # noqa: E402


def run_source(
    source: str,
    *command: str,
    vm: bool = False,
) -> subprocess.CompletedProcess[str]:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write(source)
        path = fh.name
    args = [*command] if command else ["run"]
    if vm:
        args.extend(["--vm", "--no-fallback"])
    args.append(path)
    return subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_lexer_and_parser_build_explicit_short_circuit_nodes() -> None:
    tokens = Lexer("value?.profile?.name ?? fallback ?? \"unknown\"\n").tokenize()
    assert [token.kind for token in tokens if token.kind not in {"NEWLINE", "EOF"}].count("?.") == 2
    assert [token.kind for token in tokens if token.kind not in {"NEWLINE", "EOF"}].count("??") == 2

    program = Parser(tokens).parse()
    expr = program[0][1]
    assert expr == (
        "coalesce",
        ("optional_get", ("optional_get", ("var", "value"), "profile"), "name"),
        ("coalesce", ("var", "fallback"), ("literal", "unknown")),
    )

    precedence = Parser(Lexer('value or nil ?? "fallback"\n').tokenize()).parse()[0][1]
    assert precedence == (
        "coalesce",
        ("binary", "or", ("var", "value"), ("literal", None)),
        ("literal", "fallback"),
    )


def test_interpreter_and_vm_match_safe_navigation_semantics() -> None:
    source = (
        'state = {"touches": 0}\n'
        "def touch():\n"
        "  state.touches = state.touches + 1\n"
        '  return "used"\n\n'
        "class Greeter:\n"
        "  def greet(self, prefix):\n"
        '    return prefix + " Ada"\n\n'
        'person = {"profile": {"name": "Ada"}}\n'
        "missing = nil\n"
        "greeter = Greeter()\n"
        "say person?.profile?.name ?? touch()\n"
        "say missing?.profile?.name ?? touch()\n"
        'say greeter?.greet("Hello") ?? "nobody"\n'
        'say missing?.greet(touch()) ?? "nobody"\n'
        "say false ?? True, 0 ?? 9, state.touches\n"
    )
    stable = run_source(source)
    vm = run_source(source, vm=True)
    assert stable.returncode == vm.returncode == 0, (stable.stderr, vm.stderr)
    assert stable.stdout == vm.stdout == (
        "Ada\n"
        "used\n"
        "Hello Ada\n"
        "nobody\n"
        "false 0 1\n"
    )
    assert stable.stderr == vm.stderr == ""


def test_optional_access_still_rejects_missing_members_on_present_values() -> None:
    stable = run_source('value = {"name": "Ada"}\nsay value?.missing\n')
    vm = run_source('value = {"name": "Ada"}\nsay value?.missing\n', vm=True)
    assert stable.returncode == vm.returncode == 1
    assert stable.stderr == vm.stderr
    assert "has no property 'missing'" in stable.stderr


def test_optional_access_is_not_an_assignment_target() -> None:
    result = run_source('value = {"name": "Ada"}\nvalue?.name = "Mina"\n')
    assert result.returncode == 1
    assert "Expected a variable, property, index, or slice assignment target" in result.stderr


def test_coalescing_type_inference_removes_nil() -> None:
    result = run_source(
        "def maybe_name(flag: Bool) -> String | Nil:\n"
        "  if flag:\n"
        '    return "Ada"\n'
        "  return nil\n\n"
        'let label: String = maybe_name(True) ?? "Guest"\n'
        'let wrong: Int = maybe_name(false) ?? "Guest"\n',
        "typecheck",
        "--json",
    )
    payload = json.loads(result.stdout)
    assignments = [
        item for item in payload["diagnostics"]
        if item["code"] == "SPROUT_ASSIGNMENT_TYPE"
    ]
    assert len(assignments) == 1, payload
    assert "got String" in assignments[0]["message"]


def test_formatter_preserves_nil_operators() -> None:
    result = run_source(
        'name = user?.profile?.name ?? "Guest"   \n',
        "fmt",
    )
    assert result.returncode == 0
    assert result.stdout == 'name = user?.profile?.name ?? "Guest"\n'


def main() -> int:
    test_lexer_and_parser_build_explicit_short_circuit_nodes()
    test_interpreter_and_vm_match_safe_navigation_semantics()
    test_optional_access_still_rejects_missing_members_on_present_values()
    test_optional_access_is_not_an_assignment_target()
    test_coalescing_type_inference_removes_nil()
    test_formatter_preserves_nil_operators()
    print("sprout nil operator tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
