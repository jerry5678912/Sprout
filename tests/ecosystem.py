#!/usr/bin/env python3
"""Regression tests for Sprout builds, bundles, registries, and releases."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.ecosystem import version_matches
from sprout_core.registry_server import (
    RegistryHTTPServer,
    RegistryStore,
    create_registry_token,
    load_tokens,
    revoke_registry_token,
)
from sprout_core.tooling import parse_simple_toml


def run(
    args: list[str],
    cwd: Path,
    registry: Path | str,
    check: bool = True,
    token: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["SPROUT_REGISTRY"] = str(registry)
    if token is not None:
        env["SPROUT_REGISTRY_TOKEN"] = token
    return subprocess.run(
        [sys.executable, str(ROOT / "sprout.py"), *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


def write_package(root: Path, version: str, message: str) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "docs").mkdir(exist_ok=True)
    (root / "sprout.toml").write_text(
        f"""[project]
name = "physics_tools"
version = "{version}"
main = "src/main.sprout"
authors = ["Sprout Tests"]
description = "Deterministic physics helpers"
license = "Apache-2.0"

[package]
name = "physics_tools"
version = "{version}"
description = "Deterministic physics helpers"
author = "Sprout Tests"
license = "Apache-2.0"

[paths]
source = ["src"]
modules = []

[dependencies]
""",
        encoding="utf-8",
    )
    (root / "src" / "main.sprout").write_text(f'say "{message}"\n', encoding="utf-8")
    (root / "src" / "physics_tools.sprout").write_text(
        f'## Returns the package version.\ndef package_version():\n  return "{version}"\n',
        encoding="utf-8",
    )
    (root / "tests" / "package_test.sprout").write_text(
        f'import "physics_tools.sprout" as physics\n\ntest "version":\n  expect(physics.package_version()).to_equal("{version}")\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Physics Tools\n", encoding="utf-8")
    (root / "docs" / "GUIDE.md").write_text("# Guide\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_package_publish_install_update_release() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        registry = base / "registry"
        library = base / "physics_tools"
        app = base / "app"
        write_package(library, "1.0.0", "physics v1")

        published = run(["pkg", "publish", str(library)], base, registry).stdout
        assert "published physics_tools 1.0.0" in published
        index = json.loads((registry / "index.json").read_text(encoding="utf-8"))
        assert index["packages"]["physics_tools"]["latest"] == "1.0.0"
        assert "bundle" in index["packages"]["physics_tools"]["versions"]["1.0.0"]
        assert len(index["packages"]["physics_tools"]["versions"]["1.0.0"]["sha256"]) == 64
        duplicate = run(["pkg", "publish", str(library)], base, registry, check=False)
        assert duplicate.returncode == 1
        assert "already published" in duplicate.stderr
        assert "physics_tools 1.0.0" in run(["pkg", "search", "physics"], base, registry).stdout
        assert '"latest": "1.0.0"' in run(["info", "physics_tools"], base, registry).stdout
        assert '"docs": "docs/API.md"' in run(["pkg", "docs", "physics_tools"], base, registry).stdout
        vm_build = Path(run(["build", "--vm", str(library)], base, registry).stdout.strip().split()[-1])
        assert (vm_build / "main.bytecode.txt").exists()

        app.mkdir()
        run(["pkg", "init"], app, registry)
        (app / "assets").mkdir()
        (app / "assets" / "message.txt").write_text("hello asset\n", encoding="utf-8")
        config = (app / "sprout.toml").read_text(encoding="utf-8")
        config = config.replace(
            '[paths]\nsource = ["src"]\nmodules = ["modules"]',
            '[paths]\nsource = ["src"]\nmodules = ["modules"]\nassets = ["assets"]',
        )
        (app / "sprout.toml").write_text(config, encoding="utf-8")
        run(["pkg", "install", "physics_tools@^1.0.0"], app, registry)
        (app / "src" / "main.sprout").write_text(
            'import "physics_tools.sprout" as physics\nsay physics.package_version()\n',
            encoding="utf-8",
        )
        assert run(["run", "."], app, registry).stdout.strip() == "1.0.0"
        assert "physics_tools 1.0.0 installed" in run(["list-installed"], app, registry).stdout
        assert "physics_tools 1.0.0 [path]" in run(["pkg", "tree"], app, registry).stdout

        first_build = Path(run(["build"], app, registry).stdout.strip().split()[-1])
        assert (first_build / "assets" / "message.txt").exists()
        assert (first_build / "dependencies" / "physics_tools" / "src" / "physics_tools.sprout").exists()
        manifest = json.loads((first_build / "build-manifest.json").read_text(encoding="utf-8"))
        assert manifest["dependencies"] == {"physics_tools": "1.0.0"}
        assert "dependencies/physics_tools/src/physics_tools.sprout" in manifest["files"]

        first_bundle = Path(run(["package"], app, registry).stdout.strip().split()[-1])
        first_hash = sha256(first_bundle)
        second_bundle = Path(run(["package"], app, registry).stdout.strip().split()[-1])
        assert sha256(second_bundle) == first_hash

        write_package(library, "1.1.0", "physics v1.1")
        run(["pkg", "publish", str(library)], base, registry)
        run(["pkg", "update"], app, registry)
        assert run(["run", "."], app, registry).stdout.strip() == "1.1.0"

        release = run(["release"], library, registry).stdout
        assert "release ready physics_tools 1.1.0" in release
        release_data = json.loads((library / "dist" / "release.json").read_text(encoding="utf-8"))
        assert release_data["version"] == "1.1.0"


def test_dependency_conflict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        registry = base / "registry"
        shared = base / "shared"
        plugin = base / "plugin"
        app = base / "app"
        for path in (shared, plugin, app):
            (path / "src").mkdir(parents=True)
            (path / "src" / "main.sprout").write_text('say "ok"\n', encoding="utf-8")
        (shared / "sprout.toml").write_text(
            '[project]\nname = "shared"\nversion = "1.5.0"\nmain = "src/main.sprout"\n',
            encoding="utf-8",
        )
        (plugin / "sprout.toml").write_text(
            '[project]\nname = "plugin"\nversion = "1.0.0"\nmain = "src/main.sprout"\n\n'
            '[dependencies]\nshared = { path = "../shared", version = "^2.0.0" }\n',
            encoding="utf-8",
        )
        (app / "sprout.toml").write_text(
            '[project]\nname = "app"\nversion = "1.0.0"\nmain = "src/main.sprout"\n\n'
            '[dependencies]\nshared = { path = "../shared", version = "^1.0.0" }\n'
            'plugin = { path = "../plugin", version = "^1.0.0" }\n',
            encoding="utf-8",
        )
        result = run(["build"], app, registry, check=False)
        assert result.returncode == 1
        assert "Dependency conflict for shared" in result.stderr


def test_version_constraints() -> None:
    assert version_matches("1.9.0", "^1.2.0")
    assert not version_matches("2.0.0", "^1.2.0")
    assert version_matches("0.2.9", "^0.2.3")
    assert not version_matches("0.3.0", "^0.2.3")
    assert version_matches("0.0.3", "^0.0.3")
    assert not version_matches("0.0.4", "^0.0.3")
    assert version_matches("1.3.0-beta.1", ">=1.2.0,<1.3.0")
    assert version_matches("1.3.0", "~1.3.0")
    parsed = parse_simple_toml(
        '[dependencies]\ngeometry = { path = "../geometry", version = ">=1.0.0,<2.0.0" }\n'
    )
    assert parsed["dependencies"]["geometry"]["version"] == ">=1.0.0,<2.0.0"


def test_authenticated_hosted_registry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        registry_root = base / "hosted-registry"
        library = base / "physics_tools"
        app = base / "app"
        write_package(library, "2.0.0", "hosted physics")
        allowed_token = create_registry_token(str(registry_root), "physics-publisher", ["physics_tools"])
        denied_token = create_registry_token(str(registry_root), "other-publisher", ["other_tools"])
        stored = json.dumps(load_tokens(str(registry_root)))
        assert allowed_token not in stored
        assert denied_token not in stored

        server = RegistryHTTPServer(("127.0.0.1", 0), str(registry_root))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        registry_url = f"http://127.0.0.1:{server.server_port}"
        try:
            unauthorized = run(["pkg", "publish", str(library)], base, registry_url, check=False)
            assert unauthorized.returncode == 1
            assert "requires --token" in unauthorized.stderr

            forbidden = run(["pkg", "publish", str(library)], base, registry_url, check=False, token=denied_token)
            assert forbidden.returncode == 1
            assert "valid publish token required" in forbidden.stderr

            published = run(["pkg", "publish", str(library)], base, registry_url, token=allowed_token)
            assert "published physics_tools 2.0.0" in published.stdout
            assert "physics_tools 2.0.0" in run(["pkg", "search", "physics"], base, registry_url).stdout

            duplicate = run(["pkg", "publish", str(library)], base, registry_url, check=False, token=allowed_token)
            assert duplicate.returncode == 1
            assert "already published" in duplicate.stderr

            app.mkdir()
            run(["pkg", "init"], app, registry_url)
            run(["pkg", "install", "physics_tools@2.0.0"], app, registry_url)
            installed = app / ".sprout" / "packages" / "physics_tools" / "2.0.0"
            assert (installed / "src" / "physics_tools.sprout").exists()

            revoke_registry_token(str(registry_root), "physics-publisher")
            write_package(library, "2.1.0", "hosted physics update")
            revoked = run(["pkg", "publish", str(library)], base, registry_url, check=False, token=allowed_token)
            assert revoked.returncode == 1
            assert "valid publish token required" in revoked.stderr
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


def test_registry_rejects_untrusted_archives() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegistryStore(str(Path(tmp) / "registry"))
        record = {
            "name": "physics_tools",
            "version": "1.0.0",
            "sha256": "",
        }
        malformed = Path(tmp) / "malformed.sproutpkg"
        with zipfile.ZipFile(malformed, "w") as archive:
            archive.writestr("../escape.txt", "bad")
            archive.writestr("build-manifest.json", json.dumps({
                "name": "physics_tools",
                "version": "1.0.0",
                "files": {},
            }))
        data = malformed.read_bytes()
        record["sha256"] = hashlib.sha256(data).hexdigest()
        try:
            store.publish(record, data)
            raise AssertionError("unsafe archive was accepted")
        except Exception as exc:
            assert "Unsafe package archive path" in str(exc)

        mismatched = Path(tmp) / "mismatched.sproutpkg"
        with zipfile.ZipFile(mismatched, "w") as archive:
            archive.writestr("build-manifest.json", json.dumps({
                "name": "different_name",
                "version": "1.0.0",
                "files": {},
            }))
        data = mismatched.read_bytes()
        record["sha256"] = hashlib.sha256(data).hexdigest()
        try:
            store.publish(record, data)
            raise AssertionError("mismatched archive was accepted")
        except Exception as exc:
            assert "does not match publish metadata" in str(exc)


def main() -> int:
    test_build_package_publish_install_update_release()
    test_dependency_conflict()
    test_version_constraints()
    test_authenticated_hosted_registry()
    test_registry_rejects_untrusted_archives()
    print("sprout ecosystem tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
