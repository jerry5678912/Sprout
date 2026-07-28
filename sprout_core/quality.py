from __future__ import annotations

import ast
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

from .model import SproutError


ERROR_HEADER = re.compile(r"^error:\s+([^:]+):\s+(.*)$", re.MULTILINE)
ERROR_LOCATION = re.compile(r"^\s*-->\s+(.+?):(\d+)(?::(\d+))?\s*$", re.MULTILINE)
VM_UNSUPPORTED_PREFIX = "error: experimental VM does not support this yet:"
VM_FALLBACK_MARKER = "warning: VM fallback to stable interpreter:"
PARSER_CONSTRUCT_CATEGORIES = {
    "statement": "statements",
    "function_decl": "statements",
    "class_decl": "statements",
    "interface_decl": "statements",
    "enum_decl": "statements",
    "match_stmt": "statements",
    "if_stmt": "statements",
    "while_stmt": "statements",
    "for_stmt": "statements",
    "async_for_stmt": "statements",
    "try_stmt": "statements",
    "union_type_annotation": "annotations",
    "named_type_annotation": "annotations",
    "seedfn_expr": "expressions",
    "or_expr": "expressions",
    "and_expr": "expressions",
    "equality": "expressions",
    "comparison": "expressions",
    "term": "expressions",
    "factor": "expressions",
    "unary": "expressions",
    "call": "expressions",
    "primary": "expressions",
    "pattern": "patterns",
}
BENCHMARK_WORKLOADS = (
    "startup",
    "compilation",
    "loops",
    "calls",
    "collections",
    "object_fields",
    "exceptions",
    "imports",
)


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
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
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
            stable.source_path,
            stable.line,
            stable.col,
            stable.frames,
        )
        vm_error = (
            vm.error_type,
            vm.error_message,
            vm.source_path,
            vm.line,
            vm.col,
            vm.frames,
        )
        if stable_error != vm_error:
            failures.append("diagnostic-mismatch")
    if "Traceback (most recent call last)" in stable.stderr or "Traceback (most recent call last)" in vm.stderr:
        failures.append("python-traceback")
    return list(dict.fromkeys(failures))


def vm_expectation(case: dict[str, Any]) -> tuple[str, str | None]:
    value = case.get("vm", False)
    if isinstance(value, bool):
        return ("required" if value else "not-applicable", None)
    if isinstance(value, str):
        expectation, reason = value, None
    elif isinstance(value, dict):
        expectation = str(value.get("expectation", "not-applicable"))
        reason = str(value["reason"]) if value.get("reason") else None
    else:
        raise ValueError(f"Invalid VM expectation for conformance case {case.get('name')!r}")
    if expectation not in {"required", "unsupported", "not-applicable"}:
        raise ValueError(f"Unknown VM expectation {expectation!r} for conformance case {case.get('name')!r}")
    if expectation != "required" and not reason:
        raise ValueError(f"VM expectation {expectation!r} requires a reason for case {case.get('name')!r}")
    return expectation, reason


def parser_construct_kinds(
    parser_path: str | Path | None = None,
) -> tuple[dict[str, set[str]], list[str]]:
    source_path = Path(parser_path or Path(__file__).resolve().parent / "parser.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    parser_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Parser"
        ),
        None,
    )
    if parser_class is None:
        raise ValueError(f"Parser class not found in {source_path}")

    constructs: dict[str, set[str]] = {
        category: set() for category in set(PARSER_CONSTRUCT_CATEGORIES.values())
    }
    unclassified_methods: list[str] = []
    for method in parser_class.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        kinds: set[str] = set()
        for node in ast.walk(method):
            tuple_value = None
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                tuple_value = node.value
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
                if any(
                    isinstance(target, ast.Name) and target.id in {"expr", "nil"}
                    for target in node.targets
                ):
                    tuple_value = node.value
            if tuple_value is None or not tuple_value.elts:
                continue
            first = tuple_value.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                kinds.add(first.value)
            elif isinstance(first, ast.IfExp):
                for value in (first.body, first.orelse):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        kinds.add(value.value)
        if not kinds:
            continue
        category = PARSER_CONSTRUCT_CATEGORIES.get(method.name)
        if category is None:
            unclassified_methods.append(method.name)
            continue
        constructs[category].update(kinds)
    return constructs, sorted(unclassified_methods)


def vm_coverage_report(
    path: str | None = None,
    *,
    parser_path: str | Path | None = None,
) -> dict[str, Any]:
    coverage_path = Path(
        path or Path(__file__).resolve().parent / "conformance" / "vm_coverage.json"
    ).resolve()
    data = json.loads(coverage_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    counts = {"required": 0, "unsupported": 0, "not-applicable": 0}
    valid_statuses = set(counts)
    parser_kinds, unclassified_methods = parser_construct_kinds(parser_path)
    for method in unclassified_methods:
        failures.append(f"parser method {method!r} produces unclassified constructs")
    for category, expected_kinds in parser_kinds.items():
        entries = data.get(category)
        if not isinstance(entries, dict):
            failures.append(f"missing {category} construct map")
            continue
        actual_kinds = set(entries)
        for missing in sorted(expected_kinds - actual_kinds):
            failures.append(f"{category} construct {missing!r} is not classified")
        for unknown in sorted(actual_kinds - expected_kinds):
            failures.append(f"unknown {category} construct {unknown!r}")
        for kind, entry in entries.items():
            if not isinstance(entry, dict):
                failures.append(f"{category} construct {kind!r} must be an object")
                continue
            status = entry.get("status")
            reason = entry.get("reason")
            if status not in valid_statuses:
                failures.append(f"{category} construct {kind!r} has invalid status {status!r}")
                continue
            counts[status] += 1
            if status != "required" and not reason:
                failures.append(f"{category} construct {kind!r} requires a reason")
    return {
        "ok": not failures,
        "schema": int(data.get("schema", 1)),
        "path": str(coverage_path),
        "counts": counts,
        "failures": failures,
    }


def conformance_suite(manifest_path: str | None = None) -> dict[str, Any]:
    manifest = Path(manifest_path or Path(__file__).resolve().parent / "conformance" / "manifest.json").resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for case in data.get("cases", []):
        source = (manifest.parent / str(case["file"])).resolve()
        stable = run_engine(source, engine="interpreter")
        failures: list[str] = []
        expected_exit = int(case.get("exit", 0))
        expected_stdout = case.get("stdout")
        expected_error = case.get("stderr_contains")
        if stable.exit_code != expected_exit:
            failures.append(f"exit {stable.exit_code}, expected {expected_exit}")
        if expected_stdout is not None and stable.stdout != str(expected_stdout):
            failures.append(f"stdout {stable.stdout!r}, expected {expected_stdout!r}")
        if expected_error and str(expected_error) not in stable.stderr:
            failures.append(f"stderr did not contain {expected_error!r}")
        if "Traceback (most recent call last)" in stable.stderr:
            failures.append("raw Python traceback leaked")

        expectation, unsupported_reason = vm_expectation(case)
        vm = None
        parity_failures: list[str] = []
        if expectation in {"required", "unsupported"}:
            vm = run_engine(source, engine="vm", allow_fallback=False)
            if expectation == "required":
                parity_failures = compare_engine_results(stable, vm)
            else:
                if vm.timed_out:
                    parity_failures.append("timeout")
                if vm.vm_supported is not False:
                    parity_failures.append("unsupported-feature-drift")
                if vm.fallback_used:
                    parity_failures.append("unexpected-fallback")
            if parity_failures:
                failures.append(f"VM parity failed: {', '.join(parity_failures)}")
        results.append({
            "name": str(case["name"]),
            "path": str(source),
            "ok": not failures,
            "vm_expectation": expectation,
            "vm_checked": expectation == "required",
            "vm_supported": vm.vm_supported if vm else None,
            "fallback_used": vm.fallback_used if vm else False,
            "unsupported_reason": unsupported_reason,
            "engine_results": {
                "interpreter": stable.to_json(),
                **({"vm": vm.to_json()} if vm else {}),
            },
            "parity": {"ok": not parity_failures, "failures": parity_failures},
            "failures": failures,
        })
    coverage = vm_coverage_report()
    return {
        "schema": int(data.get("schema", 1)),
        "ok": all(item["ok"] for item in results) and coverage["ok"],
        "manifest": str(manifest),
        "passed": sum(1 for item in results if item["ok"]),
        "total": len(results),
        "vm_coverage": coverage,
        "cases": results,
    }


def print_conformance(report: dict[str, Any], *, json_mode: bool = False) -> int:
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if not report["vm_coverage"]["ok"]:
            print("FAIL VM construct coverage")
            for failure in report["vm_coverage"]["failures"]:
                print(f"  {failure}")
        for case in report["cases"]:
            status = "ok" if case["ok"] else "FAIL"
            vm = " + vm" if case["vm_checked"] else ""
            print(f"{status} {case['name']}{vm}")
            for failure in case["failures"]:
                print(f"  {failure}")
        print(f"{report['passed']}/{report['total']} conformance cases passed")
    return 0 if report["ok"] else 1


def generated_program(rng: random.Random, family: int = 0) -> tuple[str, str]:
    left = rng.randint(-100, 100)
    right = rng.randint(1, 100)
    extra = rng.randint(-20, 20)
    values = [rng.randint(-30, 30) for _ in range(4)]
    family %= 6
    if family == 0:
        relation = "<" if left < right else ">="
        return "arithmetic", (
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
    if family == 1:
        limit = rng.randint(3, 12)
        return "scopes-loops", (
            "total = 0\n"
            f"for value in range({limit}):\n"
            "  if value % 2 == 0:\n"
            "    continue\n"
            "  total = total + value\n"
            "count = 0\n"
            "while count < 3:\n"
            "  count = count + 1\n"
            "say total, count\n"
        )
    if family == 2:
        start = rng.randint(-10, 20)
        step = rng.randint(1, 6)
        return "functions-closures", (
            "def make(start):\n"
            "  value = start\n"
            "  def advance(step=1):\n"
            "    value = value + step\n"
            "    return value\n"
            "  return advance\n"
            f"counter = make({start})\n"
            f"say counter(), counter({step})\n"
            "double = seedfn value: value * 2\n"
            f"say double({step})\n"
        )
    if family == 3:
        threshold = rng.randint(-10, 10)
        return "collections", (
            f"values = {values}\n"
            "values[1:3] = [7, 8]\n"
            f"selected = [value * 2 for value in values if value > {threshold}]\n"
            f"mapped = {{str(value): value + 1 for value in values if value > {threshold}}}\n"
            'record = {"items": values, "name": "seed"}\n'
            "say record.name, record.items[1:], selected, mapped\n"
        )
    if family == 4:
        amount = rng.randint(1, 9)
        return "classes", (
            "class Counter:\n"
            "  def init(self, value=0):\n"
            "    self.value = value\n"
            "  def add(self, amount):\n"
            "    self.value = self.value + amount\n"
            "    return self.value\n"
            "class LoudCounter extends Counter:\n"
            "  def add(self, amount):\n"
            "    return super.add(amount) * 2\n"
            f"counter = LoudCounter({left})\n"
            f"say counter.add({amount}), counter.value\n"
        )
    return "exceptions", (
        f"value = {left}\n"
        "try:\n"
        "  if value < 0:\n"
        '    raise "negative"\n'
        '  say "positive", value\n'
        "catch error:\n"
        '  say "caught", error\n'
    )


def malformed_source(rng: random.Random, family: int = 0) -> str:
    name = f"name_{rng.randint(0, 999)}"
    cases = [
        f"def {name}(:\n  say 1\n",
        f"if {name}:\n",
        f"say [1, 2, {rng.randint(0, 9)}\n",
        f"1 = {rng.randint(0, 9)}\n",
        f'class {name} {{\n  def run(self):\n    say "mixed"\nend\n',
        f'say "unterminated {name}\n',
    ]
    return cases[family % len(cases)]


def reduce_mismatch_source(
    source: str,
    preserves_failure: Callable[[str], bool],
    *,
    max_attempts: int = 100,
) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    attempts = 0
    index = 0
    while len(lines) > 1 and index < len(lines) and attempts < max_attempts:
        candidate_lines = lines[:index] + lines[index + 1:]
        candidate = "".join(candidate_lines)
        attempts += 1
        if candidate.strip() and preserves_failure(candidate):
            lines = candidate_lines
            index = 0
        else:
            index += 1
    return "".join(lines), attempts


def fuzz_suite(iterations: int = 100, seed: int = 1337) -> dict[str, Any]:
    if iterations < 1:
        raise SproutError("Fuzz iterations must be at least 1")
    rng = random.Random(seed)
    failures: list[dict[str, Any]] = []
    valid_checked = 0
    malformed_checked = 0
    families: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="sprout-fuzz-") as tmp:
        path = Path(tmp) / "case.sprout"
        for index in range(iterations):
            family, source = generated_program(rng, index)
            families[family] = families.get(family, 0) + 1
            path.write_text(source, encoding="utf-8")
            stable = run_engine(path, engine="interpreter", timeout=5)
            vm = run_engine(path, engine="vm", allow_fallback=False, timeout=5)
            valid_checked += 1
            classifications = compare_engine_results(stable, vm)
            if stable.exit_code != 0 and not classifications:
                classifications.append("interpreter-failure")
            if classifications:
                expected_classification = classifications[0]

                def preserves_failure(candidate: str) -> bool:
                    path.write_text(candidate, encoding="utf-8")
                    reduced_stable = run_engine(path, engine="interpreter", timeout=2)
                    reduced_vm = run_engine(path, engine="vm", allow_fallback=False, timeout=2)
                    reduced = compare_engine_results(reduced_stable, reduced_vm)
                    if reduced_stable.exit_code != 0 and not reduced:
                        reduced.append("interpreter-failure")
                    return expected_classification in reduced

                minimized, attempts = reduce_mismatch_source(source, preserves_failure)
                failures.append({
                    "iteration": index,
                    "kind": expected_classification,
                    "classification": expected_classification,
                    "classifications": classifications,
                    "family": family,
                    "source": source,
                    "engine_results": {
                        "interpreter": stable.to_json(),
                        "vm": vm.to_json(),
                    },
                    "minimized_reproduction": {
                        "source": minimized,
                        "attempts": attempts,
                    },
                })

            malformed = malformed_source(rng, index)
            path.write_text(malformed, encoding="utf-8")
            malformed_checked += 1
            malformed_result = run_engine(path, engine="interpreter", timeout=5)
            malformed_lines = malformed.splitlines()
            malformed_failure = None
            if malformed_result.timed_out:
                malformed_failure = "timeout"
            elif "Traceback (most recent call last)" in malformed_result.stderr:
                malformed_failure = "parser-crash"
            elif malformed_result.exit_code == 0 or malformed_result.error_type is None:
                malformed_failure = "parser-crash"
            elif malformed_result.line is not None:
                line = malformed_result.line
                col = malformed_result.col
                if not (1 <= line <= len(malformed_lines) + 1):
                    malformed_failure = "parser-crash"
                elif line == len(malformed_lines) + 1 and col not in {None, 1}:
                    malformed_failure = "parser-crash"
                elif line <= len(malformed_lines) and col is not None:
                    if not (1 <= col <= len(malformed_lines[line - 1]) + 1):
                        malformed_failure = "parser-crash"
            if malformed_failure:
                failures.append({
                    "iteration": index,
                    "kind": malformed_failure,
                    "classification": malformed_failure,
                    "family": "malformed",
                    "source": malformed,
                    "engine_results": {"interpreter": malformed_result.to_json()},
                    "minimized_reproduction": None,
                })
    return {
        "schema": 2,
        "ok": not failures,
        "seed": seed,
        "iterations": iterations,
        "valid_programs": valid_checked,
        "malformed_programs": malformed_checked,
        "families": families,
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


def benchmark_suite(repeat: int = 5) -> dict[str, Any]:
    if repeat < 1:
        raise SproutError("Benchmark repeat count must be at least 1")
    from .bytecode import benchmark_file

    root = Path(__file__).resolve().parent / "benchmarks"
    results: list[dict[str, Any]] = []
    for name in BENCHMARK_WORKLOADS:
        path = root / f"{name}.sprout"
        stable = run_engine(path, engine="interpreter")
        vm = run_engine(path, engine="vm", allow_fallback=False)
        parity_failures = compare_engine_results(stable, vm)
        failures = list(parity_failures)
        metrics = benchmark_file(str(path), repeat=repeat)
        ratio = metrics["speed_ratio"]
        if metrics["vm_supported"] is not True:
            failures.append("vm-unsupported")
        if metrics["fallback_used"]:
            failures.append("unexpected-fallback")
        if ratio is not None and not (0.001 <= ratio <= 1000):
            failures.append("benchmark-sanity")

        process_samples: dict[str, list[float]] | None = None
        if name == "startup":
            process_samples = {"interpreter": [], "vm": []}
            for engine in ("interpreter", "vm"):
                for _ in range(repeat):
                    started = time.perf_counter()
                    result = run_engine(path, engine=engine, allow_fallback=False)
                    process_samples[engine].append(time.perf_counter() - started)
                    if result.timed_out:
                        failures.append("timeout")
            metrics["process_startup_seconds"] = {
                engine: statistics.median(samples)
                for engine, samples in process_samples.items()
            }
            metrics["samples"]["process_startup_seconds"] = process_samples

        results.append({
            "name": name,
            "path": str(path),
            "ok": not failures,
            "failures": list(dict.fromkeys(failures)),
            "parity": {
                "ok": not parity_failures,
                "failures": parity_failures,
            },
            "engine_results": {
                "interpreter": stable.to_json(),
                "vm": vm.to_json(),
            },
            "metrics": metrics,
        })
    return {
        "schema": 1,
        "ok": all(item["ok"] for item in results),
        "repeat": repeat,
        "passed": sum(1 for item in results if item["ok"]),
        "total": len(results),
        "benchmarks": results,
    }


def print_benchmark_suite(report: dict[str, Any], *, json_mode: bool = False) -> int:
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in report["benchmarks"]:
            status = "ok" if item["ok"] else "FAIL"
            ratio = item["metrics"]["speed_ratio"]
            ratio_text = "unsupported" if ratio is None else f"{ratio:.3f}x"
            print(f"{status} {item['name']}: tree/vm {ratio_text}")
            for failure in item["failures"]:
                print(f"  {failure}")
        print(f"{report['passed']}/{report['total']} benchmark workloads passed")
    return 0 if report["ok"] else 1
