from __future__ import annotations

import html
import os
from dataclasses import dataclass, field

from .analysis import SemanticSymbol, build_workspace_index, normalize_path
from .model import SproutError
from .tooling import load_project


DOCUMENTED_FILE_KINDS = {"function", "class", "interface", "enum", "type"}
MEMBER_KINDS = {"method", "field", "enum-member"}


@dataclass
class DocItem:
    kind: str
    name: str
    signature: str
    docs: str
    path: str
    line: int
    members: list["DocItem"] = field(default_factory=list)


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


def _signature_for(symbol: SemanticSymbol) -> str:
    if symbol.signature:
        if symbol.kind in {"class", "interface", "enum", "type"} and not symbol.signature.startswith(symbol.name):
            return symbol.signature
        return symbol.signature
    if symbol.kind == "class":
        return f"class {symbol.name}"
    if symbol.kind == "interface":
        return f"interface {symbol.name}"
    if symbol.kind == "enum":
        return f"enum {symbol.name}"
    if symbol.kind == "type":
        return f"type {symbol.name}"
    return symbol.name


def _doc_item_from_symbol(symbol: SemanticSymbol) -> DocItem:
    members = [
        DocItem(
            kind=member.kind,
            name=member.name,
            signature=_signature_for(member),
            docs=member.documentation,
            path=member.location.path,
            line=member.location.line,
        )
        for member in sorted(
            symbol.members.values(),
            key=lambda item: (item.location.line, item.location.col, item.name),
        )
        if member.kind in MEMBER_KINDS
    ]
    return DocItem(
        kind=symbol.kind,
        name=symbol.name,
        signature=_signature_for(symbol),
        docs=symbol.documentation,
        path=symbol.location.path,
        line=symbol.location.line,
        members=members,
    )


def _display_path(path: str, project_root: str) -> str:
    return os.path.relpath(normalize_path(path), normalize_path(project_root))


def semantic_doc_items(root: str) -> tuple[object, dict[str, list[DocItem]]]:
    project, files = project_source_files(root)
    index = build_workspace_index(project.root, reason="docs-generation")
    items_by_path: dict[str, list[DocItem]] = {}
    for path in files:
        normalized = normalize_path(path)
        analysis = index.files.get(normalized)
        if not analysis:
            continue
        file_items: list[DocItem] = []
        for symbol in sorted(analysis.symbols, key=lambda item: (item.location.line, item.location.col, item.name)):
            if symbol.scope_id != "file" or symbol.container is not None:
                continue
            if symbol.kind not in DOCUMENTED_FILE_KINDS:
                continue
            file_items.append(_doc_item_from_symbol(symbol))
        if file_items:
            items_by_path[path] = file_items
    return project, items_by_path


def render_markdown(root: str) -> str:
    project, items_by_path = semantic_doc_items(root)
    lines = [
        f"# {project.name} API",
        "",
        project.description or "Generated Sprout project documentation.",
        "",
        f"- Version: `{project.version}`",
        f"- License: `{project.license or 'unspecified'}`",
        "",
    ]
    for path in sorted(items_by_path):
        items = items_by_path[path]
        lines.extend([f"## `{_display_path(path, project.root)}`", ""])
        for item in items:
            lines.extend([f"### `{item.signature}`", ""])
            if item.docs:
                lines.extend([item.docs, ""])
            lines.append(f"Defined at `{_display_path(item.path, project.root)}:{item.line}`.")
            lines.append("")
            if item.members:
                lines.append("#### Members")
                lines.append("")
                for member in item.members:
                    lines.append(f"- `{member.signature}`")
                    if member.docs:
                        for doc_line in member.docs.splitlines():
                            lines.append(f"  {doc_line}")
                    lines.append(
                        f"  Defined at `{_display_path(member.path, project.root)}:{member.line}`."
                    )
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def markdown_to_html(markdown: str, title: str) -> str:
    body = []
    in_list = False
    current_list_item = False
    for line in markdown.splitlines():
        if line.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            elif current_list_item:
                body.append("</li>")
            body.append(f"<li>{html.escape(line[2:])}")
            current_list_item = True
            continue
        if in_list and line.startswith("  "):
            continuation = html.escape(line.strip())
            if continuation:
                body.append(f"<br>{continuation}")
            continue
        if in_list:
            if current_list_item:
                body.append("</li>")
                current_list_item = False
            body.append("</ul>")
            in_list = False
        if line.startswith("#### "):
            body.append(f"<h4>{html.escape(line[5:])}</h4>")
        elif line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line:
            body.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        if current_list_item:
            body.append("</li>")
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
