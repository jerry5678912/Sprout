from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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


def run_test_file(path: str, verbose: bool = False) -> tuple[int, int, list[str]]:
    program, _source, resolved = parse_file(path)
    project = project_for_path(resolved)
    interpreter = Interpreter(
        source_path=resolved,
        module_search_paths=module_search_paths_for(resolved, project),
    )
    tests = [
        TestCase(stmt[1], stmt[2], resolved, stmt[3], stmt[4])
        for stmt in program
        if stmt[0] == "test"
    ]
    setup = [stmt for stmt in program if stmt[0] != "test"]
    errors: list[str] = []
    try:
        interpreter.run(setup)
    except (SproutError, SproutRaised) as exc:
        message = format_error(exc) if isinstance(exc, SproutError) else f"raised {format_value(exc.value)}"
        return 0, len(tests) or 1, [f"{resolved}: setup failed: {message}"]

    passed = 0
    for case in tests:
        env = Env(interpreter.globals)
        try:
            interpreter.execute_block(case.body, env)
            passed += 1
            if verbose:
                print(f"PASS {case.name} ({os.path.relpath(case.path)}:{case.line})")
        except SproutRaised as exc:
            errors.append(f"FAIL {case.name} ({os.path.relpath(case.path)}:{case.line}): {format_value(exc.value)}")
        except SproutError as exc:
            errors.append(f"FAIL {case.name} ({os.path.relpath(case.path)}:{case.line}): {format_error(exc)}")
        except Exception as exc:
            errors.append(f"FAIL {case.name} ({os.path.relpath(case.path)}:{case.line}): {exc}")
    return passed, len(tests) - passed, errors


def run_tests(path: str | None = None, verbose: bool = False) -> int:
    if path is None:
        project = load_project(os.getcwd())
        if project:
            path = os.path.join(project.root, "tests")
        else:
            path = "tests"
    files = discover_test_files(path)
    if not files:
        print(f"No Sprout test files found in {os.path.abspath(path)}")
        return 1

    total_passed = 0
    total_failed = 0
    all_errors: list[str] = []
    for file_path in files:
        passed, failed, errors = run_test_file(file_path, verbose=verbose)
        total_passed += passed
        total_failed += failed
        all_errors.extend(errors)
        if verbose and passed + failed == 0:
            print(f"SKIP {os.path.relpath(file_path)} (no test declarations)")

    for error in all_errors:
        print(error)
    total = total_passed + total_failed
    print(f"{total} tests: {total_passed} passed, {total_failed} failed")
    return 1 if total_failed else 0
