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
    SemanticSymbol,
    Location,
    ValueFacts,
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


def test_value_facts_join_tracks_conditional_members_and_nilability() -> None:
    left = ValueFacts.object(
        {"name": ValueFacts.of_type("String"), "hp": ValueFacts.of_type("Int")}
    )
    right = ValueFacts.object(
        {"name": ValueFacts.of_type("String"), "mood": ValueFacts.of_type("String")}
    )
    merged = left.join(right)

    assert merged.type_name == "Dict[String, Int | String]"
    assert merged.members["name"].presence == "required"
    assert merged.members["hp"].presence == "conditional"
    assert merged.members["mood"].presence == "conditional"

    nilable = ValueFacts.of_type("String").join(ValueFacts.of_type("Nil"))
    assert nilable.type_name == "Nil | String"
    assert nilable.nilable is True


def test_semantic_symbol_json_exposes_inferred_facts() -> None:
    symbol = SemanticSymbol(
        "player",
        "variable",
        Location("/tmp/player.sprout", 1, 1),
        facts=ValueFacts.object({"name": ValueFacts.of_type("String")}),
    )
    payload = symbol.to_json()
    assert payload["inferredType"] == "Dict[String, String]"
    assert payload["nilable"] is False
    assert payload["memberPresence"] == "required"


def test_nested_function_returns_do_not_leak_into_outer_shape() -> None:
    analysis = analyze_source(
        "def outer():\n"
        "  def inner():\n"
        '    return {"bad": 1}\n'
        '  return {"good": 1}\n',
        str(ROOT / "tmp_nested_return_shape.sprout"),
    )
    outer = analysis.functions["outer"]
    assert set(outer.members) == {"good"}


def test_inferred_facts_flow_through_functions_calls_and_containers() -> None:
    analysis = analyze_source(
        "def make_player(active):\n"
        "  if active:\n"
        '    return {"name": "Mina", "hp": 10}\n'
        '  return {"name": "Mina", "mood": "calm"}\n'
        "\n"
        "player = make_player(True)\n"
        "players = [player]\n"
        "first = players[0]\n",
        str(ROOT / "tmp_function_facts.sprout"),
    )

    function = analysis.functions["make_player"]
    assert function.facts.type_name == "Dict[String, Int | String]"
    assert function.members["name"].member_presence == "required"
    assert function.members["hp"].member_presence == "conditional"
    assert function.members["mood"].member_presence == "conditional"

    player = analysis.variables["player"]
    assert player.facts.type_name == "Dict[String, Int | String]"
    assert set(player.members) == {"name", "hp", "mood"}
    assert analysis.variables["players"].facts.type_name == "List[Dict[String, Int | String]]"
    assert set(analysis.variables["first"].members) == {"name", "hp", "mood"}


def test_call_site_parameter_and_self_field_facts_are_inferred() -> None:
    analysis = analyze_source(
        "class Box:\n"
        "  def init(self, value):\n"
        "    self.value = value\n"
        "\n"
        'box = Box({"label": "ready"})\n',
        str(ROOT / "tmp_self_field_facts.sprout"),
    )

    box_class = analysis.classes["Box"]
    value = box_class.members["value"]
    assert value.facts.type_name == "Dict[String, String]"
    assert set(value.members) == {"label"}
    assert set(analysis.variables["box"].members) >= {"value"}


def test_loop_variable_inherits_iterable_item_facts() -> None:
    analysis = analyze_source(
        'items = [{"title": "one"}]\n'
        "for item in items:\n"
        "  say item.title\n",
        str(ROOT / "tmp_loop_item_facts.sprout"),
    )
    item = next(symbol for symbol in analysis.symbols if symbol.name == "item")
    assert item.facts.type_name == "Dict[String, String]"
    assert set(item.members) == {"title"}


def test_conditional_members_have_mode_aware_diagnostics_and_ranking() -> None:
    source = (
        "def make(active):\n"
        "  if active:\n"
        '    return {"name": "Mina", "hp": 10}\n'
        '  return {"name": "Mina", "mood": "calm"}\n'
        "\n"
        "player = make(True)\n"
        "say player.hp\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "conditional.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        members = member_completions(index, str(path), "player")

    conditional = next(item for item in diagnostics if item.code == "SPROUT_POSSIBLY_MISSING_MEMBER")
    assert conditional.data["member"] == "hp"
    assert "SPROUT_POSSIBLY_MISSING_MEMBER" not in {
        item.code for item in apply_diagnostic_policy(diagnostics, "basic")
    }
    assert next(
        item for item in apply_diagnostic_policy(diagnostics, "standard")
        if item.code == "SPROUT_POSSIBLY_MISSING_MEMBER"
    ).severity == "warning"
    assert next(
        item for item in apply_diagnostic_policy(diagnostics, "strict")
        if item.code == "SPROUT_POSSIBLY_MISSING_MEMBER"
    ).severity == "error"
    assert members[0].name == "name"
    assert members[0].member_presence == "required"
    assert {item.name for item in members[1:]} == {"hp", "mood"}
    assert {item.member_presence for item in members[1:]} == {"conditional"}


def test_imported_function_facts_flow_into_callers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        factory = root / "factory.sprout"
        main = root / "main.sprout"
        factory.write_text(
            "def make():\n"
            '  return {"title": "imported", "meta": {"ready": True}}\n',
            encoding="utf-8",
        )
        main.write_text(
            "import factory as factory\n"
            "item = factory.make()\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        analysis = index.files[str(main.resolve())]

    assert set(analysis.variables["item"].members) == {"title", "meta"}
    assert set(analysis.variables["item"].members["meta"].members) == {"ready"}


def test_recursive_and_mutually_recursive_summaries_converge() -> None:
    analysis = analyze_source(
        "def countdown(value):\n"
        "  if value <= 0:\n"
        '    return {"done": True}\n'
        "  return countdown(value - 1)\n"
        "\n"
        "def left(flag):\n"
        "  if flag:\n"
        '    return {"side": "left"}\n'
        "  return right(True)\n"
        "\n"
        "def right(flag):\n"
        "  if flag:\n"
        '    return {"side": "right"}\n'
        "  return left(True)\n"
        "\n"
        "result = countdown(3)\n"
        "pair = left(false)\n",
        str(ROOT / "tmp_recursive_facts.sprout"),
    )
    assert set(analysis.functions["countdown"].members) == {"done"}
    assert set(analysis.variables["result"].members) == {"done"}
    assert set(analysis.functions["left"].members) == {"side"}
    assert set(analysis.functions["right"].members) == {"side"}
    assert set(analysis.variables["pair"].members) == {"side"}


def test_imported_identity_uses_call_site_facts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        main = root / "main.sprout"
        helper.write_text(
            "def identity(value):\n"
            "  return value\n",
            encoding="utf-8",
        )
        main.write_text(
            "import helper as helper\n"
            'item = helper.identity({"label": "cross-file"})\n',
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        analysis = index.files[str(main.resolve())]

    assert set(analysis.variables["item"].members) == {"label"}


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
    source = "times = 3\nrnage(timse)\n"
    analysis = analyze_source(source, str(ROOT / "tmp_code_word_typos.sprout"))
    diagnostics = [item for item in analysis.diagnostics if item.code == "SPROUT_UNKNOWN_NAME"]
    by_message = {item.message: item for item in diagnostics}
    assert any("Did you mean 'range'?" in message for message in by_message)
    assert any("Did you mean 'times'?" in message for message in by_message)
    assert {item.data.get("replacement") for item in diagnostics} >= {"range", "times"}
    strict = apply_diagnostic_policy(diagnostics, "strict")
    assert {item.severity for item in strict} == {"warning"}


def test_removed_python_aliases_suggest_sprout_replacements() -> None:
    source = "value = None\nprint(value)\nflag = true\nother = False\n"
    analysis = analyze_source(source, str(ROOT / "tmp_removed_aliases.sprout"))
    diagnostics = [item for item in analysis.diagnostics if item.code == "SPROUT_UNKNOWN_NAME"]
    replacements = {item.message: item.data.get("replacement") for item in diagnostics}
    assert any(replacement == "nil" for replacement in replacements.values())
    assert any(replacement == "say" for replacement in replacements.values())
    assert any(replacement == "True" for replacement in replacements.values())
    assert any(replacement == "false" for replacement in replacements.values())


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


def test_variable_reference_after_string_keeps_real_column() -> None:
    source = (
        "def hello(count, mood):\n"
        "  for i in range(count):\n"
        "    say(\"Hello! I'm feeling \" + mood + \" today!\")\n"
    )
    analysis = analyze_source(source, str(ROOT / "tmp_string_reference_columns.sprout"))
    mood_ref = next(
        item for item in analysis.references
        if item.name == "mood" and item.role == "read"
    )
    expected_col = source.splitlines()[2].index("mood") + 1
    assert mood_ref.location.line == 3
    assert mood_ref.location.col == expected_col


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


def test_dynamic_state_member_inference() -> None:
    source = (
        "state = {}\n"
        'state.keys = {"left": false, "right": false}\n'
        "state.cam = {}\n"
        "state.cam.yaw = 0\n"
        "say state.keys.left, state.cam.yaw\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state_shape.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "state"))
        assert {"keys", "cam"}.issubset(members)


def test_wrapper_returned_dict_members_are_visible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        main = root / "main.sprout"
        helper.write_text(
            "def window():\n"
            '  return {"base": 1, "core": 2}\n',
            encoding="utf-8",
        )
        main.write_text(
            'import "helper.sprout" as helper\n'
            "world = helper.window()\n"
            "say world.base, world.core\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        diagnostics = index.files[str(main.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(main), "world"))
        assert {"base", "core"}.issubset(members)


def test_shape_flows_through_variable_aliases() -> None:
    source = (
        'state = {"keys": {"left": false, "right": false}}\n'
        "keys = state.keys\n"
        "say keys.left, keys.right\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "alias_shape.sprout"
        path.write_text(source, encoding="utf-8")
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        assert not any(item.code == "SPROUT_UNUSED_NAME" and "keys" in item.message for item in diagnostics)
        members = names(member_completions(index, str(path), "keys"))
        assert {"left", "right"}.issubset(members)


def test_shape_flows_from_wrapper_result_into_nested_alias() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        main = root / "main.sprout"
        helper.write_text(
            "def window():\n"
            '  return {"base": {"width": 320, "height": 200}, "core": 2}\n',
            encoding="utf-8",
        )
        main.write_text(
            'import "helper.sprout" as helper\n'
            "world = helper.window()\n"
            "base = world.base\n"
            "say base.width, base.height\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        diagnostics = index.files[str(main.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(main), "base"))
        assert {"width", "height"}.issubset(members)


def test_nested_member_completion_on_chain() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        main = root / "main.sprout"
        helper.write_text(
            "def window():\n"
            '  return {"base": {"width": 320, "height": 200}, "core": 2}\n',
            encoding="utf-8",
        )
        main.write_text(
            'import "helper.sprout" as helper\n'
            "world = helper.window()\n"
            "say world.base.width\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(root))
        diagnostics = index.files[str(main.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(main), "world.base"))
        assert {"width", "height"}.issubset(members)


def test_branchy_wrapper_return_merges_member_shapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            "def make(flag):\n"
            "  if flag:\n"
            '    return {"base": {"w": 1}}\n'
            '  return {"base": {"h": 2}}\n'
            "world = make(True)\n"
            "say world.base.w\n"
            "say world.base.h\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "world.base"))
        assert {"w", "h"}.issubset(members)


def test_reassigned_variable_replaces_straight_line_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'world = {"base": {"w": 1}}\n'
            'world = {"base": {"h": 2}}\n'
            "say world.base.w\n"
            "say world.base.h\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert any(item.code == "SPROUT_UNKNOWN_MEMBER" and "'w'" in item.message for item in diagnostics)
        members = names(member_completions(index, str(path), "world.base"))
        assert members == {"h"}


def test_branch_assigned_variable_merges_member_shapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            "if True:\n"
            '  world = {"base": {"w": 1}}\n'
            "else:\n"
            '  world = {"base": {"h": 2}}\n'
            "say world.base.w\n"
            "say world.base.h\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "world.base"))
        assert {"w", "h"}.issubset(members)


def test_branch_assigned_alias_merges_nested_member_shapes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            "if True:\n"
            '  state = {"cam": {"yaw": 1}}\n'
            "else:\n"
            '  state = {"cam": {"pitch": 2}}\n'
            "cam = state.cam\n"
            "say cam.yaw\n"
            "say cam.pitch\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "cam"))
        assert {"yaw", "pitch"}.issubset(members)


def test_indexed_dict_alias_preserves_member_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'world = {"base": {"w": 1, "h": 2}}\n'
            'base = world["base"]\n'
            "say base.w\n"
            "say base.h\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "base"))
        assert {"w", "h"}.issubset(members)


def test_get_builtin_alias_preserves_member_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'world = {"base": {"w": 1, "h": 2}}\n'
            'base = get(world, "base", {})\n'
            "say base.w\n"
            "say base.h\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "base"))
        assert {"w", "h"}.issubset(members)


def test_get_builtin_default_shape_is_merged_when_key_may_be_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            "state = {}\n"
            'cam = get(state, "cam", {"yaw": 0, "pitch": 1})\n'
            "say cam.yaw\n"
            "say cam.pitch\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "cam"))
        assert {"yaw", "pitch"}.issubset(members)


def test_indexed_array_element_alias_preserves_member_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'items = [{"name": "a", "hp": 1}]\n'
            "first = items[0]\n"
            "say first.name\n"
            "say first.hp\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "first"))
        assert {"name", "hp"}.issubset(members)


def test_indexed_nested_value_alias_preserves_member_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'world = {"base": {"w": 1}}\n'
            'items = [world["base"]]\n'
            "first = items[0]\n"
            "say first.w\n",
            encoding="utf-8",
        )
        index = build_workspace_index(str(path))
        diagnostics = index.files[str(path.resolve())].diagnostics
        assert not any(item.code == "SPROUT_UNKNOWN_MEMBER" for item in diagnostics)
        members = names(member_completions(index, str(path), "first"))
        assert {"w"}.issubset(members)


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


def extension_folding_ranges(source: str) -> list[dict]:
    script = (
        "const ext=require(process.argv[1]);"
        "const source=process.argv[2];"
        "process.stdout.write(JSON.stringify(ext.computeSproutFoldingRanges(source)));"
    )
    output = subprocess.check_output(
        ["node", "-e", script, str(ROOT / "editor" / "vscode-sprout" / "folding.js"), source],
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


def test_extension_folding_ranges_cover_dedents_and_block_styles() -> None:
    source = (
        "def hello(times):\n"
        "  for i in range(times):\n"
        "    say \"Hello\"\n"
        "\n"
        "k = 3\n"
        "\n"
        "def garden(times) bloom\n"
        "  if times > 0 bloom\n"
        "    say times\n"
        "  end\n"
        "end\n"
        "\n"
        "def braces(times) {\n"
        "  if times > 0 {\n"
        "    say times\n"
        "  }\n"
        "}\n"
    )
    ranges = extension_folding_ranges(source)
    assert {"start": 0, "end": 2, "kind": "region"} in ranges
    assert {"start": 1, "end": 2, "kind": "region"} in ranges
    assert {"start": 6, "end": 10, "kind": "region"} in ranges
    assert {"start": 7, "end": 9, "kind": "region"} in ranges
    assert {"start": 12, "end": 16, "kind": "region"} in ranges
    assert {"start": 13, "end": 15, "kind": "region"} in ranges
    assert all(item["end"] < 4 or item["start"] > 4 for item in ranges)


def test_extension_uses_offside_folding_for_blank_line_guides() -> None:
    configuration = json.loads(
        (ROOT / "editor" / "vscode-sprout" / "language-configuration.json").read_text(encoding="utf-8")
    )
    assert configuration["folding"]["offSide"] is True


def test_lsp_client_prefers_server_next_to_selected_runner() -> None:
    script = (
        "const path = require('path');"
        "const client = require(process.argv[1]);"
        "const candidates = client.languageServerCandidates("
        "'/workspace/sprout.py', '/extension');"
        "process.stdout.write(JSON.stringify(candidates));"
    )
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(ROOT / "editor" / "vscode-sprout" / "lsp-client.js"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    candidates = json.loads(result.stdout)
    assert candidates[0] == str(Path("/workspace/tools/sprout_lsp.py"))
    assert candidates[1] == str(Path("/extension/tools/sprout_lsp.py"))


def test_extension_folding_supports_localized_garden_blocks() -> None:
    source = (
        "定义 问候(次数) 开始\n"
        "  如果 次数 > 0 开始\n"
        "    输出 次数\n"
        "  结束\n"
        "结束\n"
        "\n"
        "结果 = 3\n"
    )
    ranges = extension_folding_ranges(source)
    assert {"start": 0, "end": 4, "kind": "region"} in ranges
    assert {"start": 1, "end": 3, "kind": "region"} in ranges
    assert all(item["end"] < 6 for item in ranges)


def main() -> int:
    test_value_facts_join_tracks_conditional_members_and_nilability()
    test_semantic_symbol_json_exposes_inferred_facts()
    test_nested_function_returns_do_not_leak_into_outer_shape()
    test_inferred_facts_flow_through_functions_calls_and_containers()
    test_call_site_parameter_and_self_field_facts_are_inferred()
    test_loop_variable_inherits_iterable_item_facts()
    test_conditional_members_have_mode_aware_diagnostics_and_ranking()
    test_imported_function_facts_flow_into_callers()
    test_recursive_and_mutually_recursive_summaries_converge()
    test_imported_identity_uses_call_site_facts()
    test_class_member_completion()
    test_project_module_exports()
    test_named_standard_library_exports()
    test_editor_diagnostics_include_import_and_unused_warnings()
    test_diagnostic_modes_and_unknown_members()
    test_unknown_name_suggests_keyword_typo()
    test_unknown_name_suggests_builtin_and_local_typos()
    test_removed_python_aliases_suggest_sprout_replacements()
    test_import_and_member_typos_have_replacements()
    test_hover_and_signature_data()
    test_variable_reference_after_string_keeps_real_column()
    test_references_and_rename_edits()
    test_rename_safe_filters_module_aliases()
    test_python_module_members()
    test_scope_aware_references_and_rename()
    test_scope_aware_completions()
    test_completion_ranking_prefers_local_prefix_matches()
    test_member_completion_filters_by_prefix()
    test_dynamic_state_member_inference()
    test_wrapper_returned_dict_members_are_visible()
    test_shape_flows_through_variable_aliases()
    test_shape_flows_from_wrapper_result_into_nested_alias()
    test_nested_member_completion_on_chain()
    test_branchy_wrapper_return_merges_member_shapes()
    test_reassigned_variable_replaces_straight_line_shape()
    test_branch_assigned_variable_merges_member_shapes()
    test_branch_assigned_alias_merges_nested_member_shapes()
    test_indexed_dict_alias_preserves_member_shape()
    test_get_builtin_alias_preserves_member_shape()
    test_indexed_array_element_alias_preserves_member_shape()
    test_indexed_nested_value_alias_preserves_member_shape()
    test_incremental_workspace_updates()
    test_reassignment_keeps_binding()
    test_standard_mode_surfaces_deeper_flow_diagnostics()
    test_cli_intelligence_queries()
    test_extension_folding_ranges_cover_dedents_and_block_styles()
    test_extension_uses_offside_folding_for_blank_line_guides()
    test_lsp_client_prefers_server_next_to_selected_runner()
    test_extension_folding_supports_localized_garden_blocks()
    print("sprout intellisense tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
