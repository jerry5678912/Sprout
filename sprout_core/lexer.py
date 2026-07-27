from __future__ import annotations

import textwrap

from .languages import LanguagePack, bootstrap_language, load_language_pack
from .model import Token, SproutError

class Lexer:
    def __init__(
        self,
        source: str,
        language_pack: str | LanguagePack | None = None,
        default_language_pack: str | LanguagePack | None = None,
    ):
        bootstrap = bootstrap_language(source)
        selected = language_pack or bootstrap.pack_id or default_language_pack or "english-pack"
        self.language_pack = (
            selected if isinstance(selected, LanguagePack) else load_language_pack(selected)
        )
        self.source = self.normalize_pasted_indentation(bootstrap.source)
        self.i = 0
        self.line = 1
        self.col = 1
        self.at_line_start = True
        self.indents = [0]
        self.pending_indent = False
        self.nesting = 0

    @staticmethod
    def normalize_pasted_indentation(source: str) -> str:
        for raw_line in source.splitlines():
            stripped = raw_line.lstrip(" \t")
            if not stripped:
                continue
            if stripped != raw_line:
                return textwrap.dedent(source)
            break
        return source

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while not self.at_end():
            if self.at_line_start and self.nesting == 0:
                self.handle_indentation(tokens)
                if self.at_end():
                    break
            ch = self.peek()
            if self.at_line_start and ch not in " \r\t\n#":
                self.at_line_start = False
            if ch in " \r\t":
                self.advance()
            elif ch == "\n":
                tokens.append(Token("NEWLINE", "\n", self.line, self.col))
                self.pending_indent = self.previous_significant_kind(tokens) in {":", "BLOOM"}
                self.advance_line()
            elif ch == "#":
                self.skip_comment()
            elif ch.isdigit():
                tokens.append(self.number())
            elif ch.isalpha() or ch == "_":
                tokens.append(self.identifier())
            elif ch == '"':
                tokens.append(self.string())
            else:
                tokens.append(self.symbol())
        while len(self.indents) > 1:
            self.indents.pop()
            tokens.append(Token("DEDENT", None, self.line, self.col))
        tokens.append(Token("EOF", None, self.line, self.col))
        return tokens

    def handle_indentation(self, tokens: list[Token]) -> None:
        start_i = self.i
        start_col = self.col
        count = 0
        while not self.at_end() and self.peek() in " \t":
            count += 2 if self.peek() == "\t" else 1
            self.advance()
        if self.at_end():
            return
        if self.peek() in "\n#":
            return
        self.at_line_start = False
        current = self.indents[-1]
        if self.pending_indent:
            self.pending_indent = False
            if count <= current:
                raise SproutError(f"Expected an indented block at {self.line}:{start_col}")
            self.indents.append(count)
            tokens.append(Token("INDENT", None, self.line, start_col))
            return
        if count > current:
            self.i = start_i
            self.col = start_col
            raise SproutError(f"Unexpected indentation at {self.line}:{start_col}")
        while count < self.indents[-1]:
            self.indents.pop()
            tokens.append(Token("DEDENT", None, self.line, start_col))
        if count != self.indents[-1]:
            raise SproutError(f"Inconsistent indentation at {self.line}:{start_col}")

    def previous_significant_kind(self, tokens: list[Token]) -> str | None:
        for token in reversed(tokens):
            if token.kind not in {"NEWLINE", "INDENT", "DEDENT", ";"}:
                return token.kind
        return None

    def at_end(self) -> bool:
        return self.i >= len(self.source)

    def peek(self, offset: int = 0) -> str:
        pos = self.i + offset
        return "\0" if pos >= len(self.source) else self.source[pos]

    def advance(self) -> str:
        ch = self.source[self.i]
        self.i += 1
        self.col += 1
        return ch

    def advance_line(self) -> None:
        self.i += 1
        self.line += 1
        self.col = 1
        self.at_line_start = True

    def skip_comment(self) -> None:
        while not self.at_end() and self.peek() != "\n":
            self.advance()

    def number(self) -> Token:
        line, col = self.line, self.col
        start = self.i
        while self.peek().isdigit():
            self.advance()
        if self.peek() == "." and self.peek(1).isdigit():
            self.advance()
            while self.peek().isdigit():
                self.advance()
        raw = self.source[start:self.i]
        value: Any = float(raw) if "." in raw else int(raw)
        return Token("NUMBER", value, line, col)

    def identifier(self) -> Token:
        line, col = self.line, self.col
        start = self.i
        while self.peek().isalnum() or self.peek() == "_":
            self.advance()
        raw = self.source[start:self.i]
        keyword = self.language_pack.keyword(raw)
        if keyword:
            return Token(keyword.token_kind or "IDENT", keyword.canonical, line, col, raw)
        return Token("IDENT", raw, line, col)

    def string(self) -> Token:
        line, col = self.line, self.col
        self.advance()
        chars: list[str] = []
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
        while not self.at_end() and self.peek() != '"':
            if self.peek() == "\n":
                self.advance_line()
                chars.append("\n")
            elif self.peek() == "\\":
                self.advance()
                if self.at_end():
                    raise SproutError(f"Unterminated string escape at {self.line}:{self.col}")
                esc = self.advance()
                chars.append(escapes.get(esc, esc))
            else:
                chars.append(self.advance())
        if self.at_end():
            raise SproutError(f"Unterminated string at {line}:{col}")
        self.advance()
        return Token("STRING", "".join(chars), line, col)

    def symbol(self) -> Token:
        line, col = self.line, self.col
        two = self.peek() + self.peek(1)
        if two in {"==", "!=", "<=", ">=", "//", "**", "->", "=>"}:
            self.advance()
            self.advance()
            return Token(two, two, line, col)
        ch = self.advance()
        if ch in "({[":
            self.nesting += 1
        elif ch in ")}]":
            self.nesting = max(0, self.nesting - 1)
        if ch in "+-*/%(){}[],:;.=<>!|?":
            return Token(ch, ch, line, col)
        raise SproutError(f"Unexpected character {ch!r} at {line}:{col}")
