#!/usr/bin/env python3
"""Regression tests for Sprout's incremental language-server engine."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sprout_lsp_test", ROOT / "tools" / "sprout_lsp.py")
assert SPEC and SPEC.loader
LSP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LSP)


def test_incremental_rebuild_and_navigation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "def greet(name):\n  return \"hello \" + name\n\nsay greet(\"Ada\")\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        LSP.workspace_root = str(root)
        LSP.documents = {uri: source}
        LSP.workspace_index = None

        index = LSP.rebuild_index(uri)
        first_count = index.analysis_count
        assert LSP.rebuild_index(uri) is index
        assert index.analysis_count == first_count

        definition = LSP.definition(uri, {"line": 3, "character": 7})
        assert definition
        assert definition[0]["range"]["start"]["line"] == 0

        changed = source.replace('"Ada"', '"Mina"')
        LSP.documents[uri] = changed
        LSP.rebuild_index(uri)
        assert index.analysis_count == first_count + 1


def decode_messages(raw: bytes) -> list[dict]:
    messages = []
    offset = 0
    while offset < len(raw):
        boundary = raw.index(b"\r\n\r\n", offset)
        headers = raw[offset:boundary].decode("ascii")
        length = int(next(line.split(":", 1)[1] for line in headers.splitlines() if line.lower().startswith("content-length:")))
        start = boundary + 4
        messages.append(json.loads(raw[start:start + length].decode("utf-8")))
        offset = start + length
    return messages


def encode_message(message: dict) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def request(server, request_id: int, method: str, params: dict) -> dict:
    before = len(server.writer.getvalue())
    server.process_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    messages = decode_messages(server.writer.getvalue()[before:])
    return next(message for message in messages if message.get("id") == request_id)


def test_protocol_lifecycle_and_incremental_sync() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "def greet(name):\n  return \"hello \" + name\n\nsay greet(\"Ada\")\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)

        initialized = request(
            server,
            1,
            "initialize",
            {"workspaceFolders": [{"uri": root.resolve().as_uri(), "name": "sample"}]},
        )
        capabilities = initialized["result"]["capabilities"]
        assert capabilities["textDocumentSync"]["change"] == 2
        assert capabilities["renameProvider"]["prepareProvider"] is True
        assert capabilities["workspaceSymbolProvider"] is True
        assert capabilities["codeActionProvider"]["codeActionKinds"] == ["quickfix"]
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})

        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        diagnostics = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        assert diagnostics["params"]["version"] == 1
        assert diagnostics["params"]["diagnostics"] == []

        changed = "missing_name"
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 2},
                "contentChanges": [{
                    "range": {
                        "start": {"line": 3, "character": 4},
                        "end": {"line": 3, "character": 9},
                    },
                    "text": changed,
                }],
            },
        })
        assert "say missing_name" in server.documents[uri].text
        assert server.documents[uri].version == 2

        hover = request(server, 2, "textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 5},
        })
        assert "greet" in hover["result"]["contents"]["value"]

        symbols = request(server, 3, "workspace/symbol", {"query": "greet"})
        assert any(item["name"] == "greet" for item in symbols["result"])

        shutdown = request(server, 4, "shutdown", {})
        assert shutdown["result"] is None
        assert server.shutdown_requested
        assert server.handle({"jsonrpc": "2.0", "method": "exit", "params": {}}) is False


def test_references_rename_and_protocol_errors() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "value = 3\nsay value\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 1, "text": source}},
        })

        refs = request(server, 2, "textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
            "context": {"includeDeclaration": True},
        })
        assert len(refs["result"]) == 2

        prepared = request(server, 3, "textDocument/prepareRename", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
        })
        assert prepared["result"]["placeholder"] == "value"

        renamed = request(server, 4, "textDocument/rename", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
            "newName": "score",
        })
        assert len(renamed["result"]["changes"][uri]) == 2

        invalid = request(server, 5, "textDocument/rename", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
            "newName": "not valid",
        })
        assert invalid["error"]["code"] == LSP.JSONRPC_INVALID_PARAMS

        missing = request(server, 6, "sprout/notARealMethod", {})
        assert missing["error"]["code"] == LSP.JSONRPC_METHOD_NOT_FOUND

        server.handle({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 7}})
        cancelled = request(server, 7, "workspace/symbol", {"query": ""})
        assert cancelled["error"]["code"] == LSP.LSP_REQUEST_CANCELLED


def test_safe_code_actions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "\tvalue = True\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 1, "text": source}},
        })
        diagnostics = [
            {
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                "code": "SPROUT_TAB_INDENT",
                "message": "Use spaces",
            },
            {
                "range": {"start": {"line": 0, "character": 9}, "end": {"line": 0, "character": 10}},
                "code": "SPROUT_PY_ALIAS",
                "message": "Prefer Sprout constants",
            },
        ]
        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": diagnostics[0]["range"],
            "context": {"diagnostics": diagnostics},
        })
        actions = response["result"]
        assert [action["title"] for action in actions] == [
            "Convert tabs to Sprout spaces",
            "Use Sprout 'true'",
        ]
        assert actions[1]["edit"]["changes"][uri][0]["newText"] == "true"


def test_stdio_process_lifecycle() -> None:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"rootUri": ROOT.resolve().as_uri()}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ]
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "sprout_lsp.py")],
        input=b"".join(encode_message(message) for message in messages),
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    responses = decode_messages(result.stdout)
    assert responses[0]["result"]["serverInfo"]["name"] == "sprout-lsp"
    assert responses[1] == {"jsonrpc": "2.0", "id": 2, "result": None}


def main() -> int:
    test_incremental_rebuild_and_navigation()
    test_protocol_lifecycle_and_incremental_sync()
    test_references_rename_and_protocol_errors()
    test_safe_code_actions()
    test_stdio_process_lifecycle()
    print("sprout lsp tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
