from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import io
import json
import os
import re
import secrets
import shutil
import threading
from typing import Any

from .model import SPROUT_VERSION, SproutError


TOKEN_FILE = "tokens.json"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_tokens(root: str) -> dict[str, Any]:
    path = os.path.join(root, TOKEN_FILE)
    if not os.path.isfile(path):
        return {"schema": 1, "tokens": {}}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_tokens(root: str, data: dict[str, Any]) -> None:
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, TOKEN_FILE)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def create_registry_token(root: str, name: str, packages: list[str] | None = None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise SproutError("Token name may contain only letters, numbers, '.', '_' and '-'")
    data = load_tokens(root)
    if name in data.setdefault("tokens", {}):
        raise SproutError(f"Registry token '{name}' already exists")
    allowed = sorted(set(packages or ["*"]))
    for package in allowed:
        if package != "*" and not PACKAGE_RE.fullmatch(package):
            raise SproutError(f"Invalid package permission '{package}'")
    token = "sprout_" + secrets.token_urlsafe(32)
    data["tokens"][name] = {
        "sha256": token_digest(token),
        "scopes": ["publish"],
        "packages": allowed,
    }
    save_tokens(root, data)
    return token


def revoke_registry_token(root: str, name: str) -> None:
    data = load_tokens(root)
    if name not in data.get("tokens", {}):
        raise SproutError(f"Registry token '{name}' does not exist")
    del data["tokens"][name]
    save_tokens(root, data)


def list_registry_tokens(root: str) -> list[dict[str, Any]]:
    data = load_tokens(root)
    return [
        {
            "name": name,
            "scopes": record.get("scopes", []),
            "packages": record.get("packages", []),
        }
        for name, record in sorted(data.get("tokens", {}).items())
    ]


class RegistryStore:
    def __init__(self, root: str):
        self.root = os.path.realpath(os.path.abspath(root))
        self.lock = threading.Lock()
        os.makedirs(self.root, exist_ok=True)

    @property
    def index_path(self) -> str:
        return os.path.join(self.root, "index.json")

    def read_index(self) -> dict[str, Any]:
        if not os.path.isfile(self.index_path):
            return {"schema": 1, "generated_by": f"Sprout {SPROUT_VERSION}", "packages": {}}
        with open(self.index_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def write_index(self, index: dict[str, Any]) -> None:
        temporary = self.index_path + ".tmp"
        index["schema"] = 1
        index["generated_by"] = f"Sprout {SPROUT_VERSION}"
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(temporary, self.index_path)

    def authenticate(self, authorization: str, package: str) -> bool:
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            return False
        supplied = token_digest(authorization[len(prefix):].strip())
        for record in load_tokens(self.root).get("tokens", {}).values():
            if not hmac.compare_digest(str(record.get("sha256", "")), supplied):
                continue
            if "publish" not in record.get("scopes", []):
                return False
            allowed = record.get("packages", [])
            return "*" in allowed or package in allowed
        return False

    def publish(self, record: dict[str, Any], bundle: bytes) -> dict[str, Any]:
        name = str(record.get("name", ""))
        version = str(record.get("version", ""))
        if not PACKAGE_RE.fullmatch(name):
            raise SproutError("Invalid package name")
        if not VERSION_RE.fullmatch(version):
            raise SproutError("Invalid semantic version")
        expected = str(record.get("sha256", ""))
        actual = hashlib.sha256(bundle).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise SproutError("Uploaded bundle checksum does not match metadata")
        self.validate_bundle(bundle, name, version)

        with self.lock:
            index = self.read_index()
            package = index.setdefault("packages", {}).setdefault(name, {"versions": {}})
            versions = package.setdefault("versions", {})
            if version in versions:
                raise FileExistsError(f"{name} {version} is already published")
            relative = f"packages/{name}/{version}/{name}-{version}.sproutpkg"
            destination = os.path.join(self.root, *relative.split("/"))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            temporary = destination + ".tmp"
            with open(temporary, "wb") as fh:
                fh.write(bundle)
            os.replace(temporary, destination)
            versions[version] = {
                key: value for key, value in record.items()
                if key not in {"name"} and key in {
                    "version", "description", "authors", "license", "dependencies",
                    "sha256", "docs", "sprout",
                }
            }
            versions[version]["bundle"] = relative
            package["description"] = str(record.get("description", ""))
            from .ecosystem import available_versions
            package["latest"] = available_versions(index, name)[0]
            self.write_index(index)
        return {"name": name, "version": version, "sha256": actual, "bundle": relative}

    def validate_bundle(self, bundle: bytes, name: str, version: str) -> None:
        import stat
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                members = archive.infolist()
                if len(members) > MAX_ARCHIVE_FILES:
                    raise SproutError("Package archive contains too many files")
                if sum(member.file_size for member in members) > MAX_EXPANDED_BYTES:
                    raise SproutError("Package archive expands beyond the registry limit")
                names = {member.filename for member in members}
                if "build-manifest.json" not in names:
                    raise SproutError("Package archive has no build-manifest.json")
                for member in members:
                    normalized = os.path.normpath(member.filename.replace("\\", "/"))
                    if normalized.startswith("../") or normalized == ".." or os.path.isabs(normalized):
                        raise SproutError(f"Unsafe package archive path: {member.filename}")
                    if stat.S_ISLNK(member.external_attr >> 16):
                        raise SproutError(f"Package archives cannot contain symbolic links: {member.filename}")
                manifest = json.loads(archive.read("build-manifest.json").decode("utf-8"))
                if manifest.get("name") != name or manifest.get("version") != version:
                    raise SproutError("Package manifest name/version does not match publish metadata")
                for path, expected in manifest.get("files", {}).items():
                    if path not in names:
                        raise SproutError(f"Package manifest references missing file: {path}")
                    actual = hashlib.sha256(archive.read(path)).hexdigest()
                    if not hmac.compare_digest(str(expected), actual):
                        raise SproutError(f"Package file checksum failed: {path}")
        except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise SproutError(f"Invalid .sproutpkg archive: {exc}") from None


class RegistryRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "SproutRegistry/0.3"

    @property
    def store(self) -> RegistryStore:
        return self.server.store  # type: ignore[attr-defined]

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in {"/", "/health"}:
            self.send_json(200, {"ok": True, "service": "sprout-registry"})
            return
        if path == "/index.json":
            self.send_json(200, self.store.read_index())
            return
        if path.startswith("/packages/"):
            relative = path.lstrip("/")
            target = os.path.realpath(os.path.join(self.store.root, *relative.split("/")))
            packages_root = os.path.join(self.store.root, "packages")
            if not target.startswith(packages_root + os.sep) or not os.path.isfile(target):
                self.send_json(404, {"error": "package bundle not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(os.path.getsize(target)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with open(target, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile)
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/v1/publish":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self.send_json(413, {"error": "invalid or oversized upload"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            record = payload["package"]
            name = str(record.get("name", ""))
            if not self.store.authenticate(self.headers.get("Authorization", ""), name):
                self.send_json(401, {"error": "valid publish token required"})
                return
            bundle = base64.b64decode(payload["bundle"], validate=True)
            result = self.store.publish(record, bundle)
            self.send_json(201, result)
        except FileExistsError as exc:
            self.send_json(409, {"error": str(exc)})
        except (KeyError, ValueError, json.JSONDecodeError, SproutError) as exc:
            self.send_json(400, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[registry] {self.address_string()} {format % args}", file=os.sys.stderr)


class RegistryHTTPServer(http.server.ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], root: str):
        super().__init__(address, RegistryRequestHandler)
        self.store = RegistryStore(root)


def serve_registry(root: str, host: str = "127.0.0.1", port: int = 8787) -> int:
    server = RegistryHTTPServer((host, port), root)
    print(f"Sprout registry serving {root} at http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
