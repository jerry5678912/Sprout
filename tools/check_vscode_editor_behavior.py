#!/usr/bin/env python3
"""Check the Sprout LSP behavior that the VS Code extension depends on."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sprout_lsp_editor_check", ROOT / "tools" / "sprout_lsp.py")
assert SPEC and SPEC.loader
LSP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LSP)


def decode_messages(raw: bytes) -> list[dict]:
    messages = []
    offset = 0
    while offset < len(raw):
        boundary = raw.index(b"\r\n\r\n", offset)
        headers = raw[offset:boundary].decode("ascii")
        length = int(next(
            line.split(":", 1)[1]
            for line in headers.splitlines()
            if line.lower().startswith("content-length:")
        ))
        start = boundary + 4
        messages.append(json.loads(raw[start:start + length].decode("utf-8")))
        offset = start + length
    return messages


def request(server, request_id: int, method: str, params: dict) -> dict:
    before = len(server.writer.getvalue())
    server.process_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    messages = decode_messages(server.writer.getvalue()[before:])
    return next(message for message in messages if message.get("id") == request_id)


def notifications_since(output: io.BytesIO, before: int) -> list[dict]:
    return decode_messages(output.getvalue()[before:])


def open_document(server, output: io.BytesIO, path: Path, source: str, version: int = 1) -> list[dict]:
    before = len(output.getvalue())
    server.handle({
        "jsonrpc": "2.0",
        "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": path.resolve().as_uri(),
                "languageId": "sprout",
                "version": version,
                "text": source,
            }
        },
    })
    return notifications_since(output, before)


def assert_has(items, label: str) -> None:
    labels = {item.get("label") or item.get("name") for item in items}
    assert label in labels, f"missing {label!r}; got {sorted(labels)[:30]}"


def main() -> int:
    root = ROOT / "examples" / "editor_test_workspace"
    main_path = root / "src" / "main.sprout"
    diag_path = root / "src" / "diagnostics.sprout"
    main_source = main_path.read_text(encoding="utf-8")
    diag_source = diag_path.read_text(encoding="utf-8")
    main_uri = main_path.resolve().as_uri()
    diag_uri = diag_path.resolve().as_uri()

    output = io.BytesIO()
    server = LSP.SproutLanguageServer(reader=io.BytesIO(), writer=output)
    initialized = request(server, 1, "initialize", {"workspaceFolders": [{"uri": root.resolve().as_uri(), "name": "editor_test_workspace"}]})
    capabilities = initialized["result"]["capabilities"]
    assert capabilities["completionProvider"]
    assert capabilities["hoverProvider"] is True
    assert capabilities["definitionProvider"] is True
    assert capabilities["referencesProvider"] is True
    assert capabilities["renameProvider"]["prepareProvider"] is True
    server.handle({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    main_notifications = open_document(server, output, main_path, main_source)
    main_diagnostics = next(item for item in main_notifications if item.get("method") == "textDocument/publishDiagnostics")
    assert main_diagnostics["params"]["diagnostics"] == []

    status = request(server, 20, "sprout/analysisStatus", {"uri": main_uri})["result"]
    assert status["fileCount"] >= 2
    assert status["effectiveSettings"]["diagnosticMode"] in {"workspace", "openFilesOnly"}

    diag_notifications = open_document(server, output, diag_path, diag_source)
    published = next(item for item in diag_notifications if item.get("method") == "textDocument/publishDiagnostics")
    diagnostics = published["params"]["diagnostics"]
    codes = {item["code"] for item in diagnostics}
    assert "SPROUT_UNKNOWN_NAME" in codes
    assert "SPROUT_UNKNOWN_MEMBER" in codes
    typo = next(item for item in diagnostics if item["message"].startswith("Unknown name 'impo'"))
    assert typo["severity"] == 2
    assert typo["range"]["end"]["character"] == 4
    assert typo["data"]["replacement"] == "import"

    actions = request(server, 2, "textDocument/codeAction", {
        "textDocument": {"uri": diag_uri},
        "range": typo["range"],
        "context": {"diagnostics": [typo]},
    })["result"]
    assert actions and actions[0]["title"] == "Replace with 'import'"

    player_dot = main_source.index("player.name") + len("player.")
    line = main_source[:player_dot].count("\n")
    col = player_dot - main_source.rfind("\n", 0, player_dot) - 1
    completions = request(server, 3, "textDocument/completion", {
        "textDocument": {"uri": main_uri},
        "position": {"line": line, "character": col},
    })["result"]["items"]
    assert_has(completions, "name")
    assert_has(completions, "greet")
    completion_status = request(server, 21, "sprout/analysisStatus", {"uri": main_uri})["result"]
    assert completion_status["operations"]["completion"]["count"] >= 1

    add_pos = main_source.index("add")
    add_line = main_source[:add_pos].count("\n")
    add_col = add_pos - main_source.rfind("\n", 0, add_pos) - 1
    hover = request(server, 4, "textDocument/hover", {
        "textDocument": {"uri": main_uri},
        "position": {"line": add_line, "character": add_col},
    })["result"]
    assert "add" in hover["contents"]["value"]

    definition = request(server, 5, "textDocument/definition", {
        "textDocument": {"uri": main_uri},
        "position": {"line": add_line, "character": add_col},
    })["result"]
    assert definition and definition[0]["uri"].endswith("math_tools.sprout")

    player_mod_pos = main_source.index("player_mod")
    player_mod_line = main_source[:player_mod_pos].count("\n")
    player_mod_col = player_mod_pos - main_source.rfind("\n", 0, player_mod_pos) - 1
    module_definition = request(server, 51, "textDocument/definition", {
        "textDocument": {"uri": main_uri},
        "position": {"line": player_mod_line, "character": player_mod_col},
    })["result"]
    assert module_definition and module_definition[0]["uri"].endswith("player.sprout")

    score_pos = main_source.index("score", main_source.index("say score"))
    score_line = main_source[:score_pos].count("\n")
    score_col = score_pos - main_source.rfind("\n", 0, score_pos) - 1
    references = request(server, 6, "textDocument/references", {
        "textDocument": {"uri": main_uri},
        "position": {"line": score_line, "character": score_col},
        "context": {"includeDeclaration": True},
    })["result"]
    assert len(references) == 2

    prepared = request(server, 7, "textDocument/prepareRename", {
        "textDocument": {"uri": main_uri},
        "position": {"line": score_line, "character": score_col},
    })["result"]
    assert prepared["placeholder"] == "score"

    renamed = request(server, 8, "textDocument/rename", {
        "textDocument": {"uri": main_uri},
        "position": {"line": score_line, "character": score_col},
        "newName": "total",
    })["result"]
    assert len(renamed["changes"][main_uri]) == 2

    spawn_call_pos = main_source.index('spawn("Mina"') + len("spawn(")
    spawn_call_line = main_source[:spawn_call_pos].count("\n")
    spawn_call_col = spawn_call_pos - main_source.rfind("\n", 0, spawn_call_pos) - 1
    signature = request(server, 9, "textDocument/signatureHelp", {
        "textDocument": {"uri": main_uri},
        "position": {"line": spawn_call_line, "character": spawn_call_col},
    })["result"]
    assert signature["signatures"][0]["label"] == "spawn(name)"
    assert signature["activeParameter"] == 0

    final_status = request(server, 22, "sprout/analysisStatus", {"uri": main_uri})["result"]
    operations = final_status["operations"]
    assert operations["analysisStatus"]["count"] >= 1
    assert operations["hover"]["count"] >= 1
    assert operations["definition"]["count"] >= 2
    assert operations["references"]["count"] >= 1
    assert operations["rename"]["count"] >= 1
    assert operations["signatureHelp"]["count"] >= 1

    before = len(output.getvalue())
    server.handle({
        "jsonrpc": "2.0",
        "method": "textDocument/didChange",
        "params": {
            "textDocument": {"uri": diag_uri, "version": 2},
            "contentChanges": [{"text": ""}],
        },
    })
    cleared = next(item for item in notifications_since(output, before) if item.get("method") == "textDocument/publishDiagnostics")
    assert cleared["params"]["diagnostics"] == []

    print("sprout vscode editor behavior check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
