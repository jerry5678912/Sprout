from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .model import SPROUT_VERSION, SproutError


LANGUAGE_FILES = [
    "sprout.py",
    "install.py",
    "pyproject.toml",
    "sprout.toml",
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "ROADMAP.md",
]
LANGUAGE_DIRECTORIES = ["sprout_core", "docs", "editor", "examples", "tools"]
RELEASE_DIRECTORIES = LANGUAGE_DIRECTORIES + ["tests"]
IGNORED_PARTS = {
    ".git",
    ".idea",
    ".sprout",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "hello_sprout",
}


def language_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_install_prefix() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Sprout"
    return Path.home() / ".local"


def installation_paths(prefix: str | os.PathLike[str] | None = None) -> dict[str, Path]:
    base = Path(prefix).expanduser().resolve() if prefix else default_install_prefix().resolve()
    if os.name == "nt":
        runtime = base / "lib" / "sprout"
        launcher = base / "bin" / "sprout.cmd"
    else:
        runtime = base / "lib" / "sprout"
        launcher = base / "bin" / "sprout"
    manifest = base / "share" / "sprout" / "install.json"
    return {"prefix": base, "runtime": runtime, "launcher": launcher, "manifest": manifest}


def should_include(path: Path) -> bool:
    return not any(part in IGNORED_PARTS or part.endswith(".pyc") for part in path.parts)


def iter_language_files(root: Path | None = None) -> list[tuple[Path, Path]]:
    source_root = root or language_root()
    files: list[tuple[Path, Path]] = []
    for name in LANGUAGE_FILES:
        source = source_root / name
        if source.is_file():
            files.append((source, Path(name)))
    for name in LANGUAGE_DIRECTORIES:
        source_dir = source_root / name
        if not source_dir.is_dir():
            continue
        for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = source.relative_to(source_root)
            if should_include(relative):
                files.append((source, relative))
    return sorted(files, key=lambda pair: pair[1].as_posix())


def iter_release_files(root: Path | None = None) -> list[tuple[Path, Path]]:
    source_root = root or language_root()
    files = iter_language_files(source_root)
    for name in RELEASE_DIRECTORIES:
        if name in LANGUAGE_DIRECTORIES:
            continue
        source_dir = source_root / name
        for source in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative = source.relative_to(source_root)
            if should_include(relative):
                files.append((source, relative))
    return sorted(set(files), key=lambda pair: pair[1].as_posix())


def write_launcher(path: Path, runtime: Path, python_executable: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    python = python_executable or sys.executable
    if path.suffix == ".cmd":
        text = (
            "@echo off\r\n"
            f'set "PYTHONPATH={runtime};%PYTHONPATH%"\r\n'
            f'"{python}" -m sprout_core %*\r\n'
        )
    else:
        text = (
            f"#!{python}\n"
            "from pathlib import Path\n"
            "import sys\n"
            f"root = Path({str(runtime)!r})\n"
            "sys.path.insert(0, str(root))\n"
            "from sprout_core.cli import main\n"
            "raise SystemExit(main([str(root / 'sprout.py'), *sys.argv[1:]]))\n"
        )
    path.write_text(text, encoding="utf-8")
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_language(
    prefix: str | os.PathLike[str] | None = None,
    force: bool = False,
    source_root: str | os.PathLike[str] | None = None,
) -> dict[str, str]:
    paths = installation_paths(prefix)
    runtime = paths["runtime"]
    manifest = paths["manifest"]
    if runtime.exists() and not force:
        raise SproutError(f"Sprout is already installed at {runtime}. Use --force to replace it.")
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    root = Path(source_root).resolve() if source_root else language_root()
    copied: list[str] = []
    for source, relative in iter_language_files(root):
        destination = runtime / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(relative.as_posix())
    write_launcher(paths["launcher"], runtime)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1,
        "version": SPROUT_VERSION,
        "runtime": str(runtime),
        "launcher": str(paths["launcher"]),
        "files": copied,
    }
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"installed Sprout {SPROUT_VERSION} at {runtime}")
    print(f"launcher: {paths['launcher']}")
    if str(paths["launcher"].parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"add {paths['launcher'].parent} to PATH to run: sprout version")
    return {name: str(value) for name, value in paths.items()}


def uninstall_language(prefix: str | os.PathLike[str] | None = None) -> int:
    paths = installation_paths(prefix)
    manifest = paths["manifest"]
    if not manifest.exists():
        raise SproutError(f"No Sprout installation manifest found at {manifest}")
    if paths["runtime"].exists():
        shutil.rmtree(paths["runtime"])
    if paths["launcher"].exists():
        paths["launcher"].unlink()
    manifest.unlink()
    for directory in [manifest.parent, paths["launcher"].parent]:
        try:
            directory.rmdir()
        except OSError:
            pass
    print(f"uninstalled Sprout from {paths['prefix']}")
    return 0


def deterministic_zip(
    output: Path,
    files: list[tuple[Path, str]],
    executable_names: set[str] | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    executable_names = executable_names or set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, archive_name in sorted(files, key=lambda pair: pair[1]):
            info = zipfile.ZipInfo(archive_name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if archive_name in executable_names else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, source.read_bytes())
    return output


def package_language(output_dir: str | os.PathLike[str] | None = None) -> str:
    root = language_root()
    destination = Path(output_dir).resolve() if output_dir else root / "dist"
    archive_root = f"sprout-{SPROUT_VERSION}"
    files = [
        (source, f"{archive_root}/{relative.as_posix()}")
        for source, relative in iter_release_files(root)
    ]
    output = destination / f"sprout-{SPROUT_VERSION}.zip"
    deterministic_zip(output, files, {f"{archive_root}/sprout.py"})
    print(f"packaged language {output}")
    return str(output)


def extension_metadata(extension_root: Path) -> dict[str, Any]:
    package_path = extension_root / "package.json"
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SproutError(f"Could not read VS Code extension metadata: {exc}") from exc
    if data.get("version") != SPROUT_VERSION:
        raise SproutError(
            f"VS Code extension version {data.get('version')} does not match Sprout {SPROUT_VERSION}"
        )
    return data


def vsix_manifest(metadata: dict[str, Any]) -> str:
    publisher = escape(str(metadata["publisher"]))
    name = escape(str(metadata["name"]))
    display_name = escape(str(metadata.get("displayName", name)))
    description = escape(str(metadata.get("description", "")))
    version = escape(str(metadata["version"]))
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">\n'
        "  <Metadata>\n"
        f'    <Identity Language="en-US" Id="{name}" Version="{version}" Publisher="{publisher}" />\n'
        f"    <DisplayName>{display_name}</DisplayName>\n"
        f"    <Description xml:space=\"preserve\">{description}</Description>\n"
        "    <Tags>sprout,programming language</Tags>\n"
        "    <Categories>Programming Languages</Categories>\n"
        "    <Properties>\n"
        f'      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(str(metadata["engines"]["vscode"]))}" />\n'
        '      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />\n'
        '      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />\n'
        '      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />\n'
        '      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="sprout" />\n'
        "    </Properties>\n"
        "  </Metadata>\n"
        "  <Installation>\n"
        '    <InstallationTarget Id="Microsoft.VisualStudio.Code" Version="[1.80.0,)" />\n'
        "  </Installation>\n"
        "  <Dependencies />\n"
        "  <Assets>\n"
        '    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />\n'
        '    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true" />\n'
        "  </Assets>\n"
        "</PackageManifest>\n"
    )


def package_vscode_extension(output_dir: str | os.PathLike[str] | None = None) -> str:
    root = language_root()
    extension_root = root / "editor" / "vscode-sprout"
    metadata = extension_metadata(extension_root)
    destination = Path(output_dir).resolve() if output_dir else root / "dist"
    output = destination / f"{metadata['name']}-{SPROUT_VERSION}.vsix"
    generated_dir = destination / ".vscode-package"
    generated_dir.mkdir(parents=True, exist_ok=True)
    content_types = generated_dir / "[Content_Types].xml"
    content_types.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="json" ContentType="application/json" />\n'
        '  <Default Extension="code-snippets" ContentType="application/json" />\n'
        '  <Default Extension="js" ContentType="application/javascript" />\n'
        '  <Default Extension="md" ContentType="text/markdown" />\n'
        '  <Default Extension="vsixmanifest" ContentType="text/xml" />\n'
        "</Types>\n",
        encoding="utf-8",
    )
    manifest = generated_dir / "extension.vsixmanifest"
    manifest.write_text(vsix_manifest(metadata), encoding="utf-8")
    files: list[tuple[Path, str]] = [
        (content_types, "[Content_Types].xml"),
        (manifest, "extension.vsixmanifest"),
    ]
    for source in sorted(path for path in extension_root.rglob("*") if path.is_file()):
        if should_include(source.relative_to(extension_root)):
            files.append((source, f"extension/{source.relative_to(extension_root).as_posix()}"))
    files.append((root / "sprout.py", "extension/sprout.py"))
    files.append((root / "tools" / "sprout_lsp.py", "extension/tools/sprout_lsp.py"))
    files.append((root / "tools" / "sprout_dap.py", "extension/tools/sprout_dap.py"))
    for source in sorted(path for path in (root / "sprout_core").rglob("*") if path.is_file()):
        relative = source.relative_to(root)
        if should_include(relative):
            files.append((source, f"extension/{relative.as_posix()}"))
    deterministic_zip(output, files)
    shutil.rmtree(generated_dir)
    print(f"packaged VS Code extension {output}")
    return str(output)


def verify_release_versions() -> list[str]:
    root = language_root()
    errors: list[str] = []
    project = (root / "sprout.toml").read_text(encoding="utf-8")
    if f'version = "{SPROUT_VERSION}"' not in project:
        errors.append("sprout.toml version does not match runtime version")
    if 'license = "Apache-2.0"' not in project:
        errors.append("sprout.toml license must be Apache-2.0")
    packaging = (root / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{SPROUT_VERSION}"' not in packaging:
        errors.append("pyproject.toml version does not match runtime version")
    if 'license = "Apache-2.0"' not in packaging:
        errors.append("pyproject.toml license must be Apache-2.0")
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text:
        errors.append("LICENSE is not the canonical Apache License 2.0 text")
    if not (root / "NOTICE").is_file():
        errors.append("NOTICE is missing")
    if not (root / "GOVERNANCE.md").is_file():
        errors.append("GOVERNANCE.md is missing")
    try:
        extension_metadata(root / "editor" / "vscode-sprout")
    except SproutError as exc:
        errors.append(str(exc))
    return errors
