from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

from .lexer import Lexer
from .model import Diagnostic, SproutError, SproutProject, Symbol, KEYWORDS
from .parser import Parser
from .runtime import Interpreter, attach_error_source, format_value, native_runtime_error

def parse_error_location(message: str) -> tuple[str, int | None, int | None]:
    marker = " at "
    if marker not in message:
        return message, None, None
    head, tail = message.rsplit(marker, 1)
    if ":" not in tail:
        return message, None, None
    line_text, col_text = tail.rsplit(":", 1)
    if line_text.isdigit() and col_text.isdigit():
        return head, int(line_text), int(col_text)
    return message, None, None


def diagnostic_from_error(exc: SproutError, path: str | None = None) -> Diagnostic:
    message, line, col = parse_error_location(str(exc))
    return Diagnostic("error", message, path, line, col, "SPROUT_ERROR")


def find_project_root(start: str) -> str | None:
    current = os.path.abspath(start)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        candidate = os.path.join(current, "sprout.toml")
        if os.path.exists(candidate):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def parse_simple_toml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    section: dict[str, Any] = data
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data
            for part in line[1:-1].split("."):
                section = section.setdefault(part.strip(), {})
            continue
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        section[key] = parse_simple_toml_value(value)
    return data


def split_simple_toml_items(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(text[start:index].strip())
            start = index + 1
    final = text[start:].strip()
    if final:
        items.append(final)
    return items


def parse_simple_toml_value(value: str) -> Any:
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        parsed: dict[str, Any] = {}
        for item in split_simple_toml_items(value[1:-1].strip()):
            if "=" in item:
                key, subvalue = [part.strip() for part in item.split("=", 1)]
                parsed[key] = parse_simple_toml_value(subvalue)
        return parsed
    if value.startswith("[") and value.endswith("]"):
        return [parse_simple_toml_value(item) for item in split_simple_toml_items(value[1:-1].strip())]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        if value[0] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value[1:-1]
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    return value


def load_project(path: str) -> SproutProject | None:
    root = path if os.path.isdir(path) else find_project_root(path)
    if not root:
        return None
    config_path = os.path.join(root, "sprout.toml")
    if not os.path.exists(config_path):
        return None
    with open(config_path, "rb") as fh:
        if tomllib is not None:
            data = tomllib.load(fh)
        else:
            data = parse_simple_toml(fh.read().decode("utf-8"))
    project_data = data.get("project", {})
    package_data = data.get("package", {})
    metadata = {**project_data, **package_data}
    paths_data = data.get("paths", {})
    tool_data = data.get("tool", {})
    dependencies = data.get("dependencies", {})
    source_folders = paths_data.get("source", project_data.get("source_folders", project_data.get("src", ["."])))
    module_paths = paths_data.get("modules", project_data.get("module_paths", []))
    if isinstance(source_folders, str):
        source_folders = [source_folders]
    if isinstance(module_paths, str):
        module_paths = [module_paths]
    return SproutProject(
        root=root,
        name=str(metadata.get("name", os.path.basename(root) or "sprout-project")),
        version=str(metadata.get("version", "0.1.0")),
        main=str(metadata.get("main", project_data.get("main", "main.sprout"))),
        authors=[str(item) for item in metadata.get("authors", [metadata["author"]] if metadata.get("author") else [])],
        description=str(metadata.get("description", "")),
        license=str(metadata.get("license", "")),
        source_folders=[str(item) for item in source_folders],
        module_paths=[str(item) for item in module_paths],
        dependencies=dependencies,
        tool_settings=tool_data,
    )


def project_for_path(path: str) -> SproutProject | None:
    root = find_project_root(path)
    return load_project(root) if root else None


def module_search_paths_for(path: str | None = None, project: SproutProject | None = None) -> list[str]:
    if project is None and path:
        project = project_for_path(path)
    return project.search_paths() if project else []


def run_source(
    source: str,
    source_path: str | None = None,
    argv: list[str] | None = None,
    module_search_paths: list[str] | None = None,
) -> None:
    try:
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse()
        Interpreter(source_path=source_path, argv=argv, module_search_paths=module_search_paths).run(program)
    except SproutError as exc:
        attach_error_source(exc, source_path, source)
        raise
    except Exception as exc:
        error = native_runtime_error("program", exc)
        attach_error_source(error, source_path, source)
        raise error from None


def parse_source(source: str) -> list[Any]:
    return Parser(Lexer(source).tokenize()).parse()


def read_source_file(path: str) -> tuple[str, str]:
    resolved = os.path.abspath(path)
    with open(resolved, "r", encoding="utf-8") as fh:
        return fh.read(), resolved


def resolve_run_target(path: str) -> tuple[str, SproutProject | None]:
    if os.path.isdir(path):
        project = load_project(path)
        if not project:
            raise SproutError(f"No sprout.toml found in project directory '{path}'")
        return project.main_path, project
    project = project_for_path(path)
    return path, project


def run_file(path: str, args: list[str] | None = None) -> None:
    target, project = resolve_run_target(path)
    source, resolved = read_source_file(target)
    run_source(source, source_path=resolved, argv=args or [], module_search_paths=module_search_paths_for(resolved, project))


def parse_file(path: str) -> tuple[list[Any], str, str]:
    source, resolved = read_source_file(path)
    return parse_source(source), source, resolved


def check_path(path: str) -> tuple[str, list[Diagnostic], list[Symbol]]:
    target, _project = resolve_run_target(path) if os.path.isdir(path) else (path, project_for_path(path))
    try:
        program, source, resolved = parse_file(target)
    except SproutError as exc:
        resolved = os.path.abspath(target)
        return resolved, [diagnostic_from_error(exc, resolved)], []
    return resolved, lint_source(source, resolved, program, syntax_only=True), collect_symbols(program, resolved)


def check_file(path: str, json_mode: bool = False, include_warnings: bool = False) -> int:
    resolved, diagnostics, symbols = check_path(path)
    if not include_warnings:
        diagnostics = [diag for diag in diagnostics if diag.severity == "error"]
    if json_mode:
        print(json.dumps({"ok": not any(diag.severity == "error" for diag in diagnostics), "path": resolved, "diagnostics": [diag.to_json() for diag in diagnostics], "symbols": [sym.to_json() for sym in symbols]}, indent=2))
    elif diagnostics:
        for diag in diagnostics:
            location = f"{diag.path}:{diag.line}:{diag.col}" if diag.line and diag.col else (diag.path or resolved)
            print(f"{diag.severity}: {location}: {diag.message}")
    else:
        print(f"ok {resolved}")
    return 1 if any(diag.severity == "error" for diag in diagnostics) else 0


def collect_symbols(program: list[Any], path: str | None = None) -> list[Symbol]:
    symbols: list[Symbol] = []

    def walk_statement(stmt: Any) -> None:
        kind = stmt[0]
        if kind == "fn":
            symbols.append(Symbol(stmt[1], "function", path, stmt[4], stmt[5]))
        elif kind == "class":
            symbols.append(Symbol(stmt[1], "class", path, 1, 1))
            for method in stmt[3]:
                symbols.append(Symbol(f"{stmt[1]}.{method[1]}", "method", path, method[4], method[5]))
            return
        elif kind == "import":
            symbols.append(Symbol(stmt[2], "module", path, 1, 1))
        for part in stmt[1:]:
            if isinstance(part, list):
                for item in part:
                    if isinstance(item, tuple) and item:
                        walk_statement(item)

    for statement in program:
        walk_statement(statement)
    return symbols


def iter_statements(program: list[Any]) -> list[Any]:
    out: list[Any] = []

    def visit(stmt: Any) -> None:
        out.append(stmt)
        for part in stmt[1:]:
            if isinstance(part, list):
                for item in part:
                    if isinstance(item, tuple) and item:
                        visit(item)

    for statement in program:
        visit(statement)
    return out


def lint_source(source: str, path: str | None = None, program: list[Any] | None = None, syntax_only: bool = False) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    lines = source.splitlines()
    for index, line in enumerate(lines, start=1):
        if "\t" in line:
            diagnostics.append(Diagnostic("warning", "Use spaces instead of tabs for indentation", path, index, line.index("\t") + 1, "SPROUT_TAB_INDENT"))
        alias_match = None if syntax_only else re.search(r"\b(True|False|None)\b", line)
        if alias_match:
            diagnostics.append(Diagnostic("warning", "Prefer Sprout-style true, false, or nil", path, index, alias_match.start() + 1, "SPROUT_PY_ALIAS"))

    if program is None:
        try:
            program = parse_source(source)
        except SproutError as exc:
            return [diagnostic_from_error(exc, path)]

    seen_functions: set[str] = set()
    seen_classes: set[str] = set()
    declared: dict[str, int] = {}
    used: set[str] = set()

    def scan_expr(expr: Any) -> None:
        if not isinstance(expr, tuple):
            return
        if expr[0] == "var":
            used.add(expr[1])
        for part in expr[1:]:
            if isinstance(part, tuple):
                scan_expr(part)
            elif isinstance(part, list):
                for item in part:
                    if isinstance(item, tuple):
                        scan_expr(item)
                    elif isinstance(item, list):
                        for nested in item:
                            if isinstance(nested, tuple):
                                scan_expr(nested)

    for stmt in iter_statements(program):
        kind = stmt[0]
        if kind == "fn":
            if stmt[1] in seen_functions:
                diagnostics.append(Diagnostic("warning", f"Duplicate function name '{stmt[1]}' in this scope", path, stmt[4], stmt[5], "SPROUT_DUP_FUNCTION"))
            seen_functions.add(stmt[1])
            declared.setdefault(stmt[1], stmt[4])
        elif kind == "class":
            if stmt[1] in seen_classes:
                diagnostics.append(Diagnostic("warning", f"Duplicate class name '{stmt[1]}' in this scope", path, 1, 1, "SPROUT_DUP_CLASS"))
            seen_classes.add(stmt[1])
            declared.setdefault(stmt[1], 1)
        elif kind == "let":
            declared.setdefault(stmt[1], 1)
            scan_expr(stmt[2])
        elif kind == "assign" and stmt[1][0] == "var":
            if stmt[1][1] in declared:
                diagnostics.append(Diagnostic("warning", f"Assignment shadows earlier name '{stmt[1][1]}'", path, 1, 1, "SPROUT_SHADOW"))
            declared.setdefault(stmt[1][1], 1)
            scan_expr(stmt[2])
        elif kind == "import":
            import_path = stmt[1]
            base = os.path.dirname(path) if path else os.getcwd()
            if not os.path.exists(os.path.join(base, import_path)):
                project = project_for_path(path) if path else None
                found = False
                for search_path in module_search_paths_for(path, project):
                    if os.path.exists(os.path.join(search_path, import_path)):
                        found = True
                        break
                if not found:
                    diagnostics.append(Diagnostic("warning", f"Import path not found: {import_path}", path, 1, 1, "SPROUT_UNKNOWN_IMPORT"))

        if kind == "return":
            continue
        for part in stmt[1:]:
            if isinstance(part, tuple):
                scan_expr(part)
            elif isinstance(part, list):
                for item in part:
                    if isinstance(item, tuple) and item and item[0] not in {"return", "break", "continue"}:
                        scan_expr(item)

    for statement_list in [program]:
        unreachable = False
        for stmt in statement_list:
            if unreachable:
                diagnostics.append(Diagnostic("warning", "Unreachable code after return/break/continue", path, 1, 1, "SPROUT_UNREACHABLE"))
                break
            if stmt[0] in {"return", "break", "continue"}:
                unreachable = True

    builtins = set(builtin_function_names()) | set(KEYWORDS) | {"argv", "self", "super"}
    for name, line in declared.items():
        if name.startswith("_"):
            continue
        if name not in used and name not in builtins:
            diagnostics.append(Diagnostic("warning", f"Name '{name}' is declared but not used", path, line, 1, "SPROUT_UNUSED_NAME"))

    return diagnostics


def format_source(source: str) -> str:
    out = []
    for line in source.splitlines():
        expanded = line.expandtabs(2).rstrip()
        out.append(expanded)
    formatted = "\n".join(out)
    if source.endswith("\n") or formatted:
        formatted += "\n"
    return formatted


def format_file(path: str, write: bool = False) -> int:
    if os.path.isdir(path):
        project = load_project(path)
        if not project:
            raise SproutError(f"No sprout.toml found in project directory '{path}'")
        seen: set[str] = set()
        files: list[str] = []
        for root in project.search_paths():
            if not os.path.isdir(root):
                continue
            for current, _dirs, names in os.walk(root):
                for name in sorted(names):
                    if not name.endswith(".sprout"):
                        continue
                    resolved = os.path.abspath(os.path.join(current, name))
                    if resolved not in seen:
                        seen.add(resolved)
                        files.append(resolved)
        main = os.path.abspath(project.main_path)
        if os.path.exists(main) and main not in seen:
            files.insert(0, main)
        if not files:
            print(f"no .sprout files found in {project.root}")
            return 0
        for index, file_path in enumerate(sorted(files)):
            if write:
                format_file(file_path, write=True)
            else:
                if index:
                    print()
                print(f"# {file_path}")
                format_file(file_path, write=False)
        return 0
    source, resolved = read_source_file(path)
    formatted = format_source(source)
    if write:
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(formatted)
        print(f"formatted {resolved}")
    else:
        print(formatted, end="")
    return 0


def lint_file(path: str, json_mode: bool = False) -> int:
    target, _project = resolve_run_target(path) if os.path.isdir(path) else (path, project_for_path(path))
    try:
        program, source, resolved = parse_file(target)
        diagnostics = lint_source(source, resolved, program)
    except SproutError as exc:
        resolved = os.path.abspath(target)
        diagnostics = [diagnostic_from_error(exc, resolved)]
    if json_mode:
        print(json.dumps({"ok": not any(diag.severity == "error" for diag in diagnostics), "path": resolved, "diagnostics": [diag.to_json() for diag in diagnostics]}, indent=2))
    else:
        for diag in diagnostics:
            location = f"{diag.path}:{diag.line}:{diag.col}" if diag.line and diag.col else (diag.path or resolved)
            print(f"{diag.severity}: {location}: {diag.message}")
        if not diagnostics:
            print(f"ok {resolved}")
    return 1 if any(diag.severity == "error" for diag in diagnostics) else 0


def word_at_position(source: str, line: int, col: int) -> str:
    lines = source.splitlines()
    line_index = max(0, line - 1)
    if line_index >= len(lines):
        return ""
    text = lines[line_index]
    pos = min(max(0, col - 1), len(text))
    start = pos
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = pos
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return text[start:end]


def dotted_base_before(source: str, line: int, col: int) -> str | None:
    lines = source.splitlines()
    line_index = max(0, line - 1)
    if line_index >= len(lines):
        return None
    before = lines[line_index][: max(0, col - 1)]
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z0-9_]*$", before)
    return match.group(1) if match else None


def call_before(source: str, line: int, col: int) -> str | None:
    lines = source.splitlines()
    line_index = max(0, line - 1)
    if line_index >= len(lines):
        return None
    before = lines[line_index][: max(0, col - 1)]
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\([^()]*$", before)
    return match.group(1) if match else None


def intelligence_file(path: str, kind: str, line: int, col: int, source_path: str | None = None) -> int:
    from .analysis import (
        build_workspace_index,
        member_completions,
        references_at,
        signature_for,
        symbol_at_position,
        top_level_completions,
    )

    resolved = os.path.abspath(path)
    if source_path:
        source, _source_resolved = read_source_file(source_path)
    else:
        source, resolved = read_source_file(path)
    root = find_project_root(resolved) or os.path.dirname(resolved) or os.getcwd()
    index = build_workspace_index(root, {resolved: source})
    payload: dict[str, Any] = {"ok": True, "path": resolved, "kind": kind}

    if kind == "completions":
        base = dotted_base_before(source, line, col)
        symbols = member_completions(index, resolved, base) if base else top_level_completions(index, resolved, line)
        payload["base"] = base
        payload["items"] = [symbol.to_json() for symbol in symbols]
    elif kind == "hover":
        word = word_at_position(source, line, col)
        symbol = symbol_at_position(index, resolved, line, col, word)
        payload["word"] = word
        payload["symbol"] = symbol.to_json() if symbol else None
    elif kind == "definition":
        word = word_at_position(source, line, col)
        symbol = symbol_at_position(index, resolved, line, col, word)
        payload["word"] = word
        payload["definition"] = symbol.location.to_json() if symbol else None
    elif kind == "references":
        word = word_at_position(source, line, col)
        payload["word"] = word
        symbol = symbol_at_position(index, resolved, line, col, word)
        payload["symbolId"] = symbol.symbol_id if symbol else None
        payload["references"] = [ref.to_json() for ref in references_at(index, resolved, line, col, word)]
    elif kind == "signature":
        call_name = call_before(source, line, col)
        symbol = signature_for(index, resolved, call_name) if call_name else None
        payload["call"] = call_name
        payload["signature"] = symbol.to_json() if symbol else None
    elif kind == "symbols":
        file = index.files.get(resolved)
        payload["symbols"] = [symbol.to_json() for symbol in (file.symbols if file else [])]
    elif kind == "diagnostics":
        file = index.files.get(resolved)
        payload["diagnostics"] = [diag.to_json() for diag in (file.diagnostics if file else [])]
    else:
        payload = {"ok": False, "error": f"Unknown intelligence query kind: {kind}"}

    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok") else 2


def builtin_function_names() -> list[str]:
    interp = Interpreter()
    return sorted(name for name, value in interp.globals.values.items() if hasattr(value, "call"))


def example_files() -> list[str]:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    examples_root = os.path.join(root, "examples")
    out: list[str] = []
    for current, _dirs, files in os.walk(examples_root):
        for filename in files:
            if filename.endswith(".sprout"):
                out.append(os.path.relpath(os.path.join(current, filename), root))
    return sorted(out)


def print_help() -> None:
    print(
        "Sprout language runner\n"
        "\n"
        "Usage:\n"
        "  python3 sprout.py                       Start the REPL\n"
        "  python3 sprout.py FILE.sprout [args]    Run a file\n"
        "  python3 sprout.py run FILE|DIR [args]   Run a file or sprout.toml project\n"
        "  python3 sprout.py run --vm FILE [args]  Run with the experimental bytecode VM\n"
        "  python3 sprout.py compile FILE          Compile to experimental bytecode\n"
        "  python3 sprout.py dis FILE              Show experimental bytecode\n"
        "  python3 sprout.py bench FILE            Time tree-walk vs VM when supported\n"
        "  python3 sprout.py debug FILE            Step experimental VM bytecode\n"
        "  python3 sprout.py profile FILE          Profile experimental VM execution\n"
        "  python3 sprout.py test [PATH]           Discover and run Sprout tests\n"
        "                    [--list] [--json] [--filter NAME]\n"
        "  python3 sprout.py docs [DIR] [--html]   Generate project/package documentation\n"
        "  python3 sprout.py build [DIR] [--vm]    Create a reproducible project build\n"
        "  python3 sprout.py package [DIR]         Create a portable .sproutpkg bundle\n"
        "  python3 sprout.py pkg COMMAND           Manage, install, and publish packages\n"
        "  python3 sprout.py search [QUERY]        Search the configured package registry\n"
        "  python3 sprout.py info PACKAGE          Show registry package metadata\n"
        "  python3 sprout.py list-installed        List project package installations\n"
        "  python3 sprout.py new TEMPLATE NAME     Create a Sprout project\n"
        "  python3 sprout.py doctor                Check local release readiness\n"
        "  python3 sprout.py release-check         Run release readiness checks\n"
        "  python3 sprout.py release [DIR]         Validate and create a project release\n"
        "  python3 sprout.py install [--prefix P]  Install Sprout and its launcher\n"
        "  python3 sprout.py uninstall [--prefix P] Remove an installed Sprout runtime\n"
        "  python3 sprout.py language-package      Build the language release archive\n"
        "  python3 sprout.py vscode-package        Build the VS Code .vsix package\n"
        "  python3 sprout.py check FILE [--json]   Parse without running\n"
        "  python3 sprout.py lint FILE [--json]    Run syntax and style checks\n"
        "  python3 sprout.py fmt FILE [--write]    Safely format a file\n"
        "  python3 sprout.py intel FILE --kind K   Query semantic editor intelligence\n"
        "  python3 sprout.py stdlib                List built-in functions\n"
        "  python3 sprout.py examples              List example programs\n"
        "  python3 sprout.py version               Print version\n"
        "  python3 sprout.py help                  Show this help"
    )
