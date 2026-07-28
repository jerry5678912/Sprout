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
    compare_engine_results,
    conformance_suite,
    fuzz_suite,
    normalize_engine_result,
    run_engine,
)


def test_conformance_corpus() -> None:
    report = conformance_suite()
    assert report["ok"], report
    assert report["total"] >= 6
    assert sum(1 for case in report["cases"] if case["vm_checked"]) >= 4


def test_seeded_fuzzer_is_repeatable() -> None:
    first = fuzz_suite(iterations=20, seed=20260606)
    second = fuzz_suite(iterations=20, seed=20260606)
    assert first["ok"], first
    assert second["ok"], second
    assert first == second
    assert first["valid_programs"] == 20
    assert first["malformed_programs"] == 20


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
    assert compare_engine_results(stable, same) == []
    assert compare_engine_results(stable, different) == ["output-mismatch"]


def main() -> int:
    test_conformance_corpus()
    test_seeded_fuzzer_is_repeatable()
    test_machine_readable_commands()
    test_engine_result_normalizes_user_visible_errors()
    test_strict_vm_reports_unsupported_without_fallback()
    test_engine_comparison_classifies_differences()
    print("sprout quality tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
