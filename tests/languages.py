#!/usr/bin/env python3
"""Regression tests for Sprout's data-only language packs."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.languages import (
    bootstrap_language,
    load_language_pack,
    validate_language_pack_data,
)
from sprout_core.analysis import analyze_source
from sprout_core.lexer import Lexer
from sprout_core.model import SproutError
from sprout_core.tooling import format_source


def significant(tokens):
    return [
        (token.kind, token.value, token.line, token.col)
        for token in tokens
        if token.kind not in {"NEWLINE", "INDENT", "DEDENT", "EOF"}
    ]


def test_english_catalog_preserves_canonical_tokens() -> None:
    source = 'def hello(name):\n  say "Hello, " + name\nhello("Jerry")\n'
    assert significant(Lexer(source).tokenize()) == [
        ("DEF", "def", 1, 1),
        ("IDENT", "hello", 1, 5),
        ("(", "(", 1, 10),
        ("IDENT", "name", 1, 11),
        (")", ")", 1, 15),
        (":", ":", 1, 16),
        ("SAY", "say", 2, 3),
        ("STRING", "Hello, ", 2, 7),
        ("+", "+", 2, 17),
        ("IDENT", "name", 2, 19),
        ("IDENT", "hello", 3, 1),
        ("(", "(", 3, 6),
        ("STRING", "Jerry", 3, 7),
        (")", ")", 3, 14),
    ]


def test_bootstrap_scanner_accepts_only_first_meaningful_statement() -> None:
    source = '\ufeff#!/usr/bin/env sprout\n# comment\n\nlanguage "chinese-pack"\n定义 问候():\n  输出 "你好"\n'
    selection = bootstrap_language(source)
    assert selection.pack_id == "chinese-pack"
    assert selection.declaration_line == 4
    assert selection.source.splitlines()[3] == ""
    assert selection.source.splitlines()[4] == "定义 问候():"

    try:
        bootstrap_language('say "hello"\nlanguage "chinese-pack"\n')
    except SproutError as exc:
        assert "first meaningful statement" in str(exc)
    else:
        raise AssertionError("late language declaration should be rejected")


def test_analysis_ignores_bootstrap_after_leading_comments() -> None:
    source = (
        "# localized module\n"
        "\n"
        'language "chinese-pack"\n'
        "定义 问候():\n"
        '  输出 "你好"\n'
    )
    analysis = analyze_source(source, "/tmp/localized.sprout")
    assert not any(
        diagnostic.code == "SPROUT_UNKNOWN_NAME"
        and diagnostic.data
        and diagnostic.data.get("name") == "language"
        for diagnostic in analysis.diagnostics
    )


def test_chinese_keywords_emit_canonical_tokens_and_preserve_spelling() -> None:
    source = (
        'language "chinese-pack"\n'
        "定义 打招呼(名字):\n"
        '  输出 "你好，" + 名字\n'
        '打招呼("小明")\n'
    )
    tokens = Lexer(source).tokenize()
    assert significant(tokens) == [
        ("DEF", "def", 2, 1),
        ("IDENT", "打招呼", 2, 4),
        ("(", "(", 2, 7),
        ("IDENT", "名字", 2, 8),
        (")", ")", 2, 10),
        (":", ":", 2, 11),
        ("SAY", "say", 3, 3),
        ("STRING", "你好，", 3, 6),
        ("+", "+", 3, 12),
        ("IDENT", "名字", 3, 14),
        ("IDENT", "打招呼", 4, 1),
        ("(", "(", 4, 4),
        ("STRING", "小明", 4, 5),
        (")", ")", 4, 9),
    ]
    assert next(token for token in tokens if token.kind == "DEF").source_value == "定义"
    assert next(token for token in tokens if token.kind == "SAY").source_value == "输出"


def test_none_is_an_identifier_not_a_nil_literal() -> None:
    tokens = Lexer("none = 7\nsay none\n").tokenize()
    assert significant(tokens) == [
        ("IDENT", "none", 1, 1),
        ("=", "=", 1, 6),
        ("NUMBER", 7, 1, 8),
        ("SAY", "say", 2, 1),
        ("IDENT", "none", 2, 5),
    ]


def test_reviewed_aliases_are_accepted_but_preferred_spelling_is_stable() -> None:
    pack = load_language_pack("chinese-pack")
    assert pack.preferred("syntax.function") == "定义"
    assert pack.keyword("函数").canonical == "def"


def test_curated_chinese_builtins_execute() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "builtins.sprout"
        path.write_text(
            'language "chinese-pack"\n'
            '数据 = 解析JSON("{\\"分数\\": 3}")\n'
            "输出 绝对值(-4), 数据.获取(\"分数\")\n",
            encoding="utf-8",
        )
        stable = run_program(path)
        vm = run_program(path, vm=True)
        assert stable.returncode == 0, stable.stderr
        assert vm.returncode == 0, vm.stderr
        assert stable.stdout == "4 3\n"
        assert vm.stdout == stable.stdout


def test_pack_validation_rejects_unknown_and_ambiguous_entries() -> None:
    pack = load_language_pack("chinese-pack")
    data = json.loads(json.dumps(pack.data))
    data["entries"]["syntax.not-real"] = {
        "preferred": "假的概念",
        "aliases": [],
        "status": "reviewed",
    }
    errors = validate_language_pack_data(data)
    assert any("unknown concept" in error for error in errors)

    data = json.loads(json.dumps(pack.data))
    data["entries"]["syntax.function"]["aliases"].append("输出")
    errors = validate_language_pack_data(data)
    assert any("duplicate spelling" in error for error in errors)


def test_external_pack_is_data_only_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pack.json"
        path.write_text('{"id": "bad-pack"}', encoding="utf-8")
        try:
            load_language_pack(str(path))
        except SproutError as exc:
            assert "invalid language pack" in str(exc).lower()
        else:
            raise AssertionError("malformed pack should fail")


def run_program(path: Path, *, vm: bool = False) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(ROOT / "sprout.py"), "run"]
    if vm:
        args.append("--vm")
    args.append(str(path))
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def test_chinese_runtime_and_vm_match_english() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.sprout"
        path.write_text(
            'language "chinese-pack"\n'
            "定义 求和(数字们):\n"
            "  令 总数 = 0\n"
            "  对于 数字 在 数字们:\n"
            "    总数 = 总数 + 数字\n"
            "  返回 总数\n"
            "值们 = [1, 2, 3]\n"
            "值们.追加(4)\n"
            "输出 求和(值们), 值们.长度()\n",
            encoding="utf-8",
        )
        stable = run_program(path)
        vm = run_program(path, vm=True)
        assert stable.returncode == 0, stable.stderr
        assert vm.returncode == 0, vm.stderr
        assert stable.stdout == "10 4\n"
        assert vm.stdout == stable.stdout


def test_chinese_guessing_game_runs_on_interpreter_and_vm() -> None:
    path = ROOT / "examples" / "polyglot" / "chinese_guessing_game.sprout"
    outputs = []
    for vm in (False, True):
        args = [sys.executable, str(ROOT / "sprout.py"), "run"]
        if vm:
            args.append("--vm")
        args.append(str(path))
        result = subprocess.run(
            args,
            cwd=ROOT,
            input="3\n9\n7\n",
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "太小了，再试一次。" in result.stdout
        assert "太大了，再试一次。" in result.stdout
        assert "猜对了！你用了 3 次。" in result.stdout
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_chinese_moonlit_dungeon_demo_matches_interpreter_and_vm() -> None:
    path = ROOT / "examples" / "polyglot" / "chinese_moonlit_dungeon.sprout"
    outputs = []
    for vm in (False, True):
        args = [sys.executable, str(ROOT / "sprout.py"), "run"]
        if vm:
            args.append("--vm")
        args.extend([str(path), "--演示"])
        result = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "你击败了 石甲守卫" in result.stdout
        assert "你击败了 月蚀领主" in result.stdout
        assert "地牢得救了" in result.stdout
        assert "最终分数：460" in result.stdout
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_chinese_panda3d_game_has_no_blocking_static_diagnostics() -> None:
    path = ROOT / "examples" / "polyglot" / "chinese_panda3d_crystal_hunt.sprout"
    analysis = analyze_source(path.read_text(encoding="utf-8"), str(path))
    assert not [
        diagnostic
        for diagnostic in analysis.diagnostics
        if diagnostic.severity == "error"
        or diagnostic.code in {"SPROUT_ERROR", "SPROUT_SYNTAX", "SPROUT_UNKNOWN_NAME"}
    ]


def test_localized_builtin_alias_can_be_shadowed_by_user_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "shadow.sprout"
        path.write_text(
            'language "chinese-pack"\n'
            "定义 自己的长度(值):\n"
            "  返回 99\n"
            "长度 = 自己的长度\n"
            "输出 长度([1, 2, 3])\n",
            encoding="utf-8",
        )
        result = run_program(path)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "99\n"


def test_mixed_language_imports_preserve_unicode_exports() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "player.sprout").write_text(
            'language "chinese-pack"\n'
            "定义 创建玩家(名字):\n"
            "  返回 {\"名字\": 名字, \"分数\": 7}\n",
            encoding="utf-8",
        )
        main = root / "main.sprout"
        main.write_text(
            'import "player.sprout" as player\n'
            'hero = player.创建玩家("Jerry")\n'
            'say hero.名字, hero.分数\n',
            encoding="utf-8",
        )
        stable = run_program(main)
        vm = run_program(main, vm=True)
        assert stable.returncode == 0, stable.stderr
        assert vm.returncode == 0, vm.stderr
        assert stable.stdout == "Jerry 7\n"
        assert vm.stdout == stable.stdout


def test_project_default_and_cli_override_precedence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "sprout.toml").write_text(
            '[project]\nname = "polyglot"\nmain = "main.sprout"\n\n'
            '[language]\ndefault = "chinese-pack"\n',
            encoding="utf-8",
        )
        (root / "main.sprout").write_text('输出 "项目默认"\n', encoding="utf-8")
        default_run = run_program(root)
        assert default_run.returncode == 0, default_run.stderr
        assert default_run.stdout == "项目默认\n"

        override = subprocess.run(
            [
                sys.executable,
                str(ROOT / "sprout.py"),
                "run",
                "--language",
                "chinese-pack",
                str(root / "main.sprout"),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert override.returncode == 0, override.stderr


def test_run_preserves_option_shaped_program_arguments() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "args.sprout"
        path.write_text("say argv\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "sprout.py"),
                "run",
                "--language",
                "english-pack",
                str(path),
                "--player",
                "小明",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "[--player, 小明]\n"


def test_project_default_is_shared_by_analysis_and_formatter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        (root / "sprout.toml").write_text(
            '[project]\nname = "polyglot-tools"\nmain = "main.sprout"\n\n'
            '[language]\ndefault = "chinese-pack"\n',
            encoding="utf-8",
        )
        source = '函数 问候():\n  say "你好"\n'
        path.write_text(source, encoding="utf-8")
        analysis = analyze_source(source, str(path))
        assert not any(
            diagnostic.code in {"SPROUT_ERROR", "SPROUT_SYNTAX"}
            for diagnostic in analysis.diagnostics
        )
        assert "问候" in analysis.functions
        assert format_source(
            source,
            language_default="chinese-pack",
        ).startswith("定义 问候")


def test_formatter_normalizes_reviewed_aliases_to_pack_preference() -> None:
    source = (
        'language "chinese-pack"\n'
        "函数 问候():\n"
        '  say "你好"\n'
    )
    assert format_source(source) == (
        'language "chinese-pack"\n'
        "定义 问候():\n"
        '  输出 "你好"\n'
    )


def test_language_sync_adds_fallbacks_without_claiming_review() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "small-pack.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "catalogVersion": 1,
                "id": "small-pack",
                "version": "1.0.0",
                "locale": "x-test",
                "sprout": "0.3.4",
                "englishFallback": True,
                "entries": {},
                "diagnostics": {},
            }),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "language", "sync", str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        synced = json.loads(path.read_text(encoding="utf-8"))
        assert len(synced["entries"]) > 200
        assert all(entry["status"] == "fallback" for entry in synced["entries"].values())


def main() -> int:
    test_english_catalog_preserves_canonical_tokens()
    test_bootstrap_scanner_accepts_only_first_meaningful_statement()
    test_analysis_ignores_bootstrap_after_leading_comments()
    test_chinese_keywords_emit_canonical_tokens_and_preserve_spelling()
    test_none_is_an_identifier_not_a_nil_literal()
    test_reviewed_aliases_are_accepted_but_preferred_spelling_is_stable()
    test_curated_chinese_builtins_execute()
    test_pack_validation_rejects_unknown_and_ambiguous_entries()
    test_external_pack_is_data_only_json()
    test_chinese_runtime_and_vm_match_english()
    test_chinese_guessing_game_runs_on_interpreter_and_vm()
    test_chinese_moonlit_dungeon_demo_matches_interpreter_and_vm()
    test_chinese_panda3d_game_has_no_blocking_static_diagnostics()
    test_localized_builtin_alias_can_be_shadowed_by_user_binding()
    test_mixed_language_imports_preserve_unicode_exports()
    test_project_default_and_cli_override_precedence()
    test_run_preserves_option_shaped_program_arguments()
    test_project_default_is_shared_by_analysis_and_formatter()
    test_formatter_normalizes_reviewed_aliases_to_pack_preference()
    test_language_sync_adds_fallbacks_without_claiming_review()
    print("sprout language-pack tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
