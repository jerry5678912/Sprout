from __future__ import annotations

import contextlib
import io
import json
import os
from dataclasses import dataclass
from typing import Any

from .analysis import line_docs
from .model import SproutError, SproutRaised
from .runtime import Env, Interpreter, format_error, format_value
from .tooling import load_project, module_search_paths_for, parse_file, project_for_path


@dataclass
class TestCase:
    name: str
    body: list[Any]
    path: str
    line: int
    col: int
    docs: str = ""


@dataclass
class TestResult:
    name: str
    path: str
    line: int
    col: int
    status: str
    message: str = ""
    output: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "line": self.line,
            "column": self.col,
            "status": self.status,
            "message": self.message,
            "output": self.output,
        }


def discover_test_files(path: str | None = None) -> list[str]:
    target = os.path.abspath(path or "tests")
    if os.path.isfile(target):
        return [target] if target.endswith(".sprout") else []
    if not os.path.isdir(target):
        return []
    files = []
    for current, dirs, names in os.walk(target):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in names:
            if name.endswith(".sprout"):
                files.append(os.path.join(current, name))
    return sorted(files)


def discover_test_cases(path: str | None = None) -> list[TestCase]:
    cases: list[TestCase] = []
    for file_path in discover_test_files(path):
        program, source, resolved = parse_file(file_path)
        lines = source.splitlines()
        cases.extend(
            TestCase(stmt[1], stmt[2], resolved, stmt[3], stmt[4], line_docs(lines, stmt[3] - 1))
            for stmt in program
            if stmt[0] == "test"
        )
    return cases


def run_test_file_results(
    path: str,
    name_filter: str | None = None,
    capture_output: bool = False,
) -> list[TestResult]:
    program, _source, resolved = parse_file(path)
    lines = _source.splitlines()
    project = project_for_path(resolved)
    interpreter = Interpreter(
        source_path=resolved,
        module_search_paths=module_search_paths_for(resolved, project),
    )
    tests = [
        TestCase(stmt[1], stmt[2], resolved, stmt[3], stmt[4], line_docs(lines, stmt[3] - 1))
        for stmt in program
        if stmt[0] == "test" and (name_filter is None or stmt[1] == name_filter)
    ]
    setup = [stmt for stmt in program if stmt[0] != "test"]
    setup_output = io.StringIO()
    try:
        with contextlib.redirect_stdout(setup_output) if capture_output else contextlib.nullcontext():
            interpreter.run(setup)
    except (SproutError, SproutRaised) as exc:
        message = format_error(exc) if isinstance(exc, SproutError) else f"raised {format_value(exc.value)}"
        return [
            TestResult(
                case.name if tests else "<setup>",
                resolved,
                case.line if tests else 1,
                case.col if tests else 1,
                "failed",
                f"setup failed: {message}",
                setup_output.getvalue(),
            )
            for case in (tests or [TestCase("<setup>", [], resolved, 1, 1)])
        ]

    results: list[TestResult] = []
    for case in tests:
        env = Env(interpreter.globals)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output) if capture_output else contextlib.nullcontext():
                interpreter.execute_block(case.body, env)
            results.append(TestResult(case.name, case.path, case.line, case.col, "passed", output=output.getvalue()))
        except SproutRaised as exc:
            results.append(TestResult(case.name, case.path, case.line, case.col, "failed", format_value(exc.value), output.getvalue()))
        except SproutError as exc:
            results.append(TestResult(case.name, case.path, case.line, case.col, "failed", format_error(exc), output.getvalue()))
        except Exception as exc:
            results.append(TestResult(case.name, case.path, case.line, case.col, "failed", str(exc), output.getvalue()))
    return results


def run_test_file(path: str, verbose: bool = False, name_filter: str | None = None) -> tuple[int, int, list[str]]:
    results = run_test_file_results(path, name_filter=name_filter)
    if verbose:
        for result in results:
            if result.status == "passed":
                print(f"PASS {result.name} ({os.path.relpath(result.path)}:{result.line})")
    errors = [
        f"FAIL {result.name} ({os.path.relpath(result.path)}:{result.line}): {result.message}"
        for result in results
        if result.status == "failed"
    ]
    passed = sum(result.status == "passed" for result in results)
    return passed, len(results) - passed, errors


def resolve_test_path(path: str | None) -> str:
    if path is None:
        project = load_project(os.getcwd())
        if project:
            return os.path.join(project.root, "tests")
        return "tests"
    return path


def run_tests(
    path: str | None = None,
    verbose: bool = False,
    json_mode: bool = False,
    list_only: bool = False,
    name_filter: str | None = None,
) -> int:
    path = resolve_test_path(path)
    files = discover_test_files(path)
    if not files:
        if json_mode:
            print(json.dumps({"tests": [], "summary": {"total": 0, "passed": 0, "failed": 0}}))
        else:
            print(f"No Sprout test files found in {os.path.abspath(path)}")
        return 1

    if list_only:
        cases = discover_test_cases(path)
        if name_filter is not None:
            cases = [case for case in cases if case.name == name_filter]
        payload = {
            "tests": [
                {
                    "name": case.name,
                    "path": case.path,
                    "line": case.line,
                    "column": case.col,
                    "docs": case.docs,
                }
                for case in cases
            ]
        }
        if json_mode:
            print(json.dumps(payload, sort_keys=True))
        else:
            for case in cases:
                print(f"{case.path}:{case.line}:{case.col}: {case.name}")
        return 0

    total_passed = 0
    total_failed = 0
    all_errors: list[str] = []
    all_results: list[TestResult] = []
    for file_path in files:
        results = run_test_file_results(file_path, name_filter=name_filter, capture_output=json_mode)
        all_results.extend(results)
        passed = sum(result.status == "passed" for result in results)
        failed = len(results) - passed
        errors = [
            f"FAIL {result.name} ({os.path.relpath(result.path)}:{result.line}): {result.message}"
            for result in results
            if result.status == "failed"
        ]
        total_passed += passed
        total_failed += failed
        all_errors.extend(errors)
        if verbose and not json_mode:
            for result in results:
                if result.status == "passed":
                    print(f"PASS {result.name} ({os.path.relpath(result.path)}:{result.line})")
            if passed + failed == 0:
                print(f"SKIP {os.path.relpath(file_path)} (no test declarations)")

    total = total_passed + total_failed
    if json_mode:
        print(json.dumps({
            "tests": [result.to_json() for result in all_results],
            "summary": {"total": total, "passed": total_passed, "failed": total_failed},
        }, sort_keys=True))
    else:
        for error in all_errors:
            print(error)
        print(f"{total} tests: {total_passed} passed, {total_failed} failed")
    return 1 if total_failed else 0
