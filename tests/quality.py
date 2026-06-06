#!/usr/bin/env python3
"""Regression tests for conformance and deterministic fuzz infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.quality import conformance_suite, fuzz_suite  # noqa: E402


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


def main() -> int:
    test_conformance_corpus()
    test_seeded_fuzzer_is_repeatable()
    test_machine_readable_commands()
    print("sprout quality tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
