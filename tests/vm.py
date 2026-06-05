#!/usr/bin/env python3
"""Tests for the experimental Sprout bytecode VM."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


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


def test_disassembler() -> None:
    dis = run(["dis", "examples/vm_supported.sprout"]).stdout
    assert "MAKE_FUNCTION square" in dis
    assert "BUILD_ARRAY 4" in dis
    assert "ITER_NEXT" in dis
    assert "CALL_BUILTIN say" in dis


def test_unsupported_compile_message() -> None:
    result = run(["compile", "examples/super.sprout"], check=False)
    assert result.returncode == 1
    assert "experimental VM does not support this yet" in result.stderr


def test_benchmark_command() -> None:
    bench = run(["bench", "examples/vm_expanded.sprout"]).stdout
    assert "tree-walk:" in bench
    assert "vm:" in bench
    assert "ratio tree/vm:" in bench
    assert "vm supported: true" in bench


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
    test_unsupported_compile_message()
    test_benchmark_command()
    print("sprout vm tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
