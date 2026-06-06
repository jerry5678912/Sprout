from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from typing import Any

from .lexer import Lexer
from .model import SproutError
from .parser import Parser


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
