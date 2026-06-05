#!/usr/bin/env python3
"""Check that VS Code Sprout support mentions the current language surface."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sprout_core as sprout  # noqa: E402


EXTENSION = ROOT / "editor" / "vscode-sprout" / "extension.js"
SYNTAX = ROOT / "editor" / "vscode-sprout" / "syntaxes" / "sprout.tmLanguage.json"
MODULES = ROOT / "examples" / "modules"


def fail(message: str) -> None:
    raise SystemExit(f"editor coverage error: {message}")


def quoted(name: str) -> str:
    return f'"{name}"'


def module_functions() -> set[str]:
    names: set[str] = set()
    pattern = re.compile(r"^\s*(?:def|fn|bloom)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
    for path in MODULES.glob("*.sprout"):
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def main() -> int:
    extension = EXTENSION.read_text(encoding="utf-8")
    syntax = json.loads(SYNTAX.read_text(encoding="utf-8"))
    syntax_text = json.dumps(syntax)

    interp = sprout.Interpreter()
    builtins = set(interp.builtin_functions()) | {"argv"}
    methods = {name.split(".", 1)[1] for name in interp.builtin_methods()}
    keywords = set(sprout.KEYWORDS) | {"defbloom", "defbraces", "defrest", "defopts", "callspread"}
    modules = module_functions()

    missing_extension_builtins = sorted(name for name in builtins if quoted(name) not in extension)
    missing_extension_keywords = sorted(name for name in keywords if quoted(name) not in extension)
    missing_extension_methods = sorted(name for name in methods if quoted(name) not in extension)
    missing_extension_modules = sorted(name for name in modules if quoted(name) not in extension)

    missing_syntax_builtins = sorted(name for name in builtins if name not in syntax_text)
    missing_syntax_keywords = sorted(name for name in sprout.KEYWORDS if name not in syntax_text)

    problems = []
    if missing_extension_builtins:
        problems.append(f"extension missing built-ins: {', '.join(missing_extension_builtins)}")
    if missing_extension_keywords:
        problems.append(f"extension missing keywords/snippets: {', '.join(missing_extension_keywords)}")
    if missing_extension_methods:
        problems.append(f"extension missing dot methods: {', '.join(missing_extension_methods)}")
    if missing_extension_modules:
        problems.append(f"extension missing module APIs: {', '.join(missing_extension_modules)}")
    if missing_syntax_builtins:
        problems.append(f"syntax missing built-ins: {', '.join(missing_syntax_builtins)}")
    if missing_syntax_keywords:
        problems.append(f"syntax missing keywords: {', '.join(missing_syntax_keywords)}")

    if problems:
        fail("; ".join(problems))

    print("editor coverage ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
