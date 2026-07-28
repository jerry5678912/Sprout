#!/usr/bin/env python3
"""Tests for the experimental Sprout bytecode VM."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.bytecode import CodeObject, compile_file


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(ROOT / "sprout.py"), *args], cwd=ROOT, text=True, capture_output=True, check=check)


def assert_same_output(path: str) -> None:
    tree = run([path]).stdout
    vm = run(["run", "--vm", path]).stdout
    assert tree == vm, f"VM output differed for {path}\ntree={tree!r}\nvm={vm!r}"


def test_supported_programs() -> None:
    assert_same_output("examples/fibonacci.sprout")
    assert_same_output("examples/vm_supported.sprout")
    assert_same_output("examples/vm_expanded.sprout")
    assert_same_output("examples/super.sprout")
    assert_same_output("examples/super_errors.sprout")
    assert_same_output("examples/slices_defaults.sprout")
    assert_same_output("examples/seedfn.sprout")
    assert_same_output("tests/application_test.sprout")
    assert_same_output("examples/named_imports.sprout")


def test_disassembler() -> None:
    dis = run(["dis", "examples/vm_supported.sprout"]).stdout
    assert "MAKE_FUNCTION square" in dis
    assert "BUILD_ARRAY 4" in dis
    assert "ITER_NEXT" in dis
    assert "CALL_BUILTIN say" in dis
    assert "examples/vm_supported.sprout:" in dis


def test_expanded_disassembler() -> None:
    super_dis = run(["dis", "examples/super.sprout"]).stdout
    slice_dis = run(["dis", "examples/slices_defaults.sprout"]).stdout
    assert "LOAD_SUPER_METHOD init" in super_dis
    assert "GET_SLICE" in slice_dis
    assert "SET_SLICE" in slice_dis


def test_vm_error_locations() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("def crash():\n  return missing_name\n\ncrash()\n")
        path = fh.name
    stable = run(["run", path], check=False)
    vm = run(["run", "--vm", "--no-fallback", path], check=False)
    assert stable.returncode == vm.returncode == 1
    assert vm.stderr == stable.stderr
    assert "Undefined variable 'missing_name'" in vm.stderr
    assert f"{path}:4:" in vm.stderr
    assert "at crash" in vm.stderr


def test_no_fallback_flag_reports_unsupported_vm_feature() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("break\n")
        path = fh.name
    strict = run(["run", "--vm", "--no-fallback", path], check=False)
    assert strict.returncode == 1
    assert "experimental VM does not support this yet" in strict.stderr
    assert "break outside a loop" in strict.stderr
    assert "fallback" not in strict.stderr.lower()


def test_instruction_source_maps() -> None:
    code = compile_file(str(ROOT / "examples" / "super.sprout"))

    def visit(item: CodeObject):
        for instruction in item.instructions:
            yield instruction
            if instruction.op == "MAKE_FUNCTION":
                yield from visit(instruction.arg[1])
            elif instruction.op == "MAKE_CLASS":
                for _name, method in instruction.arg[1]:
                    yield from visit(method)

    instructions = list(visit(code))
    assert instructions
    assert all(instruction.source for instruction in instructions)
    assert all(instruction.line is not None for instruction in instructions)

    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("score = 10; say score\n")
        compact_path = fh.name
    compact = compile_file(compact_path)
    assert all(instruction.line == 1 for instruction in compact.instructions)


def test_benchmark_command() -> None:
    bench = run(["bench", "examples/vm_expanded.sprout"]).stdout
    assert "tree-walk:" in bench
    assert "vm:" in bench
    assert "ratio tree/vm:" in bench
    assert "compile:" in bench
    assert "vm instructions:" in bench
    assert "vm supported: true" in bench
    assert "fallback used: false" in bench


def test_debug_and_profile_commands() -> None:
    debug = run(["debug", "examples/vm_expanded.sprout", "--break", "21"]).stdout
    assert "[debug]" in debug
    assert "hero.hurt(2)" in debug

    profile = run(["profile", "examples/vm_expanded.sprout"]).stdout
    assert "instructions:" in profile
    assert "describe: calls=1" in profile


def main() -> int:
    test_supported_programs()
    test_disassembler()
    test_expanded_disassembler()
    test_vm_error_locations()
    test_no_fallback_flag_reports_unsupported_vm_feature()
    test_instruction_source_maps()
    test_benchmark_command()
    print("sprout vm tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
