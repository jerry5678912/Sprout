#!/usr/bin/env python3
"""Tests for Sprout language installation and release artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.distribution import (
    extension_metadata,
    install_language,
    package_language,
    package_vscode_extension,
    uninstall_language,
    verify_release_versions,
    write_launcher,
)
from sprout_core.model import SPROUT_VERSION
from sprout_core.package import RELEASE_TEST_SCRIPTS


def run_packaging_command(command: list[str]) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise AssertionError(f"Packaging command failed ({result.returncode}): {' '.join(command)}\n{output}")


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
        standard_library = Path(data["runtime"]) / "sprout_core" / "stdlib"
        assert (standard_library / "pixelgarden.sprout").exists()
        named_import = Path(tmp) / "named_import.sprout"
        named_import.write_text("import gamekit\nsay gamekit.make_player(\"Mina\").name\n", encoding="utf-8")
        imported = subprocess.run(
            [*command[:-1], str(named_import)],
            cwd=tmp,
            text=True,
            capture_output=True,
            check=True,
        )
        assert imported.stdout.strip() == "Mina"
        assert uninstall_language(prefix=prefix) == 0
        assert not launcher.exists()
        assert not manifest.exists()


def test_release_archives() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)
        language = Path(package_language(output))
        extension = Path(package_vscode_extension(output))
        extension_version = extension_metadata(ROOT / "editor" / "vscode-sprout")["version"]
        assert language.exists()
        assert extension.exists()
        with zipfile.ZipFile(language) as archive:
            names = archive.namelist()
            assert f"sprout-{SPROUT_VERSION}/install.py" in names
            assert f"sprout-{SPROUT_VERSION}/pyproject.toml" in names
            assert f"sprout-{SPROUT_VERSION}/LICENSE" in names
            assert f"sprout-{SPROUT_VERSION}/NOTICE" in names
            assert f"sprout-{SPROUT_VERSION}/GOVERNANCE.md" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/runtime.py" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/conformance/manifest.json" in names
            assert f"sprout-{SPROUT_VERSION}/sprout_core/conformance/typed.sprout" in names
            assert f"sprout-{SPROUT_VERSION}/tests/smoke.sh" in names
        with zipfile.ZipFile(extension) as archive:
            names = archive.namelist()
            assert "[Content_Types].xml" in names
            assert "extension.vsixmanifest" in names
            assert b"<GalleryFlags>Public</GalleryFlags>" in archive.read("extension.vsixmanifest")
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
            assert extension.name == f"sprout-language-{extension_version}.vsix"
            assert package["version"] == extension_version
            assert package["publisher"] == "jerry5678912"
            commands = {entry["command"] for entry in package["contributes"]["commands"]}
            assert {"sprout.selectInterpreter", "sprout.runCurrentFile"}.issubset(commands)


def test_version_consistency() -> None:
    assert verify_release_versions() == []


def test_python_package_metadata() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{SPROUT_VERSION}"' in metadata
    assert 'license = "Apache-2.0"' in metadata
    assert 'license-files = ["LICENSE", "NOTICE"]' in metadata
    assert 'sprout = "sprout_core.cli:entrypoint"' in metadata
    assert 'py-modules = ["sprout"]' in metadata
    assert 'sprout_core = ["conformance/*.json", "conformance/*.sprout", "stdlib/*.sprout"]' in metadata
    module = subprocess.run(
        [sys.executable, "-m", "sprout_core", "version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert module.stdout.strip() == f"Sprout {SPROUT_VERSION}"


def test_python_package_build_includes_sprout_runner_module() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(tmp) / "dist"
        run_packaging_command([sys.executable, "setup.py", "sdist", "--dist-dir", str(dist)])
        run_packaging_command([sys.executable, "setup.py", "bdist_wheel", "--dist-dir", str(dist)])
        wheel = dist / f"sprout_language-{SPROUT_VERSION}-py3-none-any.whl"
        sdist = next(
            (
                candidate
                for candidate in (
                    dist / f"sprout-language-{SPROUT_VERSION}.tar.gz",
                    dist / f"sprout_language-{SPROUT_VERSION}.tar.gz",
                )
                if candidate.exists()
            ),
            None,
        )
        assert wheel.exists()
        assert sdist is not None
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            assert "sprout.py" in names
            assert "sprout_core/cli.py" in names
        with tarfile.open(sdist, "r:gz") as archive:
            names = set(archive.getnames())
            root = sdist.name.removesuffix(".tar.gz")
            assert f"{root}/sprout.py" in names
            assert f"{root}/sprout_core/cli.py" in names


def test_portable_release_suite_is_complete() -> None:
    assert "tests/advanced_language.py" in RELEASE_TEST_SCRIPTS
    assert "tests/errors.py" in RELEASE_TEST_SCRIPTS
    assert "tests/debug_adapter.py" in RELEASE_TEST_SCRIPTS
    for script in RELEASE_TEST_SCRIPTS:
        assert (ROOT / script).is_file(), script


def test_windows_launcher_uses_installed_module() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        launcher = Path(tmp) / "sprout.cmd"
        runtime = Path(tmp) / "runtime"
        write_launcher(launcher, runtime, python_executable="python")
        text = launcher.read_text(encoding="utf-8")
        assert f"PYTHONPATH={runtime}" in text
        assert '"python" -m sprout_core %*' in text
        assert "sprout.py" not in text


def main() -> int:
    test_install_and_uninstall()
    test_release_archives()
    test_version_consistency()
    test_python_package_metadata()
    test_python_package_build_includes_sprout_runner_module()
    test_portable_release_suite_is_complete()
    test_windows_launcher_uses_installed_module()
    print("sprout distribution tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
