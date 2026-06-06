from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile
from typing import Any

from .ecosystem import build_project, project_metadata, project_root, sha256_file
from .model import SPROUT_VERSION, SproutError
from .package import read_toml_file, save_project_data


def runtime_root() -> Path:
    return Path(__file__).resolve().parents[1]


def copy_runtime(destination: Path) -> None:
    root = runtime_root()
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "sprout.py", destination / "sprout.py")
    target_core = destination / "sprout_core"
    shutil.copytree(
        root / "sprout_core",
        target_core,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def rewrite_bundled_dependencies(app_root: Path) -> None:
    config = app_root / "sprout.toml"
    data = read_toml_file(str(config))
    dependencies_root = app_root / "dependencies"
    dependencies: dict[str, Any] = {}
    if dependencies_root.is_dir():
        for package in sorted(path for path in dependencies_root.iterdir() if path.is_dir()):
            metadata = project_metadata(str(package))
            dependencies[package.name] = {
                "path": f"dependencies/{package.name}",
                "version": str(metadata["version"]),
            }
    data["dependencies"] = dependencies
    save_project_data(data, str(app_root))


def write_launchers(bundle_root: Path, name: str) -> None:
    launcher_py = bundle_root / "launcher.py"
    launcher_py.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "root = Path(__file__).resolve().parent\n"
        "sys.path.insert(0, str(root / 'runtime'))\n"
        "from sprout_core.cli import main\n"
        "raise SystemExit(main([str(root / 'runtime' / 'sprout.py'), 'run', str(root / 'app'), *sys.argv[1:]]))\n",
        encoding="utf-8",
    )
    unix = bundle_root / name
    unix.write_text(
        "#!/bin/sh\n"
        "ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "PYTHON_BIN=${PYTHON:-python3}\n"
        "command -v \"$PYTHON_BIN\" >/dev/null 2>&1 || { echo 'Sprout app requires Python 3.9 or newer.' >&2; exit 127; }\n"
        "exec \"$PYTHON_BIN\" \"$ROOT/launcher.py\" \"$@\"\n",
        encoding="utf-8",
    )
    unix.chmod(unix.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    windows = bundle_root / f"{name}.cmd"
    windows.write_text(
        "@echo off\r\n"
        "where py >nul 2>nul\r\n"
        "if %errorlevel%==0 (\r\n"
        "  py -3 \"%~dp0launcher.py\" %*\r\n"
        ") else (\r\n"
        "  python \"%~dp0launcher.py\" %*\r\n"
        ")\r\n",
        encoding="utf-8",
    )


def file_hashes(root: Path, exclude: set[str] | None = None) -> dict[str, str]:
    excluded = exclude or set()
    hashes: dict[str, str] = {}
    for source in sorted(path for path in root.rglob("*") if path.is_file()):
        relative = source.relative_to(root).as_posix()
        if relative in excluded:
            continue
        hashes[relative] = sha256_file(str(source))
    return hashes


def build_standalone(path: str = ".", registry: str | None = None) -> str:
    root = project_root(path)
    metadata = project_metadata(root)
    build = Path(build_project(root, registry=registry))
    destination = Path(root) / "dist" / f"{metadata['name']}-{metadata['version']}-standalone"
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    shutil.copytree(build, destination / "app")
    rewrite_bundled_dependencies(destination / "app")
    copy_runtime(destination / "runtime")
    write_launchers(destination, str(metadata["name"]))
    manifest = {
        "schema": 1,
        "name": metadata["name"],
        "version": metadata["version"],
        "sprout": SPROUT_VERSION,
        "main": metadata["main"],
        "python": ">=3.9",
        "files": file_hashes(destination, {"standalone-manifest.json"}),
    }
    (destination / "standalone-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"built standalone app {destination}")
    return str(destination)


def verify_standalone(path: str) -> dict[str, Any]:
    root = Path(path).resolve()
    manifest_path = root / "standalone-manifest.json"
    if not manifest_path.is_file():
        raise SproutError(f"No standalone-manifest.json found in {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_files = manifest.get("files", {})
    actual_files = set(file_hashes(root, {"standalone-manifest.json"}))
    if actual_files != set(expected_files):
        missing = sorted(set(expected_files) - actual_files)
        unexpected = sorted(actual_files - set(expected_files))
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected: " + ", ".join(unexpected))
        raise SproutError("Standalone app file set changed (" + "; ".join(detail) + ")")
    for relative, expected in expected_files.items():
        source = root / relative
        if not source.is_file():
            raise SproutError(f"Standalone app is missing {relative}")
        if sha256_file(str(source)) != expected:
            raise SproutError(f"Standalone app integrity check failed: {relative}")
    return manifest


def package_standalone(path: str = ".", registry: str | None = None) -> str:
    root = project_root(path)
    metadata = project_metadata(root)
    bundle_root = Path(build_standalone(root, registry=registry))
    output = Path(root) / "dist" / f"{metadata['name']}-{metadata['version']}.sproutapp"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(path for path in bundle_root.rglob("*") if path.is_file()):
            relative = source.relative_to(bundle_root).as_posix()
            info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if relative == str(metadata["name"]) else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, source.read_bytes())
    print(f"packaged standalone app {output}")
    return str(output)


def run_standalone(path: str, args: list[str] | None = None) -> int:
    root = Path(path).resolve()
    verify_standalone(str(root))
    return subprocess.call([sys.executable, str(root / "launcher.py"), *(args or [])])
