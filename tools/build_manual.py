#!/usr/bin/env python3
"""Build a small standalone HTML manual from docs/MANUAL.md."""

from __future__ import annotations

from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "MANUAL.md"
HTML = ROOT / "docs" / "manual.html"


STYLE = """
body {
  color: #17201a;
  background: #fbfdf9;
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 0;
}
main {
  max-width: 920px;
  margin: 0 auto;
  padding: 48px 24px 72px;
}
h1, h2, h3 {
  line-height: 1.2;
  color: #183b26;
}
h1 {
  font-size: 2.4rem;
}
h2 {
  border-top: 1px solid #dce8d8;
  margin-top: 2.4rem;
  padding-top: 1.2rem;
}
a {
  color: #256d3f;
}
code {
  background: #eef6eb;
  border-radius: 4px;
  padding: 0.1em 0.25em;
}
pre {
  background: #102016;
  color: #eef9ef;
  overflow: auto;
  padding: 16px;
  border-radius: 8px;
}
pre code {
  background: transparent;
  padding: 0;
}
blockquote {
  border-left: 4px solid #8bc28f;
  margin-left: 0;
  padding-left: 1rem;
}
table {
  border-collapse: collapse;
}
td, th {
  border: 1px solid #dce8d8;
  padding: 0.35rem 0.55rem;
}
"""


def inline(text: str) -> str:
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def build(markdown: str) -> str:
    out: list[str] = []
    in_code = False
    code_lang = ""
    in_list = False
    in_para = False

    def close_para() -> None:
        nonlocal in_para
        if in_para:
            out.append("</p>")
            in_para = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
                code_lang = ""
            else:
                close_para()
                close_list()
                code_lang = line[3:].strip()
                lang_class = f' class="language-{escape(code_lang)}"' if code_lang else ""
                out.append(f"<pre><code{lang_class}>")
                in_code = True
            continue

        if in_code:
            out.append(escape(line))
            continue

        if not line:
            close_para()
            close_list()
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            close_para()
            close_list()
            level = len(heading.group(1))
            text = inline(heading.group(2))
            slug = re.sub(r"[^a-z0-9]+", "-", heading.group(2).lower()).strip("-")
            out.append(f'<h{level} id="{slug}">{text}</h{level}>')
            continue

        if line.startswith("- "):
            close_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue

        close_list()
        if not in_para:
            out.append("<p>")
            in_para = True
        else:
            out.append(" ")
        out.append(inline(line))

    close_para()
    close_list()
    if in_code:
        out.append("</code></pre>")

    return "\n".join(out)


def main() -> int:
    markdown = MANUAL.read_text(encoding="utf-8")
    body = build(markdown)
    HTML.write_text(
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>The Sprout Programming Language Manual</title>\n"
        f"<style>{STYLE}</style>\n"
        "</head>\n"
        "<body><main>\n"
        f"{body}\n"
        "</main></body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    print(f"built {HTML.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
