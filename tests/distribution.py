#!/usr/bin/env python3
"""Tests for Sprout language installation and release artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.distribution import (
    install_language,
    package_language,
    package_vscode_extension,
    uninstall_language,
    verify_release_versions,
)
from sprout_core.model import SPROUT_VERSION


def test_install_and_uninstall() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "prefix"
        result = install_language(prefix=prefix)
        launcher = Path(result["launcher"])
        manifest = Path(result["manifest"])
        assert launcher.exists()
        assert manifest.exists()
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["version"] == SPROUT_VERSION
        command = [str(launcher), "version"]
        if launcher.suffix == ".cmd":
            command = ["cmd", "/c", str(launcher), "version"]
        output = subprocess.run(command, text=True, capture_output=True, check=True)
        assert output.stdout.strip() == f"Sprout {SPROUT_VERSION}"
        conformance = subprocess.run(
            [*command[:-1], "conformance"],
            text=True,
            capture_output=True,
            check=True,
        )
        installed_manifest = json.loads(
            (Path(data["runtime"]) / "sprout_core" / "conformance" / "manifest.json").read_text(encoding="utf-8")
        )
        count = len(installed_manifest["cases"])
        assert conformance.stdout.strip().endswith(f"{count}/{count} conformance cases passed")
        assert uninstall_language(prefix=prefix) == 0
        assert not launcher.exists()
        assert not manifest.exists()


def test_release_archives() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)
        language = Path(package_language(output))
        extension = Path(package_vscode_extension(output))
        assert language.exists()
        assert extension.exists()
        with zipfile.ZipFile(language) as archive:
            names = archive.namelist()
            assert f"sprout-{SPROUT_VERSION}/install.py" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/runtime.py" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/conformance/manifest.json" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/conformance/typed.sprout" in names
            assert f"sprout-{SPROUT_VERSION}/tests/smoke.sh" in names
        with zipfile.ZipFile(extension) as archive:
            names = archive.namelist()
            assert "[Content_Types].xml" in names
            assert "extension.vsixmanifest" in names
            assert "extension/package.json" in names
            assert "extension/sprout.py" in names
            assert "extension/sprout_core/runtime.py" in names
            assert "extension/sprout_core/conformance/manifest.json" in names
            assert "extension/sprout_core/conformance/typed.sprout" in names
            assert "extension/tools/sprout_lsp.py" in names
            assert "extension/tools/sprout_dap.py" in names
            assert "extension/lsp-client.js" in names
            assert "extension/test-controller.js" in names
            package = json.loads(archive.read("extension/package.json"))
            assert package["version"] == SPROUT_VERSION


def test_version_consistency() -> None:
    assert verify_release_versions() == []


def main() -> int:
    test_install_and_uninstall()
    test_release_archives()
    test_version_consistency()
    print("sprout distribution tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
