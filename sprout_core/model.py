from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import os

from typing import Any, Callable


SPROUT_VERSION = "0.1.0"


KEYWORDS = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "break",
    "bloom",
    "catch",
    "class",
    "continue",
    "def",
    "each",
    "elif",
    "else",
    "end",
    "extends",
    "false",
    "fn",
    "for",
    "if",
    "import",
    "importpython",
    "in",
    "let",
    "nil",
    "none",
    "not",
    "or",
    "pluck",
    "raise",
    "return",
    "say",
    "seedfn",
    "sprout",
    "super",
    "true",
    "try",
    "whirl",
    "while",
}


@dataclass
class Token:
    kind: str
    value: Any
    line: int
    col: int


@dataclass
class Diagnostic:
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    col: int | None = None
    code: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "code": self.code,
        }


@dataclass
class Symbol:
    name: str
    kind: str
    path: str | None
    line: int
    col: int

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "line": self.line,
            "col": self.col,
        }


@dataclass
class SproutProject:
    root: str
    name: str = "sprout-project"
    version: str = "0.1.0"
    main: str = "main.sprout"
    authors: list[str] | None = None
    description: str = ""
    license: str = ""
    source_folders: list[str] | None = None
    module_paths: list[str] | None = None
    dependencies: dict[str, Any] | None = None
    tool_settings: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.root = os.path.abspath(self.root)
        self.authors = self.authors or []
        self.source_folders = self.source_folders or ["."]
        self.module_paths = self.module_paths or []
        self.dependencies = self.dependencies or {}
        self.tool_settings = self.tool_settings or {}

    @property
    def main_path(self) -> str:
        return self.resolve(self.main)

    def resolve(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.root, path))

    def search_paths(self) -> list[str]:
        paths = [self.root]
        paths.extend(self.resolve(path) for path in self.source_folders or [])
        paths.extend(self.resolve(path) for path in self.module_paths or [])

        def add_package_path(path: str) -> None:
            paths.append(path)
            for child in ("src", "modules"):
                nested = os.path.join(path, child)
                if os.path.isdir(nested):
                    paths.append(nested)

        dep_paths = self.dependencies.get("paths") if isinstance(self.dependencies, dict) else None
        if isinstance(dep_paths, list):
            for path in dep_paths:
                add_package_path(self.resolve(str(path)))
        if isinstance(self.dependencies, dict):
            for value in self.dependencies.values():
                if isinstance(value, dict) and "path" in value:
                    add_package_path(self.resolve(str(value["path"])))
                elif isinstance(value, str) and (value.startswith(".") or "/" in value):
                    add_package_path(self.resolve(value))
        out: list[str] = []
        for path in paths:
            if path not in out:
                out.append(path)
        return out


class SproutError(Exception):
    def __init__(self, message: Any):
        super().__init__(str(message))
        self.message = str(message)
        self.frames: list[str] = []

    def add_frame(self, name: str) -> None:
        self.frames.append(name)

    def __str__(self) -> str:
        return self.message


class ReturnSignal(Exception):
    def __init__(self, value: Any):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class SproutRaised(Exception):
    def __init__(self, value: Any):
        self.value = value
