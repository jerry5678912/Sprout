#!/usr/bin/env python3
"""Adversarial tests for Sprout's runtime and package trust boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core import ecosystem  # noqa: E402
from sprout_core.model import SproutError  # noqa: E402
from sprout_core.registry_server import RegistryStore  # noqa: E402


def expect_error(action, text: str) -> None:
    try:
        action()
        raise AssertionError("operation unexpectedly succeeded")
    except SproutError as exc:
        assert text in str(exc), str(exc)


def test_package_extraction_limits_and_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        destination = root / "out"

        traversal = root / "traversal.sproutpkg"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr("../outside.txt", "blocked")
        expect_error(lambda: ecosystem.extract_bundle(str(traversal), str(destination)), "Unsafe package archive path")
        assert not (root / "outside.txt").exists()

        symlink = root / "symlink.sproutpkg"
        with zipfile.ZipFile(symlink, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../outside")
        expect_error(lambda: ecosystem.extract_bundle(str(symlink), str(destination)), "symbolic links")

        previous_files = ecosystem.MAX_PACKAGE_FILES
        previous_bytes = ecosystem.MAX_PACKAGE_EXPANDED_BYTES
        try:
            ecosystem.MAX_PACKAGE_FILES = 1
            many = root / "many.sproutpkg"
            with zipfile.ZipFile(many, "w") as archive:
                archive.writestr("one", "1")
                archive.writestr("two", "2")
            expect_error(lambda: ecosystem.extract_bundle(str(many), str(destination)), "too many files")

            ecosystem.MAX_PACKAGE_FILES = previous_files
            ecosystem.MAX_PACKAGE_EXPANDED_BYTES = 4
            large = root / "large.sproutpkg"
            with zipfile.ZipFile(large, "w") as archive:
                archive.writestr("large", "12345")
            expect_error(lambda: ecosystem.extract_bundle(str(large), str(destination)), "extraction limit")
        finally:
            ecosystem.MAX_PACKAGE_FILES = previous_files
            ecosystem.MAX_PACKAGE_EXPANDED_BYTES = previous_bytes


def test_registry_rejects_forged_manifest_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegistryStore(str(Path(tmp) / "registry"))
        bundle = Path(tmp) / "forged.sproutpkg"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("src/main.sprout", 'say "changed"\n')
            archive.writestr(
                "build-manifest.json",
                json.dumps({
                    "name": "secure_tools",
                    "version": "1.0.0",
                    "files": {"src/main.sprout": "0" * 64},
                }),
            )
        data = bundle.read_bytes()
        import hashlib
        record = {
            "name": "secure_tools",
            "version": "1.0.0",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        expect_error(lambda: store.publish(record, data), "checksum failed")


def test_malformed_source_never_leaks_python_traceback() -> None:
    hostile_sources = [
        "\x00\n",
        "def x(",
        (" " * 5000) + "say 1\n",
        '"\\' * 2000,
        "say [1, 2,\n",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hostile.sprout"
        for source in hostile_sources:
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "sprout.py"), "check", str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            assert result.returncode != 0
            assert "Traceback (most recent call last)" not in result.stderr
            assert "sprout_core/" not in result.stderr
            assert "IndexError" not in result.stderr


def main() -> int:
    test_package_extraction_limits_and_paths()
    test_registry_rejects_forged_manifest_hash()
    test_malformed_source_never_leaks_python_traceback()
    print("sprout security tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
