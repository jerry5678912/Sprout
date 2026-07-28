from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
from typing import Any

from .lexer import Lexer
from .model import SproutError
from .parser import Parser


ERROR_HEADER = re.compile(r"^error:\s+([^:]+):\s+(.*)$", re.MULTILINE)
ERROR_LOCATION = re.compile(r"^\s*-->\s+(.+?):(\d+)(?::(\d+))?\s*$", re.MULTILINE)
VM_UNSUPPORTED_PREFIX = "error: experimental VM does not support this yet:"
VM_FALLBACK_MARKER = "warning: VM fallback to stable interpreter:"


@dataclass
class EngineResult:
    engine: str
    exit_code: int | None
    stdout: str
    stderr: str
    error_type: str | None = None
    error_message: str = ""
    source_path: str | None = None
    line: int | None = None
    col: int | None = None
    frames: list[str] = field(default_factory=list)
    timed_out: bool = False
    vm_supported: bool | None = None
    fallback_used: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "source_path": self.source_path,
            "line": self.line,
            "col": self.col,
            "frames": list(self.frames),
            "timed_out": self.timed_out,
            "vm_supported": self.vm_supported,
            "fallback_used": self.fallback_used,
        }


def normalize_engine_result(
    *,
    engine: str,
    returncode: int | None,
    stdout: str,
    stderr: str,
    timed_out: bool = False,
) -> EngineResult:
    fallback_used = VM_FALLBACK_MARKER.lower() in stderr.lower()
    unsupported_index = stderr.lower().find(VM_UNSUPPORTED_PREFIX.lower())
    error_type = None
    error_message = ""
    if unsupported_index >= 0:
        error_type = "BytecodeUnsupported"
        line = stderr[unsupported_index:].splitlines()[0]
        error_message = line[len(VM_UNSUPPORTED_PREFIX):].strip()
    else:
        header = ERROR_HEADER.search(stderr)
        if header:
            error_type = header.group(1).strip()
            error_message = header.group(2).strip()

    source_path = None
    source_line = None
    source_col = None
    location = ERROR_LOCATION.search(stderr)
    if location:
        source_path = location.group(1)
        source_line = int(location.group(2))
        source_col = int(location.group(3)) if location.group(3) else None

    frames: list[str] = []
    in_stack = False
    for raw_line in stderr.splitlines():
        stripped = raw_line.strip()
        if stripped == "stack:":
            in_stack = True
            continue
        if not in_stack:
            continue
        if stripped.startswith("at "):
            frames.append(stripped[3:])
        elif stripped.startswith("called at "):
            frames.append(stripped)
        elif stripped:
            break

    return EngineResult(
        engine=engine,
        exit_code=returncode,
        stdout=stdout,
        stderr=stderr,
        error_type=error_type,
        error_message=error_message,
        source_path=source_path,
        line=source_line,
        col=source_col,
        frames=frames,
        timed_out=timed_out,
        vm_supported=(unsupported_index < 0) if engine == "vm" else None,
        fallback_used=fallback_used,
    )


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_engine(
    path: Path,
    *,
    engine: str = "interpreter",
    allow_fallback: bool = False,
    timeout: float = 10.0,
    args: list[str] | None = None,
    input_text: str | None = None,
) -> EngineResult:
    if engine not in {"interpreter", "vm"}:
        raise ValueError(f"Unknown Sprout engine {engine!r}")
    command = [sys.executable, "-m", "sprout_core", "run"]
    if engine == "vm":
        command.append("--vm")
        if not allow_fallback:
            command.append("--no-fallback")
    command.append(str(path))
    command.extend(args or [])
    python_path = os.pathsep.join(
        item for item in [str(repository_root()), os.environ.get("PYTHONPATH", "")] if item
    )
    try:
        completed = subprocess.run(
            command,
            cwd=path.parent,
            text=True,
            input=input_text,
            capture_output=True,
            check=False,
            timeout=timeout,
            env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": python_path},
        )
    except subprocess.TimeoutExpired as exc:
        return normalize_engine_result(
            engine=engine,
            returncode=None,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timed_out=True,
        )
    return normalize_engine_result(
        engine=engine,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def compare_engine_results(stable: EngineResult, vm: EngineResult) -> list[str]:
    failures: list[str] = []
    if stable.timed_out or vm.timed_out:
        failures.append("timeout")
    if vm.vm_supported is False:
        failures.append("vm-unsupported")
    if vm.fallback_used:
        failures.append("unexpected-fallback")
    if stable.exit_code != vm.exit_code:
        failures.append("exit-mismatch")
    if stable.stdout != vm.stdout:
        failures.append("output-mismatch")
    if stable.exit_code != 0 or vm.exit_code != 0:
        stable_error = (
            stable.error_type,
            stable.error_message,
            stable.line,
            stable.col,
            stable.frames,
        )
        vm_error = (
            vm.error_type,
            vm.error_message,
            vm.line,
            vm.col,
            vm.frames,
        )
        if stable_error != vm_error:
            failures.append("diagnostic-mismatch")
    if "Traceback (most recent call last)" in stable.stderr or "Traceback (most recent call last)" in vm.stderr:
        failures.append("python-traceback")
    return list(dict.fromkeys(failures))


def run_sprout(path: Path, *, vm: bool = False, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "sprout_core", "run"]
    if vm:
        command.append("--vm")
    command.append(str(path))
    python_path = os.pathsep.join(
        item for item in [str(repository_root()), os.environ.get("PYTHONPATH", "")] if item
    )
    return subprocess.run(
        command,
        cwd=path.parent,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONPATH": python_path},
    )


def conformance_suite(manifest_path: str | None = None) -> dict[str, Any]:
    manifest = Path(manifest_path or Path(__file__).resolve().parent / "conformance" / "manifest.json").resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in data.get("cases", []):
        source = (manifest.parent / str(case["file"])).resolve()
        stable = run_sprout(source)
        failures: list[str] = []
        expected_exit = int(case.get("exit", 0))
        expected_stdout = case.get("stdout")
        expected_error = case.get("stderr_contains")
        if stable.returncode != expected_exit:
            failures.append(f"exit {stable.returncode}, expected {expected_exit}")
        if expected_stdout is not None and stable.stdout != str(expected_stdout):
            failures.append(f"stdout {stable.stdout!r}, expected {expected_stdout!r}")
        if expected_error and str(expected_error) not in stable.stderr:
            failures.append(f"stderr did not contain {expected_error!r}")
        if "Traceback (most recent call last)" in stable.stderr:
            failures.append("raw Python traceback leaked")

        vm_checked = bool(case.get("vm", False))
        if vm_checked:
            vm = run_sprout(source, vm=True)
            if (vm.returncode, vm.stdout) != (stable.returncode, stable.stdout):
                failures.append(
                    "VM parity mismatch: "
                    f"stable=({stable.returncode}, {stable.stdout!r}) "
                    f"vm=({vm.returncode}, {vm.stdout!r})"
                )
            if "Traceback (most recent call last)" in vm.stderr:
                failures.append("VM leaked a raw Python traceback")
        results.append({
            "name": str(case["name"]),
            "path": str(source),
            "ok": not failures,
            "vm_checked": vm_checked,
            "failures": failures,
        })
    return {
        "ok": all(item["ok"] for item in results),
        "manifest": str(manifest),
        "passed": sum(1 for item in results if item["ok"]),
        "total": len(results),
        "cases": results,
    }


def print_conformance(report: dict[str, Any], *, json_mode: bool = False) -> int:
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for case in report["cases"]:
            status = "ok" if case["ok"] else "FAIL"
            vm = " + vm" if case["vm_checked"] else ""
            print(f"{status} {case['name']}{vm}")
            for failure in case["failures"]:
                print(f"  {failure}")
        print(f"{report['passed']}/{report['total']} conformance cases passed")
    return 0 if report["ok"] else 1


def generated_program(rng: random.Random) -> str:
    left = rng.randint(-100, 100)
    right = rng.randint(1, 100)
    extra = rng.randint(-20, 20)
    values = [rng.randint(-30, 30) for _ in range(4)]
    relation = "<" if left < right else ">="
    return (
        f"left = {left}\n"
        f"right = {right}\n"
        f"values = {values}\n"
        "def combine(a, b, bonus=0):\n"
        "  return (a * 3) + b - bonus\n"
        f"say combine(left, right, {extra})\n"
        "say values[1:3]\n"
        f"if left {relation} right:\n"
        '  say "branch"\n'
        "else:\n"
        '  say "wrong"\n'
    )


def malformed_source(rng: random.Random) -> str:
    atoms = [
        "def", "if", "class", "say", "return", "async", "await", "taskgroup",
        "(", ")", "[", "]", "{", "}", ":", ",", "=", "+", '"unterminated',
        str(rng.randint(-99, 99)), "name",
    ]
    lines = []
    for _ in range(rng.randint(1, 6)):
        lines.append(" ".join(rng.choice(atoms) for _ in range(rng.randint(1, 8))))
    return "\n".join(lines) + "\n"


def fuzz_suite(iterations: int = 100, seed: int = 1337) -> dict[str, Any]:
    if iterations < 1:
        raise SproutError("Fuzz iterations must be at least 1")
    rng = random.Random(seed)
    failures: list[dict[str, Any]] = []
    valid_checked = 0
    malformed_checked = 0
    with tempfile.TemporaryDirectory(prefix="sprout-fuzz-") as tmp:
        path = Path(tmp) / "case.sprout"
        for index in range(iterations):
            source = generated_program(rng)
            path.write_text(source, encoding="utf-8")
            try:
                stable = run_sprout(path, timeout=5)
                vm = run_sprout(path, vm=True, timeout=5)
            except subprocess.TimeoutExpired:
                failures.append({"iteration": index, "kind": "timeout", "source": source})
                continue
            valid_checked += 1
            if stable.returncode != 0 or (stable.returncode, stable.stdout) != (vm.returncode, vm.stdout):
                failures.append({
                    "iteration": index,
                    "kind": "differential",
                    "source": source,
                    "stable": {"exit": stable.returncode, "stdout": stable.stdout, "stderr": stable.stderr},
                    "vm": {"exit": vm.returncode, "stdout": vm.stdout, "stderr": vm.stderr},
                })

            malformed = malformed_source(rng)
            malformed_checked += 1
            try:
                with redirect_stdout(io.StringIO()):
                    Parser(Lexer(malformed).tokenize()).parse()
            except SproutError:
                pass
            except Exception as exc:
                failures.append({
                    "iteration": index,
                    "kind": "parser-crash",
                    "source": malformed,
                    "error": f"{type(exc).__name__}: {exc}",
                })
    return {
        "ok": not failures,
        "seed": seed,
        "iterations": iterations,
        "valid_programs": valid_checked,
        "malformed_programs": malformed_checked,
        "failures": failures,
    }


def print_fuzz(report: dict[str, Any], *, json_mode: bool = False) -> int:
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if report["ok"]:
            print(
                f"fuzz ok seed={report['seed']} iterations={report['iterations']} "
                f"valid={report['valid_programs']} malformed={report['malformed_programs']}"
            )
        else:
            print(f"fuzz FAILED seed={report['seed']} failures={len(report['failures'])}")
            for failure in report["failures"][:10]:
                print(f"  iteration {failure['iteration']}: {failure['kind']}")
    return 0 if report["ok"] else 1
