from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
import importlib
import os
import re
import time
from typing import Any

from .facts import ValueFacts
from .languages import (
    all_keyword_spellings,
    bootstrap_language,
    concept_spellings,
    language_pack_for_source,
)
from .model import Diagnostic, KEYWORDS, resolve_module_file
from .runtime import Interpreter
from .tooling import module_search_paths_for, parse_source, project_for_path, read_source_file


IDENT_PATTERN = r"[^\W\d]\w*"


def _concept_pattern(*concept_ids: str) -> str:
    words: list[str] = []
    for concept_id in concept_ids:
        words.extend(concept_spellings(concept_id))
    return "(?:" + "|".join(re.escape(word) for word in sorted(set(words), key=lambda item: (-len(item), item))) + ")"


LANGUAGE_KEYWORDS = all_keyword_spellings()
IDENT_RE = re.compile(rf"(?<!\w){IDENT_PATTERN}(?!\w)")
DECL_RE = re.compile(rf"^\s*(?:(?:{_concept_pattern('syntax.let', 'syntax.sprout-loop')})\s+)?({IDENT_PATTERN})(?:\s*:\s*[^=]+)?\s*=")
FN_RE = re.compile(rf"^\s*(?:{_concept_pattern('syntax.async')}\s+)?{_concept_pattern('syntax.function', 'syntax.function-value', 'syntax.bloom')}\s+({IDENT_PATTERN})(?:\s*\[[^\]]+\])?\s*\(")
CLASS_RE = re.compile(rf"^\s*{_concept_pattern('syntax.class')}\s+({IDENT_PATTERN})(?!\w)")
INTERFACE_RE = re.compile(rf"^\s*{_concept_pattern('syntax.interface')}\s+({IDENT_PATTERN})(?!\w)")
ENUM_RE = re.compile(rf"^\s*{_concept_pattern('syntax.enum')}\s+({IDENT_PATTERN})(?!\w)")
TYPE_ALIAS_RE = re.compile(rf"^\s*{_concept_pattern('syntax.type-alias')}\s+({IDENT_PATTERN})(?!\w)")
IMPORT_RE = re.compile(rf'^\s*{_concept_pattern("syntax.import")}\s+(?:"([^"]+)"|({IDENT_PATTERN}(?:\.{IDENT_PATTERN})*))(?:\s+{_concept_pattern("syntax.alias")}\s+({IDENT_PATTERN}))?')
IMPORTPY_RE = re.compile(rf'^\s*{_concept_pattern("syntax.import-python")}\s+(?:"([^"]+)"|({IDENT_PATTERN}(?:\.{IDENT_PATTERN})*))(?:\s+{_concept_pattern("syntax.alias")}\s+({IDENT_PATTERN}))?')
SELF_ASSIGN_RE = re.compile(rf"\bself\.({IDENT_PATTERN})\s*=")
FIELD_ASSIGN_RE = re.compile(rf"\b({IDENT_PATTERN}(?:\.{IDENT_PATTERN})+)\s*=")
STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')
FOR_RE = re.compile(rf"^\s*(?:{_concept_pattern('syntax.async')}\s+)?{_concept_pattern('syntax.for', 'syntax.each')}\s+({IDENT_PATTERN})\s+{_concept_pattern('operator.in')}(?!\w)")
CATCH_RE = re.compile(rf"^\s*{_concept_pattern('syntax.catch')}\s+({IDENT_PATTERN})(?!\w)")
TASKGROUP_RE = re.compile(rf"^\s*{_concept_pattern('syntax.task-group')}\s+({IDENT_PATTERN})(?!\w)")
COMP_FOR_RE = re.compile(rf"(?<!\w){_concept_pattern('syntax.for')}\s+({IDENT_PATTERN})\s+{_concept_pattern('operator.in')}(?!\w)")

CORE_DIAGNOSTIC_CODES = {
    "SPROUT_ERROR",
    "SPROUT_SYNTAX",
    "SPROUT_IMPORT",
}
STRICT_DIAGNOSTIC_CODES = {
    "SPROUT_MISSING_PARAMETER_TYPE",
    "SPROUT_MISSING_RETURN_TYPE",
}
STANDARD_DIAGNOSTIC_CODES = {
    "SPROUT_POSSIBLY_MISSING_MEMBER",
    "SPROUT_UNREACHABLE",
    "SPROUT_OVERRIDE_SIGNATURE",
}
UNUSED_DIAGNOSTIC_CODES = {
    "SPROUT_UNUSED_NAME",
    "SPROUT_UNUSED_IMPORT",
    "SPROUT_UNUSED_PARAMETER",
}
VALID_DIAGNOSTIC_SEVERITIES = {"error", "warning", "information", "hint", "none"}
LEGACY_NAME_REPLACEMENTS = {
    "print": "say",
    "true": "True",
    "False": "false",
    "None": "nil",
}


def mask_strings_preserving_columns(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        if len(value) <= 2:
            return value
        return '"' + (" " * (len(value) - 2)) + '"'
    return STRING_RE.sub(replace, text)


def normalize_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def diagnostic_severity(
    diagnostic: Diagnostic,
    mode: str = "basic",
    overrides: dict[str, str] | None = None,
) -> str:
    normalized_mode = mode if mode in {"off", "basic", "standard", "strict"} else "basic"
    code = diagnostic.code or ""
    override = (overrides or {}).get(code)
    if override in VALID_DIAGNOSTIC_SEVERITIES:
        return override
    if normalized_mode == "off":
        return diagnostic.severity if code in CORE_DIAGNOSTIC_CODES else "none"
    if code in STRICT_DIAGNOSTIC_CODES and normalized_mode != "strict":
        return "none"
    if code in STANDARD_DIAGNOSTIC_CODES and normalized_mode == "basic":
        return "none"
    if code in UNUSED_DIAGNOSTIC_CODES:
        return "hint"
    if normalized_mode == "strict" and code == "SPROUT_POSSIBLY_MISSING_MEMBER":
        return "error"
    if normalized_mode == "strict" and code in {"SPROUT_UNKNOWN_NAME", "SPROUT_UNKNOWN_MEMBER"} and not (diagnostic.data or {}).get("suggestion"):
        return "error"
    return diagnostic.severity


def apply_diagnostic_policy(
    diagnostics: list[Diagnostic],
    mode: str = "basic",
    overrides: dict[str, str] | None = None,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    for diagnostic in diagnostics:
        severity = diagnostic_severity(diagnostic, mode, overrides)
        if severity == "none":
            continue
        tags = list(diagnostic.tags or [])
        if diagnostic.code in UNUSED_DIAGNOSTIC_CODES and "unnecessary" not in tags:
            tags.append("unnecessary")
        result.append(
            Diagnostic(
                severity,
                diagnostic.message,
                diagnostic.path,
                diagnostic.line,
                diagnostic.col,
                diagnostic.code,
                tags,
                diagnostic.data,
            )
        )
    return result


def best_name_suggestion(name: str, choices: set[str] | list[str], *, max_distance: int = 2) -> str | None:
    if len(name) < 3:
        return None
    pool = sorted({choice for choice in choices if choice and choice != name})
    exact_prefixes = [choice for choice in pool if choice.startswith(name)]
    if len(exact_prefixes) == 1:
        return exact_prefixes[0]
    near_matches = [
        choice for choice in pool
        if abs(len(choice) - len(name)) <= max_distance
        and levenshtein_distance(name, choice) <= max_distance
    ]
    return sorted(near_matches, key=lambda choice: (levenshtein_distance(name, choice), len(choice), choice))[0] if near_matches else None


def keyword_suggestion(name: str) -> str | None:
    return best_name_suggestion(name, LANGUAGE_KEYWORDS)


def code_word_suggestion(name: str, choices: set[str] | list[str]) -> str | None:
    return best_name_suggestion(name, LANGUAGE_KEYWORDS | set(BUILTINS) | set(choices))


def levenshtein_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


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
    facts: ValueFacts = field(default_factory=ValueFacts.unknown_value)
    member_presence: str = "required"
    parameter_names: list[str] = field(default_factory=list)
    parameter_facts: dict[str, ValueFacts] = field(default_factory=dict)
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
            "inferredType": self.facts.type_name,
            "nilable": self.facts.nilable,
            "memberPresence": self.member_presence,
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
    types: dict[str, SemanticSymbol] = field(default_factory=dict)
    scopes: dict[str, LexicalScope] = field(default_factory=dict)
    inferred_locals: dict[str, ValueFacts] = field(default_factory=dict)
    fact_import_signature: tuple[tuple[str, str, str], ...] | None = None
    source_hash: str = ""
    parse_count: int = 1
    analysis_duration_ms: float = 0.0


@dataclass
class AnalysisOptions:
    diagnostic_mode: str = "workspace"
    indexing: bool = True
    user_file_indexing_limit: int = 2000
    use_library_code_for_types: bool = True
    exclude: list[str] = field(default_factory=list)
    language_server_mode: str = "default"

    def normalized(self) -> "AnalysisOptions":
        diagnostic_mode = self.diagnostic_mode if self.diagnostic_mode in {"openFilesOnly", "workspace"} else "workspace"
        language_server_mode = self.language_server_mode if self.language_server_mode in {"default", "light", "off"} else "default"
        limit = max(0, int(self.user_file_indexing_limit or 0))
        indexing = bool(self.indexing)
        use_library_code_for_types = bool(self.use_library_code_for_types)
        if language_server_mode == "light":
            diagnostic_mode = "openFilesOnly"
            limit = min(limit or 2000, 200)
            use_library_code_for_types = False
        elif language_server_mode == "off":
            diagnostic_mode = "openFilesOnly"
            indexing = False
            limit = min(limit or 2000, 50)
            use_library_code_for_types = False
        return AnalysisOptions(
            diagnostic_mode=diagnostic_mode,
            indexing=indexing,
            user_file_indexing_limit=limit or 2000,
            use_library_code_for_types=use_library_code_for_types,
            exclude=[str(item) for item in self.exclude],
            language_server_mode=language_server_mode,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "diagnosticMode": self.diagnostic_mode,
            "indexing": self.indexing,
            "userFileIndexingLimit": self.user_file_indexing_limit,
            "useLibraryCodeForTypes": self.use_library_code_for_types,
            "exclude": list(self.exclude),
            "languageServerMode": self.language_server_mode,
        }


@dataclass
class WorkspaceStatus:
    root: str
    file_count: int
    dependency_edges: int
    reverse_dependency_edges: int
    analysis_count: int
    cache_hits: int
    cache_misses: int
    last_build_reason: str
    last_build_target: str
    last_changed_paths: list[str] = field(default_factory=list)
    last_reindexed_files: list[str] = field(default_factory=list)
    indexing_enabled: bool = True
    excluded_patterns: list[str] = field(default_factory=list)
    cache_hit_rate: float = 0.0
    last_build_duration_ms: float = 0.0
    last_reindexed_duration_ms: float = 0.0
    last_refresh_imports_ms: float = 0.0
    total_build_duration_ms: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "fileCount": self.file_count,
            "dependencyEdges": self.dependency_edges,
            "reverseDependencyEdges": self.reverse_dependency_edges,
            "analysisCount": self.analysis_count,
            "cacheHits": self.cache_hits,
            "cacheMisses": self.cache_misses,
            "lastBuildReason": self.last_build_reason,
            "lastBuildTarget": self.last_build_target,
            "lastChangedPaths": list(self.last_changed_paths),
            "lastReindexedFiles": list(self.last_reindexed_files),
            "indexingEnabled": self.indexing_enabled,
            "excludedPatterns": list(self.excluded_patterns),
            "cacheHitRate": self.cache_hit_rate,
            "lastBuildDurationMs": round(self.last_build_duration_ms, 3),
            "lastReindexedDurationMs": round(self.last_reindexed_duration_ms, 3),
            "lastRefreshImportsMs": round(self.last_refresh_imports_ms, 3),
            "totalBuildDurationMs": round(self.total_build_duration_ms, 3),
        }


@dataclass
class WorkspaceIndex:
    root: str
    files: dict[str, FileAnalysis] = field(default_factory=dict)
    symbols: dict[str, list[SemanticSymbol]] = field(default_factory=dict)
    module_exports: dict[str, dict[str, SemanticSymbol]] = field(default_factory=dict)
    file_signatures: dict[str, tuple[int, int]] = field(default_factory=dict)
    dependency_graph: dict[str, set[str]] = field(default_factory=dict)
    reverse_dependencies: dict[str, set[str]] = field(default_factory=dict)
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    analysis_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    last_changed_paths: list[str] = field(default_factory=list)
    last_reindexed_files: list[str] = field(default_factory=list)
    last_build_reason: str = "startup"
    last_build_target: str = ""
    last_build_duration_ms: float = 0.0
    last_reindexed_duration_ms: float = 0.0
    last_refresh_imports_ms: float = 0.0
    total_build_duration_ms: float = 0.0

    def set_options(self, options: AnalysisOptions | dict[str, Any] | None) -> None:
        self.options = coerce_analysis_options(options)

    def _record_cache_hit(self) -> None:
        self.cache_hits += 1

    def _record_cache_miss(self) -> None:
        self.cache_misses += 1

    def _clear_dependencies(self, path: str) -> None:
        previous = self.dependency_graph.pop(path, set())
        for dependency in previous:
            dependents = self.reverse_dependencies.get(dependency)
            if not dependents:
                continue
            dependents.discard(path)
            if not dependents:
                self.reverse_dependencies.pop(dependency, None)

    def _set_dependencies(self, path: str, dependencies: set[str]) -> None:
        normalized = {normalize_path(item) for item in dependencies if item}
        self._clear_dependencies(path)
        if not normalized:
            return
        self.dependency_graph[path] = normalized
        for dependency in normalized:
            self.reverse_dependencies.setdefault(dependency, set()).add(path)

    def dependents_of(self, paths: set[str] | list[str]) -> set[str]:
        pending = [normalize_path(path) for path in paths]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            for dependent in self.reverse_dependencies.get(current, set()):
                if dependent in seen:
                    continue
                seen.add(dependent)
                pending.append(dependent)
        return seen

    def dependency_closure(self, paths: set[str] | list[str]) -> set[str]:
        pending = [normalize_path(path) for path in paths]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            for dependency in self.dependency_graph.get(current, set()):
                if dependency in seen:
                    continue
                seen.add(dependency)
                pending.append(dependency)
        return seen

    def mark_build(
        self,
        changed_paths: list[str],
        reindexed_files: list[str],
        *,
        reason: str,
        target: str,
        duration_ms: float = 0.0,
        reindexed_duration_ms: float = 0.0,
        refresh_imports_ms: float = 0.0,
    ) -> None:
        self.last_changed_paths = sorted({normalize_path(path) for path in changed_paths if path})
        self.last_reindexed_files = sorted({normalize_path(path) for path in reindexed_files if path})
        self.last_build_reason = reason
        self.last_build_target = normalize_path(target) if target else self.root
        self.last_build_duration_ms = duration_ms
        self.last_reindexed_duration_ms = reindexed_duration_ms
        self.last_refresh_imports_ms = refresh_imports_ms
        self.total_build_duration_ms += duration_ms

    def status(self) -> WorkspaceStatus:
        total_cache = self.cache_hits + self.cache_misses
        cache_hit_rate = (self.cache_hits / total_cache) if total_cache else 0.0
        return WorkspaceStatus(
            root=self.root,
            file_count=len(self.files),
            dependency_edges=sum(len(items) for items in self.dependency_graph.values()),
            reverse_dependency_edges=sum(len(items) for items in self.reverse_dependencies.values()),
            analysis_count=self.analysis_count,
            cache_hits=self.cache_hits,
            cache_misses=self.cache_misses,
            last_build_reason=self.last_build_reason,
            last_build_target=self.last_build_target or self.root,
            last_changed_paths=self.last_changed_paths,
            last_reindexed_files=self.last_reindexed_files,
            indexing_enabled=self.options.indexing,
            excluded_patterns=self.options.exclude,
            cache_hit_rate=cache_hit_rate,
            last_build_duration_ms=self.last_build_duration_ms,
            last_reindexed_duration_ms=self.last_reindexed_duration_ms,
            last_refresh_imports_ms=self.last_refresh_imports_ms,
            total_build_duration_ms=self.total_build_duration_ms,
        )

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
            if (
                symbol.scope_id == "file"
                and symbol.container is None
                and symbol.kind in {"function", "class", "interface", "enum", "type", "variable", "module", "python-module"}
            ):
                exports[symbol.name] = symbol
        self.module_exports[analysis.path] = exports
        self._set_dependencies(
            analysis.path,
            {
                symbol.module_path
                for symbol in analysis.imports.values()
                if symbol.kind == "module" and symbol.module_path
            },
        )

    def remove_file(self, path: str) -> None:
        previous = self.files.pop(path, None)
        if previous is None:
            return
        self.module_exports.pop(path, None)
        self._clear_dependencies(path)
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
        fact_changed: set[str] = set()
        for file in self.files.values():
            for symbol in file.imports.values():
                if symbol.kind == "module":
                    symbol.members = self.module_exports.get(symbol.module_path or "", {})
                elif symbol.kind == "python-module" and symbol.module_path:
                    symbol.members = python_module_members(symbol.module_path, symbol)
            import_signature = tuple(sorted(
                (
                    alias,
                    symbol.module_path or "",
                    fact_file_signature(self.files.get(symbol.module_path or "")),
                )
                for alias, symbol in file.imports.items()
                if symbol.kind == "module"
            ))
            if import_signature and import_signature != file.fact_import_signature:
                infer_semantic_facts(file)
                sync_bound_symbol_facts(file)
                fact_changed.add(file.path)
            file.fact_import_signature = import_signature
        if fact_changed:
            closure = set(fact_changed)
            pending = list(fact_changed)
            while pending:
                path = pending.pop()
                related = self.dependency_graph.get(path, set()) | self.reverse_dependencies.get(path, set())
                for related_path in related:
                    if related_path in self.files and related_path not in closure:
                        closure.add(related_path)
                        pending.append(related_path)
            for _iteration in range(8):
                before = {
                    path: fact_file_signature(self.files.get(path))
                    for path in closure
                }
                for path in sorted(closure):
                    infer_semantic_facts(self.files[path])
                    sync_bound_symbol_facts(self.files[path])
                after = {
                    path: fact_file_signature(self.files.get(path))
                    for path in closure
                }
                if after == before:
                    break
            for file in self.files.values():
                file.fact_import_signature = tuple(sorted(
                    (
                        alias,
                        symbol.module_path or "",
                        fact_file_signature(self.files.get(symbol.module_path or "")),
                    )
                    for alias, symbol in file.imports.items()
                    if symbol.kind == "module"
                ))
        for file in self.files.values():
            self._refresh_member_diagnostics(file)

    def _refresh_member_diagnostics(self, file: FileAnalysis) -> None:
        file.diagnostics = [
            diagnostic for diagnostic in file.diagnostics
            if diagnostic.code not in {"SPROUT_UNKNOWN_MEMBER", "SPROUT_POSSIBLY_MISSING_MEMBER"}
        ]
        for ref in file.references:
            if "." not in ref.name:
                continue
            parts = ref.name.split(".")
            base = parts[0]
            base_symbol = file.imports.get(base) or file.variables.get(base) or file.classes.get(base)
            parent_symbol = resolve_member_chain_symbol(self, file, file.path, ".".join(parts[:-1])) if len(parts) > 2 else base_symbol
            member = parts[-1]
            member_symbol = None
            member_choices: set[str] = set()
            if parent_symbol:
                resolved_members = resolve_symbol_members(self, file, parent_symbol, file.path)
                member_choices = set(resolved_members)
                member_symbol = resolved_members.get(member)
            if member_symbol:
                ref.symbol_id = member_symbol.symbol_id
                if member_symbol.member_presence == "conditional":
                    file.diagnostics.append(
                        Diagnostic(
                            "warning",
                            f"Member '{member}' may be missing from '{'.'.join(parts[:-1])}'",
                            file.path,
                            ref.location.line,
                            ref.location.col,
                            "SPROUT_POSSIBLY_MISSING_MEMBER",
                            None,
                            {
                                "member": member,
                                "owner": ".".join(parts[:-1]),
                                "presence": "conditional",
                            },
                        )
                    )
            elif parent_symbol and (
                (base_symbol and base_symbol.kind == "module" and base_symbol.module_path)
                or parent_symbol.target_type
                or bool(resolve_symbol_members(self, file, parent_symbol, file.path))
            ):
                suggestion = best_name_suggestion(member, member_choices)
                message = (
                    f"'{'.'.join(parts[:-1])}' has no member '{member}'. Did you mean '{suggestion}'?"
                    if suggestion else f"'{'.'.join(parts[:-1])}' has no member '{member}'"
                )
                file.diagnostics.append(
                    Diagnostic(
                        "warning",
                        message,
                        file.path,
                        ref.location.line,
                        ref.location.col,
                        "SPROUT_UNKNOWN_MEMBER",
                        None,
                        {
                            "owner": ".".join(parts[:-1]),
                            "member": member,
                            "suggestion": suggestion,
                            "replacement": suggestion,
                        },
                    )
                )

    def _refresh_variable_shapes(self, file: FileAnalysis) -> None:
        known_class_names = set(file.classes)
        for symbol in file.variables.values():
            if symbol.target_type and not symbol.members:
                target = file.classes.get(symbol.target_type) or self.find_symbol(symbol.target_type, file.path)
                if not target and "." in symbol.target_type:
                    factory = signature_for(self, file.path, symbol.target_type)
                    if factory:
                        if factory.members:
                            symbol.members = {
                                name: clone_member_symbol(member, file.path, symbol.location.line, symbol.location.col, container=symbol.name)
                                for name, member in factory.members.items()
                            }
                        if factory.target_type:
                            target = file.classes.get(factory.target_type) or self.find_symbol(factory.target_type, file.path)
                if target and target.members and not symbol.members:
                    symbol.members = {
                        name: clone_member_symbol(member, file.path, symbol.location.line, symbol.location.col, container=symbol.name)
                        for name, member in target.members.items()
                    }
            merged_members = dict(symbol.members)
            for stmt in walk_statements(file.program):
                if stmt[0] != "assign" or stmt[1][0] != "var" or stmt[1][1] != symbol.name:
                    continue
                target_type = infer_expr_target_from_symbol(stmt[2], known_class_names, file)
                if target_type:
                    symbol.target_type = target_type
                inferred = infer_expr_members(
                    stmt[2],
                    file.path,
                    symbol.location.line,
                    symbol.location.col,
                    container=symbol.name,
                    known_class_names=known_class_names,
                    analysis=file,
                )
                if inferred:
                    merged_members = merge_symbol_members(
                        merged_members,
                        inferred,
                        file.path,
                        symbol.location.line,
                        symbol.location.col,
                        container=symbol.name,
                    )
            if merged_members:
                symbol.members = merged_members

    def find_symbol(self, name: str, path: str | None = None) -> SemanticSymbol | None:
        if path and path in self.files:
            file = self.files[path]
            for table in (file.variables, file.functions, file.classes, file.types, file.imports):
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
            leaf_name = ref.name.split(".")[-1]
            edits.setdefault(ref.location.path, []).append(
                {
                    "range": {
                        "start": {"line": ref.location.line - 1, "character": ref.location.col - 1},
                        "end": {"line": ref.location.line - 1, "character": ref.location.col - 1 + len(leaf_name)},
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
            self._record_cache_hit()
            return previous
        self._record_cache_miss()
        started = time.perf_counter()
        analysis = analyze_source(source, resolved)
        analysis.analysis_duration_ms = (time.perf_counter() - started) * 1000.0
        self.add_file(analysis)
        self.refresh_imports()
        return analysis

    def update_file(self, path: str, force: bool = False) -> FileAnalysis | None:
        resolved = normalize_path(path)
        try:
            stat_result = os.stat(resolved)
        except OSError:
            self.remove_file(resolved)
            self.file_signatures.pop(resolved, None)
            return None
        signature = (stat_result.st_mtime_ns, stat_result.st_size)
        if not force and self.file_signatures.get(resolved) == signature and resolved in self.files:
            self._record_cache_hit()
            return self.files[resolved]
        self._record_cache_miss()
        started = time.perf_counter()
        analysis = analyze_file(resolved)
        analysis.analysis_duration_ms = (time.perf_counter() - started) * 1000.0
        self.file_signatures[resolved] = signature
        self.add_file(analysis)
        self.refresh_imports()
        return analysis


def coerce_analysis_options(options: AnalysisOptions | dict[str, Any] | None) -> AnalysisOptions:
    if isinstance(options, AnalysisOptions):
        return options.normalized()
    if not isinstance(options, dict):
        return AnalysisOptions().normalized()
    return AnalysisOptions(
        diagnostic_mode=str(options.get("diagnosticMode", options.get("diagnostic_mode", "workspace"))),
        indexing=bool(options.get("indexing", True)),
        user_file_indexing_limit=int(options.get("userFileIndexingLimit", options.get("user_file_indexing_limit", 2000)) or 2000),
        use_library_code_for_types=bool(options.get("useLibraryCodeForTypes", options.get("use_library_code_for_types", True))),
        exclude=[str(item) for item in options.get("exclude", [])],
        language_server_mode=str(options.get("languageServerMode", options.get("language_server_mode", "default"))),
    ).normalized()


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


def annotation_name(annotation: Any) -> str:
    if annotation is None:
        return ""
    if annotation[0] == "union":
        return " | ".join(annotation_name(item) for item in annotation[1])
    arguments = annotation[2]
    if arguments:
        return f"{annotation[1]}[{', '.join(annotation_name(item) for item in arguments)}]"
    return str(annotation[1])


def params_signature(
    params: list[tuple[str, Any, bool, bool]],
    metadata: dict[str, Any] | None = None,
) -> str:
    parts = []
    parameter_types = (metadata or {}).get("parameter_types", {})
    for name, default, variadic, kw_variadic in params:
        prefix = "**" if kw_variadic else ("*" if variadic else "")
        annotation = parameter_types.get(name)
        suffix = f": {annotation_name(annotation)}" if annotation else ""
        if default is not None:
            parts.append(f"{prefix}{name}{suffix}=...")
        else:
            parts.append(f"{prefix}{name}{suffix}")
    return ", ".join(parts)


def function_signature(
    name: str,
    params: list[tuple[str, Any, bool, bool]],
    metadata: dict[str, Any] | None = None,
) -> str:
    type_params = (metadata or {}).get("type_params", [])
    generic = f"[{', '.join(type_params)}]" if type_params else ""
    result = f"{name}{generic}({params_signature(params, metadata)})"
    return_type = (metadata or {}).get("return_type")
    return result + (f" -> {annotation_name(return_type)}" if return_type else "")


def inferred_return_target(stmt: Any, known_class_names: set[str]) -> str | None:
    targets = {
        target
        for expr in function_return_exprs(stmt)
        for target in [infer_expr_target(expr, known_class_names)]
        if target
    }
    if len(targets) == 1:
        return next(iter(targets))
    return None


def inferred_return_members(stmt: Any, path: str, line: int, col: int, known_class_names: set[str]) -> dict[str, SemanticSymbol]:
    merged: dict[str, SemanticSymbol] = {}
    for expr in function_return_exprs(stmt):
        members = infer_expr_members(
            expr,
            path,
            line,
            col,
            container=stmt[1],
            known_class_names=known_class_names,
        )
        if members:
            merged = merge_symbol_members(merged, members, path, line, col, container=stmt[1])
    return merged


def expr_head_name(expr: Any) -> str | None:
    if not isinstance(expr, tuple):
        return None
    if expr[0] == "var":
        return str(expr[1])
    if expr[0] == "get":
        base = expr_head_name(expr[1])
        return f"{base}.{expr[2]}" if base else None
    return None


def infer_expr_target(expr: Any, known_class_names: set[str]) -> str | None:
    if not isinstance(expr, tuple) or expr[0] != "call":
        return None
    head = expr_head_name(expr[1])
    if not head:
        return None
    if head in known_class_names or "." in head:
        return head
    return head


def infer_expr_target_from_symbol(
    expr: Any,
    known_class_names: set[str],
    analysis: FileAnalysis | None = None,
) -> str | None:
    target = infer_expr_target(expr, known_class_names)
    if target:
        return target
    if analysis is None:
        return None
    indexed_target = infer_indexed_target_type(analysis, expr, known_class_names)
    if indexed_target:
        return indexed_target
    resolved_symbol = resolve_expr_symbol(analysis, expr)
    if not resolved_symbol:
        return None
    if resolved_symbol.target_type:
        return resolved_symbol.target_type
    if resolved_symbol.kind in {"class", "enum", "interface", "type"}:
        return resolved_symbol.name
    return None


def clone_member_symbol(
    symbol: SemanticSymbol,
    path: str,
    line: int,
    col: int,
    *,
    container: str | None = None,
) -> SemanticSymbol:
    cloned = SemanticSymbol(
        symbol.name,
        symbol.kind,
        Location(path, line, col),
        signature=symbol.signature,
        documentation=symbol.documentation,
        container=container,
        module_path=symbol.module_path,
        target_type=symbol.target_type,
        facts=symbol.facts.copy(),
        member_presence=symbol.member_presence,
        parameter_names=list(symbol.parameter_names),
        parameter_facts={name: facts.copy() for name, facts in symbol.parameter_facts.items()},
    )
    if symbol.members:
        cloned.members = {
            name: clone_member_symbol(member, path, line, col, container=cloned.qualified_name)
            for name, member in symbol.members.items()
        }
    return cloned


def resolve_member_from_symbol(
    analysis: FileAnalysis,
    base: SemanticSymbol | None,
    member: str,
) -> SemanticSymbol | None:
    if not base:
        return None
    if base.members and member in base.members:
        return base.members[member]
    if base.target_type:
        target = analysis.classes.get(base.target_type)
        if not target and "." in base.target_type:
            target = next(
                (
                    symbol for symbol in analysis.symbols
                    if symbol.qualified_name == base.target_type or symbol.name == base.target_type
                ),
                None,
            )
        if target and target.members:
            return target.members.get(member)
    return None


def unwrap_call_arg(arg: Any) -> Any:
    if isinstance(arg, tuple) and len(arg) == 2 and arg[0] == "value":
        return arg[1]
    return arg


def resolve_expr_symbol(analysis: FileAnalysis, expr: Any) -> SemanticSymbol | None:
    if not isinstance(expr, tuple):
        return None
    kind = expr[0]
    if kind == "var":
        name = expr[1]
        return (
            analysis.variables.get(name)
            or analysis.imports.get(name)
            or analysis.classes.get(name)
            or analysis.functions.get(name)
            or analysis.types.get(name)
            or BUILTINS.get(name)
        )
    if kind == "get":
        return resolve_member_from_symbol(analysis, resolve_expr_symbol(analysis, expr[1]), expr[2])
    if kind == "index":
        base = resolve_expr_symbol(analysis, expr[1])
        index_expr = expr[2]
        if isinstance(index_expr, tuple) and index_expr[0] == "literal" and isinstance(index_expr[1], str):
            return resolve_member_from_symbol(analysis, base, index_expr[1])
        return None
    if kind == "call":
        callee = expr[1]
        args = [unwrap_call_arg(arg) for arg in expr[2]]
        if isinstance(callee, tuple) and callee[0] == "var" and callee[1] == "get" and len(args) >= 2:
            base = resolve_expr_symbol(analysis, args[0])
            key_expr = args[1]
            if isinstance(key_expr, tuple) and key_expr[0] == "literal" and isinstance(key_expr[1], str):
                member = resolve_member_from_symbol(analysis, base, key_expr[1])
                if member:
                    return member
                if len(args) >= 3:
                    return resolve_expr_symbol(analysis, args[2])
        return resolve_expr_symbol(analysis, expr[1])
    return None


def infer_expr_members(
    expr: Any,
    path: str,
    line: int,
    col: int,
    *,
    container: str | None = None,
    known_class_names: set[str] | None = None,
    analysis: FileAnalysis | None = None,
) -> dict[str, SemanticSymbol]:
    known_class_names = known_class_names or set()
    if (
        analysis is not None
        and isinstance(expr, tuple)
        and expr[0] == "call"
        and isinstance(expr[1], tuple)
        and expr[1][0] == "var"
        and expr[1][1] == "get"
    ):
        args = [unwrap_call_arg(arg) for arg in expr[2]]
        if len(args) >= 2:
            merged: dict[str, SemanticSymbol] = {}
            base = resolve_expr_symbol(analysis, args[0])
            key_expr = args[1]
            if (
                base
                and isinstance(key_expr, tuple)
                and key_expr[0] == "literal"
                and isinstance(key_expr[1], str)
            ):
                member = resolve_member_from_symbol(analysis, base, key_expr[1])
                if member:
                    merged = merge_symbol_members(
                        merged,
                        {
                            name: clone_member_symbol(item, path, line, col, container=container)
                            for name, item in member.members.items()
                        },
                        path,
                        line,
                        col,
                        container=container,
                    )
            if len(args) >= 3:
                fallback = infer_expr_members(
                    args[2],
                    path,
                    line,
                    col,
                    container=container,
                    known_class_names=known_class_names,
                    analysis=analysis,
                )
                if fallback:
                    merged = merge_symbol_members(merged, fallback, path, line, col, container=container)
            if merged:
                return merged
    if analysis is not None:
        indexed_members = infer_indexed_members(
            analysis,
            expr,
            path,
            line,
            col,
            container=container,
            known_class_names=known_class_names,
        )
        if indexed_members:
            return indexed_members
    if analysis is not None:
        resolved_symbol = resolve_expr_symbol(analysis, expr)
        if resolved_symbol and resolved_symbol.members:
            return {
                name: clone_member_symbol(member, path, line, col, container=container)
                for name, member in resolved_symbol.members.items()
            }
    if not isinstance(expr, tuple) or expr[0] != "dict":
        return {}
    members: dict[str, SemanticSymbol] = {}
    for key_expr, value_expr in expr[1]:
        if not (
            isinstance(key_expr, tuple)
            and key_expr[0] == "literal"
            and isinstance(key_expr[1], str)
            and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key_expr[1])
        ):
            continue
        member = SemanticSymbol(
            key_expr[1],
            "property",
            Location(path, line, col),
            container=container,
            target_type=infer_expr_target_from_symbol(value_expr, known_class_names, analysis),
        )
        nested = infer_expr_members(
            value_expr,
            path,
            line,
            col,
            container=member.qualified_name,
            known_class_names=known_class_names,
            analysis=analysis,
        )
        if nested:
            member.members = nested
        members[member.name] = member
    return members


def parse_inline_expr(text: str) -> Any | None:
    try:
        program = parse_source(f"tmp = {text}\n")
    except Exception:
        return None
    if not program:
        return None
    stmt = program[0]
    if isinstance(stmt, tuple) and stmt[0] == "assign":
        return stmt[2]
    return None


def attach_member_path(
    analysis: FileAnalysis,
    root_symbol: SemanticSymbol,
    parts: list[str],
    path: str,
    line: int,
    col: int,
    *,
    value_expr: Any | None = None,
    known_class_names: set[str] | None = None,
) -> None:
    current = root_symbol
    known_class_names = known_class_names or set()
    for index, part in enumerate(parts):
        member = current.members.get(part)
        if member is None:
            member = SemanticSymbol(part, "property", Location(path, line, col), container=current.qualified_name)
            current.members[part] = member
            analysis.symbols.append(member)
        current = member
        if index == len(parts) - 1 and value_expr is not None:
            target_type = infer_expr_target_from_symbol(value_expr, known_class_names, analysis)
            if target_type:
                current.target_type = target_type
            nested = infer_expr_members(
                value_expr,
                path,
                line,
                col,
                container=current.qualified_name,
                known_class_names=known_class_names,
                analysis=analysis,
            )
            if nested:
                current.members.update(nested)


def walk_statements(program: list[Any]) -> list[Any]:
    out: list[Any] = []

    def visit(stmt: Any) -> None:
        out.append(stmt)
        kind = stmt[0]
        if kind in {"interface", "enum", "type_alias"}:
            return
        children: list[list[Any]] = []
        if kind in {"fn", "async_fn", "test"}:
            children = [stmt[3] if kind in {"fn", "async_fn"} else stmt[2]]
        elif kind == "class":
            children = [stmt[3]]
        elif kind == "if":
            children = [stmt[2], stmt[3]]
        elif kind in {"while", "for", "async_for"}:
            children = [stmt[-1]]
        elif kind == "try":
            children = [stmt[1], stmt[3]]
        elif kind == "taskgroup":
            children = [stmt[2]]
        elif kind == "match":
            children = [case[2] for case in stmt[2]]
        for child_list in children:
            for item in child_list:
                if isinstance(item, tuple) and item:
                    visit(item)

    for stmt in program:
        visit(stmt)
    return out


def merge_symbol_members(
    existing: dict[str, SemanticSymbol],
    incoming: dict[str, SemanticSymbol],
    path: str,
    line: int,
    col: int,
    *,
    container: str | None = None,
) -> dict[str, SemanticSymbol]:
    merged = {
        name: clone_member_symbol(symbol, path, line, col, container=container)
        for name, symbol in existing.items()
    }
    for name, symbol in incoming.items():
        if name not in merged:
            merged[name] = clone_member_symbol(symbol, path, line, col, container=container)
            continue
        current = merged[name]
        if not current.documentation and symbol.documentation:
            current.documentation = symbol.documentation
        if not current.signature and symbol.signature:
            current.signature = symbol.signature
        if not current.target_type and symbol.target_type:
            current.target_type = symbol.target_type
        if symbol.members:
            current.members = merge_symbol_members(
                current.members,
                symbol.members,
                path,
                line,
                col,
                container=current.qualified_name,
            )
    return merged


def function_return_exprs(stmt: Any) -> list[Any]:
    if not isinstance(stmt, tuple) or stmt[0] not in {"fn", "async_fn"}:
        return []
    exprs: list[Any] = []

    def visit(statements: list[Any]) -> None:
        for child in statements:
            if not isinstance(child, tuple) or not child:
                continue
            kind = child[0]
            if kind == "return":
                exprs.append(child[1])
            elif kind in {"fn", "async_fn", "class", "test"}:
                continue
            elif kind == "if":
                visit(child[2])
                visit(child[3])
            elif kind in {"while", "for", "async_for"}:
                visit(child[-1])
            elif kind == "try":
                visit(child[1])
                visit(child[3])
            elif kind == "taskgroup":
                visit(child[2])
            elif kind == "match":
                for case in child[2]:
                    visit(case[2])

    visit(stmt[3])
    return exprs


def facts_from_annotation(annotation: Any) -> ValueFacts:
    if annotation is None:
        return ValueFacts.unknown_value()
    if annotation[0] == "union":
        result: ValueFacts | None = None
        for member in annotation[1]:
            facts = facts_from_annotation(member)
            result = facts if result is None else result.join(facts)
        return result or ValueFacts.unknown_value()
    name = str(annotation[1])
    arguments = annotation[2]
    if name in {"List", "Array", "Generator", "Task"} and arguments:
        item = facts_from_annotation(arguments[0])
        return ValueFacts(types=(f"{name}[{item.type_name}]",), item=item)
    if name == "Dict" and len(arguments) == 2:
        key = facts_from_annotation(arguments[0])
        value = facts_from_annotation(arguments[1])
        return ValueFacts(types=(f"Dict[{key.type_name}, {value.type_name}]",), key=key, value=value)
    return ValueFacts.of_type(name, target_type=name if name not in {"Any", "Nil", "Bool", "Int", "Float", "Number", "String"} else None)


def sync_symbol_facts(symbol: SemanticSymbol, facts: ValueFacts) -> None:
    symbol.facts = facts.copy()
    if facts.target_type:
        symbol.target_type = facts.target_type
    if not facts.members:
        return
    existing = symbol.members
    members: dict[str, SemanticSymbol] = {}
    for name, member_facts in facts.members.items():
        member = existing.get(name) or SemanticSymbol(
            name,
            "property",
            symbol.location,
            container=symbol.qualified_name,
        )
        member.member_presence = member_facts.presence
        sync_symbol_facts(member, member_facts)
        members[name] = member
    for name, member in existing.items():
        if member.kind in {"method", "function", "enum-member"}:
            members.setdefault(name, member)
    symbol.members = members


def facts_from_symbol(symbol: SemanticSymbol | None) -> ValueFacts:
    if symbol is None:
        return ValueFacts.unknown_value()
    if not symbol.facts.is_pure_unknown:
        return symbol.facts.copy()
    if symbol.kind in {"class", "interface"}:
        members = {
            name: member.facts.copy()
            for name, member in symbol.members.items()
        }
        return ValueFacts(
            types=(symbol.name,),
            members=members,
            target_type=symbol.name,
        )
    if symbol.members:
        return ValueFacts.object({
            name: member.facts.copy()
            for name, member in symbol.members.items()
        })
    if symbol.target_type:
        return ValueFacts.of_type(symbol.target_type, target_type=symbol.target_type)
    return ValueFacts.unknown_value()


def fact_file_signature(file: FileAnalysis | None) -> str:
    if file is None:
        return ""
    payload = [
        (
            symbol.symbol_id,
            symbol.facts.type_name,
            tuple(sorted(
                (name, member.member_presence, member.facts.type_name)
                for name, member in symbol.members.items()
            )),
            tuple(sorted(
                (name, facts.type_name)
                for name, facts in symbol.parameter_facts.items()
            )),
        )
        for symbol in file.symbols
        if symbol.scope_id == "file" or symbol.kind in {"function", "method", "class"}
    ]
    raw = repr((file.source_hash, payload))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _join_facts(items: list[ValueFacts]) -> ValueFacts:
    known = [item for item in items if not item.is_pure_unknown]
    source = known or items
    if not source:
        return ValueFacts.of_type("Nil")
    result = source[0].copy()
    for item in source[1:]:
        result = result.join(item)
    return result


def infer_expression_facts(
    expr: Any,
    env: dict[str, ValueFacts],
    analysis: FileAnalysis,
    call_updates: dict[str, dict[str, ValueFacts]],
) -> ValueFacts:
    if not isinstance(expr, tuple):
        return ValueFacts.unknown_value()
    kind = expr[0]
    if kind == "literal":
        value = expr[1]
        name = (
            "Nil" if value is None else
            "Bool" if isinstance(value, bool) else
            "Int" if isinstance(value, int) else
            "Float" if isinstance(value, float) else
            "String" if isinstance(value, str) else
            "Any"
        )
        return ValueFacts.of_type(name)
    if kind == "var":
        return env.get(expr[1], facts_from_symbol(resolve_expr_symbol(analysis, expr))).copy()
    if kind == "dict":
        members: dict[str, ValueFacts] = {}
        keys: list[ValueFacts] = []
        values: list[ValueFacts] = []
        for key_expr, value_expr in expr[1]:
            key_facts = infer_expression_facts(key_expr, env, analysis, call_updates)
            value_facts = infer_expression_facts(value_expr, env, analysis, call_updates)
            keys.append(key_facts)
            values.append(value_facts)
            if (
                isinstance(key_expr, tuple)
                and key_expr[0] == "literal"
                and isinstance(key_expr[1], str)
                and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key_expr[1])
            ):
                members[key_expr[1]] = value_facts
        result = ValueFacts.object(members)
        if keys:
            result.key = _join_facts(keys)
        if values:
            result.value = _join_facts(values)
            result.types = (f"Dict[{result.key.type_name}, {result.value.type_name}]",)
        return result
    if kind == "array":
        item = _join_facts([
            infer_expression_facts(value, env, analysis, call_updates)
            for value in expr[1]
        ])
        return ValueFacts(types=(f"List[{item.type_name}]",), item=item)
    if kind == "list_comp":
        local = dict(env)
        iterable = infer_expression_facts(expr[3], env, analysis, call_updates)
        local[expr[2]] = iterable.item.copy() if iterable.item else ValueFacts.unknown_value()
        item = infer_expression_facts(expr[1], local, analysis, call_updates)
        return ValueFacts(types=(f"List[{item.type_name}]",), item=item)
    if kind == "dict_comp":
        local = dict(env)
        iterable = infer_expression_facts(expr[4], env, analysis, call_updates)
        local[expr[3]] = iterable.item.copy() if iterable.item else ValueFacts.unknown_value()
        key = infer_expression_facts(expr[1], local, analysis, call_updates)
        value = infer_expression_facts(expr[2], local, analysis, call_updates)
        return ValueFacts(types=(f"Dict[{key.type_name}, {value.type_name}]",), key=key, value=value)
    if kind in {"index", "slice"}:
        container = infer_expression_facts(expr[1], env, analysis, call_updates)
        if kind == "slice":
            return container
        if container.item:
            return container.item.copy()
        if container.value:
            if (
                isinstance(expr[2], tuple)
                and expr[2][0] == "literal"
                and isinstance(expr[2][1], str)
                and expr[2][1] in container.members
            ):
                return container.members[expr[2][1]].copy()
            return container.value.copy()
        return ValueFacts.unknown_value()
    if kind == "get":
        owner = infer_expression_facts(expr[1], env, analysis, call_updates)
        if expr[2] in owner.members:
            return owner.members[expr[2]].copy()
        return facts_from_symbol(resolve_expr_symbol(analysis, expr))
    if kind == "unary":
        return ValueFacts.of_type("Bool") if expr[1] == "!" else infer_expression_facts(expr[2], env, analysis, call_updates)
    if kind == "binary":
        if expr[1] in {"==", "!=", "<", "<=", ">", ">=", "in", "and", "or"}:
            return ValueFacts.of_type("Bool")
        left = infer_expression_facts(expr[2], env, analysis, call_updates)
        right = infer_expression_facts(expr[3], env, analysis, call_updates)
        if "String" in left.types or "String" in right.types:
            return ValueFacts.of_type("String")
        return left.join(right)
    if kind == "await":
        task = infer_expression_facts(expr[1], env, analysis, call_updates)
        return task.item.copy() if task.item else ValueFacts.unknown_value()
    if kind == "call":
        callee_expr = expr[1]
        positional = [
            infer_expression_facts(unwrap_call_arg(arg), env, analysis, call_updates)
            for arg in expr[2]
        ]
        keyword = {
            arg[1]: infer_expression_facts(arg[2], env, analysis, call_updates)
            for arg in expr[3]
            if isinstance(arg, tuple) and arg[0] == "pair"
        }
        if isinstance(callee_expr, tuple) and callee_expr[0] == "var" and callee_expr[1] == "get":
            if len(positional) >= 2:
                base = positional[0]
                key_expr = unwrap_call_arg(expr[2][1])
                if (
                    isinstance(key_expr, tuple)
                    and key_expr[0] == "literal"
                    and isinstance(key_expr[1], str)
                    and key_expr[1] in base.members
                ):
                    found = base.members[key_expr[1]].copy()
                    if len(positional) >= 3:
                        return found.join(positional[2])
                    return found.join(ValueFacts.of_type("Nil"))
                if base.value:
                    return base.value.join(positional[2]) if len(positional) >= 3 else base.value.join(ValueFacts.of_type("Nil"))
            return ValueFacts.unknown_value()
        callee = resolve_expr_symbol(analysis, callee_expr)
        if callee and callee.kind in {"class", "interface"}:
            initializer = callee.members.get("init")
            if initializer:
                _record_call_facts(initializer, positional, keyword, call_updates, skip_self=True)
            facts = facts_from_symbol(callee)
            facts.target_type = callee.name
            facts.types = (callee.name,)
            return facts
        if callee:
            _record_call_facts(callee, positional, keyword, call_updates, skip_self=callee.kind == "method")
            return facts_from_symbol(callee)
        return ValueFacts.unknown_value()
    return ValueFacts.unknown_value()


def _record_call_facts(
    function: SemanticSymbol,
    positional: list[ValueFacts],
    keyword: dict[str, ValueFacts],
    updates: dict[str, dict[str, ValueFacts]],
    *,
    skip_self: bool,
) -> None:
    names = list(function.parameter_names)
    if skip_self and names and names[0] == "self":
        names = names[1:]
    target = updates.setdefault(function.symbol_id, {})
    for name, facts in zip(names, positional):
        target[name] = target[name].join(facts) if name in target else facts.copy()
        previous = function.parameter_facts.get(name, ValueFacts.unknown_value())
        function.parameter_facts[name] = previous.join(facts)
    for name, facts in keyword.items():
        if name in names:
            target[name] = target[name].join(facts) if name in target else facts.copy()
            previous = function.parameter_facts.get(name, ValueFacts.unknown_value())
            function.parameter_facts[name] = previous.join(facts)


def _merge_fact_envs(base: dict[str, ValueFacts], branches: list[dict[str, ValueFacts]]) -> dict[str, ValueFacts]:
    merged = dict(base)
    names = set().union(*(branch.keys() for branch in branches))
    for name in names:
        values = [branch.get(name, base.get(name, ValueFacts.unknown_value())) for branch in branches]
        merged[name] = _join_facts(values)
    return merged


def assign_member_facts(
    target: Any,
    value: ValueFacts,
    env: dict[str, ValueFacts],
    analysis: FileAnalysis,
) -> bool:
    if not isinstance(target, tuple) or target[0] != "get":
        return False
    owner, member_name = target[1], target[2]
    if owner[0] == "var":
        owner_name = owner[1]
        owner_facts = env.get(owner_name, facts_from_symbol(analysis.variables.get(owner_name))).copy()
        owner_facts.members[member_name] = value.copy()
        object_facts = ValueFacts.object(owner_facts.members)
        owner_facts.types = object_facts.types
        owner_facts.key = object_facts.key
        owner_facts.value = object_facts.value
        env[owner_name] = owner_facts
        symbol = analysis.variables.get(owner_name)
        if symbol:
            sync_symbol_facts(symbol, owner_facts)
        return True
    if owner[0] == "get":
        root = owner
        chain = [member_name]
        while root[0] == "get":
            chain.append(root[2])
            root = root[1]
        if root[0] != "var":
            return False
        owner_name = root[1]
        owner_facts = env.get(owner_name, facts_from_symbol(analysis.variables.get(owner_name))).copy()
        current = owner_facts
        for part in reversed(chain[1:]):
            current.members.setdefault(part, ValueFacts.object({}))
            current = current.members[part]
        current.members[chain[0]] = value.copy()
        env[owner_name] = owner_facts
        symbol = analysis.variables.get(owner_name)
        if symbol:
            sync_symbol_facts(symbol, owner_facts)
        return True
    return False


def analyze_fact_statements(
    statements: list[Any],
    env: dict[str, ValueFacts],
    analysis: FileAnalysis,
    call_updates: dict[str, dict[str, ValueFacts]],
    *,
    current_class: SemanticSymbol | None = None,
) -> list[ValueFacts]:
    returns: list[ValueFacts] = []
    for stmt in statements:
        kind = stmt[0]
        if kind == "let":
            env[stmt[1]] = facts_from_annotation(stmt[3]) if len(stmt) > 3 and stmt[3] else infer_expression_facts(stmt[2], env, analysis, call_updates)
            symbol = analysis.variables.get(stmt[1])
            if symbol:
                sync_symbol_facts(symbol, env[stmt[1]])
        elif kind == "assign":
            value = infer_expression_facts(stmt[2], env, analysis, call_updates)
            target = stmt[1]
            if target[0] == "var":
                env[target[1]] = value
                symbol = analysis.variables.get(target[1])
                if symbol:
                    sync_symbol_facts(symbol, value)
            elif target[0] == "get" and target[1] == ("var", "self") and current_class:
                member = current_class.members.get(target[2]) or SemanticSymbol(
                    target[2],
                    "field",
                    current_class.location,
                    container=current_class.name,
                )
                sync_symbol_facts(member, value)
                current_class.members[target[2]] = member
            elif target[0] == "get":
                assign_member_facts(target, value, env, analysis)
        elif kind == "return":
            returns.append(ValueFacts.of_type("Nil") if stmt[1] is None else infer_expression_facts(stmt[1], env, analysis, call_updates))
        elif kind == "yield":
            returns.append(infer_expression_facts(stmt[1], env, analysis, call_updates))
        elif kind == "expr":
            infer_expression_facts(stmt[1], env, analysis, call_updates)
        elif kind == "say":
            for expr in stmt[1]:
                infer_expression_facts(expr, env, analysis, call_updates)
        elif kind == "if":
            then_env = dict(env)
            else_env = dict(env)
            returns.extend(analyze_fact_statements(stmt[2], then_env, analysis, call_updates, current_class=current_class))
            returns.extend(analyze_fact_statements(stmt[3], else_env, analysis, call_updates, current_class=current_class))
            env.update(_merge_fact_envs(env, [then_env, else_env]))
        elif kind in {"for", "async_for"}:
            iterable = infer_expression_facts(stmt[2], env, analysis, call_updates)
            item = iterable.item.copy() if iterable.item else iterable.key.copy() if iterable.key else ValueFacts.unknown_value()
            loop_env = dict(env)
            loop_env[stmt[1]] = item
            analysis.inferred_locals[stmt[1]] = (
                analysis.inferred_locals[stmt[1]].join(item)
                if stmt[1] in analysis.inferred_locals else item.copy()
            )
            for symbol in analysis.symbols:
                if symbol.name == stmt[1] and symbol.kind == "variable":
                    sync_symbol_facts(symbol, item)
            returns.extend(analyze_fact_statements(stmt[3], loop_env, analysis, call_updates, current_class=current_class))
            env.update(_merge_fact_envs(env, [env, loop_env]))
        elif kind == "while":
            loop_env = dict(env)
            returns.extend(analyze_fact_statements(stmt[2], loop_env, analysis, call_updates, current_class=current_class))
            env.update(_merge_fact_envs(env, [env, loop_env]))
        elif kind == "try":
            try_env = dict(env)
            catch_env = dict(env)
            returns.extend(analyze_fact_statements(stmt[1], try_env, analysis, call_updates, current_class=current_class))
            returns.extend(analyze_fact_statements(stmt[3], catch_env, analysis, call_updates, current_class=current_class))
            env.update(_merge_fact_envs(env, [try_env, catch_env]))
        elif kind == "match":
            branch_envs: list[dict[str, ValueFacts]] = []
            for _pattern, _guard, body, _line, _col in stmt[2]:
                branch = dict(env)
                returns.extend(analyze_fact_statements(body, branch, analysis, call_updates, current_class=current_class))
                branch_envs.append(branch)
            if branch_envs:
                env.update(_merge_fact_envs(env, branch_envs))
        elif kind == "taskgroup":
            returns.extend(analyze_fact_statements(stmt[2], dict(env), analysis, call_updates, current_class=current_class))
    return returns


def infer_semantic_facts(analysis: FileAnalysis) -> None:
    function_defs: list[tuple[Any, SemanticSymbol, SemanticSymbol | None]] = []
    symbols_by_line = {
        (symbol.location.line, symbol.name, symbol.container): symbol
        for symbol in analysis.symbols
        if symbol.kind in {"function", "method"}
    }
    for stmt in analysis.program:
        if stmt[0] in {"fn", "async_fn"}:
            symbol = symbols_by_line.get((stmt[4], stmt[1], None))
            if symbol:
                function_defs.append((stmt, symbol, None))
        elif stmt[0] == "class":
            klass = analysis.classes.get(stmt[1])
            for method in stmt[3]:
                symbol = symbols_by_line.get((method[4], method[1], stmt[1]))
                if symbol:
                    function_defs.append((method, symbol, klass))
    for stmt, symbol, _klass in function_defs:
        metadata = stmt[6] if len(stmt) > 6 else {}
        symbol.parameter_names = [param[0] for param in stmt[2]]
        previous_parameter_facts = symbol.parameter_facts
        symbol.parameter_facts = {
            name: (
                facts_from_annotation(metadata.get("parameter_types", {}).get(name))
                if metadata.get("parameter_types", {}).get(name)
                else previous_parameter_facts.get(name, ValueFacts.unknown_value()).copy()
            )
            for name in symbol.parameter_names
        }
    call_updates: dict[str, dict[str, ValueFacts]] = {}
    for _iteration in range(12):
        before = {
            symbol.symbol_id: (
                symbol.facts.type_name,
                tuple(sorted((name, member.member_presence, member.facts.type_name) for name, member in symbol.members.items())),
                tuple(sorted((name, facts.type_name) for name, facts in symbol.parameter_facts.items())),
            )
            for _stmt, symbol, _klass in function_defs
        }
        global_env = {
            name: facts_from_symbol(symbol)
            for name, symbol in analysis.variables.items()
        }
        analyze_fact_statements(
            [stmt for stmt in analysis.program if stmt[0] not in {"fn", "async_fn", "class"}],
            global_env,
            analysis,
            call_updates,
        )
        for stmt, symbol, klass in function_defs:
            metadata = stmt[6] if len(stmt) > 6 else {}
            env = dict(global_env)
            for name in symbol.parameter_names:
                annotated = metadata.get("parameter_types", {}).get(name)
                inferred = call_updates.get(symbol.symbol_id, {}).get(name)
                if annotated:
                    env[name] = facts_from_annotation(annotated)
                elif inferred:
                    previous = symbol.parameter_facts.get(name, ValueFacts.unknown_value())
                    env[name] = previous.join(inferred)
                else:
                    env[name] = symbol.parameter_facts.get(name, ValueFacts.unknown_value())
                symbol.parameter_facts[name] = env[name].copy()
            if klass and "self" in env:
                env["self"] = facts_from_symbol(klass)
            returns = analyze_fact_statements(stmt[3], env, analysis, call_updates, current_class=klass)
            inferred_return = _join_facts(returns)
            if stmt[0] == "async_fn":
                inferred_return = ValueFacts(
                    types=(f"Task[{inferred_return.type_name}]",),
                    item=inferred_return,
                )
            sync_symbol_facts(symbol, inferred_return)
        after = {
            symbol.symbol_id: (
                symbol.facts.type_name,
                tuple(sorted((name, member.member_presence, member.facts.type_name) for name, member in symbol.members.items())),
                tuple(sorted((name, facts.type_name) for name, facts in symbol.parameter_facts.items())),
            )
            for _stmt, symbol, _klass in function_defs
        }
        if after == before:
            break
    final_env = {
        name: facts_from_symbol(symbol)
        for name, symbol in analysis.variables.items()
    }
    analyze_fact_statements(
        [stmt for stmt in analysis.program if stmt[0] not in {"fn", "async_fn", "class"}],
        final_env,
        analysis,
        call_updates,
    )
    analysis.inferred_locals.update({
        name: facts.copy()
        for name, facts in final_env.items()
    })


def sync_bound_symbol_facts(analysis: FileAnalysis) -> None:
    functions = {
        (symbol.location.line, symbol.name): symbol
        for symbol in analysis.symbols
        if symbol.kind in {"function", "method"}
    }
    for symbol in analysis.symbols:
        if symbol.kind == "variable" and symbol.name in analysis.inferred_locals:
            sync_symbol_facts(symbol, analysis.inferred_locals[symbol.name])
        elif symbol.kind == "parameter":
            owner = next(
                (
                    function for (line, _name), function in functions.items()
                    if line == symbol.location.line and symbol.name in function.parameter_facts
                ),
                None,
            )
            if owner:
                sync_symbol_facts(symbol, owner.parameter_facts[symbol.name])


def assignment_exprs_for_name(
    analysis: FileAnalysis,
    name: str,
) -> list[Any]:
    exprs: list[Any] = []
    for stmt in walk_statements(analysis.program):
        if (
            isinstance(stmt, tuple)
            and stmt[0] == "assign"
            and isinstance(stmt[1], tuple)
            and stmt[1][0] == "var"
            and stmt[1][1] == name
        ):
            exprs.append(stmt[2])
    return exprs


def indexed_element_exprs(
    analysis: FileAnalysis,
    base_expr: Any,
    index_value: int,
    visited_names: set[str] | None = None,
) -> list[Any]:
    visited_names = visited_names or set()
    if not isinstance(base_expr, tuple):
        return []
    if base_expr[0] == "array":
        items = base_expr[1]
        if 0 <= index_value < len(items):
            return [items[index_value]]
        return []
    if base_expr[0] == "var":
        name = base_expr[1]
        if name in visited_names:
            return []
        return [
            nested
            for expr in assignment_exprs_for_name(analysis, name)
            for nested in indexed_element_exprs(analysis, expr, index_value, visited_names | {name})
        ]
    return []


def infer_indexed_target_type(
    analysis: FileAnalysis,
    expr: Any,
    known_class_names: set[str],
) -> str | None:
    if not (
        isinstance(expr, tuple)
        and expr[0] == "index"
        and isinstance(expr[2], tuple)
        and expr[2][0] == "literal"
        and isinstance(expr[2][1], int)
    ):
        return None
    targets = {
        target
        for item_expr in indexed_element_exprs(analysis, expr[1], expr[2][1])
        for target in [infer_expr_target_from_symbol(item_expr, known_class_names, analysis)]
        if target
    }
    if len(targets) == 1:
        return next(iter(targets))
    return None


def infer_indexed_members(
    analysis: FileAnalysis,
    expr: Any,
    path: str,
    line: int,
    col: int,
    *,
    container: str | None = None,
    known_class_names: set[str] | None = None,
) -> dict[str, SemanticSymbol]:
    known_class_names = known_class_names or set()
    if not (
        isinstance(expr, tuple)
        and expr[0] == "index"
        and isinstance(expr[2], tuple)
        and expr[2][0] == "literal"
        and isinstance(expr[2][1], int)
    ):
        return {}
    merged: dict[str, SemanticSymbol] = {}
    for item_expr in indexed_element_exprs(analysis, expr[1], expr[2][1]):
        members = infer_expr_members(
            item_expr,
            path,
            line,
            col,
            container=container,
            known_class_names=known_class_names,
            analysis=analysis,
        )
        if members:
            merged = merge_symbol_members(merged, members, path, line, col, container=container)
    return merged


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
    return resolve_module_file(import_path, base, module_search_paths_for(source_path))


def native_import_parts(match: re.Match[str]) -> tuple[str, str, int]:
    quoted_path, bare_name, explicit_alias = match.groups()
    if quoted_path is not None:
        import_path = quoted_path
        default_alias = os.path.splitext(os.path.basename(import_path))[0].replace("-", "_")
        name_group = 1
    else:
        parts = (bare_name or "").split(".")
        import_path = os.path.join(*parts)
        default_alias = parts[-1]
        name_group = 2
    return import_path, explicit_alias or default_alias, 3 if explicit_alias else name_group


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
        if CLASS_RE.match(line) or INTERFACE_RE.match(line) or ENUM_RE.match(line):
            kind = "class"
        elif FN_RE.match(line):
            kind = "function"
        elif re.match(
            rf"^\s*{_concept_pattern('syntax.if', 'syntax.elif', 'syntax.else', 'syntax.while', 'syntax.whirl', 'syntax.for', 'syntax.each', 'syntax.try', 'syntax.catch', 'syntax.test', 'syntax.match', 'syntax.case', 'syntax.task-group')}(?!\w)",
            line,
        ):
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
    patterns = [CLASS_RE, INTERFACE_RE, ENUM_RE, TYPE_ALIAS_RE, FN_RE, IMPORT_RE, IMPORTPY_RE, DECL_RE, FOR_RE, CATCH_RE, TASKGROUP_RE]
    for line_no, line in enumerate(lines, start=1):
        for pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            group = match.lastindex or 1
            if pattern is IMPORT_RE:
                group = native_import_parts(match)[2]
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
            name_match = re.match(rf"(?:\*\*|\*)?({IDENT_PATTERN})", raw)
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


def is_lexically_declared_symbol(symbol: SemanticSymbol) -> bool:
    return symbol.kind in {
        "variable",
        "parameter",
        "function",
        "method",
        "class",
        "interface",
        "enum",
        "type",
        "module",
        "python-module",
    }


def bind_references(analysis: FileAnalysis, lines: list[str]) -> None:
    project = project_for_path(analysis.path)
    language_pack = language_pack_for_source(
        analysis.source,
        language_default=project.language_default if project else None,
    )
    localized_builtins = language_pack.aliases_for_category("builtin")
    language_declaration_line = bootstrap_language(analysis.source).declaration_line
    analysis.scopes = build_lexical_scopes(lines, analysis.path)
    declarations = declaration_token_locations(lines)
    canonical_symbols: dict[str, SemanticSymbol] = {}
    retained_symbols: list[SemanticSymbol] = []
    original_symbols = {symbol.symbol_id: symbol for symbol in analysis.symbols}

    for symbol in sorted(analysis.symbols, key=lambda item: (item.location.line, item.location.col)):
        header = symbol.kind in {"function", "method", "class", "interface", "enum", "type"}
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
        if is_lexically_declared_symbol(symbol):
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
        for pattern, kind in ((FOR_RE, "variable"), (CATCH_RE, "variable"), (TASKGROUP_RE, "variable")):
            match = pattern.match(line)
            if not match:
                continue
            symbol = SemanticSymbol(match.group(1), kind, Location(analysis.path, line_no, match.start(1) + 1))
            target_scope = scope_for_line(analysis.scopes, min(line_no + 1, max(1, len(lines))))
            target_scope.declare(symbol)
            analysis.symbols.append(symbol)
        for match in COMP_FOR_RE.finditer(line):
            if FOR_RE.match(line) and match.start() == len(line) - len(line.lstrip()):
                continue
            symbol = SemanticSymbol(match.group(1), "variable", Location(analysis.path, line_no, match.start(1) + 1))
            scope = scope_for_line(analysis.scopes, line_no)
            scope.declare(symbol)
            analysis.symbols.append(symbol)
            declarations.add((line_no, match.start(1) + 1))

    def add_pattern_symbols(pattern: Any, case_line: int) -> None:
        if pattern[0] == "binding_pattern":
            name, line, col = pattern[1], pattern[2], pattern[3]
            symbol = SemanticSymbol(name, "variable", Location(analysis.path, line, col))
            target_scope = scope_for_line(analysis.scopes, min(case_line + 1, max(1, len(lines))))
            target_scope.declare(symbol)
            analysis.symbols.append(symbol)
            declarations.add((line, col))
        elif pattern[0] == "array_pattern":
            for child in pattern[1]:
                add_pattern_symbols(child, case_line)
            if pattern[2]:
                line_text = lines[case_line - 1] if 0 < case_line <= len(lines) else ""
                start = line_text.find(pattern[2])
                if start >= 0:
                    symbol = SemanticSymbol(pattern[2], "variable", Location(analysis.path, case_line, start + 1))
                    target_scope = scope_for_line(analysis.scopes, min(case_line + 1, max(1, len(lines))))
                    target_scope.declare(symbol)
                    analysis.symbols.append(symbol)
                    declarations.add((case_line, start + 1))
        elif pattern[0] == "variant_pattern":
            for child in pattern[2]:
                add_pattern_symbols(child, case_line)

    for stmt in walk_statements(analysis.program):
        if stmt[0] == "match":
            for pattern, _guard, _body, case_line, _case_col in stmt[2]:
                add_pattern_symbols(pattern, case_line)

    analysis.references = []
    analysis.diagnostics = [diag for diag in analysis.diagnostics if diag.code != "SPROUT_UNKNOWN_NAME"]
    type_names = {"Any", "Nil", "Bool", "Int", "Float", "Number", "String", "List", "Array", "Dict", "Task", "Generator"}
    for stmt in walk_statements(analysis.program):
        if stmt[0] in {"fn", "async_fn"} and len(stmt) > 6:
            type_names.update(stmt[6].get("type_params", []))
        elif stmt[0] == "class" and len(stmt) > 4:
            type_names.update(stmt[4])
        elif stmt[0] == "interface":
            type_names.update(stmt[2])
            for method in stmt[3]:
                type_names.update(method[2].get("type_params", []))
        elif stmt[0] == "enum":
            type_names.add(stmt[1])
            type_names.update(stmt[2])
        elif stmt[0] == "type_alias":
            type_names.add(stmt[1])
            type_names.update(stmt[2])
    special_names = {"self", "super", "argv"} | type_names
    exact_symbols = {
        (symbol.location.line, symbol.location.col, symbol.name): symbol
        for symbol in analysis.symbols
    }
    for original_id, canonical in canonical_symbols.items():
        original = original_symbols.get(original_id)
        if original:
            exact_symbols[(original.location.line, original.location.col, original.name)] = canonical
    for line_no, line in enumerate(lines, start=1):
        code = mask_strings_preserving_columns(line.split("#", 1)[0])
        if line_no == language_declaration_line:
            continue
        current_scope = scope_for_line(analysis.scopes, line_no)
        import_match = IMPORT_RE.match(code)
        if import_match:
            import_path, alias, alias_group = native_import_parts(import_match)
            alias_col = import_match.start(alias_group) + 1
            symbol = analysis.imports.get(alias)
            analysis.references.append(
                Reference(alias, Location(analysis.path, line_no, alias_col), "declaration", symbol.symbol_id if symbol else None)
            )
            continue
        import_py_match = IMPORTPY_RE.match(code)
        if import_py_match:
            quoted_name, bare_name, explicit_alias = import_py_match.groups()
            module_name = quoted_name or bare_name or ""
            alias = explicit_alias or module_name.split(".")[-1]
            alias_group = 3 if explicit_alias else (1 if quoted_name is not None else 2)
            alias_col = import_py_match.start(alias_group) + 1
            symbol = analysis.imports.get(alias)
            analysis.references.append(
                Reference(alias, Location(analysis.path, line_no, alias_col), "declaration", symbol.symbol_id if symbol else None)
            )
            continue
        signature_match = FN_RE.match(code)
        signature_open = code.find("(") if signature_match else -1
        signature_close = code.find(")", signature_open + 1) if signature_open >= 0 else -1
        interface_signature = bool(
            signature_match
            and not code.rstrip().endswith(("{", ":", "bloom"))
        )
        dotted_members = {
            match.start(1): match.group(1)
            for match in re.finditer(rf"(?<!\w)({IDENT_PATTERN}(?:\.{IDENT_PATTERN})+)(?!\w)", code)
        }
        for match in IDENT_RE.finditer(code):
            name = match.group(0)
            col = match.start() + 1
            if name in LANGUAGE_KEYWORDS or (match.start() > 0 and code[match.start() - 1] == "."):
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
            signature_parameter = (
                interface_signature
                and signature_open < match.start() < signature_close
            )
            canonical_builtin = localized_builtins.get(name)
            if symbol is None and canonical_builtin in BUILTINS:
                symbol = BUILTINS[canonical_builtin]
                analysis.references[-1].symbol_id = symbol.symbol_id
            if symbol is None and name not in BUILTINS and name not in special_names and not signature_parameter:
                visible_names = set(type_names) | special_names
                if current_scope:
                    for candidate_scope in scope_chain(analysis.scopes, current_scope):
                        visible_names.update(candidate_scope.declarations)
                visible_names.update(analysis.variables)
                visible_names.update(analysis.functions)
                visible_names.update(analysis.classes)
                visible_names.update(analysis.types)
                visible_names.update(analysis.imports)
                suggestion = LEGACY_NAME_REPLACEMENTS.get(name) or code_word_suggestion(name, visible_names)
                message = (
                    f"Unknown name '{name}'. Did you mean '{suggestion}'?"
                    if suggestion else f"Unknown name '{name}'"
                )
                analysis.diagnostics.append(
                    Diagnostic(
                        "warning",
                        message,
                        analysis.path,
                        line_no,
                        col,
                        "SPROUT_UNKNOWN_NAME",
                        None,
                        {
                            "name": name,
                            "suggestion": suggestion,
                            "replacement": suggestion,
                        },
                    )
                )
        for start, dotted in dotted_members.items():
            parts = dotted.split(".")
            member_symbol = resolve_expr_symbol(analysis, ("get", ("var", parts[0]), parts[1])) if len(parts) == 2 else None
            if len(parts) > 2:
                member_symbol = None
                current_symbol = resolve_in_scope(analysis, parts[0], line_no, current_scope)
                for part in parts[1:]:
                    if current_symbol is None:
                        break
                    if current_symbol.members and part in current_symbol.members:
                        current_symbol = current_symbol.members.get(part)
                        continue
                    if current_symbol.target_type:
                        target = analysis.classes.get(current_symbol.target_type)
                        if not target and "." in current_symbol.target_type:
                            target = next(
                                (
                                    symbol for symbol in analysis.symbols
                                    if symbol.qualified_name == current_symbol.target_type or symbol.name == current_symbol.target_type
                                ),
                                None,
                            )
                        current_symbol = target.members.get(part) if target and target.members else None
                    else:
                        current_symbol = None
                member_symbol = current_symbol
            analysis.references.append(
                Reference(
                    dotted,
                    Location(analysis.path, line_no, start + len(dotted.rsplit(".", 1)[0]) + 2),
                    "read",
                    member_symbol.symbol_id if member_symbol else None,
                )
            )


def analyze_source(source: str, path: str) -> FileAnalysis:
    resolved = normalize_path(path)
    project = project_for_path(resolved)
    try:
        program = parse_source(
            source,
            language_default=project.language_default if project else None,
        )
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
        if stmt[0] in {"fn", "async_fn"}:
            parameter_names.update(param[0] for param in stmt[2])

    for line_no, line in enumerate(lines, start=1):
        indent = len(line) - len(line.lstrip(" "))
        while class_stack and indent <= class_stack[-1][0] and line.strip():
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

        interface_match = INTERFACE_RE.match(line)
        if interface_match:
            name = interface_match.group(1)
            symbol = SemanticSymbol(
                name,
                "interface",
                Location(resolved, line_no, interface_match.start(1) + 1),
                documentation=line_docs(lines, line_no - 1),
            )
            analysis.symbols.append(symbol)
            analysis.classes[name] = symbol
            class_members.setdefault(name, {})
            class_stack.append((indent, name))
            current_class = name
            continue

        enum_match = ENUM_RE.match(line)
        if enum_match:
            name = enum_match.group(1)
            symbol = SemanticSymbol(
                name,
                "enum",
                Location(resolved, line_no, enum_match.start(1) + 1),
                documentation=line_docs(lines, line_no - 1),
            )
            enum_stmt = next((stmt for stmt in program if stmt[0] == "enum" and stmt[1] == name), None)
            members = {}
            if enum_stmt:
                for variant_name, fields, variant_line, variant_col in enum_stmt[3]:
                    signature = (
                        f"{variant_name}({', '.join(field for field, _annotation in fields)})"
                        if fields else variant_name
                    )
                    members[variant_name] = SemanticSymbol(
                        variant_name,
                        "enum-member",
                        Location(resolved, variant_line, variant_col),
                        signature=signature,
                        container=name,
                    )
                    analysis.symbols.append(members[variant_name])
                    variant_text = lines[variant_line - 1] if 0 < variant_line <= len(lines) else ""
                    search_from = 0
                    for field_name, _annotation in fields:
                        field_col = variant_text.find(field_name, search_from)
                        if field_col >= 0:
                            field_symbol = SemanticSymbol(
                                field_name,
                                "field",
                                Location(resolved, variant_line, field_col + 1),
                                container=f"{name}.{variant_name}",
                            )
                            analysis.symbols.append(field_symbol)
                            search_from = field_col + len(field_name)
            symbol.members = members
            analysis.symbols.append(symbol)
            analysis.classes[name] = symbol
            analysis.types[name] = symbol
            continue

        alias_match = TYPE_ALIAS_RE.match(line)
        if alias_match:
            name = alias_match.group(1)
            symbol = SemanticSymbol(
                name,
                "type",
                Location(resolved, line_no, alias_match.start(1) + 1),
                documentation=line_docs(lines, line_no - 1),
            )
            analysis.symbols.append(symbol)
            analysis.types[name] = symbol
            continue

        fn_match = FN_RE.match(line)
        if fn_match:
            name = fn_match.group(1)
            ast_fn = next((stmt for stmt in walk_statements(program) if stmt[0] in {"fn", "async_fn"} and stmt[1] == name and stmt[4] == line_no), None)
            interface_method = None
            if current_class and analysis.classes.get(current_class) and analysis.classes[current_class].kind == "interface":
                interface_stmt = next((stmt for stmt in program if stmt[0] == "interface" and stmt[1] == current_class), None)
                if interface_stmt:
                    interface_method = next((method for method in interface_stmt[3] if method[0] == name and method[3] == line_no), None)
            params = ast_fn[2] if ast_fn else (interface_method[1] if interface_method else [])
            metadata = (
                ast_fn[6] if ast_fn and len(ast_fn) > 6
                else interface_method[2] if interface_method
                else {}
            )
            container = current_class
            kind = "method" if container else "function"
            symbol = SemanticSymbol(
                name,
                kind,
                Location(resolved, line_no, fn_match.start(1) + 1),
                signature=function_signature(name, params, metadata),
                documentation=line_docs(lines, line_no - 1),
                container=container,
                target_type=inferred_return_target(ast_fn, set(analysis.classes)) if ast_fn else None,
            )
            if ast_fn:
                symbol.members = inferred_return_members(
                    ast_fn,
                    resolved,
                    line_no,
                    fn_match.start(1) + 1,
                    set(analysis.classes),
                )
            analysis.symbols.append(symbol)
            if container:
                class_members.setdefault(container, {})[name] = symbol
            else:
                analysis.functions[name] = symbol
            continue

        import_match = IMPORT_RE.match(line)
        if import_match:
            import_path, alias, name_group = native_import_parts(import_match)
            target = resolve_module_path(import_path, resolved)
            symbol = SemanticSymbol(alias, "module", Location(resolved, line_no, import_match.start(name_group) + 1), module_path=target)
            analysis.symbols.append(symbol)
            analysis.imports[alias] = symbol
            continue

        import_py_match = IMPORTPY_RE.match(line)
        if import_py_match:
            quoted_name, bare_name, alias = import_py_match.groups()
            module_name = quoted_name or bare_name or ""
            alias = alias or module_name.split(".")[-1]
            name_group = 3 if import_py_match.group(3) else (1 if quoted_name else 2)
            symbol = SemanticSymbol(alias, "python-module", Location(resolved, line_no, import_py_match.start(name_group) + 1), module_path=module_name)
            analysis.symbols.append(symbol)
            analysis.imports[alias] = symbol
            continue

        decl_match = DECL_RE.match(line)
        if decl_match:
            name = decl_match.group(1)
            rhs = line.split("=", 1)[1].strip() if "=" in line else ""
            expr = parse_inline_expr(rhs)
            symbol = SemanticSymbol(
                name,
                "variable",
                Location(resolved, line_no, decl_match.start(1) + 1),
                target_type=infer_expr_target_from_symbol(expr, set(analysis.classes), analysis) if expr else None,
            )
            if expr:
                symbol.members = infer_expr_members(
                    expr,
                    resolved,
                    line_no,
                    decl_match.start(1) + 1,
                    container=name,
                    known_class_names=set(analysis.classes),
                    analysis=analysis,
                )
            analysis.symbols.append(symbol)
            analysis.variables[name] = symbol

        if current_class:
            for field_match in SELF_ASSIGN_RE.finditer(line):
                field_name = field_match.group(1)
                symbol = SemanticSymbol(field_name, "field", Location(resolved, line_no, field_match.start(1) + 1), container=current_class)
                class_members.setdefault(current_class, {})[field_name] = symbol

        if "=" in line:
            rhs = line.split("=", 1)[1].strip()
            value_expr = parse_inline_expr(rhs)
            for field_match in FIELD_ASSIGN_RE.finditer(line):
                dotted = field_match.group(1)
                parts = dotted.split(".")
                if not parts or parts[0] == "self":
                    continue
                root_symbol = analysis.variables.get(parts[0]) or analysis.imports.get(parts[0]) or analysis.classes.get(parts[0])
                if root_symbol is None:
                    continue
                attach_member_path(
                    analysis,
                    root_symbol,
                    parts[1:],
                    resolved,
                    line_no,
                    field_match.start(1) + len(parts[0]) + 2,
                    value_expr=value_expr,
                    known_class_names=set(analysis.classes),
                )

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

    infer_semantic_facts(analysis)
    analysis.source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    bind_references(analysis, lines)
    sync_bound_symbol_facts(analysis)
    from .tooling import lint_source
    from .typesystem import typecheck_source
    seen_diagnostics: set[tuple[str, int | None, int | None, str, str]] = {
        (diag.path or "", diag.line, diag.col, diag.code or "", diag.message)
        for diag in analysis.diagnostics
    }

    def add_diagnostic(diag: Diagnostic) -> None:
        key = (diag.path or "", diag.line, diag.col, diag.code or "", diag.message)
        if key not in seen_diagnostics:
            seen_diagnostics.add(key)
            analysis.diagnostics.append(diag)

    for diagnostic in lint_source(source, resolved, program):
        if diagnostic.code != "SPROUT_UNUSED_NAME":
            add_diagnostic(diagnostic)
    for diagnostic in typecheck_source(
        source,
        resolved,
        language_default=project.language_default if project else None,
        program=program,
    ):
        add_diagnostic(diagnostic)

    referenced_symbols = {
        reference.symbol_id
        for reference in analysis.references
        if reference.symbol_id and reference.role not in {"declaration", "write"}
    }
    import_error_lines = {
        diag.line
        for diag in analysis.diagnostics
        if diag.code == "SPROUT_IMPORT"
    }
    for symbol in analysis.symbols:
        if symbol.name == "self" or symbol.name.startswith("_"):
            continue
        if symbol.symbol_id in referenced_symbols:
            continue
        if symbol.kind in {"module", "python-module"}:
            if symbol.location.line in import_error_lines:
                continue
            add_diagnostic(
                Diagnostic(
                    "warning",
                    f"Import '{symbol.name}' is not used",
                    resolved,
                    symbol.location.line,
                    symbol.location.col,
                    "SPROUT_UNUSED_IMPORT",
                    ["unnecessary"],
                )
            )
        elif symbol.kind == "parameter":
            add_diagnostic(
                Diagnostic(
                    "warning",
                    f"Parameter '{symbol.name}' is not used",
                    resolved,
                    symbol.location.line,
                    symbol.location.col,
                    "SPROUT_UNUSED_PARAMETER",
                    ["unnecessary"],
                )
            )
        elif symbol.kind == "variable":
            add_diagnostic(
                Diagnostic(
                    "warning",
                    f"Name '{symbol.name}' is declared but not used",
                    resolved,
                    symbol.location.line,
                    symbol.location.col,
                    "SPROUT_UNUSED_NAME",
                    ["unnecessary"],
                )
            )

    for statement in walk_statements(program):
        if statement[0] not in {"fn", "async_fn"}:
            continue
        name = statement[1]
        params = statement[2]
        line = statement[4]
        col = statement[5]
        metadata = statement[6] if len(statement) > 6 else {}
        parameter_types = metadata.get("parameter_types", {})
        for param_name, _default, _variadic, _kw_variadic in params:
            if param_name == "self" or param_name in parameter_types:
                continue
            param_symbol = next(
                (
                    symbol for symbol in analysis.symbols
                    if symbol.kind == "parameter"
                    and symbol.name == param_name
                    and symbol.location.line == line
                ),
                None,
            )
            add_diagnostic(
                Diagnostic(
                    "warning",
                    f"Parameter '{param_name}' has no type annotation",
                    resolved,
                    param_symbol.location.line if param_symbol else line,
                    param_symbol.location.col if param_symbol else col,
                    "SPROUT_MISSING_PARAMETER_TYPE",
                )
            )
        if name != "init" and metadata.get("return_type") is None:
            add_diagnostic(
                Diagnostic(
                    "warning",
                    f"Function '{name}' has no return type annotation",
                    resolved,
                    line,
                    col,
                    "SPROUT_MISSING_RETURN_TYPE",
                )
            )
    return analysis


def analyze_file(path: str) -> FileAnalysis:
    source, resolved = read_source_file(path)
    return analyze_source(source, resolved)


def workspace_files(root: str, options: AnalysisOptions | dict[str, Any] | None = None) -> list[str]:
    normalized = coerce_analysis_options(options)
    paths: list[str] = []
    for current, dirs, files in os.walk(root):
        relative_current = os.path.relpath(current, root)
        if relative_current == ".":
            relative_current = ""
        dirs[:] = [
            d for d in dirs
            if d not in {
                ".git",
                ".hg",
                ".svn",
                ".vscode",
                ".venv",
                "venv",
                "__pycache__",
                "node_modules",
                "dist",
                "build",
            }
            and not any(
                fnmatch.fnmatch(os.path.join(relative_current, d) if relative_current else d, pattern)
                for pattern in normalized.exclude
            )
        ]
        for filename in files:
            if not filename.endswith(".sprout"):
                continue
            relative_file = os.path.join(relative_current, filename) if relative_current else filename
            if any(fnmatch.fnmatch(relative_file, pattern) for pattern in normalized.exclude):
                continue
            paths.append(os.path.join(current, filename))
            if normalized.indexing and len(paths) >= normalized.user_file_indexing_limit:
                return sorted(paths)
    return sorted(paths)


def build_workspace_index(
    root_or_file: str,
    open_documents: dict[str, str] | None = None,
    previous: WorkspaceIndex | None = None,
    changed_paths: list[str] | None = None,
    options: AnalysisOptions | dict[str, Any] | None = None,
    reason: str = "workspace-build",
) -> WorkspaceIndex:
    build_started = time.perf_counter()
    is_file_target = not os.path.isdir(root_or_file)
    root = normalize_path(root_or_file if not is_file_target else os.path.dirname(root_or_file))
    project = project_for_path(root_or_file)
    standalone_file = is_file_target and not project
    if project:
        root = project.root
    index = previous if previous and normalize_path(previous.root) == root else WorkspaceIndex(root)
    normalized_options = coerce_analysis_options(options or getattr(index, "options", None))
    index.set_options(normalized_options)
    normalized_documents = {
        normalize_path(path): source for path, source in (open_documents or {}).items()
    }
    normalized_changed = [normalize_path(path) for path in (changed_paths or []) if path]
    if standalone_file:
        target = normalize_path(root_or_file)
        files = [target] if os.path.exists(target) and target.endswith(".sprout") else []
    elif normalized_options.diagnostic_mode == "openFilesOnly":
        files = sorted(
            path for path in normalized_documents
            if path.endswith(".sprout")
        )
    else:
        files = workspace_files(root, normalized_options)
    current = {normalize_path(path) for path in files}
    current.update(normalized_documents)
    for stale in set(index.files) - current:
        index.remove_file(stale)
        index.file_signatures.pop(stale, None)

    needs_full_refresh = (
        previous is None
        or index is not previous
        or standalone_file
        or not normalized_changed
        or not normalized_options.indexing
        or normalized_options.language_server_mode == "off"
    )
    if needs_full_refresh:
        candidates = set(current)
    else:
        candidates = set(normalized_changed)
        candidates.update(path for path in normalized_documents if path in current)
        candidates.intersection_update(current)

    reindexed: set[str] = set()
    reindexed_duration_ms = 0.0
    for path in sorted(candidates):
        resolved = normalize_path(path)
        if resolved in normalized_documents:
            analysis = index.update_document(resolved, normalized_documents[resolved])
            reindexed_duration_ms += analysis.analysis_duration_ms
            reindexed.add(resolved)
        elif resolved in current:
            try:
                result = index.update_file(resolved)
            except (OSError, UnicodeDecodeError):
                continue
            if result is not None:
                reindexed_duration_ms += result.analysis_duration_ms
                reindexed.add(resolved)
    if normalized_documents:
        for path, source in normalized_documents.items():
            resolved = normalize_path(path)
            if resolved not in index.files and resolved.endswith(".sprout"):
                analysis = index.update_document(resolved, source)
                reindexed_duration_ms += analysis.analysis_duration_ms
                reindexed.add(resolved)

    pending_imports = [
        symbol.module_path
        for analysis in list(index.files.values())
        for symbol in analysis.imports.values()
        if symbol.kind == "module" and symbol.module_path
    ]
    visited_imports: set[str] = set()
    while pending_imports:
        imported = normalize_path(pending_imports.pop())
        if imported in visited_imports:
            continue
        visited_imports.add(imported)
        if imported not in index.files:
            try:
                result = index.update_file(imported)
            except (OSError, UnicodeDecodeError):
                continue
            if result is not None:
                reindexed_duration_ms += result.analysis_duration_ms
            reindexed.add(imported)
        imported_analysis = index.files.get(imported)
        if imported_analysis:
            pending_imports.extend(
                symbol.module_path
                for symbol in imported_analysis.imports.values()
                if symbol.kind == "module" and symbol.module_path
            )

    if not needs_full_refresh:
        downstream = index.dependents_of(reindexed)
        for dependent in sorted(downstream):
            if dependent in reindexed or dependent in normalized_documents and dependent not in current:
                continue
            if dependent in normalized_documents:
                analysis = index.update_document(dependent, normalized_documents[dependent])
                reindexed_duration_ms += analysis.analysis_duration_ms
                reindexed.add(dependent)
                continue
            if dependent in current:
                try:
                    result = index.update_file(dependent, force=True)
                except (OSError, UnicodeDecodeError):
                    continue
                if result is not None:
                    reindexed_duration_ms += result.analysis_duration_ms
                    reindexed.add(dependent)

    refresh_started = time.perf_counter()
    index.refresh_imports()
    refresh_imports_ms = (time.perf_counter() - refresh_started) * 1000.0
    build_duration_ms = (time.perf_counter() - build_started) * 1000.0
    index.mark_build(
        normalized_changed or list(normalized_documents) or list(current if needs_full_refresh else candidates),
        list(reindexed),
        reason=reason,
        target=root_or_file,
        duration_ms=build_duration_ms,
        reindexed_duration_ms=reindexed_duration_ms,
        refresh_imports_ms=refresh_imports_ms,
    )
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


def completion_prefix(before: str) -> str:
    match = re.search(rf"({IDENT_PATTERN})$", before)
    return match.group(1) if match else ""


def member_completion_parts(before: str) -> tuple[str | None, str]:
    match = re.search(rf"({IDENT_PATTERN}(?:\.{IDENT_PATTERN})*)\.((?:{IDENT_PATTERN})?)$", before)
    if not match:
        return (None, "")
    return (match.group(1), match.group(2))


def resolve_symbol_members(
    index: WorkspaceIndex,
    file: FileAnalysis,
    symbol: SemanticSymbol | None,
    path: str,
) -> dict[str, SemanticSymbol]:
    if not symbol:
        return {}
    if symbol.members:
        return symbol.members
    if symbol.target_type and symbol.target_type in file.classes:
        return file.classes[symbol.target_type].members
    if symbol.target_type:
        target = index.find_symbol(symbol.target_type, path)
        if not target and "." in symbol.target_type:
            factory = signature_for(index, path, symbol.target_type)
            if factory:
                if factory.members:
                    return factory.members
                if factory.target_type:
                    target = index.find_symbol(factory.target_type, path)
        if target and target.members:
            return target.members
    return {}


def resolve_member_chain_symbol(
    index: WorkspaceIndex,
    file: FileAnalysis,
    path: str,
    dotted_name: str,
) -> SemanticSymbol | None:
    parts = dotted_name.split(".")
    if not parts:
        return None
    current = file.imports.get(parts[0]) or file.variables.get(parts[0]) or file.classes.get(parts[0]) or file.types.get(parts[0])
    for member in parts[1:]:
        if current is None:
            return None
        members = resolve_symbol_members(index, file, current, path)
        current = members.get(member)
    return current


def _rank_completion(symbol: SemanticSymbol, prefix: str, local_names: set[str], imported_names: set[str]) -> tuple[int, int, int, int, int, int, int, str]:
    name = symbol.name
    exact = 0 if prefix and name == prefix else 1
    starts = 0 if prefix and name.startswith(prefix) else 1
    contains = 0 if prefix and prefix in name else 1
    scope = 0 if name in local_names else 1 if name in imported_names else 2 if symbol.kind in {"builtin"} else 3
    kind_rank = {
        "parameter": 0,
        "variable": 1,
        "field": 2,
        "property": 2,
        "method": 3,
        "function": 4,
        "class": 5,
        "interface": 6,
        "module": 7,
        "python-module": 7,
        "builtin": 8,
    }.get(symbol.kind, 9)
    declared_line = symbol.location.line if symbol.location and symbol.location.line > 0 else 10**9
    presence = 0 if symbol.member_presence == "required" else 1
    return (exact, starts, contains, presence, scope * 10 + kind_rank, declared_line, len(name), name.lower())


def _ranked_visible_symbols(
    symbols: list[SemanticSymbol],
    prefix: str,
    local_names: set[str] | None = None,
    imported_names: set[str] | None = None,
) -> list[SemanticSymbol]:
    local_names = local_names or set()
    imported_names = imported_names or set()
    filtered = [
        symbol for symbol in symbols
        if not symbol.name.startswith("_")
        and (not prefix or symbol.name.startswith(prefix) or prefix in symbol.name)
    ]
    unique: dict[str, SemanticSymbol] = {}
    for symbol in filtered:
        unique.setdefault(symbol.name, symbol)
    return sorted(
        unique.values(),
        key=lambda item: _rank_completion(item, prefix, local_names, imported_names),
    )


def member_completions(index: WorkspaceIndex, path: str, base_name: str, prefix: str = "") -> list[SemanticSymbol]:
    file = index.files.get(normalize_path(path))
    if not file:
        return []
    def visible(items: dict[str, SemanticSymbol]) -> list[SemanticSymbol]:
        return _ranked_visible_symbols(list(items.values()), prefix)
    symbol = resolve_member_chain_symbol(index, file, path, base_name)
    if symbol:
        members = resolve_symbol_members(index, file, symbol, path)
        if members:
            return visible(members)
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


def top_level_completions(index: WorkspaceIndex, path: str, line: int | None = None, prefix: str = "") -> list[SemanticSymbol]:
    file = index.files.get(normalize_path(path))
    out: dict[str, SemanticSymbol] = {}
    local_names: set[str] = set()
    imported_names: set[str] = set()
    if file:
        if line is not None:
            visible = visible_symbols(index, path, line)
            local_names.update(symbol.name for symbol in visible)
            out.update({symbol.name: symbol for symbol in visible})
        else:
            for table in (file.variables, file.functions, file.classes, file.types, file.imports):
                out.update(table)
        imported_names.update(file.imports)
    for name, symbols in index.symbols.items():
        if "." not in name and symbols:
            out.setdefault(name, symbols[0])
    for name, symbol in BUILTINS.items():
        out.setdefault(name, symbol)
    return _ranked_visible_symbols(list(out.values()), prefix, local_names, imported_names)


def symbol_at(index: WorkspaceIndex, path: str, word: str) -> SemanticSymbol | None:
    path = normalize_path(path)
    file = index.files.get(path)
    if file:
        for table in (file.variables, file.functions, file.classes, file.types, file.imports):
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


def rename_safe(symbol: SemanticSymbol | None) -> bool:
    if symbol is None or not symbol.symbol_id:
        return False
    return symbol.kind in {
        "variable",
        "parameter",
        "function",
        "class",
        "method",
        "field",
        "type",
        "interface",
        "enum",
    }


def references_at(index: WorkspaceIndex, path: str, line: int, col: int, word: str) -> list[Reference]:
    symbol = symbol_at_position(index, path, line, col, word)
    return index.references_to(word, symbol.symbol_id if symbol else None)


def signature_for(index: WorkspaceIndex, path: str, name: str) -> SemanticSymbol | None:
    dotted = name.split(".")
    if len(dotted) == 2:
        members = member_completions(index, path, dotted[0])
        return next((member for member in members if member.name == dotted[1]), None)
    return symbol_at(index, path, name)
