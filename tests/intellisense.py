#!/usr/bin/env python3
"""Tests for Sprout semantic workspace intelligence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.analysis import (
    build_workspace_index,
    member_completions,
    references_at,
    signature_for,
    symbol_at,
    symbol_at_position,
    top_level_completions,
)


def names(symbols):
    return {symbol.name for symbol in symbols}


def test_class_member_completion() -> None:
    path = str(ROOT / "examples" / "intellisense.sprout")
    index = build_workspace_index(path)
    members = names(member_completions(index, path, "player"))
    assert {"name", "hp", "hurt"}.issubset(members)


def test_project_module_exports() -> None:
    root = str(ROOT / "examples" / "project")
    index = build_workspace_index(root)
    main = str(ROOT / "examples" / "project" / "src" / "main.sprout")
    assert {"make", "move"}.issubset(names(member_completions(index, main, "player")))
    assert {"vec2"}.issubset(names(member_completions(index, main, "vec")))
    make = symbol_at_position(index, main, 4, 16, "make")
    assert make is not None
    refs = references_at(index, main, 4, 16, "make")
    assert {(Path(ref.location.path).name, ref.location.line) for ref in refs} == {
        ("player.sprout", 1),
        ("main.sprout", 4),
    }


def test_hover_and_signature_data() -> None:
    path = str(ROOT / "examples" / "intellisense.sprout")
    index = build_workspace_index(path)
    spawn = symbol_at(index, path, "spawn")
    assert spawn is not None
    assert spawn.signature == "spawn(name, hp=...)"
    assert "Create a named player" in spawn.documentation
    assert signature_for(index, path, "spawn").signature == "spawn(name, hp=...)"


def test_references_and_rename_edits() -> None:
    path = str(ROOT / "examples" / "intellisense.sprout")
    index = build_workspace_index(path)
    refs = index.references_to("player")
    assert len(refs) >= 3
    edits = index.rename_edits("player", "hero")
    assert path in edits
    assert all(edit["newText"] == "hero" for edit in edits[path])


def test_python_module_members() -> None:
    source = ROOT / "examples" / "pythonlibs.sprout"
    index = build_workspace_index(str(source))
    assert "sqrt" in names(member_completions(index, str(source), "math"))


def test_scope_aware_references_and_rename() -> None:
    source = """def first(value):
  local = value + 1
  return local

def second(value):
  local = value + 2
  return local

say first(1), second(2)
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scopes.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        first_value = symbol_at_position(index, str(path), 2, 12, "value")
        second_value = symbol_at_position(index, str(path), 6, 12, "value")
        assert first_value is not None and second_value is not None
        assert first_value.symbol_id != second_value.symbol_id
        first_refs = references_at(index, str(path), 2, 12, "value")
        second_refs = references_at(index, str(path), 6, 12, "value")
        assert {(ref.location.line, ref.location.col) for ref in first_refs} == {(1, 11), (2, 11)}
        assert {(ref.location.line, ref.location.col) for ref in second_refs} == {(5, 12), (6, 11)}
        edits = index.rename_edits("value", "amount", first_value.symbol_id)
        assert len(edits[str(path.resolve())]) == 2


def test_scope_aware_completions() -> None:
    source = """outside = 1
def calculate(input):
  inside = input + outside
  say inside

say outside
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "complete.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        inside_names = names(top_level_completions(index, str(path), 4))
        outside_names = names(top_level_completions(index, str(path), 6))
        assert {"input", "inside", "outside", "calculate"}.issubset(inside_names)
        assert "inside" not in outside_names
        assert "input" not in outside_names


def test_incremental_workspace_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "first.sprout"
        second = root / "second.sprout"
        first.write_text('value = 1\nsay value\n', encoding="utf-8")
        second.write_text('other = 2\nsay other\n', encoding="utf-8")
        index = build_workspace_index(str(root))
        initial_count = index.analysis_count
        same_index = build_workspace_index(str(root), previous=index)
        assert same_index is index
        assert index.analysis_count == initial_count
        changed = 'value = 3\nsay value\n'
        build_workspace_index(str(root), {str(first.resolve()): changed}, previous=index)
        assert index.analysis_count == initial_count + 1
        assert index.files[str(first.resolve())].source == changed


def test_reassignment_keeps_binding() -> None:
    source = "score = 1\nscore = score + 1\nsay score\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "assignment.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        symbol = symbol_at_position(index, str(path), 3, 6, "score")
        assert symbol is not None
        refs = references_at(index, str(path), 3, 6, "score")
        assert {(ref.location.line, ref.role) for ref in refs} == {
            (1, "declaration"),
            (2, "write"),
            (2, "read"),
            (3, "read"),
        }


def intel(kind: str, line: int, col: int) -> dict:
    path = ROOT / "examples" / "intellisense.sprout"
    output = subprocess.check_output(
        [sys.executable, str(ROOT / "sprout.py"), "intel", str(path), "--kind", kind, "--line", str(line), "--col", str(col)],
        text=True,
    )
    return json.loads(output)


def test_cli_intelligence_queries() -> None:
    completion = intel("completions", 20, 8)
    assert completion["base"] == "player"
    assert {"name", "hp", "hurt"}.issubset({item["name"] for item in completion["items"]})

    dotted_prefix = intel("completions", 20, 9)
    assert dotted_prefix["base"] == "player"
    assert {"hp", "hurt"}.issubset({item["name"] for item in dotted_prefix["items"]})
    assert "harvest" not in {item["name"] for item in dotted_prefix["items"]}

    hover = intel("hover", 14, 6)
    assert hover["symbol"]["signature"] == "spawn(name, hp=...)"
    assert "Create a named player" in hover["symbol"]["documentation"]

    signature = intel("signature", 17, 17)
    assert signature["signature"]["signature"] == "Player(name, hp=...)"

    diagnostics = intel("diagnostics", 1, 1)
    assert diagnostics["diagnostics"] == []


def main() -> int:
    test_class_member_completion()
    test_project_module_exports()
    test_hover_and_signature_data()
    test_references_and_rename_edits()
    test_python_module_members()
    test_scope_aware_references_and_rename()
    test_scope_aware_completions()
    test_incremental_workspace_updates()
    test_reassignment_keeps_binding()
    test_cli_intelligence_queries()
    print("sprout intellisense tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
