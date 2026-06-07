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
    analyze_source,
    apply_diagnostic_policy,
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


def test_imported_factory_member_completion() -> None:
    root = str(ROOT / "examples" / "editor_test_workspace")
    main = str(ROOT / "examples" / "editor_test_workspace" / "src" / "main.sprout")
    index = build_workspace_index(root)
    members = names(member_completions(index, main, "player"))
    assert {"name", "hp", "greet", "hurt"}.issubset(members)


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


def test_named_standard_library_exports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "main.sprout"
        source.write_text("import pixelgarden as pix\nsay pix.vec2(1, 2)\n", encoding="utf-8")
        index = build_workspace_index(str(source))
        assert {"vec2", "sprite_asset", "animation"}.issubset(names(member_completions(index, str(source), "pix")))


def test_editor_diagnostics_include_import_and_unused_warnings() -> None:
    bad_import = analyze_source("import totally_missing_module as m\n", str(ROOT / "tmp_bad_import.sprout"))
    by_code = {diag.code: diag for diag in bad_import.diagnostics}
    assert "SPROUT_IMPORT" in by_code
    assert "SPROUT_UNUSED_IMPORT" not in by_code
    assert "SPROUT_UNKNOWN_NAME" not in by_code
    assert by_code["SPROUT_IMPORT"].line == 1
    assert by_code["SPROUT_IMPORT"].col == 8

    unused_import = analyze_source("import pixelgarden as pix\n", str(ROOT / "tmp_unused_import.sprout"))
    by_code = {diag.code: diag for diag in unused_import.diagnostics}
    assert "SPROUT_UNUSED_IMPORT" in by_code
    assert apply_diagnostic_policy([by_code["SPROUT_UNUSED_IMPORT"]], "basic")[0].severity == "hint"
    assert by_code["SPROUT_UNUSED_IMPORT"].line == 1
    assert by_code["SPROUT_UNUSED_IMPORT"].col == 23


def test_diagnostic_modes_and_unknown_members() -> None:
    source = """import pixelgarden as pix
def greet(name, unused):
  return name

say pix.not_a_real_member()
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics

    basic = {diag.code: diag for diag in apply_diagnostic_policy(diagnostics, "basic")}
    strict = {diag.code: diag for diag in apply_diagnostic_policy(diagnostics, "strict")}
    off = {diag.code: diag for diag in apply_diagnostic_policy(diagnostics, "off")}

    assert basic["SPROUT_UNKNOWN_MEMBER"].severity == "warning"
    assert "SPROUT_MISSING_PARAMETER_TYPE" not in basic
    assert strict["SPROUT_UNKNOWN_MEMBER"].severity == "error"
    assert strict["SPROUT_MISSING_PARAMETER_TYPE"].severity == "warning"
    assert strict["SPROUT_MISSING_RETURN_TYPE"].severity == "warning"
    assert off == {}

    overridden = apply_diagnostic_policy(
        diagnostics,
        "strict",
        {"SPROUT_UNKNOWN_MEMBER": "information", "SPROUT_UNUSED_PARAMETER": "none"},
    )
    by_code = {diag.code: diag for diag in overridden}
    assert by_code["SPROUT_UNKNOWN_MEMBER"].severity == "information"
    assert "SPROUT_UNUSED_PARAMETER" not in by_code


def test_unknown_name_suggests_keyword_typo() -> None:
    analysis = analyze_source("impo\n", str(ROOT / "tmp_keyword_typo.sprout"))
    diagnostic = next(item for item in analysis.diagnostics if item.code == "SPROUT_UNKNOWN_NAME")
    assert diagnostic.line == 1
    assert diagnostic.col == 1
    assert "Did you mean 'import'?" in diagnostic.message
    assert diagnostic.data["replacement"] == "import"


def test_unknown_name_suggests_builtin_and_local_typos() -> None:
    source = "times = 3\npritn(timse)\n"
    analysis = analyze_source(source, str(ROOT / "tmp_code_word_typos.sprout"))
    diagnostics = [item for item in analysis.diagnostics if item.code == "SPROUT_UNKNOWN_NAME"]
    by_message = {item.message: item for item in diagnostics}
    assert any("Did you mean 'print'?" in message for message in by_message)
    assert any("Did you mean 'times'?" in message for message in by_message)
    assert {item.data.get("replacement") for item in diagnostics} >= {"print", "times"}
    strict = apply_diagnostic_policy(diagnostics, "strict")
    assert {item.severity for item in strict} == {"warning"}


def test_import_and_member_typos_have_replacements() -> None:
    import_diag = next(
        item for item in analyze_source("import pixelgardn as pix\n", str(ROOT / "tmp_import_typo.sprout")).diagnostics
        if item.code == "SPROUT_IMPORT"
    )
    assert import_diag.data["replacement"] == "pixelgarden"

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text("import pixelgarden as pix\nsay pix.vec22(1, 2)\n", encoding="utf-8")
        index = build_workspace_index(str(path))
        diagnostic = next(item for item in index.files[str(path.resolve())].diagnostics if item.code == "SPROUT_UNKNOWN_MEMBER")
        assert diagnostic.data["replacement"] == "vec2"


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


def test_rename_safe_filters_module_aliases() -> None:
    source = 'import "helper.sprout" as helper\nsay helper\n'
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        path = root / "main.sprout"
        helper.write_text("def greet():\n  return 1\n", encoding="utf-8")
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(root))
        symbol = symbol_at_position(index, str(path), 2, 6, "helper")
        from sprout_core.analysis import rename_safe
        assert symbol is not None
        assert rename_safe(symbol) is False


def test_python_module_members() -> None:
    source = ROOT / "examples" / "pythonlibs.sprout"
    index = build_workspace_index(str(source))
    assert "sqrt" in names(member_completions(index, str(source), "math"))


def test_incomplete_named_module_member_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "module_completion.sprout"
        source.write_text("import pixelgarden as pix\npix.\n", encoding="utf-8")
        index = build_workspace_index(str(source), {str(source.resolve()): "import pixelgarden as pix\npix.__sprout_completion__\n"})
        members = names(member_completions(index, str(source), "pix"))
        assert {"vec2", "sprite_asset", "animation"}.issubset(members)


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


def test_completion_ranking_prefers_local_prefix_matches() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        main = root / "main.sprout"
        helper.write_text("def spawn_enemy():\n  return 1\n", encoding="utf-8")
        main.write_text(
            'import "helper.sprout" as helper\n'
            "def spawn():\n"
            "  return 1\n\n"
            "def scope():\n"
            "  speed = 2\n"
            "  sp\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        items = top_level_completions(index, str(main), 7, "sp")
        labels = [item.name for item in items[:3]]
        assert labels[0] == "speed"
        assert "spawn" in labels[:3]


def test_member_completion_filters_by_prefix() -> None:
    path = str(ROOT / "examples" / "intellisense.sprout")
    index = build_workspace_index(path)
    members = [item.name for item in member_completions(index, path, "player", "h")]
    assert members[:2] == ["hp", "hurt"]
    assert "name" not in members


def test_incremental_workspace_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "first.sprout"
        second = root / "second.sprout"
        third = root / "third.sprout"
        first.write_text('import "second.sprout" as second\nvalue = second.other\nsay value\n', encoding="utf-8")
        second.write_text('other = 2\nsay other\n', encoding="utf-8")
        third.write_text('say "independent"\n', encoding="utf-8")
        index = build_workspace_index(str(root))
        initial_count = index.analysis_count
        same_index = build_workspace_index(str(root), previous=index)
        assert same_index is index
        assert index.analysis_count == initial_count
        changed = 'other = 3\nsay other\n'
        build_workspace_index(
            str(root),
            {str(second.resolve()): changed},
            previous=index,
            changed_paths=[str(second.resolve())],
            reason="test-incremental",
        )
        assert index.analysis_count == initial_count + 2
        assert index.files[str(second.resolve())].source == changed
        status = index.status().to_json()
        assert str(second.resolve()) in status["lastChangedPaths"]
        assert str(second.resolve()) in status["lastReindexedFiles"]
        assert str(first.resolve()) in status["lastReindexedFiles"]
        assert str(third.resolve()) not in status["lastReindexedFiles"]
        assert index.cache_misses >= initial_count + 2


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


def test_standard_mode_surfaces_deeper_flow_diagnostics() -> None:
    source = (
        "class Base:\n"
        "  def value(self, amount: Int) -> Int:\n"
        "    return amount\n\n"
        "class Child extends Base:\n"
        "  def value(self, amount: String) -> String:\n"
        "    return amount\n\n"
        "def early() -> Int:\n"
        "  return 1\n"
        "  say 2\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "flow.sprout"
        analysis = analyze_source(source, str(path))
        basic = apply_diagnostic_policy(analysis.diagnostics, "basic")
        standard = apply_diagnostic_policy(analysis.diagnostics, "standard")
        basic_codes = {item.code for item in basic}
        standard_codes = {item.code for item in standard}
        assert "SPROUT_OVERRIDE_SIGNATURE" not in basic_codes
        assert "SPROUT_UNREACHABLE" not in basic_codes
        assert "SPROUT_OVERRIDE_SIGNATURE" in standard_codes
        assert "SPROUT_UNREACHABLE" in standard_codes


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
    test_named_standard_library_exports()
    test_editor_diagnostics_include_import_and_unused_warnings()
    test_diagnostic_modes_and_unknown_members()
    test_unknown_name_suggests_keyword_typo()
    test_unknown_name_suggests_builtin_and_local_typos()
    test_import_and_member_typos_have_replacements()
    test_hover_and_signature_data()
    test_references_and_rename_edits()
    test_rename_safe_filters_module_aliases()
    test_python_module_members()
    test_scope_aware_references_and_rename()
    test_scope_aware_completions()
    test_completion_ranking_prefers_local_prefix_matches()
    test_member_completion_filters_by_prefix()
    test_incremental_workspace_updates()
    test_reassignment_keeps_binding()
    test_standard_mode_surfaces_deeper_flow_diagnostics()
    test_cli_intelligence_queries()
    print("sprout intellisense tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
