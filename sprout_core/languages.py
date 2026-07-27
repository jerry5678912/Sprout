from __future__ import annotations

from dataclasses import dataclass
import json
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unicodedata
from typing import Any

from .model import SPROUT_VERSION, SproutError


LANGUAGE_PACK_SCHEMA_VERSION = 1
LANGUAGE_CATALOG_VERSION = 1
LANGUAGE_PACK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "language_packs")
BOOTSTRAP_RE = re.compile(r'^\s*language\s+"([a-z0-9][a-z0-9._-]*)"\s*(?:#.*)?$')


@dataclass(frozen=True)
class LanguageConcept:
    id: str
    category: str
    canonical: str
    token_kind: str | None
    english: str
    context: str


@dataclass(frozen=True)
class LanguageWord:
    concept_id: str
    canonical: str
    token_kind: str | None
    source: str
    preferred: bool


@dataclass(frozen=True)
class BootstrapSelection:
    source: str
    pack_id: str | None
    declaration_line: int | None


def _keyword(
    concept_id: str,
    canonical: str,
    context: str,
    *,
    category: str = "syntax",
    token_kind: str | None = None,
) -> LanguageConcept:
    return LanguageConcept(
        concept_id,
        category,
        canonical,
        token_kind or canonical.upper(),
        canonical,
        context,
    )


KEYWORD_CONCEPTS = (
    _keyword("constant.true", "True", "Boolean true literal.", category="constant"),
    _keyword("operator.and", "and", "Logical conjunction.", category="operator"),
    _keyword("syntax.alias", "as", "Import and binding alias."),
    _keyword("syntax.async", "async", "Asynchronous declaration modifier."),
    _keyword("syntax.await", "await", "Await an asynchronous value."),
    _keyword("syntax.break", "break", "Exit the nearest loop."),
    _keyword("syntax.bloom", "bloom", "Open a garden-style block."),
    _keyword("syntax.case", "case", "Pattern-match case."),
    _keyword("syntax.catch", "catch", "Exception handler."),
    _keyword("syntax.class", "class", "Class declaration."),
    _keyword("syntax.continue", "continue", "Continue the nearest loop."),
    _keyword("syntax.function", "def", "Named function or method declaration."),
    _keyword("syntax.each", "each", "Garden-style item iteration."),
    _keyword("syntax.elif", "elif", "Conditional alternative branch."),
    _keyword("syntax.else", "else", "Final conditional branch."),
    _keyword("syntax.end", "end", "Close a garden-style block."),
    _keyword("syntax.enum", "enum", "Enumeration declaration."),
    _keyword("syntax.extends", "extends", "Class inheritance clause."),
    _keyword("constant.false", "false", "Boolean false literal.", category="constant"),
    _keyword("syntax.function-value", "fn", "Anonymous function expression."),
    _keyword("syntax.for", "for", "Item iteration loop."),
    _keyword("syntax.if", "if", "Conditional branch."),
    _keyword("syntax.implements", "implements", "Interface implementation clause."),
    _keyword("syntax.import", "import", "Sprout module import."),
    _keyword("syntax.import-python", "importpython", "Python module import."),
    _keyword("operator.in", "in", "Membership or iteration relation.", category="operator"),
    _keyword("syntax.interface", "interface", "Interface declaration."),
    _keyword("operator.is", "is", "Type or identity relation.", category="operator"),
    _keyword("syntax.let", "let", "Explicit variable declaration."),
    _keyword("syntax.match", "match", "Pattern matching expression."),
    _keyword("constant.nil", "nil", "Absence of a value.", category="constant"),
    _keyword("operator.not", "not", "Logical negation.", category="operator"),
    _keyword("operator.or", "or", "Logical disjunction.", category="operator"),
    _keyword("syntax.pluck", "pluck", "Garden-style return statement."),
    _keyword("syntax.raise", "raise", "Raise a value as an error."),
    _keyword("syntax.return", "return", "Return from a function."),
    _keyword("syntax.say", "say", "Print values to standard output."),
    _keyword("syntax.seed-function", "seedfn", "Generator function declaration."),
    _keyword("syntax.sprout-loop", "sprout", "Garden-style counted loop."),
    _keyword("syntax.super", "super", "Access a superclass implementation."),
    _keyword("syntax.test", "test", "Test declaration."),
    _keyword("syntax.task-group", "taskgroup", "Structured concurrency block."),
    _keyword("syntax.type-alias", "type", "Type alias declaration.", token_kind="IDENT"),
    _keyword("syntax.try", "try", "Protected error-handling block."),
    _keyword("syntax.whirl", "whirl", "Garden-style conditional loop."),
    _keyword("syntax.while", "while", "Conditional loop."),
    _keyword("syntax.yield", "yield", "Yield a generator value."),
)


METHOD_NAMES = (
    "append",
    "collect",
    "contains",
    "get",
    "has",
    "items",
    "join",
    "keys",
    "len",
    "lower",
    "next",
    "pop",
    "set",
    "split",
    "strip",
    "upper",
    "values",
)

BUILTIN_NAMES = tuple(
    """
    abs acos appendfile array asin ask atan atan2 avg basename between bundle
    cancel_token ceil chant chars choose chunks clamp clear compact concat
    contains copy cos countby cwd degrees delkey dice dict dirname dist drop
    endswith ensure enumerate exists exp expect extname fail fill first flatten
    floor force frompairs functions get grow harvest has http_get http_get_async
    http_post http_post_async http_request http_request_async http_server hypot
    indexof insert int interpolate is_array is_bool is_class is_dict is_empty
    is_even is_function is_instance is_nil is_number is_odd is_string isdir
    isfile items join joinpath json_parse json_stringify keys kinetic_energy last
    len lerp lines listdir log log10 lower ltrim mat_mul max median merge methods
    min mirror mkdir now num omit padleft padright pick plant pow pressure prune
    push py_available py_import queue_open radians rand randint range readfile
    readfile_async readjson remove repeat replace rest reverse round rtrim sample
    say seed shout shuffle sign sin sleep sleep_async slice sort sparkle sprinkle
    sqlite_begin sqlite_close sqlite_commit sqlite_exec sqlite_open sqlite_query
    sqlite_rollback sqrt startswith str stream_open substr sum take tan
    task_after task_spawn task_wait_all title trim type unique unit_convert upper
    values vec_add vec_dot vec_magnitude vec_normalize vec_sub weave whisper
    words wrap writefile writefile_async writejson zipbud
    """.split()
)


CATALOG: dict[str, LanguageConcept] = {concept.id: concept for concept in KEYWORD_CONCEPTS}
for _builtin_name in BUILTIN_NAMES:
    _concept = LanguageConcept(
        f"builtin.{_builtin_name}",
        "builtin",
        _builtin_name,
        None,
        _builtin_name,
        f"Built-in function '{_builtin_name}'.",
    )
    CATALOG[_concept.id] = _concept
for _method_name in METHOD_NAMES:
    _concept = LanguageConcept(
        f"method.{_method_name}",
        "method",
        _method_name,
        None,
        _method_name,
        f"Built-in method '{_method_name}'.",
    )
    CATALOG[_concept.id] = _concept


class LanguagePack:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.id = str(data["id"])
        self.locale = str(data["locale"])
        self.entries = dict(data.get("entries", {}))
        self._words: dict[str, LanguageWord] = {}
        self._words_by_category: dict[str, dict[str, LanguageWord]] = {}
        self._preferred: dict[str, str] = {}
        for concept_id, concept in CATALOG.items():
            entry = self.entries.get(concept_id, {})
            preferred = str(entry.get("preferred") or concept.english)
            self._preferred[concept_id] = preferred
            spellings = [preferred, *[str(alias) for alias in entry.get("aliases", [])]]
            if bool(data.get("englishFallback", True)) and concept.english not in spellings:
                spellings.append(concept.english)
            for index, spelling in enumerate(spellings):
                word = LanguageWord(
                    concept_id,
                    concept.canonical,
                    concept.token_kind,
                    spelling,
                    index == 0,
                )
                self._words_by_category.setdefault(concept.category, {})[spelling] = word
                self._words.setdefault(spelling, word)

    def word(self, spelling: str) -> LanguageWord | None:
        return self._words.get(spelling)

    def keyword(self, spelling: str) -> LanguageWord | None:
        for category in ("syntax", "constant", "operator"):
            word = self._words_by_category.get(category, {}).get(spelling)
            if word and word.token_kind:
                return word
        return None

    def preferred(self, concept_id: str) -> str:
        return self._preferred.get(concept_id, CATALOG[concept_id].english)

    def aliases_for_category(self, category: str) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for spelling, word in self._words_by_category.get(category, {}).items():
            if spelling != word.canonical:
                aliases[spelling] = word.canonical
        return aliases

    def coverage(self) -> dict[str, int]:
        if self.id == "english-pack":
            return {"reviewed": len(CATALOG), "generated": 0, "fallback": 0}
        counts = {"reviewed": 0, "generated": 0, "fallback": 0}
        for concept_id in CATALOG:
            status = str(self.entries.get(concept_id, {}).get("status", "fallback"))
            counts[status if status in counts else "fallback"] += 1
        return counts

    def diagnostic(
        self,
        code: str | None,
        fallback: str,
        values: dict[str, Any] | None = None,
    ) -> str:
        template = self.data.get("diagnostics", {}).get(code or "")
        if not isinstance(template, str):
            return fallback
        fields = set(re.findall(r"\{([^{}]+)\}", template))
        available = values or {}
        if not fields.issubset(available):
            return fallback
        return template.format(**available)


def builtin_pack_path(pack_id: str) -> str:
    return os.path.join(LANGUAGE_PACK_DIR, f"{pack_id}.json")


def language_pack_search_paths() -> list[str]:
    configured = os.environ.get("SPROUT_LANGUAGE_PACK_PATH", "")
    paths = [item for item in configured.split(os.pathsep) if item]
    paths.append(os.path.expanduser("~/.sprout/languages"))
    paths.append(LANGUAGE_PACK_DIR)
    return paths


def resolve_language_pack_path(pack_id_or_path: str) -> str | None:
    if os.path.isfile(pack_id_or_path):
        return os.path.realpath(pack_id_or_path)
    safe_name = f"{pack_id_or_path}.json"
    for root in language_pack_search_paths():
        candidate = os.path.join(root, safe_name)
        if os.path.isfile(candidate):
            return os.path.realpath(candidate)
    return None


_PACK_CACHE: dict[str, LanguagePack] = {}


def load_language_pack(pack_id_or_path: str | None) -> LanguagePack:
    requested = pack_id_or_path or "english-pack"
    path = resolve_language_pack_path(requested)
    if not path:
        raise SproutError(f"Unknown language pack '{requested}'")
    stamp = f"{path}:{os.path.getmtime(path)}:{os.path.getsize(path)}"
    if stamp in _PACK_CACHE:
        return _PACK_CACHE[stamp]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SproutError(f"Invalid language pack '{requested}': {exc}") from None
    errors = validate_language_pack_data(data)
    if errors:
        raise SproutError(f"Invalid language pack '{requested}': {'; '.join(errors)}")
    pack = LanguagePack(data)
    _PACK_CACHE[stamp] = pack
    return pack


def validate_language_pack_data(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be an object"]
    required = {
        "schemaVersion": int,
        "catalogVersion": int,
        "id": str,
        "version": str,
        "locale": str,
        "sprout": str,
        "englishFallback": bool,
        "entries": dict,
    }
    for name, expected_type in required.items():
        if not isinstance(data.get(name), expected_type):
            errors.append(f"{name} must be {expected_type.__name__}")
    if errors:
        return errors
    if data["schemaVersion"] != LANGUAGE_PACK_SCHEMA_VERSION:
        errors.append(f"unsupported schema version {data['schemaVersion']}")
    if data["catalogVersion"] > LANGUAGE_CATALOG_VERSION:
        errors.append(f"unsupported catalog version {data['catalogVersion']}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", data["id"]):
        errors.append("id must be a lowercase package id")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", data["version"]):
        errors.append("version must use semantic versioning")
    if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", data["locale"]):
        errors.append("locale must be a non-empty language tag")
    if not _supports_current_sprout(data["sprout"]):
        errors.append(f"unsupported Sprout constraint {data['sprout']!r}")
    if not data["englishFallback"]:
        missing = sorted(set(CATALOG) - set(data["entries"]))
        if missing:
            errors.append(
                f"pack without English fallback is missing {len(missing)} catalog entries"
            )

    seen: dict[tuple[str, str], str] = {}
    normalized_seen: dict[tuple[str, str], str] = {}
    for concept_id, entry in data["entries"].items():
        if concept_id not in CATALOG:
            errors.append(f"unknown concept {concept_id!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"entry {concept_id!r} must be an object")
            continue
        preferred = entry.get("preferred")
        aliases = entry.get("aliases", [])
        status = entry.get("status")
        if not isinstance(preferred, str) or not preferred:
            errors.append(f"entry {concept_id!r} needs a preferred spelling")
            continue
        if not isinstance(aliases, list) or not all(isinstance(item, str) and item for item in aliases):
            errors.append(f"entry {concept_id!r} aliases must be non-empty strings")
            continue
        if status not in {"reviewed", "generated", "fallback"}:
            errors.append(f"entry {concept_id!r} has invalid translation status")
        domain = "member" if CATALOG[concept_id].category == "method" else "lexical"
        entry_spellings: set[str] = set()
        for spelling in [preferred, *aliases]:
            if spelling in entry_spellings:
                errors.append(f"entry {concept_id!r} repeats spelling {spelling!r}")
                continue
            entry_spellings.add(spelling)
            key = (domain, spelling)
            previous = seen.get(key)
            if (
                previous
                and previous != concept_id
                and CATALOG[previous].canonical != CATALOG[concept_id].canonical
            ):
                errors.append(
                    f"duplicate spelling {spelling!r} for {previous!r} and {concept_id!r}"
                )
            seen[key] = concept_id
            normalized = unicodedata.normalize("NFKC", spelling).casefold()
            normalized_key = (domain, normalized)
            normalized_previous = normalized_seen.get(normalized_key)
            if normalized_previous and normalized_previous != spelling:
                errors.append(
                    f"Unicode-confusable spellings {normalized_previous!r} and {spelling!r}"
                )
            normalized_seen[normalized_key] = spelling

    diagnostics = data.get("diagnostics", {})
    if diagnostics is not None and not isinstance(diagnostics, dict):
        errors.append("diagnostics must be an object")
    elif isinstance(diagnostics, dict):
        for code, template in diagnostics.items():
            if not isinstance(code, str) or not isinstance(template, str):
                errors.append("diagnostic codes and templates must be strings")
                continue
            if not _valid_placeholders(template):
                errors.append(f"diagnostic {code!r} contains malformed placeholders")
    return errors


def _supports_current_sprout(constraint: str) -> bool:
    if constraint in {"*", SPROUT_VERSION}:
        return True
    major_minor = ".".join(SPROUT_VERSION.split(".")[:2])
    return constraint in {f"{major_minor}.x", f"~{major_minor}", ">=0.3,<0.4"}


def _valid_placeholders(template: str) -> bool:
    try:
        fields = re.findall(r"\{([^{}]+)\}", template)
        stripped = re.sub(r"\{[^{}]+\}", "", template)
        return "{" not in stripped and "}" not in stripped and all(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) for field in fields
        )
    except (TypeError, re.error):
        return False


def bootstrap_language(source: str) -> BootstrapSelection:
    lines = source.splitlines(keepends=True)
    if lines and lines[0].startswith("\ufeff"):
        lines[0] = lines[0][1:]
    declaration_line: int | None = None
    pack_id: str | None = None
    first_meaningful_seen = False
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if index == 0:
            if content.startswith("#!"):
                continue
        stripped = content.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = BOOTSTRAP_RE.fullmatch(content)
        if match:
            if first_meaningful_seen:
                raise SproutError(
                    "The language declaration must be the first meaningful statement"
                )
            pack_id = match.group(1)
            declaration_line = index + 1
            newline = line[len(line.rstrip("\r\n")):]
            lines[index] = newline
            first_meaningful_seen = True
            continue
        first_meaningful_seen = True

    if declaration_line is None:
        for index, line in enumerate(lines):
            if BOOTSTRAP_RE.fullmatch(line.rstrip("\r\n").lstrip("\ufeff")):
                raise SproutError(
                    f"The language declaration at line {index + 1} must be the first meaningful statement"
                )
    return BootstrapSelection("".join(lines), pack_id, declaration_line)


def keyword_compatibility_view() -> set[str]:
    return {
        concept.english
        for concept in KEYWORD_CONCEPTS
        if concept.token_kind != "IDENT"
    }


def language_pack_for_source(
    source: str,
    language_override: str | None = None,
    language_default: str | None = None,
) -> LanguagePack:
    bootstrap = bootstrap_language(source)
    return load_language_pack(
        language_override or bootstrap.pack_id or language_default or "english-pack"
    )


def concept_spellings(concept_id: str) -> list[str]:
    spellings = {CATALOG[concept_id].english}
    for item in list_language_packs():
        pack = load_language_pack(item["path"])
        entry = pack.entries.get(concept_id, {})
        preferred = entry.get("preferred")
        if isinstance(preferred, str):
            spellings.add(preferred)
        spellings.update(
            alias for alias in entry.get("aliases", []) if isinstance(alias, str)
        )
    return sorted(spellings, key=lambda item: (-len(item), item))


def all_keyword_spellings() -> set[str]:
    result: set[str] = set()
    for concept in KEYWORD_CONCEPTS:
        result.update(concept_spellings(concept.id))
    return result


def list_language_packs() -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for root in reversed(language_pack_search_paths()):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if not name.endswith(".json") or name == "installed.json":
                continue
            path = os.path.join(root, name)
            try:
                pack = load_language_pack(path)
            except SproutError:
                continue
            found[pack.id] = {
                "id": pack.id,
                "version": str(pack.data["version"]),
                "locale": pack.locale,
                "path": path,
                **pack.coverage(),
            }
    return [found[name] for name in sorted(found)]


def validate_language_pack(path_or_id: str) -> dict[str, Any]:
    pack = load_language_pack(path_or_id)
    missing = (
        []
        if pack.id == "english-pack"
        else [concept_id for concept_id in CATALOG if concept_id not in pack.entries]
    )
    return {
        "id": pack.id,
        "version": pack.data["version"],
        "locale": pack.locale,
        "catalogVersion": pack.data["catalogVersion"],
        "concepts": len(CATALOG),
        "missing": missing,
        **pack.coverage(),
    }


def sync_language_pack(
    path: str,
    translator_command: str | None = None,
) -> dict[str, Any]:
    resolved = os.path.realpath(path)
    with open(resolved, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    errors = validate_language_pack_data(data)
    if errors:
        raise SproutError(f"Invalid language pack '{path}': {'; '.join(errors)}")
    missing = [concept_id for concept_id in CATALOG if concept_id not in data["entries"]]
    memory = data.get("translationMemory", {})
    generated: dict[str, str] = {}
    if translator_command and missing:
        request = {
            "pack": {"id": data["id"], "locale": data["locale"]},
            "concepts": [
                {
                    "id": concept_id,
                    "english": CATALOG[concept_id].english,
                    "context": CATALOG[concept_id].context,
                    "category": CATALOG[concept_id].category,
                }
                for concept_id in missing
            ],
        }
        result = subprocess.run(
            shlex.split(translator_command),
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise SproutError(
                f"Translator command failed with exit {result.returncode}: {result.stderr.strip()}"
            )
        try:
            response = json.loads(result.stdout)
            generated = {
                str(key): str(value)
                for key, value in response.get("translations", {}).items()
            }
        except (AttributeError, json.JSONDecodeError) as exc:
            raise SproutError(f"Translator command returned invalid JSON: {exc}") from None
    for concept_id in missing:
        preferred = memory.get(concept_id) or generated.get(concept_id)
        status = "generated" if preferred else "fallback"
        data["entries"][concept_id] = {
            "preferred": str(preferred or CATALOG[concept_id].english),
            "aliases": [],
            "status": status,
        }
    data["catalogVersion"] = LANGUAGE_CATALOG_VERSION
    errors = validate_language_pack_data(data)
    if errors:
        raise SproutError(f"Synced language pack is invalid: {'; '.join(errors)}")
    with open(resolved, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    _PACK_CACHE.clear()
    return validate_language_pack(resolved)


def install_language_pack(
    source: str,
    registry: str | None = None,
) -> dict[str, Any]:
    source_path = resolve_language_pack_path(source)
    registry_source: str | None = None
    version: str | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if source_path is None:
        from .ecosystem import materialize_registry_bundle, read_registry, select_version

        spec_name, constraint = (
            source.rsplit("@", 1) if "@" in source else (source, "*")
        )
        index, registry_root = read_registry(registry)
        version, entry = select_version(index, spec_name, constraint)
        if entry.get("type") != "language-pack":
            raise SproutError(f"Registry package '{spec_name}' is not a language-pack")
        temporary = tempfile.TemporaryDirectory()
        materialize_registry_bundle(
            {
                "name": spec_name,
                "registry": registry_root,
                "bundle": entry.get("bundle"),
                "sha256": entry.get("sha256"),
            },
            temporary.name,
        )
        files = []
        for current, dirs, names in os.walk(temporary.name):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            files.extend(os.path.join(current, name) for name in names)
        json_files = [path for path in files if path.endswith(".json")]
        unsafe = [path for path in files if not path.endswith((".json", ".md", ".txt"))]
        if len(json_files) != 1 or unsafe:
            raise SproutError("Language-pack bundles must contain one JSON pack and no executable files")
        source_path = json_files[0]
        registry_source = f"{spec_name}@{version}"
    try:
        pack = load_language_pack(source_path)
        root = os.path.expanduser("~/.sprout/languages")
        os.makedirs(root, exist_ok=True)
        destination = os.path.join(root, f"{pack.id}.json")
        if os.path.realpath(source_path) != os.path.realpath(destination):
            shutil.copy2(source_path, destination)
        checksum = _sha256_file(destination)
        metadata_path = os.path.join(root, "installed.json")
        metadata = {}
        if os.path.isfile(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        metadata[pack.id] = {
            "version": version or pack.data["version"],
            "sha256": checksum,
            "source": registry_source or os.path.realpath(source),
            "registry": registry,
        }
        with open(metadata_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")
        _record_language_lock(pack.id, metadata[pack.id])
        _PACK_CACHE.clear()
        return {"id": pack.id, **metadata[pack.id], "path": destination}
    finally:
        if temporary is not None:
            temporary.cleanup()


def update_language_pack(pack_id: str, registry: str | None = None) -> dict[str, Any]:
    metadata_path = os.path.expanduser("~/.sprout/languages/installed.json")
    if not os.path.isfile(metadata_path):
        raise SproutError(f"Language pack '{pack_id}' is not installed")
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    entry = metadata.get(pack_id)
    if not entry:
        raise SproutError(f"Language pack '{pack_id}' is not installed")
    return install_language_pack(
        str(entry["source"]),
        registry=registry or entry.get("registry"),
    )


def _record_language_lock(pack_id: str, entry: dict[str, Any]) -> None:
    current = os.path.abspath(os.getcwd())
    while True:
        config = os.path.join(current, "sprout.toml")
        if os.path.isfile(config):
            lock_path = os.path.join(current, "sprout.lock")
            lock: dict[str, Any] = {"schema": 1, "dependencies": {}}
            if os.path.isfile(lock_path):
                with open(lock_path, "r", encoding="utf-8") as handle:
                    lock = json.load(handle)
            lock.setdefault("languagePacks", {})[pack_id] = dict(entry)
            with open(lock_path, "w", encoding="utf-8") as handle:
                json.dump(lock, handle, indent=2, sort_keys=True)
                handle.write("\n")
            return
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
