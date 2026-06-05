#!/usr/bin/env python3
"""Small Language Server Protocol foundation for Sprout."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sprout_core as sprout  # noqa: E402


documents: dict[str, str] = {}
workspace_root = str(ROOT)
workspace_index: sprout.WorkspaceIndex | None = None


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line_text = line.decode("ascii", errors="replace").strip()
        if not line_text:
            break
        key, value = line_text.split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    sys.stdout.buffer.flush()


def response(message: dict[str, Any], result: Any) -> None:
    send({"jsonrpc": "2.0", "id": message.get("id"), "result": result})


def notify(method: str, params: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "method": method, "params": params})


def path_from_uri(uri: str) -> str:
    if uri.startswith("file://"):
        from urllib.parse import unquote, urlparse

        return unquote(urlparse(uri).path)
    return uri


def uri_from_path(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).resolve().as_uri()


def rebuild_index(changed_uri: str | None = None) -> sprout.WorkspaceIndex:
    global workspace_index
    open_documents = {path_from_uri(uri): text for uri, text in documents.items()}
    root = workspace_root
    if changed_uri:
        changed_path = path_from_uri(changed_uri)
        root = sprout.find_project_root(changed_path) or root
    workspace_index = sprout.build_workspace_index(root, open_documents)
    return workspace_index


def lsp_diagnostic(diag: sprout.Diagnostic) -> dict[str, Any]:
    line = max(0, (diag.line or 1) - 1)
    col = max(0, (diag.col or 1) - 1)
    return {
        "range": {"start": {"line": line, "character": col}, "end": {"line": line, "character": col + 1}},
        "severity": 1 if diag.severity == "error" else 2,
        "code": diag.code,
        "source": "sprout",
        "message": diag.message,
    }


def analyze(uri: str, source: str) -> None:
    path = path_from_uri(uri)
    index = rebuild_index(uri)
    file = index.files.get(path)
    diagnostics = file.diagnostics if file else []
    notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": [lsp_diagnostic(diag) for diag in diagnostics]})


def completion_item(symbol: sprout.SemanticSymbol) -> dict[str, Any]:
    kind_map = {
        "function": 3,
        "builtin": 3,
        "method": 2,
        "class": 7,
        "module": 9,
        "python-module": 9,
        "variable": 6,
        "field": 5,
    }
    label = symbol.name
    detail = symbol.signature or f"Sprout {symbol.kind}"
    documentation = symbol.documentation or f"Sprout {symbol.kind}."
    insert_text = label
    if symbol.kind in {"function", "builtin", "method"} and symbol.signature:
        insert_text = label + "($1)"
    return {
        "label": label,
        "kind": kind_map.get(symbol.kind, 6),
        "detail": detail,
        "documentation": {"kind": "markdown", "value": documentation},
        "insertText": insert_text,
        "insertTextFormat": 2 if "$1" in insert_text else 1,
    }


def completion_items(uri: str, position: dict[str, int]) -> list[dict[str, Any]]:
    index = workspace_index or rebuild_index(uri)
    source = documents.get(uri, "")
    path = path_from_uri(uri)
    line = source.splitlines()[position.get("line", 0)] if position.get("line", 0) < len(source.splitlines()) else ""
    before = line[: position.get("character", 0)]
    dotted = re_match_dotted(before)
    if dotted:
        return [completion_item(symbol) for symbol in sprout.member_completions(index, path, dotted)]
    items = []
    for word in sorted(sprout.KEYWORDS):
        items.append({"label": word, "kind": 14, "detail": "Sprout keyword"})
    existing = {item["label"] for item in items}
    for symbol in sprout.top_level_completions(index, path):
        if symbol.name not in existing:
            items.append(completion_item(symbol))
    return items


def re_match_dotted(text: str) -> str | None:
    import re

    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z0-9_]*$", text)
    return match.group(1) if match else None


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


def hover(uri: str, position: dict[str, int]) -> dict[str, Any] | None:
    index = workspace_index or rebuild_index(uri)
    path = path_from_uri(uri)
    source = documents.get(uri, "")
    word = word_at(source, position.get("line", 0), position.get("character", 0))
    symbol = sprout.symbol_at(index, path, word)
    if symbol:
        title = symbol.signature or symbol.qualified_name
        docs = symbol.documentation or f"Sprout {symbol.kind}."
        loc = "" if symbol.location.path.startswith("<") else f"\n\nDefined at `{symbol.location.path}:{symbol.location.line}:{symbol.location.col}`."
        text = f"**{title}**\n\n{docs}{loc}"
    elif word in sprout.KEYWORDS:
        text = f"**{word}**\n\nSprout keyword."
    else:
        return None
    return {"contents": {"kind": "markdown", "value": text}}


def definition(uri: str, position: dict[str, int]) -> list[dict[str, Any]]:
    index = workspace_index or rebuild_index(uri)
    path = path_from_uri(uri)
    source = documents.get(uri, "")
    word = word_at(source, position.get("line", 0), position.get("character", 0))
    symbol = sprout.symbol_at(index, path, word)
    if not symbol:
        return []
    matches = [symbol]
    return [
        {
            "uri": uri_from_path(sym.location.path) or uri,
            "range": {
                "start": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col - 1)},
                "end": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col)},
            },
        }
        for sym in matches
    ]


def references(uri: str, position: dict[str, int]) -> list[dict[str, Any]]:
    index = workspace_index or rebuild_index(uri)
    source = documents.get(uri, "")
    word = word_at(source, position.get("line", 0), position.get("character", 0))
    return [
        {
            "uri": uri_from_path(ref.location.path),
            "range": {
                "start": {"line": ref.location.line - 1, "character": ref.location.col - 1},
                "end": {"line": ref.location.line - 1, "character": ref.location.col - 1 + len(word)},
            },
        }
        for ref in index.references_to(word)
    ]


def rename(uri: str, position: dict[str, int], new_name: str) -> dict[str, Any]:
    index = workspace_index or rebuild_index(uri)
    source = documents.get(uri, "")
    word = word_at(source, position.get("line", 0), position.get("character", 0))
    changes = {uri_from_path(path): edits for path, edits in index.rename_edits(word, new_name).items()}
    return {"changes": changes}


def signature_help(uri: str, position: dict[str, int]) -> dict[str, Any] | None:
    index = workspace_index or rebuild_index(uri)
    path = path_from_uri(uri)
    source = documents.get(uri, "")
    lines = source.splitlines()
    line = lines[position.get("line", 0)] if position.get("line", 0) < len(lines) else ""
    before = line[: position.get("character", 0)]
    import re

    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\([^()]*$", before)
    if not match:
        return None
    symbol = sprout.signature_for(index, path, match.group(1))
    if not symbol or not symbol.signature:
        return None
    return {
        "signatures": [{"label": symbol.signature, "documentation": {"kind": "markdown", "value": symbol.documentation}}],
        "activeSignature": 0,
        "activeParameter": max(0, before[match.end() :].count(",")),
    }


def document_symbol(uri: str) -> list[dict[str, Any]]:
    index = workspace_index or rebuild_index(uri)
    path = path_from_uri(uri)
    file = index.files.get(path)
    symbols = file.symbols if file else []
    kind_map = {"function": 12, "class": 5, "method": 6, "module": 2}
    return [
        {
            "name": sym.name,
            "kind": kind_map.get(sym.kind, 13),
            "range": {
                "start": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col - 1)},
                "end": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col)},
            },
            "selectionRange": {
                "start": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col - 1)},
                "end": {"line": max(0, sym.location.line - 1), "character": max(0, sym.location.col)},
            },
        }
        for sym in symbols
    ]


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        method = message.get("method")
        params = message.get("params", {})

        if method == "initialize":
            global workspace_root
            root_uri = params.get("rootUri")
            if root_uri:
                workspace_root = path_from_uri(root_uri)
            response(
                message,
                {
                    "capabilities": {
                        "textDocumentSync": 1,
                        "completionProvider": {"triggerCharacters": ["."]},
                        "hoverProvider": True,
                        "definitionProvider": True,
                        "referencesProvider": True,
                        "renameProvider": True,
                        "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
                        "documentSymbolProvider": True,
                    },
                    "serverInfo": {"name": "sprout-lsp", "version": sprout.SPROUT_VERSION},
                },
            )
        elif method == "shutdown":
            response(message, None)
        elif method == "textDocument/didOpen":
            doc = params["textDocument"]
            documents[doc["uri"]] = doc.get("text", "")
            analyze(doc["uri"], documents[doc["uri"]])
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            text = params.get("contentChanges", [{}])[-1].get("text", documents.get(uri, ""))
            documents[uri] = text
            analyze(uri, text)
        elif method == "textDocument/completion":
            response(message, {"isIncomplete": False, "items": completion_items(params["textDocument"]["uri"], params["position"])})
        elif method == "textDocument/hover":
            response(message, hover(params["textDocument"]["uri"], params["position"]))
        elif method == "textDocument/definition":
            response(message, definition(params["textDocument"]["uri"], params["position"]))
        elif method == "textDocument/references":
            response(message, references(params["textDocument"]["uri"], params["position"]))
        elif method == "textDocument/rename":
            response(message, rename(params["textDocument"]["uri"], params["position"], params.get("newName", "")))
        elif method == "textDocument/signatureHelp":
            response(message, signature_help(params["textDocument"]["uri"], params["position"]))
        elif method == "textDocument/documentSymbol":
            response(message, document_symbol(params["textDocument"]["uri"]))
        elif "id" in message:
            response(message, None)


if __name__ == "__main__":
    raise SystemExit(main())
