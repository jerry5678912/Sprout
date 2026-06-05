#!/usr/bin/env python3
"""Tests for Sprout semantic workspace intelligence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.analysis import (
    build_workspace_index,
    member_completions,
    signature_for,
    symbol_at,
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
    test_cli_intelligence_queries()
    print("sprout intellisense tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
