from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
import re
from typing import Any

from .model import Diagnostic, KEYWORDS
from .runtime import Interpreter
from .tooling import module_search_paths_for, parse_source, project_for_path, read_source_file


IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
DECL_RE = re.compile(r"^\s*(?:(?:let|sprout)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
FN_RE = re.compile(r"^\s*(?:def|fn|bloom)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")
IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"\s+as\s+([A-Za-z_][A-Za-z0-9_]*)')
IMPORTPY_RE = re.compile(r'^\s*importpython\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_.]*))(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?')
SELF_ASSIGN_RE = re.compile(r"\bself\.([A-Za-z_][A-Za-z0-9_]*)\s*=")
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')


@dataclass
class Location:
    path: str
    line: int
    col: int

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "col": self.col}


@dataclass
class SemanticSymbol:
    name: str
    kind: str
    location: Location
    signature: str | None = None
    documentation: str = ""
    container: str | None = None
    members: dict[str, "SemanticSymbol"] = field(default_factory=dict)
    module_path: str | None = None
    target_type: str | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualifiedName": self.qualified_name,
            "kind": self.kind,
            "location": self.location.to_json(),
            "signature": self.signature,
            "documentation": self.documentation,
            "container": self.container,
            "modulePath": self.module_path,
            "targetType": self.target_type,
        }


@dataclass
class Reference:
    name: str
    location: Location
    role: str = "read"

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "location": self.location.to_json()}


@dataclass
class FileAnalysis:
    path: str
    source: str
    program: list[Any]
    symbols: list[SemanticSymbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    imports: dict[str, SemanticSymbol] = field(default_factory=dict)
    variables: dict[str, SemanticSymbol] = field(default_factory=dict)
    functions: dict[str, SemanticSymbol] = field(default_factory=dict)
    classes: dict[str, SemanticSymbol] = field(default_factory=dict)


@dataclass
class WorkspaceIndex:
    root: str
    files: dict[str, FileAnalysis] = field(default_factory=dict)
    symbols: dict[str, list[SemanticSymbol]] = field(default_factory=dict)
    module_exports: dict[str, dict[str, SemanticSymbol]] = field(default_factory=dict)

    def add_file(self, analysis: FileAnalysis) -> None:
        self.files[analysis.path] = analysis
        exports: dict[str, SemanticSymbol] = {}
        for symbol in analysis.symbols:
            self.symbols.setdefault(symbol.name, []).append(symbol)
            self.symbols.setdefault(symbol.qualified_name, []).append(symbol)
            if symbol.container is None and symbol.kind in {"function", "class", "variable", "module", "python-module"}:
                exports[symbol.name] = symbol
        self.module_exports[analysis.path] = exports

    def find_symbol(self, name: str, path: str | None = None) -> SemanticSymbol | None:
        if path and path in self.files:
            file = self.files[path]
            for table in (file.variables, file.functions, file.classes, file.imports):
                if name in table:
                    return table[name]
        matches = self.symbols.get(name) or []
        return matches[0] if matches else None

    def references_to(self, name: str) -> list[Reference]:
        refs: list[Reference] = []
        for file in self.files.values():
            refs.extend(ref for ref in file.references if ref.name == name or ref.name.endswith(f".{name}"))
        return refs

    def rename_edits(self, name: str, new_name: str) -> dict[str, list[dict[str, Any]]]:
        edits: dict[str, list[dict[str, Any]]] = {}
        for ref in self.references_to(name):
            edits.setdefault(ref.location.path, []).append(
                {
                    "range": {
                        "start": {"line": ref.location.line - 1, "character": ref.location.col - 1},
                        "end": {"line": ref.location.line - 1, "character": ref.location.col - 1 + len(name.split(".")[-1])},
                    },
                    "newText": new_name,
                }
            )
        return edits


def builtin_docs() -> dict[str, SemanticSymbol]:
    interp = Interpreter()
    docs: dict[str, SemanticSymbol] = {}
    for name, value in interp.globals.values.items():
        if not hasattr(value, "call"):
            continue
        arity = getattr(value, "arity", None)
        if arity is None:
            signature = f"{name}(*values)"
        elif arity == 0:
            signature = f"{name}()"
        else:
            args = ", ".join(f"value{i}" for i in range(1, int(arity) + 1))
            signature = f"{name}({args})"
        docs[name] = SemanticSymbol(
            name=name,
            kind="builtin",
            location=Location("<builtins>", 1, 1),
            signature=signature,
            documentation="Sprout built-in function.",
        )
    return docs


BUILTINS = builtin_docs()


def line_docs(lines: list[str], line_index: int) -> str:
    docs: list[str] = []
    i = line_index - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped.startswith("##"):
            docs.append(stripped[2:].strip())
            i -= 1
            continue
        if not stripped:
            i -= 1
            continue
        break
    return "\n".join(reversed(docs))


def params_signature(params: list[tuple[str, Any, bool, bool]]) -> str:
    parts = []
    for name, default, variadic, kw_variadic in params:
        prefix = "**" if kw_variadic else ("*" if variadic else "")
        if default is not None:
            parts.append(f"{prefix}{name}=...")
        else:
            parts.append(f"{prefix}{name}")
    return ", ".join(parts)


def function_signature(name: str, params: list[tuple[str, Any, bool, bool]]) -> str:
    return f"{name}({params_signature(params)})"


def walk_statements(program: list[Any]) -> list[Any]:
    out: list[Any] = []

    def visit(stmt: Any) -> None:
        out.append(stmt)
        for part in stmt[1:]:
            if isinstance(part, list):
                for item in part:
                    if isinstance(item, tuple) and item:
                        visit(item)

    for stmt in program:
        visit(stmt)
    return out


def expr_names(expr: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(expr, tuple):
        return names
    if expr[0] == "var":
        names.append(expr[1])
    elif expr[0] == "get":
        names.extend(expr_names(expr[1]))
        if expr[1][0] == "var":
            names.append(f"{expr[1][1]}.{expr[2]}")
    for part in expr[1:]:
        if isinstance(part, tuple):
            names.extend(expr_names(part))
        elif isinstance(part, list):
            for item in part:
                if isinstance(item, tuple):
                    names.extend(expr_names(item))
                elif isinstance(item, list):
                    for nested in item:
                        names.extend(expr_names(nested))
    return names


def resolve_module_path(import_path: str, source_path: str) -> str | None:
    base = os.path.dirname(source_path)
    candidates = [os.path.abspath(os.path.join(base, import_path))]
    candidates.extend(os.path.abspath(os.path.join(root, import_path)) for root in module_search_paths_for(source_path))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def analyze_source(source: str, path: str) -> FileAnalysis:
    resolved = os.path.abspath(path)
    try:
        program = parse_source(source)
    except Exception as exc:
        from .tooling import diagnostic_from_error

        return FileAnalysis(resolved, source, [], diagnostics=[diagnostic_from_error(exc, resolved)])

    analysis = FileAnalysis(resolved, source, program)
    lines = source.splitlines()
    current_class: str | None = None
    class_stack: list[tuple[int, str]] = []
    class_members: dict[str, dict[str, SemanticSymbol]] = {}
    parameter_names: set[str] = set()
    for stmt in walk_statements(program):
        if stmt[0] == "fn":
            parameter_names.update(param[0] for param in stmt[2])

    for line_no, line in enumerate(lines, start=1):
        indent = len(line) - len(line.lstrip(" "))
        while class_stack and indent <= class_stack[-1][0] and line.strip() and not line.lstrip().startswith(("def ", "fn ", "bloom ")):
            class_stack.pop()
        current_class = class_stack[-1][1] if class_stack else None

        class_match = CLASS_RE.match(line)
        if class_match:
            name = class_match.group(1)
            symbol = SemanticSymbol(name, "class", Location(resolved, line_no, class_match.start(1) + 1), documentation=line_docs(lines, line_no - 1))
            analysis.symbols.append(symbol)
            analysis.classes[name] = symbol
            class_members.setdefault(name, {})
            class_stack.append((indent, name))
            current_class = name
            continue

        fn_match = FN_RE.match(line)
        if fn_match:
            name = fn_match.group(1)
            ast_fn = next((stmt for stmt in walk_statements(program) if stmt[0] == "fn" and stmt[1] == name and stmt[4] == line_no), None)
            params = ast_fn[2] if ast_fn else []
            container = current_class
            kind = "method" if container else "function"
            symbol = SemanticSymbol(
                name,
                kind,
                Location(resolved, line_no, fn_match.start(1) + 1),
                signature=function_signature(name, params),
                documentation=line_docs(lines, line_no - 1),
                container=container,
            )
            analysis.symbols.append(symbol)
            if container:
                class_members.setdefault(container, {})[name] = symbol
            else:
                analysis.functions[name] = symbol
            continue

        import_match = IMPORT_RE.match(line)
        if import_match:
            import_path, alias = import_match.groups()
            target = resolve_module_path(import_path, resolved)
            symbol = SemanticSymbol(alias, "module", Location(resolved, line_no, import_match.start(2) + 1), module_path=target)
            analysis.symbols.append(symbol)
            analysis.imports[alias] = symbol
            continue

        import_py_match = IMPORTPY_RE.match(line)
        if import_py_match:
            quoted_name, bare_name, alias = import_py_match.groups()
            module_name = quoted_name or bare_name or ""
            alias = alias or module_name.split(".")[-1]
            name_group = 1 if quoted_name else 2
            symbol = SemanticSymbol(alias, "python-module", Location(resolved, line_no, import_py_match.start(name_group) + 1), module_path=module_name)
            analysis.symbols.append(symbol)
            analysis.imports[alias] = symbol
            continue

        decl_match = DECL_RE.match(line)
        if decl_match:
            name = decl_match.group(1)
            target_type = None
            rhs = line.split("=", 1)[1].strip() if "=" in line else ""
            call_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\(", rhs)
            if call_match:
                target_type = call_match.group(1)
            symbol = SemanticSymbol(name, "variable", Location(resolved, line_no, decl_match.start(1) + 1), target_type=target_type)
            analysis.symbols.append(symbol)
            analysis.variables[name] = symbol

        if current_class:
            for field_match in SELF_ASSIGN_RE.finditer(line):
                field_name = field_match.group(1)
                symbol = SemanticSymbol(field_name, "field", Location(resolved, line_no, field_match.start(1) + 1), container=current_class)
                class_members.setdefault(current_class, {})[field_name] = symbol

    for class_name, members in class_members.items():
        if class_name in analysis.classes:
            analysis.classes[class_name].members = members
            init = members.get("init")
            if init and init.signature:
                inner = init.signature.partition("(")[2].rpartition(")")[0]
                parts = [part.strip() for part in inner.split(",") if part.strip()]
                if parts and parts[0] == "self":
                    parts = parts[1:]
                analysis.classes[class_name].signature = f"{class_name}({', '.join(parts)})"

    for line_no, line in enumerate(lines, start=1):
        code = line.split("#", 1)[0]
        code = STRING_RE.sub('""', code)
        for match in IDENT_RE.finditer(code):
            name = match.group(0)
            if name in KEYWORDS:
                continue
            if match.start() > 0 and code[match.start() - 1] == ".":
                continue
            role = "write" if DECL_RE.match(code) and DECL_RE.match(code).group(1) == name else "read"
            analysis.references.append(Reference(name, Location(resolved, line_no, match.start() + 1), role))
        for dotted in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", code):
            analysis.references.append(Reference(f"{dotted.group(1)}.{dotted.group(2)}", Location(resolved, line_no, dotted.start(2) + 1), "read"))

    known = set(BUILTINS) | set(KEYWORDS) | {"self", "super", "argv"}
    known.update(parameter_names)
    known.update(analysis.variables)
    known.update(analysis.functions)
    known.update(analysis.classes)
    known.update(analysis.imports)
    for members in class_members.values():
        known.update(members)
    for ref in analysis.references:
        if "." in ref.name or ref.role == "write" or ref.name in known:
            continue
        analysis.diagnostics.append(Diagnostic("warning", f"Unknown name '{ref.name}'", resolved, ref.location.line, ref.location.col, "SPROUT_UNKNOWN_NAME"))
    return analysis


def analyze_file(path: str) -> FileAnalysis:
    source, resolved = read_source_file(path)
    return analyze_source(source, resolved)


def workspace_files(root: str) -> list[str]:
    paths: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}]
        for filename in files:
            if filename.endswith(".sprout"):
                paths.append(os.path.join(current, filename))
    return sorted(paths)


def build_workspace_index(root_or_file: str, open_documents: dict[str, str] | None = None) -> WorkspaceIndex:
    root = os.path.abspath(root_or_file if os.path.isdir(root_or_file) else os.path.dirname(root_or_file))
    project = project_for_path(root_or_file)
    if project:
        root = project.root
    index = WorkspaceIndex(root)
    files = workspace_files(root)
    for path in files:
        if open_documents and path in open_documents:
            analysis = analyze_source(open_documents[path], path)
        else:
            try:
                analysis = analyze_file(path)
            except OSError:
                continue
        index.add_file(analysis)
    if open_documents:
        for path, source in open_documents.items():
            resolved = os.path.abspath(path)
            if resolved not in index.files and resolved.endswith(".sprout"):
                index.add_file(analyze_source(source, resolved))

    # Attach imported module exports now that all files have been analyzed.
    for file in index.files.values():
        for symbol in file.imports.values():
            if symbol.kind == "module" and symbol.module_path in index.module_exports:
                symbol.members = index.module_exports[symbol.module_path]
            elif symbol.kind == "python-module" and symbol.module_path:
                symbol.members = python_module_members(symbol.module_path, symbol)
    return index


def python_module_members(module_name: str, parent: SemanticSymbol) -> dict[str, SemanticSymbol]:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return {}
    members: dict[str, SemanticSymbol] = {}
    for name in dir(module):
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        kind = "function" if callable(value) else "variable"
        signature = f"{name}(...)" if callable(value) else None
        members[name] = SemanticSymbol(name, kind, parent.location, signature=signature, container=parent.name)
    return members


def member_completions(index: WorkspaceIndex, path: str, base_name: str) -> list[SemanticSymbol]:
    file = index.files.get(os.path.abspath(path))
    if not file:
        return []
    symbol = file.imports.get(base_name) or file.variables.get(base_name) or file.classes.get(base_name)
    if symbol and symbol.members:
        return sorted(symbol.members.values(), key=lambda item: item.name)
    if symbol and symbol.target_type and symbol.target_type in file.classes:
        return sorted(file.classes[symbol.target_type].members.values(), key=lambda item: item.name)
    if symbol and symbol.target_type:
        target = index.find_symbol(symbol.target_type, path)
        if target and target.members:
            return sorted(target.members.values(), key=lambda item: item.name)
    return []


def top_level_completions(index: WorkspaceIndex, path: str) -> list[SemanticSymbol]:
    file = index.files.get(os.path.abspath(path))
    out: dict[str, SemanticSymbol] = dict(BUILTINS)
    if file:
        for table in (file.variables, file.functions, file.classes, file.imports):
            out.update(table)
    for name, symbols in index.symbols.items():
        if "." not in name and symbols:
            out.setdefault(name, symbols[0])
    return sorted(out.values(), key=lambda item: item.name)


def symbol_at(index: WorkspaceIndex, path: str, word: str) -> SemanticSymbol | None:
    path = os.path.abspath(path)
    file = index.files.get(path)
    if file:
        for table in (file.variables, file.functions, file.classes, file.imports):
            if word in table:
                return table[word]
    if word in BUILTINS:
        return BUILTINS[word]
    return index.find_symbol(word, path)


def signature_for(index: WorkspaceIndex, path: str, name: str) -> SemanticSymbol | None:
    dotted = name.split(".")
    if len(dotted) == 2:
        members = member_completions(index, path, dotted[0])
        return next((member for member in members if member.name == dotted[1]), None)
    return symbol_at(index, path, name)
