#!/usr/bin/env python3
"""Regression tests for Sprout's incremental language-server engine."""

from __future__ import annotations

import importlib.util
from pathlib import Path
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


def main() -> int:
    test_incremental_rebuild_and_navigation()
    print("sprout lsp tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
