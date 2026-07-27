#!/usr/bin/env python3
"""Structured tests for Sprout tooling commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SPROUT = ROOT / "sprout.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(SPROUT), *args], cwd=ROOT, text=True, capture_output=True, check=check)


def test_check_json_ok() -> None:
    result = run("check", "examples/fibonacci.sprout", "--json")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["diagnostics"] == []
    assert any(symbol["name"] == "fib" for symbol in payload["symbols"])


def test_check_json_error() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("def bad(:\n")
        path = fh.name
    result = run("check", path, "--json", check=False)
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["severity"] == "error"
    assert payload["diagnostics"][0]["line"] is not None


def test_project_run() -> None:
    result = run("run", "examples/project")
    assert "project: Mina 2 3" in result.stdout


def test_fmt_safe_output() -> None:
    result = run("fmt", "examples/seedfn.sprout")
    assert "double = seedfn x: x * 2" in result.stdout
    assert result.stdout.endswith("\n")


def test_check_json_import_and_unused_diagnostics() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("import totally_missing_module as m\n")
        bad_import = fh.name
    result = run("check", bad_import, "--json", "--warnings", check=False)
    payload = json.loads(result.stdout)
    codes = {item["code"] for item in payload["diagnostics"]}
    assert "SPROUT_IMPORT" in codes
    assert "SPROUT_UNUSED_IMPORT" not in codes
    import_diag = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_IMPORT")
    assert import_diag["line"] == 1
    assert import_diag["col"] == 8

    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("import pixelgarden as pix\n")
        unused_import = fh.name
    result = run("check", unused_import, "--json", "--warnings")
    payload = json.loads(result.stdout)
    unused = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_UNUSED_IMPORT")
    assert unused["severity"] == "hint"
    assert unused["line"] == 1
    assert unused["col"] == 23


def test_import_context_completion_suggests_modules() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("import pixel\n")
        path = fh.name
    result = run(
        "intel",
        path,
        "--kind",
        "completions",
        "--line",
        "1",
        "--col",
        "13",
        "--source",
        path,
    )
    payload = json.loads(result.stdout)
    labels = {item["name"] for item in payload["items"]}
    assert "pixelgarden" in labels


def test_import_context_completion_does_not_fall_back_to_keywords() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("import ef\n")
        path = fh.name
    result = run(
        "intel",
        path,
        "--kind",
        "completions",
        "--line",
        "1",
        "--col",
        "10",
        "--source",
        path,
    )
    payload = json.loads(result.stdout)
    labels = {item["name"] for item in payload["items"]}
    assert "elif" not in labels
    assert labels == set()


def test_check_warnings_include_semantic_keyword_typos() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("impo\n")
        path = fh.name
    result = run("check", path, "--json", "--warnings")
    payload = json.loads(result.stdout)
    diagnostic = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_UNKNOWN_NAME")
    assert diagnostic["line"] == 1
    assert diagnostic["col"] == 1
    assert "Did you mean 'import'?" in diagnostic["message"]


def test_normal_reassignment_is_not_reported_as_shadowing() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("def bump():\n  score = 1\n  score = 2\n")
        path = fh.name
    result = run("lint", path, "--json")
    payload = json.loads(result.stdout)
    assert "SPROUT_SHADOW" not in {item["code"] for item in payload["diagnostics"]}


def test_duplicate_declarations_are_checked_per_lexical_scope() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write(
            "class First:\n"
            "  def init():\n"
            "    return nil\n"
            "\n"
            "class Second:\n"
            "  def init():\n"
            "    return nil\n"
            "\n"
            "def duplicate():\n"
            "  return 1\n"
            "def duplicate():\n"
            "  return 2\n"
        )
        path = fh.name
    result = run("lint", path, "--json")
    payload = json.loads(result.stdout)
    duplicates = [
        item for item in payload["diagnostics"]
        if item["code"] == "SPROUT_DUP_FUNCTION"
    ]
    assert len(duplicates) == 1
    assert duplicates[0]["line"] == 11


def test_trailing_whitespace_warning_is_reported() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write('say "hi"   \n')
        path = fh.name
    result = run("lint", path, "--json")
    payload = json.loads(result.stdout)
    trailing = next(item for item in payload["diagnostics"] if item["code"] == "SPROUT_TRAILING_WHITESPACE")
    assert trailing["severity"] == "warning"
    assert trailing["line"] == 1
    assert trailing["col"] == len('say "hi"') + 1


def test_blank_indented_line_has_no_style_warning() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write("def hello():\n  say 1\n  \nhello()\n")
        path = fh.name
    result = run("lint", path, "--json")
    payload = json.loads(result.stdout)
    codes = {item["code"] for item in payload["diagnostics"]}
    assert "SPROUT_TRAILING_WHITESPACE" not in codes
    assert "SPROUT_TAB_INDENT" not in codes


def test_pasted_indented_snippet_runs_cleanly() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sprout", delete=False) as fh:
        fh.write(
            "    def hello(count):\n"
            "      for i in range(count):\n"
            '        say "sprout is good"\n'
            "\n"
            "    hello(2)\n"
        )
        path = fh.name
    result = run("run", path)
    assert result.stdout.splitlines() == ["sprout is good", "sprout is good"]


def test_analysis_status_and_rebuild_index_commands() -> None:
    result = run("analysis-status", "examples/editor_test_workspace", "--json")
    payload = json.loads(result.stdout)
    assert payload["fileCount"] >= 1
    assert payload["analysisCount"] >= 1
    assert "lastBuildReason" in payload
    assert "cacheHitRate" in payload
    assert payload["lastBuildDurationMs"] >= 0
    assert "effectiveSettings" in payload

    rebuilt = run("rebuild-index", "examples/editor_test_workspace", "--json")
    rebuilt_payload = json.loads(rebuilt.stdout)
    assert rebuilt_payload["lastBuildReason"] == "manual-rebuild"
    assert rebuilt_payload["lastReindexedFiles"]
    assert rebuilt_payload["lastReindexedDurationMs"] >= 0


def test_vscode_editor_behavior_script() -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "tools" / "check_vscode_editor_behavior.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "sprout vscode editor behavior check passed" in result.stdout


def main() -> int:
    test_check_json_ok()
    test_check_json_error()
    test_project_run()
    test_fmt_safe_output()
    test_check_json_import_and_unused_diagnostics()
    test_import_context_completion_suggests_modules()
    test_import_context_completion_does_not_fall_back_to_keywords()
    test_check_warnings_include_semantic_keyword_typos()
    test_normal_reassignment_is_not_reported_as_shadowing()
    test_duplicate_declarations_are_checked_per_lexical_scope()
    test_trailing_whitespace_warning_is_reported()
    test_blank_indented_line_has_no_style_warning()
    test_pasted_indented_snippet_runs_cleanly()
    test_analysis_status_and_rebuild_index_commands()
    test_vscode_editor_behavior_script()
    print("sprout tooling tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
