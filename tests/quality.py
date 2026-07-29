#!/usr/bin/env python3
"""Regression tests for conformance and deterministic fuzz infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.quality import (  # noqa: E402
    benchmark_suite,
    compare_engine_results,
    conformance_suite,
    fuzz_suite,
    normalize_engine_result,
    parser_construct_kinds,
    reduce_mismatch_source,
    run_engine,
    vm_coverage_report,
)


def test_conformance_corpus() -> None:
    report = conformance_suite()
    assert report["ok"], report
    assert report["schema"] == 2
    assert report["total"] >= 8
    assert all(case["vm_expectation"] == "required" for case in report["cases"])
    assert all(case["vm_checked"] for case in report["cases"])
    assert all(case["parity"]["ok"] for case in report["cases"])
    assert all(not case["fallback_used"] for case in report["cases"])
    assert all("interpreter" in case["engine_results"] for case in report["cases"])
    assert all("vm" in case["engine_results"] for case in report["cases"])
    assert report["vm_coverage"]["ok"], report


def test_vm_construct_coverage() -> None:
    report = vm_coverage_report()
    assert report["ok"], report
    assert report["counts"]["required"] >= 40, report
    assert report["counts"]["not-applicable"] == 3, report


def test_vm_construct_coverage_is_derived_from_parser() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        parser_path = Path(tmp) / "parser.py"
        parser_path.write_text(
            "class Parser:\n"
            "    def statement(self):\n"
            "        return ('future_statement',)\n",
            encoding="utf-8",
        )
        constructs, unclassified = parser_construct_kinds(parser_path)
    assert constructs["statements"] == {"future_statement"}
    assert unclassified == []


def test_seeded_fuzzer_is_repeatable() -> None:
    first = fuzz_suite(iterations=20, seed=20260606)
    second = fuzz_suite(iterations=20, seed=20260606)
    assert first["ok"], first
    assert second["ok"], second
    assert first == second
    assert first["valid_programs"] == 20
    assert first["malformed_programs"] == 20
    assert len(first["families"]) == 7


def test_mismatch_reducer_is_bounded_and_preserves_failure() -> None:
    source = "setup = 1\nsay setup\nsay mismatch\ncleanup = 2\n"
    reduced, attempts = reduce_mismatch_source(
        source,
        lambda candidate: "say mismatch" in candidate,
        max_attempts=20,
    )
    assert reduced == "say mismatch\n"
    assert 1 <= attempts <= 20


def test_machine_readable_commands() -> None:
    conformance = subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), "conformance", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(conformance.stdout)["ok"] is True
    fuzz = subprocess.run(
        [
            sys.executable,
            str(ROOT / "sprout.py"),
            "fuzz",
            "--iterations",
            "3",
            "--seed",
            "7",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(fuzz.stdout)
    assert payload["ok"] is True
    assert payload["seed"] == 7
    benchmark = subprocess.run(
        [
            sys.executable,
            str(ROOT / "sprout.py"),
            "bench",
            "--suite",
            "--repeat",
            "2",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    benchmark_payload = json.loads(benchmark.stdout)
    assert benchmark_payload["ok"] is True
    assert benchmark_payload["total"] == 8


def test_benchmark_suite_uses_medians_and_strict_parity() -> None:
    report = benchmark_suite(repeat=3)
    assert report["ok"], report
    assert report["total"] == 8
    assert all(item["parity"]["ok"] for item in report["benchmarks"])
    assert all(item["metrics"]["repeat"] == 3 for item in report["benchmarks"])
    assert all(len(item["metrics"]["samples"]["compile_seconds"]) == 3 for item in report["benchmarks"])
    assert all(not item["metrics"]["fallback_used"] for item in report["benchmarks"])


def test_engine_result_normalizes_user_visible_errors() -> None:
    result = normalize_engine_result(
        engine="vm",
        returncode=1,
        stdout="",
        stderr=(
            "error: NameError: Undefined variable 'missing'\n"
            "  --> /tmp/main.sprout:2:10\n"
            "stack:\n"
            "  at crash (/tmp/main.sprout:2:10)\n"
            "  called at /tmp/main.sprout:4:1\n"
        ),
    )
    assert result.error_type == "NameError"
    assert result.error_message == "Undefined variable 'missing'"
    assert result.source_path == "/tmp/main.sprout"
    assert (result.line, result.col) == (2, 10)
    assert result.frames == [
        "crash (/tmp/main.sprout:2:10)",
        "called at /tmp/main.sprout:4:1",
    ]
    assert result.vm_supported is True
    assert result.fallback_used is False


def test_strict_vm_reports_unsupported_without_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "unsupported.sprout"
        path.write_text("break\n", encoding="utf-8")
        strict = run_engine(path, engine="vm", allow_fallback=False)
        fallback = run_engine(path, engine="vm", allow_fallback=True)

    assert strict.exit_code == 1
    assert strict.vm_supported is False
    assert strict.fallback_used is False
    assert "break outside a loop" in strict.error_message
    assert fallback.fallback_used is True


def test_engine_comparison_classifies_differences() -> None:
    stable = normalize_engine_result(
        engine="interpreter",
        returncode=0,
        stdout="one\n",
        stderr="",
    )
    same = normalize_engine_result(
        engine="vm",
        returncode=0,
        stdout="one\n",
        stderr="",
    )
    different = normalize_engine_result(
        engine="vm",
        returncode=0,
        stdout="two\n",
        stderr="",
    )
    timed_out = normalize_engine_result(
        engine="vm",
        returncode=None,
        stdout="",
        stderr="",
        timed_out=True,
    )
    unsupported = normalize_engine_result(
        engine="vm",
        returncode=1,
        stdout="",
        stderr="error: experimental VM does not support this yet: feature\n",
    )
    assert compare_engine_results(stable, same) == []
    assert compare_engine_results(stable, different) == ["output-mismatch"]
    assert "timeout" in compare_engine_results(stable, timed_out)
    assert "vm-unsupported" in compare_engine_results(stable, unsupported)


def test_vm_runtime_error_locations_match_interpreter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "function_error.sprout"
        path.write_text(
            "def crash():\n"
            "  return missing_value\n"
            "crash()\n",
            encoding="utf-8",
        )
        stable = run_engine(path, engine="interpreter")
        vm = run_engine(path, engine="vm")
    assert compare_engine_results(stable, vm) == [], (stable, vm)


def test_engine_runs_isolate_module_caches() -> None:
    path = ROOT / "sprout_core" / "conformance" / "modules.sprout"
    first = run_engine(path, engine="interpreter")
    second = run_engine(path, engine="interpreter")
    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout == "1\n1\n1\n"


def main() -> int:
    test_conformance_corpus()
    test_vm_construct_coverage()
    test_vm_construct_coverage_is_derived_from_parser()
    test_seeded_fuzzer_is_repeatable()
    test_mismatch_reducer_is_bounded_and_preserves_failure()
    test_machine_readable_commands()
    test_benchmark_suite_uses_medians_and_strict_parity()
    test_engine_result_normalizes_user_visible_errors()
    test_strict_vm_reports_unsupported_without_fallback()
    test_engine_comparison_classifies_differences()
    test_vm_runtime_error_locations_match_interpreter()
    test_engine_runs_isolate_module_caches()
    print("sprout quality tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
