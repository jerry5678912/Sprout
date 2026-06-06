from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Any

from .model import SPROUT_VERSION, SproutError
from .distribution import verify_release_versions
from .tooling import check_file, example_files, load_project, parse_simple_toml


RELEASE_TEST_SCRIPTS = [
    "tests/tooling.py",
    "tests/intellisense.py",
    "tests/vm.py",
    "tests/package.py",
    "tests/dogfood.py",
    "tests/application.py",
    "tests/ecosystem.py",
    "tests/standalone.py",
    "tests/async_language.py",
    "tests/advanced_language.py",
    "tests/quality.py",
    "tests/security.py",
    "tests/typesystem.py",
    "tests/distribution.py",
    "tests/lsp.py",
    "tests/errors.py",
    "tests/debug_adapter.py",
]


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_toml_file(path: str) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None
    with open(path, "rb") as fh:
        if tomllib:
            return tomllib.load(fh)
        return parse_simple_toml(fh.read().decode("utf-8"))


def dump_sprout_toml(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for section in ("project", "package", "paths", "dependencies", "build", "registry", "tool"):
        value = data.get(section)
        if not isinstance(value, dict):
            continue
        lines.append(f"[{section}]")
        for key, item in value.items():
            lines.append(f"{key} = {toml_value(item)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{key} = {toml_value(item)}" for key, item in value.items()) + " }"
    return str(value)


def project_config_path(root: str | None = None) -> str:
    return os.path.abspath(os.path.join(root or os.getcwd(), "sprout.toml"))


def load_project_data(root: str | None = None) -> dict[str, Any]:
    path = project_config_path(root)
    if not os.path.exists(path):
        raise SproutError("No sprout.toml found. Run 'python3 sprout.py pkg init' first.")
    return read_toml_file(path)


def save_project_data(data: dict[str, Any], root: str | None = None) -> None:
    write_text(project_config_path(root), dump_sprout_toml(data))


def pkg_init(root: str | None = None, name: str | None = None) -> int:
    root = os.path.realpath(root or os.getcwd())
    path = project_config_path(root)
    if os.path.exists(path):
        print(f"sprout.toml already exists at {path}")
        return 0
    project_name = name or os.path.basename(root) or "sprout-project"
    data = {
        "project": {
            "name": project_name.replace("-", "_").replace(" ", "_"),
            "version": "0.1.0",
            "main": "src/main.sprout",
            "authors": [],
            "description": "",
            "license": "MIT",
        },
        "paths": {"source": ["src"], "modules": ["modules"]},
        "dependencies": {},
    }
    save_project_data(data, root)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    print(f"created {path}")
    return 0


def pkg_list(root: str | None = None) -> int:
    data = load_project_data(root)
    deps = data.get("dependencies", {})
    if not deps:
        print("no packages")
        return 0
    for name, value in sorted(deps.items()):
        if isinstance(value, dict):
            print(f"{name} {value.get('version', '')} {value.get('path', '')}".strip())
        else:
            print(f"{name} {value}")
    return 0


def package_name_from_path(path: str) -> str:
    config = os.path.join(path, "sprout.toml")
    if os.path.exists(config):
        data = read_toml_file(config)
        project = data.get("project", {})
        if project.get("name"):
            return str(project["name"])
    return os.path.basename(os.path.abspath(path)).replace("-", "_")


def pkg_add(package_path: str, root: str | None = None) -> int:
    root = os.path.abspath(root or os.getcwd())
    data = load_project_data(root)
    deps = data.setdefault("dependencies", {})
    resolved = os.path.realpath(package_path)
    if not os.path.isdir(resolved):
        raise SproutError(f"Package path does not exist: {package_path}")
    name = package_name_from_path(resolved)
    metadata = read_toml_file(os.path.join(resolved, "sprout.toml")) if os.path.isfile(os.path.join(resolved, "sprout.toml")) else {}
    package = {**metadata.get("project", {}), **metadata.get("package", {})}
    deps[name] = {"path": os.path.relpath(resolved, root), "version": str(package.get("version", "0.1.0"))}
    save_project_data(data, root)
    print(f"added {name} -> {deps[name]['path']}")
    return 0


def pkg_remove(name: str, root: str | None = None) -> int:
    data = load_project_data(root)
    deps = data.setdefault("dependencies", {})
    if name not in deps:
        raise SproutError(f"Package not found: {name}")
    del deps[name]
    save_project_data(data, root)
    print(f"removed {name}")
    return 0


def pkg_info(name: str, root: str | None = None) -> int:
    data = load_project_data(root)
    deps = data.get("dependencies", {})
    if name not in deps:
        raise SproutError(f"Package not found: {name}")
    value = deps[name]
    print(json.dumps({name: value}, indent=2))
    return 0


def project_toml(name: str, main: str, description: str = "") -> str:
    data = {
        "project": {
            "name": name,
            "version": "0.1.0",
            "main": main,
            "authors": [],
            "description": description,
            "license": "MIT",
        },
        "paths": {"source": ["src"], "modules": ["modules"]},
        "dependencies": {},
    }
    return dump_sprout_toml(data)


def new_project(template: str, name: str, root: str | None = None) -> int:
    base = os.path.abspath(os.path.join(root or os.getcwd(), name))
    if os.path.exists(base):
        raise SproutError(f"Path already exists: {base}")
    os.makedirs(base)
    safe_name = name.replace("-", "_").replace(" ", "_")
    os.makedirs(os.path.join(base, "src"))
    os.makedirs(os.path.join(base, "modules"))
    os.makedirs(os.path.join(base, "tests"))
    os.makedirs(os.path.join(base, "docs"))
    write_text(os.path.join(base, "sprout.toml"), project_toml(safe_name, "src/main.sprout", f"{template} Sprout project"))
    write_text(os.path.join(base, "README.md"), f"# {safe_name}\n\nCreated with `sprout.py new {template} {name}`.\n\nRun:\n\n```sh\npython3 sprout.py run .\n```\n")
    main = TEMPLATE_SOURCES.get(template)
    if main is None:
        raise SproutError(f"Unknown template '{template}'. Use cli, game2d, game3d, or library.")
    write_text(os.path.join(base, "src", "main.sprout"), main.replace("{name}", safe_name))
    if template == "library":
        write_text(os.path.join(base, "src", f"{safe_name}.sprout"), LIBRARY_MODULE_SOURCE)
        write_text(os.path.join(base, "tests", "main.sprout"), LIBRARY_TEST_SOURCE.replace("{name}", safe_name))
        write_text(os.path.join(base, "docs", "API.md"), f"# {safe_name} API\n\n- `greet(name)` returns a friendly greeting.\n- `slug(text)` lowercases text and replaces spaces with dashes.\n")
    print(f"created {template} project at {base}")
    return 0


TEMPLATE_SOURCES = {
    "cli": 'def help():\n  say "{name}"\n  say "usage:"\n  say "  {name} greet NAME"\n  say "  {name} count WORDS..."\n\nif len(argv) == 0 or argv[0] == "help":\n  help()\nelse if argv[0] == "greet":\n  name = "Sprout"\n  if len(argv) > 1:\n    name = argv[1]\n  say "hello", name\nelse if argv[0] == "count":\n  words = argv[1:]\n  say "words:", len(words)\n  say "text:", words.join(" ")\nelse:\n  say "unknown command:", argv[0]\n  help()\n',
    "game2d": 'width = 16\nheight = 8\nplayer = {"x": 2, "y": 2, "score": 0}\ncoins = [[5, 2], [8, 4], [12, 5]]\nwalls = [[6, 3], [6, 4], [6, 5]]\n\nmoves = argv\nif len(moves) == 0:\n  moves = ["right", "right", "right", "down", "down", "right", "right"]\n\ndef has_cell(cells, x, y):\n  for cell in cells:\n    if cell[0] == x and cell[1] == y:\n      return true\n  return false\n\ndef remove_cell(cells, x, y):\n  kept = []\n  for cell in cells:\n    if cell[0] != x or cell[1] != y:\n      kept.append(cell)\n  return kept\n\ndef update(move):\n  dx = 0\n  dy = 0\n  if move == "right":\n    dx = 1\n  else if move == "left":\n    dx = 0 - 1\n  else if move == "down":\n    dy = 1\n  else if move == "up":\n    dy = 0 - 1\n\n  nx = player.x + dx\n  ny = player.y + dy\n  if nx > 0 and ny > 0 and nx < width - 1 and ny < height - 1 and not has_cell(walls, nx, ny):\n    player.x = nx\n    player.y = ny\n\n  if has_cell(coins, player.x, player.y):\n    player.score = player.score + 1\n    coins = remove_cell(coins, player.x, player.y)\n\ndef draw():\n  y = 0\n  while y < height:\n    row = ""\n    x = 0\n    while x < width:\n      if x == 0 or y == 0 or x == width - 1 or y == height - 1:\n        row = row + "#"\n      else if player.x == x and player.y == y:\n        row = row + "@"\n      else if has_cell(walls, x, y):\n        row = row + "X"\n      else if has_cell(coins, x, y):\n        row = row + "*"\n      else:\n        row = row + "."\n      x = x + 1\n    say row\n    y = y + 1\n\nfor move in moves:\n  update(move)\n\ndraw()\nsay "score:", player.score\n',
    "game3d": 'def project(point):\n  z = point[2] + 5\n  return [round(point[0] * 6 / z + 18), round(point[1] * 3 / z + 7)]\n\nvertices = [\n  [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],\n  [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]\n]\nedges = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]]\ncanvas = []\ny = 0\nwhile y < 15:\n  canvas.append("....................................")\n  y = y + 1\n\nfor edge in edges:\n  a = project(vertices[edge[0]])\n  b = project(vertices[edge[1]])\n  canvas[a[1]] = substr(canvas[a[1]], 0, a[0]) + "*" + substr(canvas[a[1]], a[0] + 1, 36)\n  canvas[b[1]] = substr(canvas[b[1]], 0, b[0]) + "*" + substr(canvas[b[1]], b[0] + 1, 36)\n\nsay "{name} 3D wireframe"\nfor row in canvas:\n  say row\n',
    "library": 'import "{name}.sprout" as lib\n\nsay lib.greet("Sprout")\nsay lib.slug("My Library")\n',
}

LIBRARY_MODULE_SOURCE = '## Returns a friendly greeting.\ndef greet(name):\n  return "hello " + name\n\n## Converts text into a lowercase dash slug.\ndef slug(text):\n  return lower(replace(text, " ", "-"))\n'

LIBRARY_TEST_SOURCE = 'import "{name}.sprout" as lib\n\ntest "greeting":\n  expect(lib.greet("Sprout")).to_equal("hello Sprout")\n\ntest "slug":\n  expect(lib.slug("My Library")).to_equal("my-library")\n'


def doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    checks.append(("python >= 3.9", sys.version_info >= (3, 9), platform.python_version()))
    if not os.path.isfile(os.path.join(root, "sprout.py")):
        runtime_files = [
            "sprout_core/__init__.py",
            "sprout_core/cli.py",
            "sprout_core/runtime.py",
            "sprout_core/parser.py",
            "sprout_core/conformance/manifest.json",
        ]
        for path in runtime_files:
            full = os.path.join(root, path)
            checks.append((path, os.path.isfile(full), full))
        checks.append(("runtime version", bool(SPROUT_VERSION), SPROUT_VERSION))
        ok = True
        print("doctor mode installed-runtime")
        for name, passed, detail in checks:
            ok = ok and passed
            print(f"{'ok' if passed else 'fail'} {name} {detail}")
        return 0 if ok else 1
    for path in [
        "sprout.py",
        "install.py",
        "pyproject.toml",
        "README.md",
        "docs/MANUAL.md",
        "editor/vscode-sprout/package.json",
        "tests/smoke.sh",
        "tests/application.py",
        "tests/ecosystem.py",
        "tests/standalone.py",
        "tests/async_language.py",
        "tests/advanced_language.py",
        "tests/quality.py",
        "tests/security.py",
        "tests/typesystem.py",
        "sprout_core/conformance/manifest.json",
        "tests/distribution.py",
        "tests/lsp.py",
        "tools/package_vscode.py",
        "docs/ECOSYSTEM.md",
        "docs/CAPABILITY_AUDIT.md",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        ".github/workflows/publish-pypi.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        "docs/ARCHITECTURE.md",
        "examples/modules/engineering.sprout",
        "examples/modules/appgame.sprout",
        "examples/typed_abstractions.sprout",
        "examples/advanced_features.sprout",
    ]:
        full = os.path.join(root, path)
        checks.append((path, os.path.exists(full), full))
    project = load_project(root) if os.path.exists(os.path.join(root, "sprout.toml")) else None
    checks.append(("sprout.toml", project is not None, "project and package metadata"))
    ok = True
    for name, passed, detail in checks:
        ok = ok and passed
        print(f"{'ok' if passed else 'fail'} {name} {detail}")
    return 0 if ok else 1


def release_check() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isfile(os.path.join(root, "sprout.py")):
        raise SproutError("release-check requires a Sprout source checkout")
    status = doctor()
    examples_ok = True
    for rel in example_files():
        if check_file(os.path.join(root, rel)) != 0:
            examples_ok = False
    shell = shutil.which("sh")
    if shell:
        tests_ok = subprocess.run([shell, "tests/smoke.sh"], cwd=root).returncode == 0
    else:
        tests_ok = True
        print("release-check: no POSIX shell; running portable structured tests")
        for script in RELEASE_TEST_SCRIPTS:
            result = subprocess.run([sys.executable, script], cwd=root)
            if result.returncode != 0:
                tests_ok = False
                break
        if tests_ok:
            tests_ok = subprocess.run(
                [sys.executable, "sprout.py", "conformance"],
                cwd=root,
            ).returncode == 0
        if tests_ok:
            tests_ok = subprocess.run(
                [sys.executable, "tools/check_editor_coverage.py"],
                cwd=root,
            ).returncode == 0
    version_errors = verify_release_versions()
    for error in version_errors:
        print(f"fail version {error}")
    ok = status == 0 and examples_ok and tests_ok and not version_errors
    print("release-check:", "ok" if ok else "failed")
    return 0 if ok else 1


def ensure_release_docs(root: str | None = None) -> int:
    root = os.path.abspath(root or os.getcwd())
    files = {
        "LICENSE": "MIT License\n\nCopyright (c) 2026 Sprout contributors\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files to deal in the Software without restriction.\n",
        "CONTRIBUTING.md": "# Contributing to Sprout\n\nThanks for helping Sprout grow.\n\n## Setup\n\n```sh\npython3 sprout.py help\ntests/smoke.sh\n```\n\nKeep changes small, add tests, and update docs when behavior changes.\n",
        "CODE_OF_CONDUCT.md": "# Code of Conduct\n\nBe kind, curious, and respectful. Harassment, threats, and exclusionary behavior are not welcome.\n",
        "SECURITY.md": "# Security Policy\n\nPlease report security issues privately to the project maintainers. Do not publish exploit details before a fix is available.\n",
        "CHANGELOG.md": "# Changelog\n\n## 0.1.0\n\n- Early Sprout language, tooling, VM, editor, and package-manager foundations.\n",
        "ROADMAP.md": "# Roadmap\n\n- Host the JSON registry with authentication.\n- Add package signing and trust policy.\n- Expand VM compatibility and release automation.\n",
        ".github/ISSUE_TEMPLATE/bug_report.md": "---\nname: Bug report\nabout: Report a Sprout problem\n---\n\n## What happened?\n\n## How to reproduce\n\n## Expected behavior\n",
        ".github/ISSUE_TEMPLATE/package_request.md": "---\nname: Package or registry issue\nabout: Report an ecosystem problem\n---\n\n## Package and version\n\n## Command\n\n## Expected behavior\n\n## Actual output\n",
        ".github/pull_request_template.md": "## Summary\n\n## Tests\n\n## Docs\n",
    }
    for path, text in files.items():
        full = os.path.join(root, path)
        if not os.path.exists(full):
            write_text(full, text)
            print(f"created {path}")
    return 0
