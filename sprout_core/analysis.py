from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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
FOR_RE = re.compile(r"^\s*(?:for|each)\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
CATCH_RE = re.compile(r"^\s*catch\s+([A-Za-z_][A-Za-z0-9_]*)\b")


def normalize_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


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
    symbol_id: str = ""
    scope_id: str = ""

    def __post_init__(self) -> None:
        if not self.symbol_id:
            raw = f"{self.location.path}:{self.location.line}:{self.location.col}:{self.kind}:{self.qualified_name}"
            self.symbol_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

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
            "symbolId": self.symbol_id,
        }


@dataclass
class Reference:
    name: str
    location: Location
    role: str = "read"
    symbol_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "location": self.location.to_json(),
            "symbolId": self.symbol_id,
        }


@dataclass
class LexicalScope:
    scope_id: str
    kind: str
    path: str
    start_line: int
    end_line: int
    indent: int
    parent_id: str | None = None
    declarations: dict[str, list[SemanticSymbol]] = field(default_factory=dict)

    def contains(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    def declare(self, symbol: SemanticSymbol) -> None:
        symbol.scope_id = self.scope_id
        self.declarations.setdefault(symbol.name, []).append(symbol)


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
    scopes: dict[str, LexicalScope] = field(default_factory=dict)
    source_hash: str = ""
    parse_count: int = 1


@dataclass
class WorkspaceIndex:
    root: str
    files: dict[str, FileAnalysis] = field(default_factory=dict)
    symbols: dict[str, list[SemanticSymbol]] = field(default_factory=dict)
    module_exports: dict[str, dict[str, SemanticSymbol]] = field(default_factory=dict)
    file_signatures: dict[str, tuple[int, int]] = field(default_factory=dict)
    analysis_count: int = 0

    def add_file(self, analysis: FileAnalysis) -> None:
        self.remove_file(analysis.path)
        self.files[analysis.path] = analysis
        self.analysis_count += 1
        exports: dict[str, SemanticSymbol] = {}
        for symbol in analysis.symbols:
            keys: set[str] = set()
            if symbol.scope_id == "file":
                keys.add(symbol.name)
            if symbol.container:
                keys.add(symbol.qualified_name)
            for key in keys:
                self.symbols.setdefault(key, []).append(symbol)
            if symbol.container is None and symbol.kind in {"function", "class", "variable", "module", "python-module"}:
                exports[symbol.name] = symbol
        self.module_exports[analysis.path] = exports

    def remove_file(self, path: str) -> None:
        previous = self.files.pop(path, None)
        if previous is None:
            return
        self.module_exports.pop(path, None)
        for symbol in previous.symbols:
            keys: set[str] = set()
            if symbol.scope_id == "file":
                keys.add(symbol.name)
            if symbol.container:
                keys.add(symbol.qualified_name)
            for key in keys:
                matches = self.symbols.get(key, [])
                self.symbols[key] = [item for item in matches if item.symbol_id != symbol.symbol_id]
                if not self.symbols[key]:
                    self.symbols.pop(key, None)

    def refresh_imports(self) -> None:
        for file in self.files.values():
            for symbol in file.imports.values():
                if symbol.kind == "module":
                    symbol.members = self.module_exports.get(symbol.module_path or "", {})
                elif symbol.kind == "python-module" and symbol.module_path:
                    symbol.members = python_module_members(symbol.module_path, symbol)
            for ref in file.references:
                if "." not in ref.name:
                    continue
                base, member = ref.name.split(".", 1)
                base_symbol = file.imports.get(base) or file.variables.get(base) or file.classes.get(base)
                member_symbol = None
                if base_symbol and base_symbol.members:
                    member_symbol = base_symbol.members.get(member)
                elif base_symbol and base_symbol.target_type:
                    target = file.classes.get(base_symbol.target_type) or self.find_symbol(base_symbol.target_type, file.path)
                    if target:
                        member_symbol = target.members.get(member)
                if member_symbol:
                    ref.symbol_id = member_symbol.symbol_id

    def find_symbol(self, name: str, path: str | None = None) -> SemanticSymbol | None:
        if path and path in self.files:
            file = self.files[path]
            for table in (file.variables, file.functions, file.classes, file.imports):
                if name in table:
                    return table[name]
        matches = self.symbols.get(name) or []
        return matches[0] if matches else None

    def find_symbol_id(self, symbol_id: str | None) -> SemanticSymbol | None:
        if not symbol_id:
            return None
        for file in self.files.values():
            for symbol in file.symbols:
                if symbol.symbol_id == symbol_id:
                    return symbol
        return None

    def references_to(self, name: str, symbol_id: str | None = None) -> list[Reference]:
        refs: list[Reference] = []
        for file in self.files.values():
            if symbol_id:
                refs.extend(ref for ref in file.references if ref.symbol_id == symbol_id)
            else:
                refs.extend(ref for ref in file.references if ref.name == name or ref.name.endswith(f".{name}"))
        return refs

    def rename_edits(self, name: str, new_name: str, symbol_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
        edits: dict[str, list[dict[str, Any]]] = {}
        for ref in self.references_to(name, symbol_id):
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

    def update_document(self, path: str, source: str) -> FileAnalysis:
        resolved = normalize_path(path)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        previous = self.files.get(resolved)
        if previous and previous.source_hash == digest:
            return previous
        analysis = analyze_source(source, resolved)
        self.add_file(analysis)
        self.refresh_imports()
        return analysis

    def update_file(self, path: str) -> FileAnalysis | None:
        resolved = normalize_path(path)
        try:
            stat_result = os.stat(resolved)
        except OSError:
            self.remove_file(resolved)
            self.file_signatures.pop(resolved, None)
            return None
        signature = (stat_result.st_mtime_ns, stat_result.st_size)
        if self.file_signatures.get(resolved) == signature and resolved in self.files:
            return self.files[resolved]
        analysis = analyze_file(resolved)
        self.file_signatures[resolved] = signature
        self.add_file(analysis)
        self.refresh_imports()
        return analysis


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


def leading_indent(line: str) -> int:
    expanded = line.expandtabs(2)
    return len(expanded) - len(expanded.lstrip(" "))


def build_lexical_scopes(lines: list[str], path: str) -> dict[str, LexicalScope]:
    root = LexicalScope("file", "file", path, 1, max(1, len(lines)), -1)
    scopes = {root.scope_id: root}
    stack = [root]
    serial = 0

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = leading_indent(line)
        while len(stack) > 1 and indent <= stack[-1].indent:
            stack[-1].end_line = line_no - 1
            stack.pop()

        kind = None
        if CLASS_RE.match(line):
            kind = "class"
        elif FN_RE.match(line):
            kind = "function"
        elif re.match(r"^\s*(?:if|elif|else|while|whirl|for|each|try|catch|test)\b", line):
            kind = "block"
        if kind and (line.rstrip().endswith(":") or line.rstrip().endswith("{") or stripped.endswith("bloom")):
            serial += 1
            scope_id = f"{kind}:{line_no}:{serial}"
            scope = LexicalScope(scope_id, kind, path, line_no + 1, max(1, len(lines)), indent, stack[-1].scope_id)
            scopes[scope_id] = scope
            stack.append(scope)

    while len(stack) > 1:
        stack[-1].end_line = max(1, len(lines))
        stack.pop()
    return scopes


def scope_for_line(scopes: dict[str, LexicalScope], line: int, declaration_header: bool = False) -> LexicalScope:
    candidates = [scope for scope in scopes.values() if scope.contains(line)]
    if declaration_header:
        candidates = [scope for scope in candidates if scope.start_line != line + 1]
    return max(candidates, key=lambda scope: (scope.start_line, scope.indent))


def scope_chain(scopes: dict[str, LexicalScope], scope: LexicalScope) -> list[LexicalScope]:
    chain = [scope]
    while chain[-1].parent_id:
        chain.append(scopes[chain[-1].parent_id])
    return chain


def declaration_token_locations(lines: list[str]) -> set[tuple[int, int]]:
    locations: set[tuple[int, int]] = set()
    patterns = [CLASS_RE, FN_RE, IMPORT_RE, IMPORTPY_RE, DECL_RE, FOR_RE, CATCH_RE]
    for line_no, line in enumerate(lines, start=1):
        for pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            group = match.lastindex or 1
            if pattern is IMPORT_RE:
                group = 2
            elif pattern is IMPORTPY_RE:
                group = 3 if match.group(3) else (1 if match.group(1) else 2)
            locations.add((line_no, match.start(group) + 1))
            break
    return locations


def parameter_symbols(lines: list[str], path: str, scopes: dict[str, LexicalScope]) -> list[SemanticSymbol]:
    symbols: list[SemanticSymbol] = []
    for line_no, line in enumerate(lines, start=1):
        match = FN_RE.match(line)
        if not match:
            continue
        open_paren = line.find("(", match.end(1))
        close_paren = line.find(")", open_paren + 1)
        if open_paren < 0 or close_paren < 0:
            continue
        function_scopes = [
            scope for scope in scopes.values()
            if scope.kind == "function" and scope.start_line == line_no + 1
        ]
        if not function_scopes:
            continue
        scope = function_scopes[0]
        params_text = line[open_paren + 1:close_paren]
        offset = open_paren + 1
        for item in params_text.split(","):
            raw = item.strip()
            name_match = re.match(r"(?:\*\*|\*)?([A-Za-z_][A-Za-z0-9_]*)", raw)
            if not name_match:
                offset += len(item) + 1
                continue
            name = name_match.group(1)
            local_start = item.find(name)
            col = offset + local_start + 1
            symbol = SemanticSymbol(name, "parameter", Location(path, line_no, col))
            scope.declare(symbol)
            symbols.append(symbol)
            offset += len(item) + 1
    return symbols


def resolve_in_scope(
    analysis: FileAnalysis,
    name: str,
    line: int,
    scope: LexicalScope,
) -> SemanticSymbol | None:
    for candidate_scope in scope_chain(analysis.scopes, scope):
        declarations = candidate_scope.declarations.get(name, [])
        visible = [
            symbol for symbol in declarations
            if symbol.location.line <= line or symbol.kind in {"function", "class", "method", "module", "python-module"}
        ]
        if visible:
            return visible[-1]
    return None


def bind_references(analysis: FileAnalysis, lines: list[str]) -> None:
    analysis.scopes = build_lexical_scopes(lines, analysis.path)
    declarations = declaration_token_locations(lines)
    canonical_symbols: dict[str, SemanticSymbol] = {}
    retained_symbols: list[SemanticSymbol] = []
    original_symbols = {symbol.symbol_id: symbol for symbol in analysis.symbols}

    for symbol in sorted(analysis.symbols, key=lambda item: (item.location.line, item.location.col)):
        header = symbol.kind in {"function", "method", "class"}
        scope = scope_for_line(analysis.scopes, symbol.location.line, declaration_header=header)
        if symbol.kind == "variable":
            line = lines[symbol.location.line - 1] if symbol.location.line <= len(lines) else ""
            explicit = bool(re.match(r"^\s*(?:let|sprout)\s+", line))
            existing = None
            if not explicit:
                for candidate_scope in scope_chain(analysis.scopes, scope):
                    matches = candidate_scope.declarations.get(symbol.name, [])
                    if matches:
                        existing = matches[-1]
                        break
            if existing:
                canonical_symbols[symbol.symbol_id] = existing
                continue
        scope.declare(symbol)
        canonical_symbols[symbol.symbol_id] = symbol
        retained_symbols.append(symbol)
    analysis.symbols = retained_symbols
    analysis.variables = {
        name: canonical_symbols.get(symbol.symbol_id, symbol)
        for name, symbol in analysis.variables.items()
    }
    params = parameter_symbols(lines, analysis.path, analysis.scopes)
    analysis.symbols.extend(params)

    for line_no, line in enumerate(lines, start=1):
        for pattern, kind in ((FOR_RE, "variable"), (CATCH_RE, "variable")):
            match = pattern.match(line)
            if not match:
                continue
            symbol = SemanticSymbol(match.group(1), kind, Location(analysis.path, line_no, match.start(1) + 1))
            target_scope = scope_for_line(analysis.scopes, min(line_no + 1, max(1, len(lines))))
            target_scope.declare(symbol)
            analysis.symbols.append(symbol)

    analysis.references = []
    analysis.diagnostics = [diag for diag in analysis.diagnostics if diag.code != "SPROUT_UNKNOWN_NAME"]
    special_names = {"self", "super", "argv"}
    exact_symbols = {
        (symbol.location.line, symbol.location.col, symbol.name): symbol
        for symbol in analysis.symbols
    }
    for original_id, canonical in canonical_symbols.items():
        original = original_symbols.get(original_id)
        if original:
            exact_symbols[(original.location.line, original.location.col, original.name)] = canonical
    for line_no, line in enumerate(lines, start=1):
        code = STRING_RE.sub('""', line.split("#", 1)[0])
        current_scope = scope_for_line(analysis.scopes, line_no)
        dotted_members = {
            match.start(2): (match.group(1), match.group(2))
            for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", code)
        }
        for match in IDENT_RE.finditer(code):
            name = match.group(0)
            col = match.start() + 1
            if name in KEYWORDS or (match.start() > 0 and code[match.start() - 1] == "."):
                continue
            declaration_symbol = exact_symbols.get((line_no, col, name))
            if declaration_symbol is None and (line_no, col) in declarations:
                declaration_symbol = resolve_in_scope(analysis, name, line_no, current_scope)
                if declaration_symbol is None:
                    declaration_symbol = next(
                        (symbol for symbol in analysis.symbols if symbol.name == name and symbol.location.line == line_no and symbol.location.col == col),
                        None,
                    )
            symbol = declaration_symbol or resolve_in_scope(analysis, name, line_no, current_scope)
            if declaration_symbol and (
                declaration_symbol.location.line != line_no or declaration_symbol.location.col != col
            ):
                role = "write"
            else:
                role = "declaration" if declaration_symbol else "read"
            analysis.references.append(
                Reference(name, Location(analysis.path, line_no, col), role, symbol.symbol_id if symbol else None)
            )
            if symbol is None and name not in BUILTINS and name not in special_names:
                analysis.diagnostics.append(
                    Diagnostic("warning", f"Unknown name '{name}'", analysis.path, line_no, col, "SPROUT_UNKNOWN_NAME")
                )
        for start, (base, member) in dotted_members.items():
            base_symbol = resolve_in_scope(analysis, base, line_no, current_scope)
            member_symbol = None
            if base_symbol:
                if base_symbol.members:
                    member_symbol = base_symbol.members.get(member)
                elif base_symbol.target_type:
                    target = analysis.classes.get(base_symbol.target_type)
                    if target:
                        member_symbol = target.members.get(member)
            analysis.references.append(
                Reference(
                    f"{base}.{member}",
                    Location(analysis.path, line_no, start + len(base) + 2),
                    "read",
                    member_symbol.symbol_id if member_symbol else None,
                )
            )


def analyze_source(source: str, path: str) -> FileAnalysis:
    resolved = normalize_path(path)
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

    analysis.source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    bind_references(analysis, lines)
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


def build_workspace_index(
    root_or_file: str,
    open_documents: dict[str, str] | None = None,
    previous: WorkspaceIndex | None = None,
) -> WorkspaceIndex:
    root = normalize_path(root_or_file if os.path.isdir(root_or_file) else os.path.dirname(root_or_file))
    project = project_for_path(root_or_file)
    if project:
        root = project.root
    index = previous if previous and normalize_path(previous.root) == root else WorkspaceIndex(root)
    files = workspace_files(root)
    normalized_documents = {
        normalize_path(path): source for path, source in (open_documents or {}).items()
    }
    current = {normalize_path(path) for path in files}
    current.update(normalized_documents)
    for stale in set(index.files) - current:
        index.remove_file(stale)
        index.file_signatures.pop(stale, None)
    for path in files:
        resolved = normalize_path(path)
        if resolved in normalized_documents:
            index.update_document(resolved, normalized_documents[resolved])
        else:
            try:
                index.update_file(resolved)
            except OSError:
                continue
    if normalized_documents:
        for path, source in normalized_documents.items():
            resolved = normalize_path(path)
            if resolved not in index.files and resolved.endswith(".sprout"):
                index.update_document(resolved, source)

    index.refresh_imports()
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
    file = index.files.get(normalize_path(path))
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


def visible_symbols(index: WorkspaceIndex, path: str, line: int) -> list[SemanticSymbol]:
    file = index.files.get(normalize_path(path))
    if not file or not file.scopes:
        return []
    scope = scope_for_line(file.scopes, line)
    visible: dict[str, SemanticSymbol] = {}
    for candidate_scope in scope_chain(file.scopes, scope):
        for name, declarations in candidate_scope.declarations.items():
            candidates = [
                symbol for symbol in declarations
                if symbol.location.line <= line or symbol.kind in {"function", "class", "method", "module", "python-module"}
            ]
            if candidates:
                visible.setdefault(name, candidates[-1])
    return list(visible.values())


def top_level_completions(index: WorkspaceIndex, path: str, line: int | None = None) -> list[SemanticSymbol]:
    file = index.files.get(normalize_path(path))
    out: dict[str, SemanticSymbol] = dict(BUILTINS)
    if file:
        if line is not None:
            out.update({symbol.name: symbol for symbol in visible_symbols(index, path, line)})
        else:
            for table in (file.variables, file.functions, file.classes, file.imports):
                out.update(table)
    for name, symbols in index.symbols.items():
        if "." not in name and symbols:
            out.setdefault(name, symbols[0])
    return sorted(out.values(), key=lambda item: item.name)


def symbol_at(index: WorkspaceIndex, path: str, word: str) -> SemanticSymbol | None:
    path = normalize_path(path)
    file = index.files.get(path)
    if file:
        for table in (file.variables, file.functions, file.classes, file.imports):
            if word in table:
                return table[word]
    if word in BUILTINS:
        return BUILTINS[word]
    return index.find_symbol(word, path)


def symbol_at_position(
    index: WorkspaceIndex,
    path: str,
    line: int,
    col: int,
    word: str | None = None,
) -> SemanticSymbol | None:
    resolved = normalize_path(path)
    file = index.files.get(resolved)
    if not file:
        return None
    candidates = [
        ref for ref in file.references
        if ref.location.line == line
        and ref.location.col <= col <= ref.location.col + len(ref.name.split(".")[-1])
    ]
    if word:
        exact = [ref for ref in candidates if ref.name == word or ref.name.endswith(f".{word}")]
        if exact:
            candidates = exact
    if candidates:
        ref = min(candidates, key=lambda item: len(item.name))
        symbol = index.find_symbol_id(ref.symbol_id)
        if symbol:
            return symbol
        if "." in ref.name:
            base, member = ref.name.split(".", 1)
            return next((item for item in member_completions(index, resolved, base) if item.name == member), None)
    if word in BUILTINS:
        return BUILTINS[word]
    scope = scope_for_line(file.scopes, line) if file.scopes else None
    if scope and word:
        symbol = resolve_in_scope(file, word, line, scope)
        if symbol:
            return symbol
    return symbol_at(index, resolved, word or "")


def references_at(index: WorkspaceIndex, path: str, line: int, col: int, word: str) -> list[Reference]:
    symbol = symbol_at_position(index, path, line, col, word)
    return index.references_to(word, symbol.symbol_id if symbol else None)


def signature_for(index: WorkspaceIndex, path: str, name: str) -> SemanticSymbol | None:
    dotted = name.split(".")
    if len(dotted) == 2:
        members = member_completions(index, path, dotted[0])
        return next((member for member in members if member.name == dotted[1]), None)
    return symbol_at(index, path, name)
