#!/usr/bin/env python3
"""Sprout Language Server Protocol implementation over stdio."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
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
    return text[start:end], start, end


def dotted_base(text: str) -> str | None:
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z0-9_]*$", text)
    return match.group(1) if match else None


def lsp_diagnostic(diag: sprout.Diagnostic) -> dict[str, Any]:
    return {
        "range": location_range(diag.line or 1, diag.col or 1),
        "severity": 1 if diag.severity == "error" else 2,
        "code": diag.code,
        "source": "sprout",
        "message": diag.message,
    }


def completion_item(symbol: sprout.SemanticSymbol) -> dict[str, Any]:
    kinds = {
        "method": 2,
        "function": 3,
        "builtin": 3,
        "field": 5,
        "variable": 6,
        "class": 7,
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
    if symbol.kind in {"function", "builtin", "method", "class"} and symbol.signature:
        item["insertText"] = f"{symbol.name}($1)"
        item["insertTextFormat"] = 2
    return item


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
    if changed_uri:
        changed_path = path_from_uri(changed_uri)
        root = sprout.find_project_root(changed_path) or root
    workspace_index = sprout.build_workspace_index(root, open_documents, previous=workspace_index)
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

    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                return None
            decoded = line.decode("ascii", errors="replace").strip()
            if not decoded:
                break
            if ":" not in decoded:
                raise ValueError("Malformed LSP header")
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            raise ValueError("Missing Content-Length header")
        return json.loads(self.reader.read(length).decode("utf-8"))

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

    def index_for_uri(self, uri: str, rebuild: bool = True) -> sprout.WorkspaceIndex:
        path = path_from_uri(uri)
        root = self.root_for_path(path)
        previous = self.indexes.get(root)
        if not rebuild and previous:
            return previous
        open_documents = {
            path_from_uri(item.uri): item.text
            for item in self.documents.values()
            if self.root_for_path(path_from_uri(item.uri)) == root
        }
        index = sprout.build_workspace_index(root, open_documents, previous=previous)
        self.indexes[root] = index
        return index

    def source_for_uri(self, uri: str) -> str:
        document = self.documents.get(uri)
        if document:
            return document.text
        try:
            return Path(path_from_uri(uri)).read_text(encoding="utf-8")
        except OSError:
            return ""

    def publish_diagnostics(self, uri: str) -> None:
        index = self.index_for_uri(uri)
        file = index.files.get(os.path.realpath(path_from_uri(uri)))
        diagnostics = file.diagnostics if file else []
        self.notify(
            "textDocument/publishDiagnostics",
            {
                "uri": uri,
                "version": self.documents.get(uri).version if uri in self.documents else None,
                "diagnostics": [lsp_diagnostic(diag) for diag in diagnostics],
            },
        )

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
        index = self.index_for_uri(uri, rebuild=False)
        source = self.source_for_uri(uri)
        lines = source.splitlines()
        line_number = int(pos.get("line", 0))
        line = lines[line_number] if line_number < len(lines) else ""
        before = line[: int(pos.get("character", 0))]
        base = dotted_base(before)
        symbols = (
            sprout.member_completions(index, path_from_uri(uri), base)
            if base
            else sprout.top_level_completions(index, path_from_uri(uri), line_number + 1)
        )
        items = [completion_item(symbol) for symbol in symbols]
        if not base:
            existing = {item["label"] for item in items}
            items.extend(
                {"label": word, "kind": 14, "detail": "Sprout keyword"}
                for word in sorted(sprout.KEYWORDS)
                if word not in existing
            )
        return {"isIncomplete": False, "items": items}

    def hover(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        _index, _path, word, symbol = self.symbol_at(uri, pos)
        if symbol:
            title = symbol.signature or symbol.qualified_name
            docs = symbol.documentation or f"Sprout {symbol.kind}."
            defined = ""
            if symbol.location.path and not symbol.location.path.startswith("<"):
                defined = f"\n\nDefined at `{symbol.location.path}:{symbol.location.line}:{symbol.location.col}`."
            return {"contents": {"kind": "markdown", "value": f"**{title}**\n\n{docs}{defined}"}}
        if word in sprout.KEYWORDS:
            return {"contents": {"kind": "markdown", "value": f"**{word}**\n\nSprout keyword."}}
        return None

    def definition(self, uri: str, pos: dict[str, int]) -> list[dict[str, Any]]:
        _index, _path, _word, symbol = self.symbol_at(uri, pos)
        if not symbol or symbol.location.path.startswith("<"):
            return []
        return [location_payload(symbol.location.path, symbol.location.line, symbol.location.col, len(symbol.name))]

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
            location_payload(ref.location.path, ref.location.line, ref.location.col, len(word))
            for ref in refs
        ]

    def prepare_rename(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        _index, _path, word, symbol = self.symbol_at(uri, pos)
        if not word or not symbol or symbol.kind == "builtin":
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
        if not word or not symbol or symbol.kind == "builtin":
            return {"changes": {}}
        changes = {
            uri_from_path(edit_path): edits
            for edit_path, edits in index.rename_edits(word, new_name, symbol.symbol_id).items()
        }
        return {"changes": changes}

    def signature_help(self, uri: str, pos: dict[str, int]) -> dict[str, Any] | None:
        index = self.index_for_uri(uri, rebuild=False)
        source = self.source_for_uri(uri)
        lines = source.splitlines()
        line_number = int(pos.get("line", 0))
        line = lines[line_number] if line_number < len(lines) else ""
        before = line[: int(pos.get("character", 0))]
        match = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\(([^()]*)$", before)
        if not match:
            return None
        symbol = sprout.signature_for(index, path_from_uri(uri), match.group(1))
        if not symbol or not symbol.signature:
            return None
        active = match.group(2).count(",")
        return {
            "signatures": [{
                "label": symbol.signature,
                "documentation": {"kind": "markdown", "value": symbol.documentation or ""},
            }],
            "activeSignature": 0,
            "activeParameter": active,
        }

    def document_symbols(self, uri: str) -> list[dict[str, Any]]:
        index = self.index_for_uri(uri, rebuild=False)
        file = index.files.get(os.path.realpath(path_from_uri(uri)))
        symbols = file.symbols if file else []
        kinds = {"function": 12, "class": 5, "method": 6, "module": 2, "python-module": 2, "variable": 13, "field": 8}
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
                        "kind": {"function": 12, "class": 5, "method": 6, "variable": 13}.get(symbol.kind, 13),
                        "location": location_payload(symbol.location.path, symbol.location.line, symbol.location.col, len(symbol.name)),
                        "containerName": symbol.container,
                    })
        return out[:500]

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
            if code == "SPROUT_TAB_INDENT" and "\t" in line:
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
            for root in self.workspace_folders:
                self.indexes[root] = sprout.build_workspace_index(root)
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
            self.publish_diagnostics(uri)
            return True
        if method == "textDocument/didChange":
            item = params["textDocument"]
            uri = item["uri"]
            document = self.documents.get(uri, OpenDocument(uri, self.source_for_uri(uri)))
            document.text = apply_content_changes(document.text, params.get("contentChanges", []))
            document.version = item.get("version", document.version)
            self.documents[uri] = document
            documents[uri] = document.text
            self.publish_diagnostics(uri)
            return True
        if method == "textDocument/didSave":
            uri = params["textDocument"]["uri"]
            self.publish_diagnostics(uri)
            return True
        if method == "textDocument/didClose":
            uri = params["textDocument"]["uri"]
            self.documents.pop(uri, None)
            documents.pop(uri, None)
            self.index_for_uri(uri)
            self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
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

        uri = (params.get("textDocument") or {}).get("uri", "")
        pos = params.get("position") or {}
        if method == "textDocument/completion":
            self.respond(message, self.completion(uri, pos))
        elif method == "textDocument/hover":
            self.respond(message, self.hover(uri, pos))
        elif method == "textDocument/definition":
            self.respond(message, self.definition(uri, pos))
        elif method == "textDocument/references":
            self.respond(message, self.references(uri, pos, bool((params.get("context") or {}).get("includeDeclaration", True))))
        elif method == "textDocument/prepareRename":
            result = self.prepare_rename(uri, pos)
            if result is None:
                self.error(message, JSONRPC_INVALID_REQUEST, "This symbol cannot be renamed")
            else:
                self.respond(message, result)
        elif method == "textDocument/rename":
            self.respond(message, self.rename(uri, pos, str(params.get("newName", ""))))
        elif method == "textDocument/signatureHelp":
            self.respond(message, self.signature_help(uri, pos))
        elif method == "textDocument/documentSymbol":
            self.respond(message, self.document_symbols(uri))
        elif method == "textDocument/codeAction":
            self.respond(message, self.code_actions(uri, params))
        elif method == "workspace/symbol":
            self.respond(message, self.workspace_symbols(str(params.get("query", ""))))
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
            if "id" in message:
                self.error(message, JSONRPC_INVALID_PARAMS, str(exc))
            return True
        except Exception as exc:
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
