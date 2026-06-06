#!/usr/bin/env python3
"""Tests for Sprout async functions, await, and structured task groups."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run_source(source: str, vm: bool = False) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(source, encoding="utf-8")
        args = [sys.executable, str(ROOT / "sprout.py"), "run"]
        if vm:
            args.append("--vm")
        args.append(str(path))
        return subprocess.run(args, text=True, capture_output=True, check=False)


def test_async_await_and_methods() -> None:
    result = run_source(
        "async def double(value):\n"
        "  return value * 2\n\n"
        "class Worker:\n"
        "  async def label(self, value):\n"
        '    return "job-" + str(value)\n\n'
        "worker = Worker()\n"
        "say await double(21)\n"
        "say await worker.label(7)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["42", "job-7"]


def test_taskgroup_waits_and_propagates_failure() -> None:
    result = run_source(
        "events = []\n"
        "async def record(value):\n"
        "  sleep(0.01)\n"
        "  events.append(value)\n"
        "  return value\n\n"
        "taskgroup jobs:\n"
        "  for value in range(25):\n"
        "    jobs.spawn(record, value)\n"
        "say len(events)\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "25"

    failed = run_source(
        "async def broken():\n"
        '  raise "boom"\n\n'
        "try:\n"
        "  await broken()\n"
        "catch err:\n"
        '  say err.contains("boom")\n'
    )
    assert failed.returncode == 0, failed.stderr
    assert failed.stdout.strip() == "true"


def test_await_validation_and_vm_fallback() -> None:
    invalid = run_source("say await 3\n")
    assert invalid.returncode == 1
    assert "await expects an async task" in invalid.stderr

    fallback = run_source(
        "async def value():\n"
        "  return 9\n"
        "say await value()\n",
        vm=True,
    )
    assert fallback.returncode == 0
    assert fallback.stdout.strip() == "9"
    assert "VM fallback to stable interpreter" in fallback.stderr
    assert "Structured async execution" in fallback.stderr


def main() -> int:
    test_async_await_and_methods()
    test_taskgroup_waits_and_propagates_failure()
    test_await_validation_and_vm_fallback()
    print("sprout async language tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
