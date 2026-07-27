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


def test_inferred_hover_completion_and_conditional_diagnostics_agree() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "def make(active):\n"
            "  if active:\n"
            '    return {"name": "Mina", "hp": 10}\n'
            '  return {"name": "Mina", "mood": "calm"}\n'
            "\n"
            "player = make(True)\n"
            "say player.hp\n"
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(
            server,
            1,
            "initialize",
            {
                "workspaceFolders": [{"uri": root.resolve().as_uri(), "name": "sample"}],
                "initializationOptions": {
                    "analysis": {"typeCheckingMode": "standard"},
                },
            },
        )
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        conditional = next(
            item for item in published["params"]["diagnostics"]
            if item["code"] == "SPROUT_POSSIBLY_MISSING_MEMBER"
        )
        assert conditional["severity"] == 2

        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 6, "character": 11},
        })
        items = completion["result"]["items"]
        name = next(item for item in items if item["label"] == "name")
        hp = next(item for item in items if item["label"] == "hp")
        assert name["sortText"] < hp["sortText"]
        assert "possibly missing" in hp["detail"]

        hover = request(server, 3, "textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": 5, "character": 2},
        })
        value = hover["result"]["contents"]["value"]
        assert "Inferred type" in value
        assert "Conditional fields" in value
        assert "hp" in value and "mood" in value


def test_imported_factory_partial_member_completion_stays_member_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "player.sprout"
        main = root / "main.sprout"
        helper.write_text(
            "def create_player(name):\n"
            '  return {"name": name, "health": 100}\n',
            encoding="utf-8",
        )
        source = (
            "import player as player\n"
            'hero = player.create_player("Jerry")\n'
            "hero.n\n"
        )
        main.write_text(source, encoding="utf-8")
        uri = main.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(
            server,
            1,
            "initialize",
            {
                "workspaceFolders": [{"uri": root.resolve().as_uri(), "name": "sample"}],
            },
        )
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "sprout",
                    "version": 1,
                    "text": source,
                },
            },
        })

        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 2, "character": 6},
        })
        labels = [item["label"] for item in completion["result"]["items"]]
        assert "name" in labels
        assert "nil" not in labels
        assert "none" not in labels
        assert "not" not in labels


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


def decode_semantic_token_data(data: list[int]) -> list[tuple[int, int, int, int, int]]:
    tokens = []
    line = 0
    start = 0
    for offset in range(0, len(data), 5):
        delta_line, delta_start, length, token_type, modifiers = data[offset:offset + 5]
        line = line + delta_line
        start = start + delta_start if delta_line == 0 else delta_start
        tokens.append((line, start, length, token_type, modifiers))
    return tokens


class FragmentedReader:
    def __init__(self, data: bytes, chunk_size: int = 2):
        self.data = data
        self.chunk_size = chunk_size
        self.offset = 0

    def readline(self) -> bytes:
        if self.offset >= len(self.data):
            return b""
        newline = self.data.find(b"\n", self.offset)
        if newline == -1:
            end = len(self.data)
        else:
            end = newline + 1
        line = self.data[self.offset:end]
        self.offset = end
        return line

    def read(self, length: int) -> bytes:
        if self.offset >= len(self.data):
            return b""
        end = min(len(self.data), self.offset + min(length, self.chunk_size))
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk


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
        assert capabilities["semanticTokensProvider"]["legend"]["tokenTypes"] == LSP.SEMANTIC_TOKEN_TYPES
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

        completion = request(server, 22, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 7},
        })
        assert isinstance(completion["result"]["items"], list)

        symbols = request(server, 3, "workspace/symbol", {"query": "greet"})
        assert any(item["name"] == "greet" for item in symbols["result"])

        semantic = request(server, 23, "textDocument/semanticTokens/full", {
            "textDocument": {"uri": uri},
        })
        tokens = decode_semantic_token_data(semantic["result"]["data"])
        assert tokens
        assert any(token[0] == 0 for token in tokens)

        status = request(server, 30, "sprout/analysisStatus", {"uri": uri})
        assert status["result"]["fileCount"] >= 1
        assert status["result"]["settings"]["typeCheckingMode"] == "basic"
        assert status["result"]["lastBuildDurationMs"] >= 0
        assert "cacheHitRate" in status["result"]
        assert status["result"]["operations"]["hover"]["count"] >= 1
        assert status["result"]["operations"]["completion"]["count"] >= 1
        assert status["result"]["operations"]["workspaceSymbol"]["count"] >= 1

        rebuilt = request(server, 31, "sprout/rebuildWorkspaceIndex", {"uri": uri})
        assert rebuilt["result"]["lastBuildReason"] == "manual-rebuild"
        assert rebuilt["result"]["lastReindexedFiles"]
        assert rebuilt["result"]["lastReindexedDurationMs"] >= 0

        shutdown = request(server, 4, "shutdown", {})
        assert shutdown["result"] is None
        assert server.shutdown_requested
        assert server.handle({"jsonrpc": "2.0", "method": "exit", "params": {}}) is False


def test_loose_file_open_defers_full_project_index_until_workspace_query() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main = root / "main.sprout"
        unrelated = root / "unrelated.sprout"
        (root / "sprout.toml").write_text(
            '[project]\nname = "latency-test"\nmain = "main.sprout"\n',
            encoding="utf-8",
        )
        source = 'say "ready"\n'
        main.write_text(source, encoding="utf-8")
        unrelated.write_text("def hidden_workspace_symbol():\n  return 1\n", encoding="utf-8")
        uri = main.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)

        request(
            server,
            1,
            "initialize",
            {"rootUri": None, "workspaceFolders": []},
        )
        assert server.workspace_folders == []
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "sprout",
                    "version": 1,
                    "text": source,
                },
            },
        })

        project_root = str(root.resolve())
        initial_index = server.indexes[project_root]
        assert str(main.resolve()) in initial_index.files
        assert str(unrelated.resolve()) not in initial_index.files

        symbols = request(
            server,
            2,
            "workspace/symbol",
            {"query": "hidden_workspace_symbol"},
        )
        assert [item["name"] for item in symbols["result"]] == [
            "hidden_workspace_symbol"
        ]
        assert str(unrelated.resolve()) in server.indexes[project_root].files


def test_blank_document_semantic_tokens_do_not_trigger_full_project_index() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main = root / "main.sprout"
        unrelated = root / "unrelated.sprout"
        (root / "sprout.toml").write_text(
            '[project]\nname = "blank-latency-test"\nmain = "main.sprout"\n',
            encoding="utf-8",
        )
        main.write_text("", encoding="utf-8")
        unrelated.write_text("def unrelated():\n  return 1\n", encoding="utf-8")
        uri = main.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": None, "workspaceFolders": []})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "sprout",
                    "version": 1,
                    "text": "",
                },
            },
        })

        assert server.semantic_tokens(uri) == {"data": []}
        index = server.indexes[str(root.resolve())]
        assert str(unrelated.resolve()) not in index.files


def test_workspace_initialize_defers_full_index_until_workspace_query() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main = root / "main.sprout"
        unrelated = root / "unrelated.sprout"
        source = 'say "ready"\n'
        main.write_text(source, encoding="utf-8")
        unrelated.write_text("def workspace_only_symbol():\n  return 1\n", encoding="utf-8")
        uri = main.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())

        request(
            server,
            1,
            "initialize",
            {
                "rootUri": root.resolve().as_uri(),
                "workspaceFolders": [{"uri": root.resolve().as_uri(), "name": "latency-test"}],
            },
        )
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        assert server.indexes == {}

        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "sprout",
                    "version": 1,
                    "text": source,
                },
            },
        })
        initial_index = server.indexes[str(root.resolve())]
        assert str(main.resolve()) in initial_index.files
        assert str(unrelated.resolve()) not in initial_index.files

        symbols = request(
            server,
            2,
            "workspace/symbol",
            {"query": "workspace_only_symbol"},
        )
        assert [item["name"] for item in symbols["result"]] == ["workspace_only_symbol"]
        assert str(unrelated.resolve()) in server.indexes[str(root.resolve())].files


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


def test_prepare_rename_refuses_module_aliases() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        path = root / "main.sprout"
        helper.write_text("def greet():\n  return 1\n", encoding="utf-8")
        source = 'import "helper.sprout" as helper\nsay helper.greet()\n'
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
        prepared = request(server, 2, "textDocument/prepareRename", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
        })
        assert prepared["error"]["code"] == LSP.JSONRPC_INVALID_REQUEST


def test_definition_resolves_imported_module_aliases_and_members() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        path = root / "main.sprout"
        helper.write_text("## Friendly helper\n\ndef greet(name):\n  return name\n", encoding="utf-8")
        source = 'import "helper.sprout" as helper\nsay helper.greet("Ada")\n'
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

        alias_definition = request(server, 2, "textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 6},
        })
        assert alias_definition["result"][0]["uri"] == helper.resolve().as_uri()
        assert alias_definition["result"][0]["range"]["start"]["line"] == 2

        member_definition = request(server, 3, "textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 13},
        })
        assert member_definition["result"][0]["uri"] == helper.resolve().as_uri()
        assert member_definition["result"][0]["range"]["start"]["line"] == 2

        hover = request(server, 4, "textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 13},
        })
        value = hover["result"]["contents"]["value"]
        assert "```sprout" in value
        assert "Kind: `function`" in value
        assert "Defined at" in value


def test_signature_help_tracks_nested_arguments() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "def pair(left, right, label=\"ok\"):\n"
            "  return left\n\n"
            "def wrap(value):\n"
            "  return value\n\n"
            "say pair(wrap(1), [2, 3], \n"
        )
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
        signature = request(server, 2, "textDocument/signatureHelp", {
            "textDocument": {"uri": uri},
            "position": {"line": 6, "character": 26},
        })
        result = signature["result"]
        assert result["activeParameter"] == 2
        assert result["signatures"][0]["label"] == "pair(left, right, label=...)"
        assert len(result["signatures"][0]["parameters"]) == 3


def test_safe_code_actions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "\tvalue = true\n"
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
            "Use Sprout 'True'",
        ]
        assert actions[1]["edit"]["changes"][uri][0]["newText"] == "True"


def test_keyword_argument_code_action_and_richer_semantic_tokens() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "def hello(count, mood):\n"
            "  say(\"Hello! I'm feeling \" + mood + \" today!\")\n\n"
            'hello(count=1, modd=\"happy\")\n'
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        unknown = next(item for item in published["params"]["diagnostics"] if item["code"] == "SPROUT_UNKNOWN_ARGUMENT")

        semantic = request(server, 2, "textDocument/semanticTokens/full", {
            "textDocument": {"uri": uri},
        })
        tokens = decode_semantic_token_data(semantic["result"]["data"])
        token_types = {token[3] for token in tokens}
        assert LSP.SEMANTIC_TOKEN_TYPE_INDEX["keyword"] in token_types
        assert LSP.SEMANTIC_TOKEN_TYPE_INDEX["string"] in token_types
        assert LSP.SEMANTIC_TOKEN_TYPE_INDEX["parameter"] in token_types
        response = request(server, 4, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": unknown["range"],
            "context": {"diagnostics": [unknown]},
        })
        action = next(item for item in response["result"] if item["title"] == "Rename argument to 'mood'")
        assert action["edit"]["changes"][uri][0]["newText"] == "mood"


def test_duplicate_argument_gets_removal_quick_fix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "def hello(count, mood):\n"
            "  say mood\n\n"
            'hello(1, mood="happy", count=2)\n'
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        duplicate = next(item for item in published["params"]["diagnostics"] if item["code"] == "SPROUT_DUPLICATE_ARGUMENT")

        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": duplicate["range"],
            "context": {"diagnostics": [duplicate]},
        })
        action = next(item for item in response["result"] if item["title"] == "Remove duplicate argument 'count'")
        edit = action["edit"]["changes"][uri][0]
        assert edit["newText"] == ""
        assert edit["range"]["start"]["line"] == 3
        assert edit["range"]["start"]["character"] < edit["range"]["end"]["character"]


def test_builtin_calls_are_semantic_function_tokens() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "values = [1, 2]\n"
            "say len(values)\n"
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 1, "text": source}},
        })
        semantic = request(server, 2, "textDocument/semanticTokens/full", {
            "textDocument": {"uri": uri},
        })
        tokens = decode_semantic_token_data(semantic["result"]["data"])
        function_token = LSP.SEMANTIC_TOKEN_TYPE_INDEX["function"]
        assert (1, 4, 3, function_token, 0) in tokens


def test_typo_diagnostics_and_quick_fixes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "impo\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostic = published["params"]["diagnostics"][0]
        assert diagnostic["code"] == "SPROUT_UNKNOWN_NAME"
        assert diagnostic["range"]["end"]["character"] == 4
        assert diagnostic["data"]["replacement"] == "import"

        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": diagnostic["range"],
            "context": {"diagnostics": [diagnostic]},
        })
        action = response["result"][0]
        assert action["title"] == "Replace with 'import'"
        assert action["edit"]["changes"][uri][0]["newText"] == "import"


def test_legacy_print_gets_say_quick_fix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = 'print("x")\n'
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostic = published["params"]["diagnostics"][0]
        assert diagnostic["code"] == "SPROUT_UNKNOWN_NAME"
        assert diagnostic["data"]["replacement"] == "say"

        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": diagnostic["range"],
            "context": {"diagnostics": [diagnostic]},
        })
        action = response["result"][0]
        assert action["title"] == "Replace with 'say'"
        assert action["edit"]["changes"][uri][0]["newText"] == "say"


def test_missing_argument_gets_named_nil_quick_fix() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "def hello(count, mood):\n  return count\n\nhello()\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostic = next(item for item in published["params"]["diagnostics"] if item["code"] == "SPROUT_ARGUMENT_COUNT")
        assert diagnostic["data"]["missing"] == ["count", "mood"]

        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": diagnostic["range"],
            "context": {"diagnostics": [diagnostic]},
        })
        action = next(item for item in response["result"] if item["title"] == "Add missing required arguments")
        assert action["edit"]["changes"][uri][0]["newText"] == "count=nil, mood=nil"


def test_protocol_reader_handles_fragmented_utf8_messages() -> None:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"rootUri": None},
        },
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": "file:///tmp/nonascii.sprout",
                    "languageId": "sprout",
                    "version": 1,
                    "text": 'say "π λ Ω"\nimpo\n',
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": "file:///tmp/nonascii.sprout"},
                "position": {"line": 1, "character": 2},
            },
        },
    ]
    stream = b"".join(encode_message(message) for message in messages)
    server = LSP.SproutLanguageServer(reader=FragmentedReader(stream, chunk_size=1), writer=io.BytesIO())

    first = server.read_message()
    second = server.read_message()
    third = server.read_message()

    assert first["method"] == "initialize"
    assert second["params"]["textDocument"]["text"].startswith('say "π')
    assert third["method"] == "textDocument/completion"


def test_standalone_file_does_not_scan_entire_parent_folder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        extension_root = root / "fake-extension"
        extension_root.mkdir()
        home_like = root / "home"
        home_like.mkdir()
        main = home_like / "main.sprout"
        bad = home_like / "bad_encoding.sprout"
        main.write_text("say impo\n", encoding="utf-8")
        bad.write_bytes(b"\xce\xce\xce")
        uri = main.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)

        request(server, 1, "initialize", {
            "workspaceFolders": [{"uri": extension_root.resolve().as_uri(), "name": "extension"}],
        })
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": "say impo\n"}},
        })

        index = server.index_for_uri(uri, rebuild=False)
        assert str(main.resolve()) in index.files
        assert str(bad.resolve()) not in index.files
        messages = decode_messages(output.getvalue())
        published = [message for message in messages if message.get("method") == "textDocument/publishDiagnostics"]
        assert published


def test_completion_recovers_for_incomplete_module_member_access() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "import pixelgarden as pix\npix.\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })

        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 1, "character": 5},
        })
        labels = {item["label"] for item in completion["result"]["items"]}
        assert {"vec2", "sprite_asset", "animation"}.issubset(labels)


def test_import_context_completion_suggests_module_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "import pixel"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })

        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 12},
        })
        labels = {item["label"] for item in completion["result"]["items"]}
        assert "pixelgarden" in labels


def test_import_context_completion_does_not_offer_keywords() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "import ef"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })

        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 0, "character": 9},
        })
        labels = {item["label"] for item in completion["result"]["items"]}
        assert "elif" not in labels
        assert labels == set()


def test_trailing_whitespace_gets_quick_fix_and_full_range() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = 'say "hi"   \n'
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostic = next(item for item in published["params"]["diagnostics"] if item["code"] == "SPROUT_TRAILING_WHITESPACE")
        assert diagnostic["range"]["start"]["character"] == len('say "hi"')
        assert diagnostic["range"]["end"]["character"] == len('say "hi"   ')

        response = request(server, 2, "textDocument/codeAction", {
            "textDocument": {"uri": uri},
            "range": diagnostic["range"],
            "context": {"diagnostics": [diagnostic]},
        })
        action = next(item for item in response["result"] if item["title"] == "Remove trailing whitespace")
        edit = action["edit"]["changes"][uri][0]
        assert edit["range"]["start"]["character"] == len('say "hi"')
        assert edit["range"]["end"]["character"] == len('say "hi"   ')
        assert edit["newText"] == ""


def test_incomplete_import_publishes_error_diagnostic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "import\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostic = published["params"]["diagnostics"][0]
        assert diagnostic["severity"] == 1
        assert diagnostic["code"] == "SPROUT_ERROR"
        assert "Expected a module name" in diagnostic["message"]
        assert diagnostic["range"]["start"]["character"] == len("import")
        assert diagnostic["range"]["end"]["character"] == len("import")


def test_completion_ranking_prefers_local_symbols() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        path = root / "main.sprout"
        helper.write_text("def spawn_enemy():\n  return 1\n", encoding="utf-8")
        source = (
            'import "helper.sprout" as helper\n'
            "def spawn():\n"
            "  return 1\n\n"
            "def scope():\n"
            "  speed = 2\n"
            "  sp\n"
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 6, "character": 4},
        })
        labels = [item["label"] for item in completion["result"]["items"][:3]]
        assert labels[0] == "speed"
        assert "spawn" in labels[:3]
        assert "sprout" not in labels[:3]


def test_completion_with_semantic_matches_skips_extra_keywords() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = (
            "def scope():\n"
            "  speed = 2\n"
            "  spawn = 3\n"
            "  sp\n"
        )
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        completion = request(server, 2, "textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": 3, "character": 4},
        })
        labels = [item["label"] for item in completion["result"]["items"]]
        assert set(labels[:2]) == {"speed", "spawn"}
        assert "sprout" not in labels


def test_blank_document_has_no_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "blank.sprout"
        source = ""
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        assert published["params"]["diagnostics"] == []


def test_diagnostics_are_republished_for_new_document_version() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "say missing_name\n# note\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })

        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 2},
                "contentChanges": [{
                    "range": {
                        "start": {"line": 1, "character": len("# note")},
                        "end": {"line": 1, "character": len("# note")},
                    },
                    "text": " still a comment",
                }],
            },
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = [message for message in notifications if message.get("method") == "textDocument/publishDiagnostics"]
        assert len(published) == 1
        assert published[0]["params"]["version"] == 2
        assert published[0]["params"]["diagnostics"][0]["range"] == {
            "start": {"line": 0, "character": 4},
            "end": {"line": 0, "character": 16},
        }

        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 2},
                "contentChanges": [{"text": server.documents[uri].text}],
            },
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = [message for message in notifications if message.get("method") == "textDocument/publishDiagnostics"]
        assert published == []


def test_stale_did_change_version_is_ignored() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "say 1\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(server, 1, "initialize", {"rootUri": root.resolve().as_uri()})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "version": 3, "text": source}},
        })
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didChange",
            "params": {
                "textDocument": {"uri": uri, "version": 2},
                "contentChanges": [{"text": "say 2\n"}],
            },
        })
        assert server.documents[uri].text == source
        assert server.documents[uri].version == 3


def test_diagnostic_modes_overrides_and_unused_tags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "import pixelgarden as pix\ndef greet(name):\n  return \"hello\"\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(
            server,
            1,
            "initialize",
            {
                "rootUri": root.resolve().as_uri(),
                "initializationOptions": {
                    "sprout": {
                        "analysis": {
                            "typeCheckingMode": "strict",
                            "diagnosticSeverityOverrides": {
                                "SPROUT_MISSING_RETURN_TYPE": "none",
                            },
                        }
                    }
                },
            },
        )
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostics = published["params"]["diagnostics"]
        by_code = {item["code"]: item for item in diagnostics}
        assert by_code["SPROUT_UNUSED_IMPORT"]["tags"] == [1]
        assert by_code["SPROUT_UNUSED_IMPORT"]["severity"] == 4
        assert by_code["SPROUT_MISSING_PARAMETER_TYPE"]["severity"] == 2
        assert "SPROUT_MISSING_RETURN_TYPE" not in by_code

        status = request(server, 20, "sprout/analysisStatus", {"uri": uri})
        assert status["result"]["settings"]["diagnosticMode"] == "workspace"
        assert status["result"]["settings"]["indexing"] is True

        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "workspace/didChangeConfiguration",
            "params": {
                "settings": {
                    "sprout": {
                        "analysis": {
                            "typeCheckingMode": "off",
                            "diagnosticMode": "openFilesOnly",
                            "indexing": False,
                            "languageServerMode": "light",
                        }
                    }
                }
            },
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        assert published["params"]["diagnostics"] == []
        updated = request(server, 21, "sprout/analysisStatus", {"uri": uri})
        assert updated["result"]["settings"]["diagnosticMode"] == "openFilesOnly"
        assert updated["result"]["settings"]["indexing"] is False
        assert updated["result"]["effectiveSettings"]["diagnosticMode"] == "openFilesOnly"
        assert updated["result"]["effectiveSettings"]["indexing"] is False
        assert updated["result"]["effectiveSettings"]["languageServerMode"] == "light"
        assert updated["result"]["effectiveSettings"]["useLibraryCodeForTypes"] is False
        assert updated["result"]["effectiveSettings"]["userFileIndexingLimit"] == 200


def test_style_warnings_off_suppresses_legacy_name_compatibility_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "main.sprout"
        source = "value = None\nprint(value)\nflag = true\nother = False\nmystery\n"
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        output = io.BytesIO()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
        request(
            server,
            1,
            "initialize",
            {
                "rootUri": root.resolve().as_uri(),
                "initializationOptions": {
                    "sprout": {
                        "diagnostics": {
                            "styleWarnings": False,
                            "typoChecking": True,
                        }
                    }
                },
            },
        )
        before = len(output.getvalue())
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        notifications = decode_messages(output.getvalue()[before:])
        published = next(message for message in notifications if message.get("method") == "textDocument/publishDiagnostics")
        diagnostics = published["params"]["diagnostics"]
        unknown_names = [item for item in diagnostics if item["code"] == "SPROUT_UNKNOWN_NAME"]
        assert len(unknown_names) == 1
        assert unknown_names[0]["message"].startswith("Unknown name 'mystery'")
        assert all((item.get("data") or {}).get("replacement") not in {"say", "nil", "True", "false"} for item in diagnostics)


def test_open_files_only_limits_workspace_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        helper = root / "helper.sprout"
        extra = root / "extra.sprout"
        path = root / "main.sprout"
        helper.write_text("def greet():\n  return 1\n", encoding="utf-8")
        extra.write_text("def unused():\n  return 2\n", encoding="utf-8")
        source = 'import "helper.sprout" as helper\nsay helper.greet()\n'
        path.write_text(source, encoding="utf-8")
        uri = path.resolve().as_uri()
        server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=io.BytesIO())
        request(
            server,
            1,
            "initialize",
            {
                "rootUri": root.resolve().as_uri(),
                "initializationOptions": {
                    "sprout": {
                        "analysis": {
                            "diagnosticMode": "openFilesOnly",
                            "languageServerMode": "light",
                        }
                    }
                },
            },
        )
        server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        server.handle({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "sprout", "version": 1, "text": source}},
        })
        status = request(server, 22, "sprout/analysisStatus", {"uri": uri})
        indexed_paths = set(server.index_for_uri(uri, rebuild=False).files)
        assert str(path.resolve()) in indexed_paths
        assert str(helper.resolve()) in indexed_paths
        assert str(extra.resolve()) not in indexed_paths
        assert status["result"]["fileCount"] == 2
        assert status["result"]["effectiveSettings"]["diagnosticMode"] == "openFilesOnly"
        assert status["result"]["effectiveSettings"]["languageServerMode"] == "light"
        assert status["result"]["effectiveSettings"]["userFileIndexingLimit"] == 200


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
    test_inferred_hover_completion_and_conditional_diagnostics_agree()
    test_imported_factory_partial_member_completion_stays_member_only()
    test_protocol_lifecycle_and_incremental_sync()
    test_loose_file_open_defers_full_project_index_until_workspace_query()
    test_blank_document_semantic_tokens_do_not_trigger_full_project_index()
    test_workspace_initialize_defers_full_index_until_workspace_query()
    test_references_rename_and_protocol_errors()
    test_prepare_rename_refuses_module_aliases()
    test_definition_resolves_imported_module_aliases_and_members()
    test_signature_help_tracks_nested_arguments()
    test_safe_code_actions()
    test_keyword_argument_code_action_and_richer_semantic_tokens()
    test_duplicate_argument_gets_removal_quick_fix()
    test_builtin_calls_are_semantic_function_tokens()
    test_typo_diagnostics_and_quick_fixes()
    test_missing_argument_gets_named_nil_quick_fix()
    test_completion_recovers_for_incomplete_module_member_access()
    test_import_context_completion_suggests_module_names()
    test_import_context_completion_does_not_offer_keywords()
    test_trailing_whitespace_gets_quick_fix_and_full_range()
    test_incomplete_import_publishes_error_diagnostic()
    test_completion_ranking_prefers_local_symbols()
    test_completion_with_semantic_matches_skips_extra_keywords()
    test_blank_document_has_no_diagnostics()
    test_diagnostics_are_republished_for_new_document_version()
    test_stale_did_change_version_is_ignored()
    test_diagnostic_modes_overrides_and_unused_tags()
    test_style_warnings_off_suppresses_legacy_name_compatibility_only()
    test_open_files_only_limits_workspace_scope()
    test_stdio_process_lifecycle()
    print("sprout lsp tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
