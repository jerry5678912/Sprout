#!/usr/bin/env python3
"""Sprout Language Server Protocol implementation over stdio."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, BinaryIO
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sprout_core as sprout  # noqa: E402


JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
LSP_SERVER_NOT_INITIALIZED = -32002
LSP_REQUEST_CANCELLED = -32800


class OpenDocument:
    def __init__(
        self,
        uri: str,
        text: str,
        version: int | None = None,
        language_id: str = "sprout",
    ):
        self.uri = uri
        self.text = text
        self.version = version
        self.language_id = language_id


documents: dict[str, str] = {}
workspace_root = str(ROOT)
workspace_index: sprout.WorkspaceIndex | None = None


def log(message: str) -> None:
    print(f"[Sprout LSP] {message}", file=sys.stderr, flush=True)


def path_from_uri(uri: str) -> str:
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    return uri


def uri_from_path(path: str | None) -> str:
    if not path or path.startswith("<"):
        return ""
    return Path(path).resolve().as_uri()


def position(line: int, character: int) -> dict[str, int]:
    return {"line": max(0, line), "character": max(0, character)}


def location_range(line: int, col: int, length: int = 1) -> dict[str, Any]:
    start = position(line - 1, col - 1)
    return {"start": start, "end": position(line - 1, col - 1 + max(1, length))}


def location_payload(path: str, line: int, col: int, length: int = 1) -> dict[str, Any]:
    return {"uri": uri_from_path(path), "range": location_range(line, col, length)}


def word_at(source: str, line: int, character: int) -> str:
    lines = source.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    text = lines[line]
    character = min(max(0, character), len(text))
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return text[start:end]


def identifier_span(text: str, index: int) -> tuple[int, int]:
    if not text:
        return (0, 0)
    index = min(max(0, index), len(text))
    if index >= len(text):
        if text and (text[-1].isalnum() or text[-1] == "_"):
            index = len(text) - 1
        else:
            return (len(text), len(text))
    if not (text[index].isalnum() or text[index] == "_"):
        if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
            index -= 1
        else:
            return (index, index)
    start = index
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = index
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return (start, end)


def word_span(source: str, line: int, character: int) -> tuple[str, int, int]:
    lines = source.splitlines()
    if line < 0 or line >= len(lines):
        return "", character, character
    text = lines[line]
    character = min(max(0, character), len(text))
    start = character
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    if start == end:
        start, end = identifier_span(text, character)
    return text[start:end], start, end


def dotted_base(text: str) -> str | None:
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z0-9_]*$", text)
    return match.group(1) if match else None


def definition_location_for_symbol(index: sprout.WorkspaceIndex, symbol: sprout.SemanticSymbol) -> dict[str, Any] | None:
    if symbol.kind == "module" and symbol.module_path:
        target_path = os.path.realpath(symbol.module_path)
        target_file = index.files.get(target_path)
        if target_file and target_file.symbols:
            first = min(target_file.symbols, key=lambda item: (item.location.line, item.location.col, item.name))
            return location_payload(first.location.path, first.location.line, first.location.col, len(first.name))
        return location_payload(target_path, 1, 1, 1)
    if symbol.location.path.startswith("<"):
        return None
    return location_payload(symbol.location.path, symbol.location.line, symbol.location.col, len(symbol.name))


def signature_parameter_ranges(signature: str) -> list[dict[str, Any]]:
    open_paren = signature.find("(")
    close_paren = signature.rfind(")")
    if open_paren < 0 or close_paren <= open_paren:
        return []
    inner = signature[open_paren + 1:close_paren]
    if not inner.strip():
        return []
    ranges: list[dict[str, Any]] = []
    depth = 0
    start = 0
    for index, char in enumerate(inner):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            label = inner[start:index].strip()
            if label:
                left_trim = len(inner[start:index]) - len(inner[start:index].lstrip())
                begin = open_paren + 1 + start + left_trim
                ranges.append({"label": [begin, begin + len(label)]})
            start = index + 1
    tail = inner[start:].strip()
    if tail:
        left_trim = len(inner[start:]) - len(inner[start:].lstrip())
        begin = open_paren + 1 + start + left_trim
        ranges.append({"label": [begin, begin + len(tail)]})
    return ranges


def call_context(before: str) -> tuple[str, int] | None:
    depth = 0
    string_quote = ""
    escaped = False
    for index in range(len(before) - 1, -1, -1):
        char = before[index]
        if string_quote:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == string_quote:
                string_quote = ""
            continue
        if char in {'"', "'"}:
            string_quote = char
            continue
        if char in ")]}":
            depth += 1
            continue
        if char in "([{":
            if depth > 0:
                depth -= 1
                continue
            prefix = before[:index]
            match = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*$", prefix)
            if not match:
                return None
            return match.group(1), active_argument_index(before[index + 1:])
    return None


def active_argument_index(arguments: str) -> int:
    depth = 0
    string_quote = ""
    escaped = False
    commas = 0
    for char in arguments:
        if string_quote:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == string_quote:
                string_quote = ""
            continue
        if char in {'"', "'"}:
            string_quote = char
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            commas += 1
    return commas


def diagnostic_length(diag: sprout.Diagnostic, source: str) -> int:
    lines = source.splitlines()
    line = (diag.line or 1) - 1
    col = (diag.col or 1) - 1
    if line < 0 or line >= len(lines):
        return 1
    text = lines[line]
    index = max(0, min(col, len(text)))
    start, end = identifier_span(text, index)
    if end <= start:
        if index < len(text):
            return 1
        return 1
    return max(1, end - start)


def lsp_diagnostic(diag: sprout.Diagnostic, source: str = "") -> dict[str, Any]:
    severity = {
        "error": 1,
        "warning": 2,
        "information": 3,
        "hint": 4,
    }.get(diag.severity, 2)
    payload = {
        "range": location_range(diag.line or 1, diag.col or 1, diagnostic_length(diag, source)),
        "severity": severity,
        "code": diag.code,
        "source": "sprout",
        "message": diag.message,
    }
    if diag.data:
        payload["data"] = diag.data
    tags = []
    if "unnecessary" in (diag.tags or []):
        tags.append(1)
    if "deprecated" in (diag.tags or []):
        tags.append(2)
    if tags:
        payload["tags"] = tags
    return payload


def completion_item(symbol: sprout.SemanticSymbol) -> dict[str, Any]:
    kinds = {
        "method": 2,
        "function": 3,
        "builtin": 3,
        "field": 5,
        "variable": 6,
        "class": 7,
        "interface": 8,
        "module": 9,
        "python-module": 9,
        "parameter": 6,
    }
    item: dict[str, Any] = {
        "label": symbol.name,
        "kind": kinds.get(symbol.kind, 6),
        "detail": symbol.signature or symbol.qualified_name or f"Sprout {symbol.kind}",
        "documentation": {"kind": "markdown", "value": symbol.documentation or f"Sprout {symbol.kind}."},
        "data": {"symbolId": symbol.symbol_id},
    }
    if symbol.kind in {"function", "builtin", "method", "class", "interface"} and symbol.signature:
        item["insertText"] = f"{symbol.name}($1)"
        item["insertTextFormat"] = 2
    return item


def completion_sort_key(index: int) -> str:
    return f"{index:04d}"


def utf16_offset(text: str, target: dict[str, int]) -> int:
    lines = text.splitlines(keepends=True)
    line = min(max(0, int(target.get("line", 0))), len(lines))
    offset = sum(len(part) for part in lines[:line])
    if line >= len(lines):
        return len(text)
    current = lines[line]
    wanted = max(0, int(target.get("character", 0)))
    units = 0
    chars = 0
    for char in current:
        width = len(char.encode("utf-16-le")) // 2
        if units + width > wanted:
            break
        units += width
        chars += 1
    return offset + chars


def apply_content_changes(text: str, changes: list[dict[str, Any]]) -> str:
    current = text
    for change in changes:
        if "range" not in change:
            current = str(change.get("text", ""))
            continue
        edit_range = change["range"]
        start = utf16_offset(current, edit_range.get("start", {}))
        end = utf16_offset(current, edit_range.get("end", {}))
        current = current[:start] + str(change.get("text", "")) + current[end:]
    return current


def rebuild_index(changed_uri: str | None = None) -> sprout.WorkspaceIndex:
    global workspace_index
    open_documents = {path_from_uri(uri): text for uri, text in documents.items()}
    root = workspace_root
    changed_paths: list[str] = []
    if changed_uri:
        changed_path = path_from_uri(changed_uri)
        root = sprout.find_project_root(changed_path) or root
        changed_paths.append(changed_path)
    workspace_index = sprout.build_workspace_index(
        root,
        open_documents,
        previous=workspace_index,
        changed_paths=changed_paths,
        reason="legacy-rebuild",
    )
    return workspace_index


class SproutLanguageServer:
    def __init__(self, reader: BinaryIO | None = None, writer: BinaryIO | None = None):
        self.reader = reader or sys.stdin.buffer
        self.writer = writer or sys.stdout.buffer
        self.documents: dict[str, OpenDocument] = {}
        self.workspace_folders: list[str] = [workspace_root]
        self.indexes: dict[str, sprout.WorkspaceIndex] = {}
        self.initialized = False
        self.shutdown_requested = False
        self.cancelled: set[Any] = set()
        self.settings: dict[str, Any] = {
            "diagnostics": {
                "enabled": True,
                "styleWarnings": True,
                "typoChecking": True,
            },
            "analysis": {
                "typeCheckingMode": "basic",
                "diagnosticMode": "workspace",
                "indexing": True,
                "userFileIndexingLimit": 2000,
                "useLibraryCodeForTypes": True,
                "exclude": [],
                "languageServerMode": "default",
                "diagnosticSeverityOverrides": {},
            },
        }
        self.operation_stats: dict[str, dict[str, float | int]] = {}

    def record_operation(self, name: str, duration_ms: float) -> None:
        stats = self.operation_stats.setdefault(
            name,
            {"count": 0, "totalMs": 0.0, "maxMs": 0.0, "lastMs": 0.0},
        )
        stats["count"] = int(stats["count"]) + 1
        stats["totalMs"] = float(stats["totalMs"]) + duration_ms
        stats["maxMs"] = max(float(stats["maxMs"]), duration_ms)
        stats["lastMs"] = duration_ms

    def operation_status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, stats in sorted(self.operation_stats.items()):
            count = int(stats.get("count", 0))
            total = float(stats.get("totalMs", 0.0))
            out[name] = {
                "count": count,
                "avgMs": round((total / count) if count else 0.0, 3),
                "maxMs": round(float(stats.get("maxMs", 0.0)), 3),
                "lastMs": round(float(stats.get("lastMs", 0.0)), 3),
            }
        return out

    def current_analysis_options(self) -> dict[str, Any]:
        analysis = self.settings.get("analysis") or {}
        return {
            "diagnosticMode": analysis.get("diagnosticMode", "workspace"),
            "indexing": analysis.get("indexing", True),
            "userFileIndexingLimit": analysis.get("userFileIndexingLimit", 2000),
            "useLibraryCodeForTypes": analysis.get("useLibraryCodeForTypes", True),
            "exclude": analysis.get("exclude", []),
            "languageServerMode": analysis.get("languageServerMode", "default"),
        }

    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                return None
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded.startswith("\ufeff"):
                decoded = decoded.lstrip("\ufeff");
            if not decoded:
                break
            if ":" not in decoded:
                raise ValueError("Malformed LSP header")
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            raise ValueError("Missing Content-Length header")
        body = self.read_exact(length)
        try:
            text = body.decode("utf-8", errors="replace")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Invalid LSP body encoding: {exc}") from exc
        return json.loads(text)

    def read_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining > 0:
            chunk = self.reader.read(remaining)
            if not chunk:
                raise ValueError("Incomplete LSP message body")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def send(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.writer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
        self.writer.write(raw)
        self.writer.flush()

    def respond(self, message: dict[str, Any], result: Any) -> None:
        self.send({"jsonrpc": "2.0", "id": message.get("id"), "result": result})

    def error(self, message: dict[str, Any], code: int, text: str, data: Any = None) -> None:
        payload: dict[str, Any] = {"code": code, "message": text}
        if data is not None:
            payload["data"] = data
        self.send({"jsonrpc": "2.0", "id": message.get("id"), "error": payload})

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def root_for_path(self, path: str) -> str:
        resolved = os.path.realpath(os.path.abspath(path))
        project = sprout.find_project_root(resolved)
        if project:
            return os.path.realpath(project)
        matches = [
            root for root in self.workspace_folders
            if resolved == root or resolved.startswith(root + os.sep)
        ]
        return max(matches, key=len) if matches else os.path.dirname(resolved)

    def index_for_uri(
        self,
        uri: str,
        rebuild: bool = True,
        changed_paths: list[str] | None = None,
        reason: str = "query",
        force_full: bool = False,
    ) -> sprout.WorkspaceIndex:
        path = path_from_uri(uri)
        root = self.root_for_path(path)
        resolved_path = os.path.realpath(os.path.abspath(path))
        project = sprout.find_project_root(resolved_path)
        in_workspace = any(
            resolved_path == workspace or resolved_path.startswith(workspace + os.sep)
            for workspace in self.workspace_folders
        )
        build_target = root if project or in_workspace else resolved_path
        previous = self.indexes.get(root)
        if not rebuild and previous:
            return previous
        open_documents = {
            path_from_uri(item.uri): item.text
            for item in self.documents.values()
            if self.root_for_path(path_from_uri(item.uri)) == root
        }
        index = sprout.build_workspace_index(
            build_target,
            open_documents,
            previous=None if force_full else previous,
            changed_paths=changed_paths,
            options=self.current_analysis_options(),
            reason=reason,
        )
        self.indexes[root] = index
        return index

    def source_for_uri(self, uri: str) -> str:
        document = self.documents.get(uri)
        if document:
            return document.text
        try:
            return Path(path_from_uri(uri)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def publish_diagnostics(self, uri: str, changed_paths: list[str] | None = None, reason: str = "diagnostics") -> None:
        source = self.source_for_uri(uri)
        if not source.strip():
            log(f"diagnostics {uri}: 0 blank")
            self.notify(
                "textDocument/publishDiagnostics",
                {
                    "uri": uri,
                    "version": self.documents.get(uri).version if uri in self.documents else None,
                    "diagnostics": [],
                },
            )
            return
        index = self.index_for_uri(uri, changed_paths=changed_paths, reason=reason)
        file = index.files.get(os.path.realpath(path_from_uri(uri)))
        diagnostics = file.diagnostics if file else []
        diagnostics_settings = self.settings.get("diagnostics") or {}
        analysis_settings = self.settings.get("analysis") or {}
        if not diagnostics_settings.get("enabled", True):
            diagnostics = []
        else:
            if not diagnostics_settings.get("styleWarnings", True):
                diagnostics = [
                    diagnostic for diagnostic in diagnostics
                    if diagnostic.code not in {"SPROUT_TAB_INDENT", "SPROUT_PY_ALIAS"}
                ]
            if not diagnostics_settings.get("typoChecking", True):
                diagnostics = [
                    diagnostic for diagnostic in diagnostics
                    if not (diagnostic.data or {}).get("suggestion")
                ]
            diagnostics = sprout.apply_diagnostic_policy(
                diagnostics,
                str(analysis_settings.get("typeCheckingMode", "basic")),
                analysis_settings.get("diagnosticSeverityOverrides") or {},
            )
        payload = [lsp_diagnostic(diag, source) for diag in diagnostics]
        deduped = {}
        for item in payload:
            start = item["range"]["start"]
            end = item["range"]["end"]
            key = (
                start.get("line", 0),
                start.get("character", 0),
                end.get("line", 0),
                end.get("character", 0),
                item.get("severity", 2),
                item.get("code") or "",
                item.get("message") or "",
            )
            if key not in deduped:
                deduped[key] = item
        self.notify(
            "textDocument/publishDiagnostics",
            {
                "uri": uri,
                "version": self.documents.get(uri).version if uri in self.documents else None,
                "diagnostics": list(deduped.values()),
            },
        )
        if diagnostics:
            log(f"diagnostics {uri}: {len(diagnostics)}")



    def update_settings(self, settings: dict[str, Any] | None) -> None:
        candidate = settings or {}
        if "sprout" in candidate and isinstance(candidate["sprout"], dict):
            candidate = candidate["sprout"]
        diagnostics = candidate.get("diagnostics")
        if isinstance(diagnostics, dict):
            self.settings["diagnostics"].update(diagnostics)
        analysis = candidate.get("analysis")
        if isinstance(analysis, dict):
            self.settings["analysis"].update(analysis)

    def analysis_status(self, uri: str | None = None) -> dict[str, Any]:
        root = self.workspace_folders[0] if self.workspace_folders else workspace_root
        if uri:
            path = path_from_uri(uri)
            root = self.root_for_path(path)
            index = self.index_for_uri(uri, rebuild=False)
        else:
            index = self.indexes.get(root)
            if index is None:
                build_target = root if os.path.isdir(root) else workspace_root
                index = sprout.build_workspace_index(build_target, options=self.current_analysis_options(), reason="status")
                self.indexes[root] = index
        status = index.status().to_json()
        status["settings"] = {
            "typeCheckingMode": self.settings["analysis"].get("typeCheckingMode", "basic"),
            **self.current_analysis_options(),
        }
        status["effectiveSettings"] = index.options.to_json()
        status["operations"] = self.operation_status()
        return status

    def rebuild_workspace_index(self, uri: str | None = None) -> dict[str, Any]:
        target_uri = uri
        if not target_uri and self.documents:
            target_uri = next(iter(self.documents))
        if target_uri:
            index = self.index_for_uri(
                target_uri,
                rebuild=True,
                changed_paths=[path_from_uri(target_uri)],
                reason="manual-rebuild",
                force_full=True,
            )
            return index.status().to_json()
        root = self.workspace_folders[0] if self.workspace_folders else workspace_root
        build_target = root if os.path.isdir(root) else workspace_root
        index = sprout.build_workspace_index(
            build_target,
            options=self.current_analysis_options(),
            reason="manual-rebuild",
        )
        self.indexes[root] = index
        return index.status().to_json()

    def symbol_at(self, uri: str, pos: dict[str, int]) -> tuple[sprout.WorkspaceIndex, str, str, sprout.SemanticSymbol | None]:
        index = self.index_for_uri(uri, rebuild=False)
        path = os.path.realpath(path_from_uri(uri))
        source = self.source_for_uri(uri)
        word = word_at(source, int(pos.get("line", 0)), int(pos.get("character", 0)))
        symbol = sprout.symbol_at_position(
            index,
            path,
            int(pos.get("line", 0)) + 1,
            int(pos.get("character", 0)) + 1,
            word,
        )
        return index, path, word, symbol

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        global workspace_root
        self.update_settings(params.get("initializationOptions"))
        folders = params.get("workspaceFolders") or []
        roots = [path_from_uri(item["uri"]) for item in folders if item.get("uri")]
        root_uri = params.get("rootUri")
        root_path = params.get("rootPath")
        if not roots and root_uri:
            roots = [path_from_uri(root_uri)]
        if not roots and root_path:
            roots = [root_path]
        if roots:
            self.workspace_folders = [os.path.realpath(os.path.abspath(root)) for root in roots]
            workspace_root = self.workspace_folders[0]
        self.initialized = True
        log(f"initialize root={workspace_root} folders={len(self.workspace_folders)}")
        return {
            "capabilities": {
                "positionEncoding": "utf-16",
                "textDocumentSync": {
                    "openClose": True,
                    "change": 2,
                    "save": {"includeText": False},
                },
                "completionProvider": {"triggerCharacters": ["."]},
                "hoverProvider": True,
                "definitionProvider": True,
                "referencesProvider": True,
                "renameProvider": {"prepareProvider": True},
                "signatureHelpProvider": {"triggerCharacters": ["(", ","], "retriggerCharacters": [","]},
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "codeActionProvider": {"codeActionKinds": ["quickfix"]},
            },
            "serverInfo": {"name": "sprout-lsp", "version": sprout.SPROUT_VERSION},
        }

    def completion(self, uri: str, pos: dict[str, int]) -> dict[str, Any]:
        source = self.source_for_uri(uri)
        lines = source.splitlines()
        line_number = int(pos.get("line", 0))
        line = lines[line_number] if line_number < len(lines) else ""
        before = line[: int(pos.get("character", 0))]
        base, member_prefix = sprout.member_completion_parts(before)
        index = self.index_for_uri(uri, rebuild=False)
        import_context = sprout.is_import_context(source, line_number + 1, int(pos.get("character", 0)) + 1)
        import_symbols = sprout.import_completion_symbols(path_from_uri(uri), source, line_number + 1, int(pos.get("character", 0)) + 1)
        prefix = member_prefix if base else sprout.completion_prefix(before)
        if import_context:
            symbols = import_symbols
            base = None
        elif import_symbols:
            symbols = import_symbols
            base = None
        else:
            symbols = (
                sprout.member_completions(index, path_from_uri(uri), base, member_prefix)
                if base
                else sprout.top_level_completions(index, path_from_uri(uri), line_number + 1, prefix)
            )
        if base and not symbols:
            patched = sprout.completion_ready_source(source, line_number + 1, int(pos.get("character", 0)) + 1)
            if patched != source:
                recovered = sprout.build_workspace_index(
                    path_from_uri(uri),
                    {path_from_uri(uri): patched},
                )
                symbols = sprout.member_completions(recovered, path_from_uri(uri), base, member_prefix)
        items = []
        for idx, symbol in enumerate(symbols):
            item = completion_item(symbol)
            item["sortText"] = completion_sort_key(idx)
            items.append(item)
        if not base and not import_context:
            existing = {item["label"] for item in items}
            start_index = len(items)
            for offset, word in enumerate(sorted(sprout.KEYWORDS)):
                if word in existing:
                    continue
                items.append({
                    "label": word,
                    "kind": 14,
                    "detail": "Sprout keyword",
                    "sortText": completion_sort_key(start_index + offset),
                })
        return {"isIncomplete": False, "items": items}

    def hover(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        _index, _path, word, symbol = self.symbol_at(uri, pos)
        if symbol:
            title = symbol.signature or symbol.qualified_name
            docs = symbol.documentation or f"Sprout {symbol.kind}."
            details = [f"Kind: `{symbol.kind}`"]
            if symbol.container:
                details.append(f"Container: `{symbol.container}`")
            if symbol.target_type:
                details.append(f"Target type: `{symbol.target_type}`")
            if symbol.module_path:
                details.append(f"Module: `{symbol.module_path}`")
            defined = ""
            if symbol.location.path and not symbol.location.path.startswith("<"):
                defined = f"\n\nDefined at `{symbol.location.path}:{symbol.location.line}:{symbol.location.col}`."
            meta = "\n".join(f"- {item}" for item in details)
            return {"contents": {"kind": "markdown", "value": f"```sprout\n{title}\n```\n\n{meta}\n\n{docs}{defined}"}}
        if word in sprout.KEYWORDS:
            return {"contents": {"kind": "markdown", "value": f"**{word}**\n\nSprout keyword."}}
        return None

    def definition(self, uri: str, pos: dict[str, int]) -> list[dict[str, Any]]:
        index, _path, _word, symbol = self.symbol_at(uri, pos)
        if not symbol:
            return []
        location = definition_location_for_symbol(index, symbol)
        return [location] if location else []

    def references(self, uri: str, pos: dict[str, int], include_declaration: bool) -> list[dict[str, Any]]:
        index, path, word, symbol = self.symbol_at(uri, pos)
        if not word:
            return []
        refs = sprout.references_at(
            index,
            path,
            int(pos.get("line", 0)) + 1,
            int(pos.get("character", 0)) + 1,
            word,
        )
        if not include_declaration:
            refs = [ref for ref in refs if ref.role != "declaration"]
        return [
            location_payload(ref.location.path, ref.location.line, ref.location.col, len(ref.name.split(".")[-1]))
            for ref in refs
        ]

    def prepare_rename(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        _index, _path, word, symbol = self.symbol_at(uri, pos)
        if not word or not sprout.rename_safe(symbol):
            return None
        line = int(pos.get("line", 0))
        _word, start, end = word_span(self.source_for_uri(uri), line, int(pos.get("character", 0)))
        return {
            "range": {"start": position(line, start), "end": position(line, end)},
            "placeholder": word,
        }

    def rename(self, uri: str, pos: dict[str, int], new_name: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new_name):
            raise ValueError("New name must be a valid Sprout identifier")
        index, _path, word, symbol = self.symbol_at(uri, pos)
        if not word or not sprout.rename_safe(symbol):
            return {"changes": {}}
        changes = {
            uri_from_path(edit_path): edits
            for edit_path, edits in index.rename_edits(word, new_name, symbol.symbol_id).items()
        }
        return {"changes": changes}

    def signature_help(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        source = self.source_for_uri(uri)
        lines = source.splitlines()
        line_number = int(pos.get("line", 0))
        line = lines[line_number] if line_number < len(lines) else ""
        before = line[: int(pos.get("character", 0))]
        context = call_context(before)
        if not context:
            return None
        target_name, active = context
        index = self.index_for_uri(uri, rebuild=False)
        symbol = sprout.signature_for(index, path_from_uri(uri), target_name)
        if not symbol:
            patched = sprout.signature_ready_source(source, line_number + 1, int(pos.get("character", 0)) + 1)
            if patched != source:
                recovered = sprout.build_workspace_index(
                    path_from_uri(uri),
                    {path_from_uri(uri): patched},
                )
                symbol = sprout.signature_for(recovered, path_from_uri(uri), target_name)
        if not symbol or not symbol.signature:
            return None
        parameters = signature_parameter_ranges(symbol.signature)
        if parameters:
            active = min(active, len(parameters) - 1)
        return {
            "signatures": [{
                "label": symbol.signature,
                "documentation": {"kind": "markdown", "value": symbol.documentation or ""},
                "parameters": parameters,
            }],
            "activeSignature": 0,
            "activeParameter": active,
        }

    def document_symbols(self, uri: str) -> list[dict[str, Any]]:
        index = self.index_for_uri(uri, rebuild=False)
        file = index.files.get(os.path.realpath(path_from_uri(uri)))
        symbols = file.symbols if file else []
        kinds = {"function": 12, "class": 5, "interface": 11, "method": 6, "module": 2, "python-module": 2, "variable": 13, "field": 8}
        return [{
            "name": symbol.name,
            "detail": symbol.signature or symbol.kind,
            "kind": kinds.get(symbol.kind, 13),
            "range": location_range(symbol.location.line, symbol.location.col, len(symbol.name)),
            "selectionRange": location_range(symbol.location.line, symbol.location.col, len(symbol.name)),
        } for symbol in symbols]

    def workspace_symbols(self, query: str) -> list[dict[str, Any]]:
        lowered = query.lower()
        out = []
        for root in self.workspace_folders:
            uri = uri_from_path(root)
            index = self.indexes.get(root) or self.index_for_uri(uri)
            for file in index.files.values():
                for symbol in file.symbols:
                    if lowered and lowered not in symbol.qualified_name.lower():
                        continue
                    if symbol.location.path.startswith("<"):
                        continue
                    out.append({
                        "name": symbol.name,
                        "kind": {"function": 12, "class": 5, "interface": 11, "method": 6, "variable": 13}.get(symbol.kind, 13),
                        "location": location_payload(symbol.location.path, symbol.location.line, symbol.location.col, len(symbol.name)),
                        "containerName": symbol.container,
                        "_qualifiedName": symbol.qualified_name,
                    })
        def rank(item: dict[str, Any]) -> tuple[int, int, str]:
            qualified = str(item.get("_qualifiedName") or item.get("name") or "")
            name = str(item.get("name") or "")
            exact = 0 if lowered and name.lower() == lowered else 1
            starts = 0 if lowered and qualified.lower().startswith(lowered) else 1
            return (exact, starts, qualified.lower())
        ranked = sorted(out, key=rank)
        for item in ranked:
            item.pop("_qualifiedName", None)
        return ranked[:500]

    def code_actions(self, uri: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        source = self.source_for_uri(uri)
        lines = source.splitlines()
        actions: list[dict[str, Any]] = []
        for diagnostic in (params.get("context") or {}).get("diagnostics", []):
            code = diagnostic.get("code")
            target = diagnostic.get("range") or {}
            start = target.get("start") or {}
            line_number = int(start.get("line", 0))
            character = int(start.get("character", 0))
            line = lines[line_number] if 0 <= line_number < len(lines) else ""
            edit_range = None
            new_text = None
            title = None
            data = diagnostic.get("data") if isinstance(diagnostic.get("data"), dict) else {}
            replacement = data.get("replacement") or data.get("suggestion")
            if code in {"SPROUT_UNKNOWN_NAME", "SPROUT_UNKNOWN_MEMBER", "SPROUT_IMPORT"} and replacement:
                edit_range = target
                new_text = str(replacement)
                title = f"Replace with '{replacement}'"
            elif code == "SPROUT_UNUSED_IMPORT":
                edit_range = {
                    "start": position(line_number, 0),
                    "end": position(line_number + 1, 0) if line_number + 1 < len(lines) else position(line_number, len(line)),
                }
                new_text = ""
                title = "Remove unused import"
            elif code == "SPROUT_UNUSED_NAME":
                word, start_char, end_char = word_span(source, line_number, character)
                if word and not word.startswith("_"):
                    edit_range = {
                        "start": position(line_number, start_char),
                        "end": position(line_number, end_char),
                    }
                    new_text = f"_{word}"
                    title = f"Rename unused name to _{word}"
            elif code == "SPROUT_UNUSED_PARAMETER":
                word, start_char, end_char = word_span(source, line_number, character)
                if word and not word.startswith("_"):
                    edit_range = {
                        "start": position(line_number, start_char),
                        "end": position(line_number, end_char),
                    }
                    new_text = f"_{word}"
                    title = f"Rename unused parameter to _{word}"
            elif code == "SPROUT_TAB_INDENT" and "\t" in line:
                edit_range = {
                    "start": position(line_number, 0),
                    "end": position(line_number, len(line)),
                }
                new_text = line.replace("\t", "  ")
                title = "Convert tabs to Sprout spaces"
            elif code == "SPROUT_PY_ALIAS":
                match = None
                for candidate in re.finditer(r"\b(?:True|False|None)\b", line):
                    if candidate.start() <= character <= candidate.end():
                        match = candidate
                        break
                if match:
                    replacement = {"True": "true", "False": "false", "None": "nil"}[match.group(0)]
                    edit_range = {
                        "start": position(line_number, match.start()),
                        "end": position(line_number, match.end()),
                    }
                    new_text = replacement
                    title = f"Use Sprout '{replacement}'"
            if edit_range is not None and new_text is not None and title:
                actions.append({
                    "title": title,
                    "kind": "quickfix",
                    "diagnostics": [diagnostic],
                    "isPreferred": True,
                    "edit": {"changes": {uri: [{"range": edit_range, "newText": new_text}]}},
                })
        return actions

    def handle(self, message: dict[str, Any]) -> bool:
        method = message.get("method")
        params = message.get("params") or {}
        request_id = message.get("id")
        if method == "$/cancelRequest":
            self.cancelled.add(params.get("id"))
            return True
        if request_id in self.cancelled:
            self.cancelled.discard(request_id)
            self.error(message, LSP_REQUEST_CANCELLED, "Request cancelled")
            return True
        if method == "initialize":
            self.respond(message, self.initialize(params))
            return True
        if method == "exit":
            return False
        if not self.initialized:
            if request_id is not None:
                self.error(message, LSP_SERVER_NOT_INITIALIZED, "Sprout language server is not initialized")
            return True
        if method == "initialized":
            log("initialized notification received; building workspace indexes")
            for root in self.workspace_folders:
                self.indexes[root] = sprout.build_workspace_index(
                    root,
                    options=self.current_analysis_options(),
                    reason="initialized",
                )
            return True
        if method == "shutdown":
            self.shutdown_requested = True
            self.respond(message, None)
            return True
        if self.shutdown_requested:
            if request_id is not None:
                self.error(message, JSONRPC_INVALID_REQUEST, "Server has already shut down")
            return True

        if method == "textDocument/didOpen":
            item = params["textDocument"]
            uri = item["uri"]
            document = OpenDocument(uri, item.get("text", ""), item.get("version"), item.get("languageId", "sprout"))
            self.documents[uri] = document
            documents[uri] = document.text
            log(f"didOpen {uri} v{document.version}")
            self.publish_diagnostics(uri, changed_paths=[path_from_uri(uri)], reason="didOpen")
            return True
        if method == "textDocument/didChange":
            item = params["textDocument"]
            uri = item["uri"]
            document = self.documents.get(uri, OpenDocument(uri, self.source_for_uri(uri)))
            document.text = apply_content_changes(document.text, params.get("contentChanges", []))
            document.version = item.get("version", document.version)
            self.documents[uri] = document
            documents[uri] = document.text
            self.publish_diagnostics(uri, changed_paths=[path_from_uri(uri)], reason="didChange")
            return True
        if method == "textDocument/didSave":
            uri = params["textDocument"]["uri"]
            log(f"didSave {uri}")
            self.publish_diagnostics(uri, changed_paths=[path_from_uri(uri)], reason="didSave")
            return True
        if method == "textDocument/didClose":
            uri = params["textDocument"]["uri"]
            self.documents.pop(uri, None)
            documents.pop(uri, None)
            self.index_for_uri(uri)
            self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
            log(f"didClose {uri}")
            return True
        if method == "workspace/didChangeWorkspaceFolders":
            event = params.get("event", {})
            removed = {path_from_uri(item["uri"]) for item in event.get("removed", [])}
            self.workspace_folders = [root for root in self.workspace_folders if root not in removed]
            self.workspace_folders.extend(
                os.path.realpath(path_from_uri(item["uri"]))
                for item in event.get("added", [])
                if path_from_uri(item["uri"]) not in self.workspace_folders
            )
            return True
        if method == "workspace/didChangeWatchedFiles":
            for change in params.get("changes", []):
                uri = change.get("uri", "")
                if uri:
                    root = self.root_for_path(path_from_uri(uri))
                    self.indexes.pop(root, None)
            return True
        if method == "workspace/didChangeConfiguration":
            self.update_settings(params.get("settings"))
            log("configuration changed")
            self.indexes.clear()
            for uri in list(self.documents):
                self.publish_diagnostics(uri, changed_paths=[path_from_uri(uri)], reason="configuration")
            return True

        uri = (params.get("textDocument") or {}).get("uri", "")
        pos = params.get("position") or {}
        def timed(name: str, callback):
            started = time.perf_counter()
            result = callback()
            self.record_operation(name, (time.perf_counter() - started) * 1000.0)
            return result
        if method == "textDocument/completion":
            self.respond(message, timed("completion", lambda: self.completion(uri, pos)))
        elif method == "textDocument/hover":
            self.respond(message, timed("hover", lambda: self.hover(uri, pos)))
        elif method == "textDocument/definition":
            self.respond(message, timed("definition", lambda: self.definition(uri, pos)))
        elif method == "textDocument/references":
            self.respond(message, timed("references", lambda: self.references(uri, pos, bool((params.get("context") or {}).get("includeDeclaration", True)))))
        elif method == "textDocument/prepareRename":
            result = timed("prepareRename", lambda: self.prepare_rename(uri, pos))
            if result is None:
                self.error(message, JSONRPC_INVALID_REQUEST, "This symbol cannot be renamed")
            else:
                self.respond(message, result)
        elif method == "textDocument/rename":
            self.respond(message, timed("rename", lambda: self.rename(uri, pos, str(params.get("newName", "")))))
        elif method == "textDocument/signatureHelp":
            self.respond(message, timed("signatureHelp", lambda: self.signature_help(uri, pos)))
        elif method == "textDocument/documentSymbol":
            self.respond(message, timed("documentSymbol", lambda: self.document_symbols(uri)))
        elif method == "textDocument/codeAction":
            self.respond(message, timed("codeAction", lambda: self.code_actions(uri, params)))
        elif method == "workspace/symbol":
            self.respond(message, timed("workspaceSymbol", lambda: self.workspace_symbols(str(params.get("query", "")))))
        elif method == "sprout/analysisStatus":
            self.respond(message, timed("analysisStatus", lambda: self.analysis_status(uri or params.get("uri"))))
        elif method == "sprout/rebuildWorkspaceIndex":
            self.respond(message, timed("rebuildWorkspaceIndex", lambda: self.rebuild_workspace_index(uri or params.get("uri"))))
        elif request_id is not None:
            self.error(message, JSONRPC_METHOD_NOT_FOUND, f"Unsupported method: {method}")
        return True

    def run(self) -> int:
        while True:
            try:
                message = self.read_message()
            except (ValueError, json.JSONDecodeError) as exc:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": JSONRPC_PARSE_ERROR, "message": str(exc)}})
                continue
            if message is None:
                return 0
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                self.error(message if isinstance(message, dict) else {}, JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC request")
                continue
            if not self.process_message(message):
                return 0 if self.shutdown_requested else 1

    def process_message(self, message: dict[str, Any]) -> bool:
        try:
            return self.handle(message)
        except (KeyError, TypeError, ValueError) as exc:
            log(f"request error: {exc}")
            if "id" in message:
                self.error(message, JSONRPC_INVALID_PARAMS, str(exc))
            return True
        except Exception as exc:
            log(f"internal error: {exc}")
            if "id" in message:
                self.error(message, JSONRPC_INTERNAL_ERROR, f"Sprout LSP failure: {exc}")
            return True


def read_message() -> dict[str, Any] | None:
    return SproutLanguageServer().read_message()


def send(payload: dict[str, Any]) -> None:
    SproutLanguageServer().send(payload)


def analyze(uri: str, source: str) -> None:
    documents[uri] = source
    server = SproutLanguageServer()
    server.documents[uri] = OpenDocument(uri, source)
    server.publish_diagnostics(uri)


def completion_items(uri: str, target: dict[str, int]) -> list[dict[str, Any]]:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.completion(uri, target)["items"]


def hover(uri: str, target: dict[str, int]) -> dict[str, Any] | None:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.hover(uri, target)


def definition(uri: str, target: dict[str, int]) -> list[dict[str, Any]]:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.definition(uri, target)


def references(uri: str, target: dict[str, int]) -> list[dict[str, Any]]:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.references(uri, target, True)


def rename(uri: str, target: dict[str, int], new_name: str) -> dict[str, Any]:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.rename(uri, target, new_name)


def signature_help(uri: str, target: dict[str, int]) -> dict[str, Any] | None:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.signature_help(uri, target)


def document_symbol(uri: str) -> list[dict[str, Any]]:
    server = SproutLanguageServer()
    server.documents = {key: OpenDocument(key, value) for key, value in documents.items()}
    server.indexes[server.root_for_path(path_from_uri(uri))] = rebuild_index(uri)
    return server.document_symbols(uri)


def main() -> int:
    return SproutLanguageServer().run()


if __name__ == "__main__":
    raise SystemExit(main())
