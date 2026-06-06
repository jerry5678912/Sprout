from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Any

from .bytecode import compile_file as compile_bytecode_file, disassemble
from .docsgen import generate_docs
from .model import SPROUT_VERSION, SproutError
from .package import dump_sprout_toml, read_toml_file, save_project_data
from .tooling import check_file, load_project


VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)
REGISTRY_SCHEMA = 1


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple[tuple[int, int | str], ...] | None
    raw: str

    @classmethod
    def parse(cls, value: str) -> Version:
        match = VERSION_RE.match(value)
        if not match:
            raise SproutError(f"Invalid semantic version '{value}'")
        prerelease = None
        if match.group(4):
            prerelease = tuple(
                (0, int(item)) if item.isdigit() else (1, item)
                for item in match.group(4).split(".")
            )
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease, value)

    def key(self) -> tuple[Any, ...]:
        release_rank = 1 if self.prerelease is None else 0
        return self.major, self.minor, self.patch, release_rank, self.prerelease or ()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.key() < other.key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.key() <= other.key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.key() > other.key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.key() >= other.key()


def version_matches(version: str, constraint: str | None) -> bool:
    if not constraint or constraint in {"*", "latest"}:
        return True
    current = Version.parse(version)
    constraint = constraint.strip()
    if constraint.startswith("^"):
        base = Version.parse(constraint[1:])
        if base.major > 0:
            upper = Version(base.major + 1, 0, 0, None, "")
        elif base.minor > 0:
            upper = Version(0, base.minor + 1, 0, None, "")
        else:
            upper = Version(0, 0, base.patch + 1, None, "")
        return base <= current < upper
    if constraint.startswith("~"):
        base = Version.parse(constraint[1:])
        return base <= current < Version(base.major, base.minor + 1, 0, None, "")
    if "," in constraint:
        return all(version_matches(version, part.strip()) for part in constraint.split(","))
    for operator in (">=", "<=", ">", "<"):
        if constraint.startswith(operator):
            target = Version.parse(constraint[len(operator):].strip())
            return {
                ">=": current >= target,
                "<=": current <= target,
                ">": current > target,
                "<": current < target,
            }[operator]
    return current.key() == Version.parse(constraint).key()


def project_root(path: str | None = None) -> str:
    root = os.path.abspath(path or os.getcwd())
    if os.path.isfile(root):
        root = os.path.dirname(root)
    if not os.path.exists(os.path.join(root, "sprout.toml")):
        raise SproutError(f"No sprout.toml found in '{root}'")
    return root


def project_metadata(root: str) -> dict[str, Any]:
    data = read_toml_file(os.path.join(root, "sprout.toml"))
    project = data.get("project", {})
    package = data.get("package", {})
    merged = {**project, **package}
    merged.setdefault("name", os.path.basename(root))
    merged.setdefault("version", "0.1.0")
    merged.setdefault("main", project.get("main", "src/main.sprout"))
    merged.setdefault("description", "")
    merged.setdefault("license", "")
    merged.setdefault("authors", project.get("authors", []))
    return merged


def validate_metadata(root: str, publishing: bool = False) -> tuple[dict[str, Any], list[str]]:
    metadata = project_metadata(root)
    errors: list[str] = []
    name = str(metadata.get("name", ""))
    if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", name):
        errors.append("package name must start with a letter and contain only letters, numbers, '_' or '-'")
    try:
        Version.parse(str(metadata.get("version", "")))
    except SproutError as exc:
        errors.append(str(exc))
    main = os.path.join(root, str(metadata.get("main", "src/main.sprout")))
    if not os.path.isfile(main):
        errors.append(f"main file does not exist: {metadata.get('main')}")
    if publishing:
        if not str(metadata.get("description", "")).strip():
            errors.append("package description is required for publishing")
        if not str(metadata.get("license", "")).strip():
            errors.append("package license is required for publishing")
        if not metadata.get("authors") and not metadata.get("author"):
            errors.append("package author/authors is required for publishing")
    return metadata, errors


def registry_location(value: str | None = None) -> str:
    return value or os.environ.get("SPROUT_REGISTRY") or os.path.expanduser("~/.sprout/registry")


def empty_registry() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "generated_by": f"Sprout {SPROUT_VERSION}", "packages": {}}


def read_registry(location: str | None = None) -> tuple[dict[str, Any], str]:
    target = registry_location(location)
    if target.startswith(("http://", "https://")):
        index_url = target if target.endswith(".json") else target.rstrip("/") + "/index.json"
        try:
            with urllib.request.urlopen(index_url, timeout=10) as response:
                registry_root = target.rsplit("/", 1)[0] if target.endswith(".json") else target.rstrip("/")
                return json.loads(response.read().decode("utf-8")), registry_root
        except Exception as exc:
            raise SproutError(f"Could not read registry {index_url}: {exc}") from exc
    root = os.path.abspath(os.path.expanduser(target))
    index_path = os.path.join(root, "index.json")
    if not os.path.exists(index_path):
        return empty_registry(), root
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            return json.load(fh), root
    except (OSError, json.JSONDecodeError) as exc:
        raise SproutError(f"Could not read registry index: {exc}") from exc


def write_registry(index: dict[str, Any], root: str) -> None:
    if root.startswith(("http://", "https://")):
        raise SproutError("Publishing to HTTP registries is not supported yet")
    os.makedirs(root, exist_ok=True)
    index["schema"] = REGISTRY_SCHEMA
    index["generated_by"] = f"Sprout {SPROUT_VERSION}"
    index_path = os.path.join(root, "index.json")
    temporary = index_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(temporary, index_path)


def available_versions(index: dict[str, Any], name: str) -> list[str]:
    package = index.get("packages", {}).get(name, {})
    versions = package.get("versions", {})
    return sorted(versions, key=Version.parse, reverse=True)


def select_version(index: dict[str, Any], name: str, constraint: str | None = None) -> tuple[str, dict[str, Any]]:
    package = index.get("packages", {}).get(name)
    if not package:
        raise SproutError(f"Package not found in registry: {name}")
    for version in available_versions(index, name):
        if version_matches(version, constraint):
            return version, package["versions"][version]
    raise SproutError(f"No version of {name} matches '{constraint or '*'}'")


def dependency_spec(value: Any) -> tuple[str | None, str]:
    if isinstance(value, dict):
        return (str(value["path"]) if "path" in value else None, str(value.get("version", "*")))
    if isinstance(value, str):
        if value.startswith(".") or "/" in value:
            return value, "*"
        return None, value
    return None, "*"


def resolve_dependencies(root: str, registry: str | None = None) -> dict[str, Any]:
    data = read_toml_file(os.path.join(root, "sprout.toml"))
    declared = data.get("dependencies", {})
    index, registry_root = read_registry(registry)
    resolved: dict[str, dict[str, Any]] = {}
    constraints: dict[str, list[str]] = {}

    def resolve(name: str, value: Any, owner_root: str) -> None:
        path_value, constraint = dependency_spec(value)
        constraints.setdefault(name, []).append(constraint)
        if name in resolved:
            version = resolved[name]["version"]
            if not all(version_matches(version, item) for item in constraints[name]):
                joined = ", ".join(constraints[name])
                raise SproutError(f"Dependency conflict for {name}: {joined}")
            return
        if path_value is not None:
            package_root = os.path.realpath(os.path.join(owner_root, path_value))
            config = os.path.join(package_root, "sprout.toml")
            if not os.path.isfile(config):
                raise SproutError(f"Local dependency {name} has no sprout.toml: {package_root}")
            metadata = project_metadata(package_root)
            version = str(metadata["version"])
            if not version_matches(version, constraint):
                raise SproutError(f"Local dependency {name} {version} does not match '{constraint}'")
            entry = {
                "name": name,
                "version": version,
                "source": "path",
                "path": package_root,
                "dependencies": read_toml_file(config).get("dependencies", {}),
            }
        else:
            version, registry_entry = select_version(index, name, constraint)
            entry = {
                "name": name,
                "version": version,
                "source": "registry",
                "registry": registry_root,
                "bundle": registry_entry.get("bundle"),
                "sha256": registry_entry.get("sha256"),
                "dependencies": registry_entry.get("dependencies", {}),
            }
        resolved[name] = entry
        nested_root = entry.get("path", owner_root)
        for child_name, child_value in entry["dependencies"].items():
            resolve(child_name, child_value, nested_root)

    for dep_name, dep_value in declared.items():
        resolve(dep_name, dep_value, root)
    return {
        "schema": 1,
        "project": project_metadata(root)["name"],
        "registry": registry_root,
        "dependencies": {name: resolved[name] for name in sorted(resolved)},
    }


def write_lock(root: str, lock: dict[str, Any]) -> str:
    path = os.path.join(root, "sprout.lock")
    portable = json.loads(json.dumps(lock))
    for entry in portable["dependencies"].values():
        if entry.get("source") == "path":
            entry["path"] = os.path.relpath(entry["path"], root).replace(os.sep, "/")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(portable, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def source_roots(root: str) -> list[str]:
    data = read_toml_file(os.path.join(root, "sprout.toml"))
    paths = data.get("paths", {})
    source_values = paths.get("source", ["src"])
    module_values = paths.get("modules", ["modules"])
    if isinstance(source_values, str):
        source_values = [source_values]
    if isinstance(module_values, str):
        module_values = [module_values]
    values = list(source_values) + list(module_values)
    return [os.path.join(root, str(value)) for value in values]


def iter_project_files(root: str) -> list[tuple[str, str]]:
    data = read_toml_file(os.path.join(root, "sprout.toml"))
    paths = data.get("paths", {})
    roots = source_roots(root)
    assets = paths.get("assets", ["assets"])
    if isinstance(assets, str):
        assets = [assets]
    for asset in assets:
        roots.append(os.path.join(root, str(asset)))
    files: list[tuple[str, str]] = []
    for path in ["sprout.toml", "README.md", "LICENSE"]:
        source = os.path.join(root, path)
        if os.path.isfile(source):
            files.append((source, path))
    docs = os.path.join(root, "docs")
    if os.path.isdir(docs):
        roots.append(docs)
    for source_root in roots:
        if not os.path.exists(source_root):
            continue
        if os.path.isfile(source_root):
            files.append((source_root, os.path.relpath(source_root, root).replace(os.sep, "/")))
            continue
        for current, dirs, names in os.walk(source_root):
            dirs[:] = sorted(name for name in dirs if not name.startswith("."))
            for name in sorted(names):
                source = os.path.join(current, name)
                files.append((source, os.path.relpath(source, root).replace(os.sep, "/")))
    return sorted(set(files), key=lambda pair: pair[1])


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_project(
    root: str,
    publishing: bool = False,
    run_quality: bool = False,
    registry: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata, errors = validate_metadata(root, publishing=publishing)
    project = load_project(root)
    if not project:
        errors.append("could not load project metadata")
    elif check_file(root) != 0:
        errors.append("project main file failed syntax validation")
    for source_root in source_roots(root):
        if not os.path.exists(source_root):
            continue
        for current, _dirs, names in os.walk(source_root):
            for name in names:
                if name.endswith(".sprout") and check_file(os.path.join(current, name)) != 0:
                    errors.append(f"source file failed validation: {os.path.relpath(os.path.join(current, name), root)}")
    lock = resolve_dependencies(root, registry=registry)
    if run_quality:
        tests_dir = os.path.join(root, "tests")
        if os.path.isdir(tests_dir):
            command = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), "sprout.py"), "test", tests_dir]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True)
            if result.returncode != 0:
                errors.append("package tests failed:\n" + (result.stdout + result.stderr).strip())
        docs_ok = os.path.isfile(os.path.join(root, "README.md")) or os.path.isdir(os.path.join(root, "docs"))
        if publishing and not docs_ok:
            errors.append("publishing requires README.md or docs/")
    if errors:
        raise SproutError("Project validation failed:\n- " + "\n- ".join(errors))
    return metadata, lock


def copy_tree_file(source: str, destination_root: str, relative: str) -> None:
    destination = os.path.join(destination_root, relative)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(source, destination)


def extract_bundle(bundle: str, destination: str) -> None:
    with zipfile.ZipFile(bundle) as archive:
        base = os.path.realpath(destination)
        for member in archive.infolist():
            target = os.path.realpath(os.path.join(destination, member.filename))
            if target != base and not target.startswith(base + os.sep):
                raise SproutError(f"Unsafe package archive path: {member.filename}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SproutError(f"Package archives cannot contain symbolic links: {member.filename}")
        archive.extractall(destination)


def verify_bundle(path: str, expected: str | None, name: str) -> None:
    if expected and sha256_file(path) != expected:
        raise SproutError(f"Checksum verification failed for package {name}")


def materialize_registry_bundle(entry: dict[str, Any], destination: str) -> None:
    registry = str(entry["registry"])
    bundle = str(entry.get("bundle", ""))
    if not bundle:
        raise SproutError(f"Registry package {entry['name']} has no bundle")
    if registry.startswith(("http://", "https://")):
        url = bundle if bundle.startswith(("http://", "https://")) else urllib.parse.urljoin(registry.rstrip("/") + "/", bundle)
        with tempfile.NamedTemporaryFile(suffix=".sproutpkg") as fh:
            try:
                urllib.request.urlretrieve(url, fh.name)
            except Exception as exc:
                raise SproutError(f"Could not download {entry['name']}: {exc}") from exc
            verify_bundle(fh.name, entry.get("sha256"), str(entry["name"]))
            extract_bundle(fh.name, destination)
    else:
        bundle_path = os.path.join(registry, bundle)
        verify_bundle(bundle_path, entry.get("sha256"), str(entry["name"]))
        extract_bundle(bundle_path, destination)


def build_project(path: str = ".", vm: bool = False, registry: str | None = None) -> str:
    root = project_root(path)
    metadata, lock = validate_project(root, registry=registry)
    write_lock(root, lock)
    build_root = os.path.join(root, "build", f"{metadata['name']}-{metadata['version']}")
    if os.path.exists(build_root):
        shutil.rmtree(build_root)
    os.makedirs(build_root)
    hashes: dict[str, str] = {}
    for source, relative in iter_project_files(root):
        copy_tree_file(source, build_root, relative)
        hashes[relative] = sha256_file(source)
    dependencies_root = os.path.join(build_root, "dependencies")
    for name, entry in lock["dependencies"].items():
        destination = os.path.join(dependencies_root, name)
        if entry["source"] == "path":
            for source, relative in iter_project_files(entry["path"]):
                copy_tree_file(source, destination, relative)
        else:
            materialize_registry_bundle(entry, destination)
    if vm:
        project = load_project(root)
        if not project:
            raise SproutError("Could not load project for VM build")
        code = compile_bytecode_file(project.main_path)
        with open(os.path.join(build_root, "main.bytecode.txt"), "w", encoding="utf-8") as fh:
            fh.write(disassemble(code))
            fh.write("\n")
    shutil.copy2(os.path.join(root, "sprout.lock"), os.path.join(build_root, "sprout.lock"))
    for current, dirs, names in os.walk(build_root):
        dirs.sort()
        for name in sorted(names):
            source = os.path.join(current, name)
            relative = os.path.relpath(source, build_root).replace(os.sep, "/")
            hashes[relative] = sha256_file(source)
    manifest = {
        "schema": 1,
        "name": metadata["name"],
        "version": metadata["version"],
        "description": metadata.get("description", ""),
        "authors": metadata.get("authors", metadata.get("author", [])),
        "license": metadata.get("license", ""),
        "main": metadata["main"],
        "documentation": "docs/API.md" if os.path.isfile(os.path.join(build_root, "docs", "API.md")) else None,
        "sprout": SPROUT_VERSION,
        "vm": vm,
        "dependencies": {name: entry["version"] for name, entry in lock["dependencies"].items()},
        "files": {name: hashes[name] for name in sorted(hashes)},
    }
    with open(os.path.join(build_root, "build-manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"built {build_root}")
    return build_root


def package_project(path: str = ".", vm: bool = False, registry: str | None = None) -> str:
    root = project_root(path)
    metadata = project_metadata(root)
    build_root = build_project(root, vm=vm, registry=registry)
    dist = os.path.join(root, "dist")
    os.makedirs(dist, exist_ok=True)
    bundle = os.path.join(dist, f"{metadata['name']}-{metadata['version']}.sproutpkg")
    if os.path.exists(bundle):
        os.unlink(bundle)
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for current, dirs, names in os.walk(build_root):
            dirs.sort()
            for name in sorted(names):
                source = os.path.join(current, name)
                relative = os.path.relpath(source, build_root).replace(os.sep, "/")
                info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(source, "rb") as fh:
                    archive.writestr(info, fh.read())
    print(f"packaged {bundle}")
    return bundle


def package_record(
    metadata: dict[str, Any],
    lock: dict[str, Any],
    bundle_relative: str,
    checksum: str,
) -> dict[str, Any]:
    return {
        "version": metadata["version"],
        "description": metadata.get("description", ""),
        "authors": metadata.get("authors", metadata.get("author", [])),
        "license": metadata.get("license", ""),
        "dependencies": {name: entry["version"] for name, entry in lock["dependencies"].items()},
        "bundle": bundle_relative,
        "sha256": checksum,
        "docs": metadata.get("docs", "docs/API.md"),
        "sprout": SPROUT_VERSION,
    }


def pkg_publish(path: str = ".", registry: str | None = None) -> int:
    root = project_root(path)
    metadata, lock = validate_project(root, publishing=True, run_quality=True, registry=registry)
    index, registry_root = read_registry(registry)
    if registry_root.startswith(("http://", "https://")):
        raise SproutError("Publishing requires a writable local registry path")
    package = index.setdefault("packages", {}).setdefault(metadata["name"], {"versions": {}})
    if metadata["version"] in package.setdefault("versions", {}):
        raise SproutError(f"{metadata['name']} {metadata['version']} is already published")
    docs_path = os.path.join(root, "docs", "API.md")
    if not os.path.isfile(docs_path):
        generate_docs(root)
    bundle = package_project(root, registry=registry)
    relative = posixpath.join("packages", metadata["name"], metadata["version"], os.path.basename(bundle))
    destination = os.path.join(registry_root, relative)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(bundle, destination)
    package["description"] = metadata.get("description", "")
    package["versions"][metadata["version"]] = package_record(metadata, lock, relative, sha256_file(bundle))
    package["latest"] = available_versions(index, metadata["name"])[0]
    write_registry(index, registry_root)
    print(f"published {metadata['name']} {metadata['version']} to {registry_root}")
    return 0


def pkg_search(query: str = "", registry: str | None = None) -> int:
    index, _root = read_registry(registry)
    query_lower = query.lower()
    found = 0
    for name, package in sorted(index.get("packages", {}).items()):
        description = str(package.get("description", ""))
        if query_lower and query_lower not in name.lower() and query_lower not in description.lower():
            continue
        latest = package.get("latest") or (available_versions(index, name)[0] if available_versions(index, name) else "")
        print(f"{name} {latest} - {description}".rstrip())
        found += 1
    if not found:
        print("no packages found")
    return 0


def pkg_registry_info(name: str, registry: str | None = None) -> int:
    index, _root = read_registry(registry)
    package = index.get("packages", {}).get(name)
    if not package:
        raise SproutError(f"Package not found in registry: {name}")
    print(json.dumps({"name": name, **package}, indent=2, sort_keys=True))
    return 0


def install_root(root: str) -> str:
    return os.path.join(root, ".sprout", "packages")


def pkg_install(spec: str, root: str | None = None, registry: str | None = None) -> int:
    project = project_root(root)
    if "@" in spec:
        name, constraint = spec.rsplit("@", 1)
    else:
        name, constraint = spec, "*"
    index, registry_root = read_registry(registry)
    version, entry = select_version(index, name, constraint)
    destination = os.path.join(install_root(project), name, version)
    if os.path.exists(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)
    materialize_registry_bundle(
        {
            "name": name,
            "registry": registry_root,
            "bundle": entry.get("bundle"),
            "sha256": entry.get("sha256"),
        },
        destination,
    )
    data = read_toml_file(os.path.join(project, "sprout.toml"))
    data.setdefault("dependencies", {})[name] = {
        "version": version,
        "constraint": constraint,
        "path": os.path.relpath(destination, project).replace(os.sep, "/"),
        "registry": True,
    }
    save_project_data(data, project)
    lock = resolve_dependencies(project, registry=registry)
    write_lock(project, lock)
    print(f"installed {name} {version}")
    return 0


def pkg_update(name_filter: str | None = None, root: str | None = None, registry: str | None = None) -> int:
    project = project_root(root)
    data = read_toml_file(os.path.join(project, "sprout.toml"))
    dependencies = data.get("dependencies", {})
    if name_filter and name_filter not in dependencies:
        raise SproutError(f"Package not found: {name_filter}")
    updated = 0
    for name, value in list(dependencies.items()):
        if name_filter and name != name_filter:
            continue
        if isinstance(value, dict) and str(value.get("path", "")).startswith(".sprout/packages"):
            constraint = str(value.get("constraint", "*"))
            index, _registry_root = read_registry(registry)
            version, _entry = select_version(index, name, constraint)
            if version != str(value.get("version", "")):
                pkg_install(f"{name}@{constraint}", project, registry)
                updated += 1
    if not updated:
        print(f"{name_filter or 'all packages'} are up to date")
    return 0


def pkg_tree(root: str | None = None, registry: str | None = None) -> int:
    project = project_root(root)
    lock = resolve_dependencies(project, registry=registry)
    write_lock(project, lock)
    metadata = project_metadata(project)
    print(f"{metadata['name']} {metadata['version']}")
    dependencies = lock["dependencies"]
    if not dependencies:
        print("  (no dependencies)")
        return 0
    for name, entry in dependencies.items():
        print(f"  {name} {entry['version']} [{entry['source']}]")
    return 0


def pkg_list_installed(root: str | None = None) -> int:
    project = project_root(root)
    data = read_toml_file(os.path.join(project, "sprout.toml"))
    found = 0
    for name, value in sorted(data.get("dependencies", {}).items()):
        if isinstance(value, dict) and "path" in value:
            path = os.path.join(project, str(value["path"]))
            status = "installed" if os.path.exists(path) else "missing"
            print(f"{name} {value.get('version', '')} {status}")
            found += 1
    if not found:
        print("no installed packages")
    return 0


def pkg_docs(name: str, root: str | None = None, registry: str | None = None) -> int:
    candidate = os.path.abspath(root or os.getcwd())
    if os.path.isfile(os.path.join(candidate, "sprout.toml")):
        data = read_toml_file(os.path.join(candidate, "sprout.toml"))
        dependency = data.get("dependencies", {}).get(name)
        if dependency and isinstance(dependency, dict) and "path" in dependency:
            package_root = os.path.join(candidate, str(dependency["path"]))
            if os.path.exists(os.path.join(package_root, "sprout.toml")):
                return generate_docs(package_root, html_mode=True)
            docs = os.path.join(package_root, "docs", "API.md")
            if os.path.isfile(docs):
                print(docs)
                return 0
    index, registry_root = read_registry(registry)
    version, entry = select_version(index, name)
    print(json.dumps({"name": name, "version": version, "docs": entry.get("docs"), "registry": registry_root}, indent=2))
    return 0


def release_project(path: str = ".", registry: str | None = None, publish: bool = False) -> int:
    root = project_root(path)
    metadata, lock = validate_project(root, publishing=True, run_quality=True, registry=registry)
    generate_docs(root, html_mode=True)
    bundle = package_project(root, registry=registry)
    release = {
        "name": metadata["name"],
        "version": metadata["version"],
        "description": metadata.get("description", ""),
        "license": metadata.get("license", ""),
        "bundle": os.path.relpath(bundle, root),
        "documentation": "docs/API.html",
        "dependencies": {name: entry["version"] for name, entry in lock["dependencies"].items()},
        "sprout": SPROUT_VERSION,
    }
    with open(os.path.join(root, "dist", "release.json"), "w", encoding="utf-8") as fh:
        json.dump(release, fh, indent=2, sort_keys=True)
        fh.write("\n")
    if publish:
        return pkg_publish(root, registry)
    print(f"release ready {metadata['name']} {metadata['version']}")
    return 0
