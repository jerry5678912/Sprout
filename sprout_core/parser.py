from __future__ import annotations

import os
from typing import Any

from .model import Token, SproutError

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def parse(self) -> list[Any]:
        statements = []
        self.skip_newlines()
        while not self.check("EOF"):
            statements.append(self.statement())
            self.skip_newlines()
        return statements

    def statement(self) -> Any:
        self.skip_newlines()
        if self.match("LET", "SPROUT"):
            name = self.consume("IDENT", "Expected a variable name")
            self.consume("=", "Expected '=' after variable name")
            expr = self.expression()
            self.terminator("Expected a line ending after variable declaration")
            return ("let", name.value, expr)
        if self.match("IMPORTPYTHON"):
            if self.match("STRING"):
                module_name = self.previous().value
                parts = module_name.split(".")
            else:
                parts = [self.consume("IDENT", "Expected Python module name after importpython").value]
                while self.match("."):
                    parts.append(self.consume("IDENT", "Expected module path after '.'").value)
                module_name = ".".join(parts)
            alias = parts[-1]
            if self.match("AS"):
                alias = self.consume("IDENT", "Expected alias after as").value
            self.terminator("Expected a line ending after importpython")
            return ("importpython", module_name, alias)
        if self.match("IMPORT"):
            path = self.consume("STRING", "Expected module path string after import").value
            alias = os.path.splitext(os.path.basename(path))[0].replace("-", "_")
            if self.match("AS"):
                alias = self.consume("IDENT", "Expected alias after as").value
            self.terminator("Expected a line ending after import")
            return ("import", path, alias)
        if self.match("FN", "DEF", "BLOOM"):
            return self.function_decl()
        if self.match("CLASS"):
            return self.class_decl()
        if self.match("IF"):
            return self.if_stmt()
        if self.match("WHILE", "WHIRL"):
            return self.while_stmt()
        if self.match("FOR", "EACH"):
            return self.for_stmt()
        if self.match("BREAK"):
            self.terminator("Expected a line ending after break")
            return ("break",)
        if self.match("CONTINUE"):
            self.terminator("Expected a line ending after continue")
            return ("continue",)
        if self.match("RAISE"):
            expr = self.expression()
            self.terminator("Expected a line ending after raise")
            return ("raise", expr)
        if self.match("TRY"):
            return self.try_stmt()
        if self.match("RETURN", "PLUCK"):
            expr = None if self.at_statement_end() else self.expression()
            self.terminator("Expected a line ending after return")
            return ("return", expr)
        if self.match("SAY"):
            args = []
            if not self.at_statement_end():
                while True:
                    args.append(self.expression())
                    if not self.match(","):
                        break
            self.terminator("Expected a line ending after say")
            return ("say", args)
        expr = self.expression()
        if self.match("="):
            target = expr
            value = self.expression()
            self.terminator("Expected a line ending after assignment")
            return ("assign", target, value)
        self.terminator("Expected a line ending after expression")
        return ("expr", expr)

    def function_decl(self) -> Any:
        name = self.consume("IDENT", "Expected function name")
        params = self.parameter_list()
        return ("fn", name.value, params, self.block(), name.line, name.col)

    def parameter_list(self) -> list[tuple[str, Any, bool, bool]]:
        self.consume("(", "Expected '(' after function name")
        params = []
        saw_default = False
        if not self.check(")"):
            while True:
                kw_variadic = self.match("**")
                variadic = False if kw_variadic else self.match("*")
                param = self.consume("IDENT", "Expected parameter name").value
                default = None
                if (variadic or kw_variadic) and self.check("="):
                    tok = self.peek()
                    raise SproutError(f"Variadic parameter '{param}' cannot have a default at {tok.line}:{tok.col}")
                if self.match("="):
                    saw_default = True
                    default = self.expression()
                elif saw_default and not variadic and not kw_variadic:
                    tok = self.previous()
                    raise SproutError(f"Parameter '{param}' needs a default after earlier default at {tok.line}:{tok.col}")
                params.append((param, default, variadic, kw_variadic))
                if (kw_variadic or variadic) and not self.check(")"):
                    tok = self.peek()
                    if kw_variadic:
                        raise SproutError(f"Keyword variadic parameter '{param}' must be last at {tok.line}:{tok.col}")
                    if not (self.check(",") and self.peek_next().kind == "**"):
                        raise SproutError(f"Variadic parameter '{param}' must be last at {tok.line}:{tok.col}")
                if not self.match(","):
                    break
        self.consume(")", "Expected ')' after parameters")
        return params

    def seedfn_expr(self) -> Any:
        token = self.previous()
        if self.match("("):
            self.i -= 1
            params = self.parameter_list()
        else:
            name = self.consume("IDENT", "Expected seedfn parameter name")
            params = [(name.value, None, False, False)]
            while self.match(","):
                name = self.consume("IDENT", "Expected seedfn parameter name")
                params.append((name.value, None, False, False))
        self.consume(":", "Expected ':' after seedfn parameters")
        body = [("return", self.expression())]
        return ("seedfn", params, body, token.line, token.col)

    def class_decl(self) -> Any:
        name = self.consume("IDENT", "Expected class name")
        superclass = None
        if self.match("EXTENDS"):
            superclass = self.consume("IDENT", "Expected superclass name after extends").value
        style = self.block_start("Expected class body")
        self.skip_newlines()
        methods = []
        while not self.block_done(style) and not self.check("EOF"):
            if not self.match("FN", "DEF", "BLOOM"):
                tok = self.peek()
                raise SproutError(f"Expected method declaration at {tok.line}:{tok.col}")
            methods.append(self.function_decl())
            self.skip_newlines()
        self.block_end(style, "Expected end of class body")
        return ("class", name.value, superclass, methods)

    def if_stmt(self) -> Any:
        condition = self.expression()
        then_body = self.block()
        self.skip_newlines()
        if self.match("ELIF"):
            else_body = [self.if_stmt()]
        elif self.match("ELSE"):
            self.skip_newlines()
            if self.match("IF", "ELIF"):
                else_body = [self.if_stmt()]
            else:
                else_body = self.block()
        else:
            else_body = []
        return ("if", condition, then_body, else_body)

    def while_stmt(self) -> Any:
        condition = self.expression()
        return ("while", condition, self.block())

    def for_stmt(self) -> Any:
        name = self.consume("IDENT", "Expected loop variable name")
        self.consume("IN", "Expected 'in' after loop variable")
        iterable = self.expression()
        return ("for", name.value, iterable, self.block())

    def try_stmt(self) -> Any:
        try_body = self.block()
        self.skip_newlines()
        self.consume("CATCH", "Expected catch after try block")
        name = self.consume("IDENT", "Expected catch variable name")
        catch_body = self.block()
        return ("try", try_body, name.value, catch_body)

    def block(self) -> list[Any]:
        style = self.block_start("Expected block")
        self.skip_newlines()
        statements = []
        while not self.block_done(style) and not self.check("EOF"):
            statements.append(self.statement())
            self.skip_newlines()
        self.block_end(style, "Expected end of block")
        return statements

    def block_start(self, message: str) -> str:
        if self.match("{"):
            return "brace"
        if self.match(":"):
            if self.match("NEWLINE"):
                self.skip_newlines()
                self.consume("INDENT", "Expected indented block after ':'")
                return "indent"
            tok = self.peek()
            raise SproutError(f"Expected a newline after ':' at {tok.line}:{tok.col}")
        if self.match("BLOOM"):
            self.terminator("Expected a line ending after bloom")
            if self.match("INDENT"):
                return "bloom-indent"
            return "bloom"
        tok = self.peek()
        raise SproutError(f"{message}: expected '{{', ':', or bloom at {tok.line}:{tok.col}")

    def block_done(self, style: str) -> bool:
        if style == "brace":
            return self.check("}")
        if style == "indent":
            return self.check("DEDENT")
        if style == "bloom-indent":
            return self.check("DEDENT", "END")
        return self.check("END")

    def block_end(self, style: str, message: str) -> None:
        if style == "brace":
            self.consume("}", message)
        elif style == "indent":
            self.consume("DEDENT", message)
        elif style == "bloom-indent":
            if self.match("DEDENT"):
                self.skip_newlines()
            self.consume("END", message)
        else:
            self.consume("END", message)

    def expression(self) -> Any:
        return self.or_expr()

    def or_expr(self) -> Any:
        expr = self.and_expr()
        while self.match("OR"):
            expr = ("binary", "or", expr, self.and_expr())
        return expr

    def and_expr(self) -> Any:
        expr = self.equality()
        while self.match("AND"):
            expr = ("binary", "and", expr, self.equality())
        return expr

    def equality(self) -> Any:
        expr = self.comparison()
        while self.match("==", "!="):
            op = self.previous().kind
            expr = ("binary", op, expr, self.comparison())
        return expr

    def comparison(self) -> Any:
        expr = self.term()
        while self.match("<", "<=", ">", ">=", "IN"):
            op = self.previous().kind
            if op == "IN":
                op = "in"
            expr = ("binary", op, expr, self.term())
        return expr

    def term(self) -> Any:
        expr = self.factor()
        while self.match("+", "-"):
            op = self.previous().kind
            expr = ("binary", op, expr, self.factor())
        return expr

    def factor(self) -> Any:
        expr = self.unary()
        while self.match("*", "/", "//", "%"):
            op = self.previous().kind
            expr = ("binary", op, expr, self.unary())
        return expr

    def unary(self) -> Any:
        if self.match("!", "-", "NOT"):
            op = self.previous().kind
            if op == "NOT":
                op = "!"
            return ("unary", op, self.unary())
        return self.call()

    def call(self) -> Any:
        expr = self.primary()
        while True:
            if self.match("("):
                call_token = self.previous()
                call_line = call_token.line
                call_col = call_token.col
                arg_parts = []
                kw_parts = []
                saw_kwarg = False
                self.skip_newlines()
                if not self.check(")"):
                    while True:
                        if self.match("**"):
                            saw_kwarg = True
                            kw_parts.append(("spread", self.expression()))
                        elif self.match("*"):
                            if saw_kwarg:
                                tok = self.previous()
                                raise SproutError(f"Positional spread cannot follow keyword argument at {tok.line}:{tok.col}")
                            arg_parts.append(("spread", self.expression()))
                        elif self.check("IDENT") and self.peek_next().kind == "=":
                            saw_kwarg = True
                            name = self.consume("IDENT", "Expected keyword name").value
                            self.consume("=", "Expected '=' after keyword name")
                            kw_parts.append(("pair", name, self.expression()))
                        else:
                            if saw_kwarg:
                                tok = self.peek()
                                raise SproutError(f"Positional argument cannot follow keyword argument at {tok.line}:{tok.col}")
                            arg_parts.append(("value", self.expression()))
                        self.skip_newlines()
                        if not self.match(","):
                            break
                        self.skip_newlines()
                self.consume(")", "Expected ')' after arguments")
                expr = ("call", expr, arg_parts, kw_parts, call_line, call_col)
            elif self.match("["):
                self.skip_newlines()
                if self.match(":"):
                    start = None
                    end = None if self.check("]") else self.expression()
                    self.skip_newlines()
                    self.consume("]", "Expected ']' after slice")
                    expr = ("slice", expr, start, end)
                    continue
                index = self.expression()
                self.skip_newlines()
                if self.match(":"):
                    self.skip_newlines()
                    end = None if self.check("]") else self.expression()
                    self.skip_newlines()
                    self.consume("]", "Expected ']' after slice")
                    expr = ("slice", expr, index, end)
                    continue
                self.consume("]", "Expected ']' after index")
                expr = ("index", expr, index)
            elif self.match("."):
                name = self.consume("IDENT", "Expected property name after '.'")
                expr = ("get", expr, name.value)
            else:
                break
        return expr

    def primary(self) -> Any:
        if self.match("NUMBER", "STRING"):
            return ("literal", self.previous().value)
        if self.match("TRUE"):
            return ("literal", True)
        if self.match("FALSE"):
            return ("literal", False)
        if self.match("NIL", "NONE"):
            return ("literal", None)
        if self.match("SUPER"):
            self.consume(".", "Expected '.' after super")
            method = self.consume("IDENT", "Expected superclass method name after super.")
            return ("super", method.value)
        if self.match("SEEDFN"):
            return self.seedfn_expr()
        if self.match("IDENT"):
            return ("var", self.previous().value)
        if self.match("["):
            items = []
            self.skip_newlines()
            if not self.check("]"):
                while True:
                    items.append(self.expression())
                    self.skip_newlines()
                    if not self.match(","):
                        break
                    self.skip_newlines()
            self.consume("]", "Expected ']' after array literal")
            return ("array", items)
        if self.match("{"):
            pairs = []
            self.skip_newlines()
            if not self.check("}"):
                while True:
                    key = self.expression()
                    self.skip_newlines()
                    self.consume(":", "Expected ':' between dictionary key and value")
                    self.skip_newlines()
                    value = self.expression()
                    pairs.append((key, value))
                    self.skip_newlines()
                    if not self.match(","):
                        break
                    self.skip_newlines()
            self.consume("}", "Expected '}' after dictionary literal")
            return ("dict", pairs)
        if self.match("("):
            self.skip_newlines()
            expr = self.expression()
            self.skip_newlines()
            self.consume(")", "Expected ')' after expression")
            return expr
        tok = self.peek()
        raise SproutError(f"Expected expression at {tok.line}:{tok.col}")

    def match(self, *kinds: str) -> bool:
        if self.check(*kinds):
            self.i += 1
            return True
        return False

    def check(self, *kinds: str) -> bool:
        return self.peek().kind in kinds

    def consume(self, kind: str, message: str) -> Token:
        if self.check(kind):
            self.i += 1
            return self.previous()
        tok = self.peek()
        raise SproutError(f"{message} at {tok.line}:{tok.col}")

    def skip_newlines(self) -> None:
        while self.match("NEWLINE", ";"):
            pass

    def at_statement_end(self) -> bool:
        return self.check("NEWLINE", ";", "}", "DEDENT", "END", "EOF")

    def terminator(self, message: str) -> None:
        if self.match(";"):
            self.skip_newlines()
            return
        if self.match("NEWLINE"):
            self.skip_newlines()
            return
        if self.check("}", "DEDENT", "END", "EOF"):
            return
        tok = self.peek()
        raise SproutError(f"{message} at {tok.line}:{tok.col}")

    def peek(self) -> Token:
        return self.tokens[self.i]

    def peek_next(self) -> Token:
        return self.tokens[self.i + 1] if self.i + 1 < len(self.tokens) else self.tokens[-1]

    def previous(self) -> Token:
        return self.tokens[self.i - 1]
