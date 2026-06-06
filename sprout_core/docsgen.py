from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass

from .model import SproutError
from .tooling import load_project


DECLARATION_RE = re.compile(
    r"^\s*(?:(def|fn|bloom)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))|class\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+extends\s+([A-Za-z_][A-Za-z0-9_]*))?)"
)


@dataclass
class DocItem:
    kind: str
    name: str
    signature: str
    docs: str
    path: str
    line: int


def scan_docs(path: str) -> list[DocItem]:
    items = []
    comments: list[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("##"):
            comments.append(stripped[2:].strip())
            continue
        match = DECLARATION_RE.match(line)
        if match:
            function_kind, function_name, params, class_name, superclass = match.groups()
            if function_name:
                kind = "function"
                name = function_name
                signature = f"{name}{params}"
            else:
                kind = "class"
                name = class_name
                signature = f"class {name}" + (f" extends {superclass}" if superclass else "")
            items.append(DocItem(kind, name, signature, "\n".join(comments), path, line_number))
            comments = []
            continue
        if stripped and not stripped.startswith("#"):
            comments = []
    return items


def project_source_files(root: str) -> tuple[object, list[str]]:
    project = load_project(root)
    if not project:
        raise SproutError(f"No sprout.toml found in project directory '{root}'")
    files: list[str] = []
    seen: set[str] = set()
    roots = [project.resolve(path) for path in (project.source_folders or []) + (project.module_paths or [])]
    main_root = os.path.dirname(project.main_path)
    if main_root not in roots:
        roots.append(main_root)
    for search_root in roots:
        if not os.path.isdir(search_root):
            continue
        for current, dirs, names in os.walk(search_root):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name not in {"packages", "tests"}]
            for name in names:
                if name.endswith(".sprout"):
                    path = os.path.abspath(os.path.join(current, name))
                    if path not in seen:
                        seen.add(path)
                        files.append(path)
    return project, sorted(files)


def render_markdown(root: str) -> str:
    project, files = project_source_files(root)
    lines = [
        f"# {project.name} API",
        "",
        project.description or "Generated Sprout project documentation.",
        "",
        f"- Version: `{project.version}`",
        f"- License: `{project.license or 'unspecified'}`",
        "",
    ]
    for path in files:
        items = scan_docs(path)
        if not items:
            continue
        lines.extend([f"## `{os.path.relpath(path, project.root)}`", ""])
        for item in items:
            lines.extend([f"### `{item.signature}`", ""])
            if item.docs:
                lines.extend([item.docs, ""])
            lines.append(f"Defined at `{os.path.relpath(item.path, project.root)}:{item.line}`.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def markdown_to_html(markdown: str, title: str) -> str:
    body = []
    in_list = False
    for line in markdown.splitlines():
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        body.append("</ul>")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:0 20px;line-height:1.55}"
        "code{background:#f2f2f2;padding:2px 5px}</style></head><body>"
        + "\n".join(body)
        + "</body></html>\n"
    )


def generate_docs(path: str = ".", html_mode: bool = False) -> int:
    root = os.path.abspath(path)
    project = load_project(root)
    if not project:
        raise SproutError(f"No sprout.toml found in project directory '{path}'")
    markdown = render_markdown(root)
    docs_dir = os.path.join(project.root, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    markdown_path = os.path.join(docs_dir, "API.md")
    with open(markdown_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
    print(f"generated {markdown_path}")
    if html_mode:
        html_path = os.path.join(docs_dir, "API.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(markdown_to_html(markdown, f"{project.name} API"))
        print(f"generated {html_path}")
    return 0
