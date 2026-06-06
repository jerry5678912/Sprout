from __future__ import annotations

from dataclasses import dataclass, field
import contextlib
import io
import os
import re
import sys
import time
from typing import Any

from .model import SproutError, SproutRaised
from .runtime import (
    Builtin,
    Env,
    Interpreter,
    NativeMethod,
    attach_error_source,
    bind_arguments,
    format_value,
    iterable_values,
    native_runtime_error,
    truthy,
)
from .tooling import module_search_paths_for, parse_source, read_source_file, run_file


class BytecodeUnsupported(SproutError):
    pass


@dataclass
class Instruction:
    op: str
    arg: Any = None
    line: int | None = None
    col: int | None = None
    source: str | None = None
    context: str = "<module>"


@dataclass
class CodeObject:
    name: str
    instructions: list[Instruction] = field(default_factory=list)
    params: list[tuple[str, Any, bool, bool]] = field(default_factory=list)
    source_path: str | None = None


@dataclass
class DebugFrame:
    code: CodeObject
    env: Env
    instruction: Instruction | None = None
    ip: int = 0


@dataclass
class VMFunction:
    name: str
    code: CodeObject
    closure: Env

    def call(self, vm: "BytecodeVM", args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        env = Env(self.closure, is_scope_boundary=True)
        bound = bind_arguments(self.name, self.code.params, args, kwargs or {}, vm.interpreter, self.closure)
        for name, value in bound:
            env.define(name, value)
        started = time.perf_counter()
        vm.call_counts[self.name] = vm.call_counts.get(self.name, 0) + 1
        try:
            return vm.run_code(self.code, env)
        finally:
            vm.call_times[self.name] = vm.call_times.get(self.name, 0.0) + (time.perf_counter() - started)

    def __repr__(self) -> str:
        return f"<vm-fn {self.name}>"


class VMBoundMethod:
    def __init__(self, function: VMFunction, instance: "VMInstance"):
        self.function = function
        self.instance = instance

    def call(self, vm: "BytecodeVM", args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        return self.function.call(vm, [self.instance, *args], kwargs or {})

    def __repr__(self) -> str:
        return f"<vm-method {self.function.name}>"


class VMClass:
    def __init__(self, name: str, methods: dict[str, VMFunction], superclass: "VMClass | None" = None):
        self.name = name
        self.methods = methods
        self.superclass = superclass

    def call(self, vm: "BytecodeVM", args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        instance = VMInstance(self)
        init = self.find_method("init")
        if init:
            VMBoundMethod(init, instance).call(vm, args, kwargs or {})
        elif args or kwargs:
            raise SproutError(f"{self.name} expected 0 args, got {len(args) + len(kwargs or {})}")
        return instance

    def find_method(self, name: str) -> VMFunction | None:
        if name in self.methods:
            return self.methods[name]
        if self.superclass:
            return self.superclass.find_method(name)
        return None

    def __repr__(self) -> str:
        return f"<vm-class {self.name}>"


class VMInstance:
    def __init__(self, klass: VMClass):
        self.klass = klass
        self.fields: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        if name in self.fields:
            return self.fields[name]
        method = self.klass.find_method(name)
        if method:
            return VMBoundMethod(method, self)
        raise SproutError(f"{self.klass.name} has no property '{name}'")

    def set(self, name: str, value: Any) -> None:
        self.fields[name] = value

    def __repr__(self) -> str:
        return f"<{self.klass.name} vm-instance>"


class Compiler:
    def __init__(self, source_path: str | None = None, source: str | None = None):
        self.source_path = source_path
        self.code = CodeObject("<module>", source_path=source_path)
        self.loop_stack: list[tuple[list[int], list[int]]] = []
        self.source_lines = (source or "").splitlines()
        self.scan_line = 0
        self.current_line: int | None = None
        self.current_col: int | None = None

    def compile(self, program: list[Any]) -> CodeObject:
        for stmt in program:
            self.statement(stmt)
        if self.current_line is None and self.source_lines:
            self.current_line = len(self.source_lines)
            self.current_col = 1
        self.emit("HALT")
        return self.code

    def emit(self, op: str, arg: Any = None, line: int | None = None, col: int | None = None) -> int:
        self.code.instructions.append(
            Instruction(
                op,
                arg,
                line if line is not None else self.current_line,
                col if col is not None else self.current_col,
                self.source_path,
                self.code.name,
            )
        )
        return len(self.code.instructions) - 1

    def patch(self, index: int, target: int) -> None:
        self.code.instructions[index].arg = target

    def locate_statement(self, stmt: Any) -> tuple[int | None, int | None]:
        kind = stmt[0]
        if kind == "fn":
            self.scan_line = max(self.scan_line, stmt[4])
            return stmt[4], stmt[5]
        if kind == "test":
            self.scan_line = max(self.scan_line, stmt[3])
            return stmt[3], stmt[4]
        patterns = {
            "let": rf"^\s*(?:let|sprout)\s+{re.escape(str(stmt[1]))}\b",
            "import": r"^\s*import\b",
            "importpython": r"^\s*importpython\b",
            "class": rf"^\s*class\s+{re.escape(str(stmt[1]))}\b",
            "if": r"^\s*(?:if|elif|else\s+if)\b",
            "while": r"^\s*(?:while|whirl)\b",
            "for": r"^\s*(?:for|each)\b",
            "try": r"^\s*try\b",
            "raise": r"^\s*raise\b",
            "return": r"^\s*(?:return|pluck)\b",
            "break": r"^\s*break\b",
            "continue": r"^\s*continue\b",
            "say": r"^\s*say\b",
            "assign": r"^\s*[A-Za-z_][A-Za-z0-9_.\[\]:]*\s*=",
            "expr": r"^\s*\S",
        }
        pattern = patterns.get(kind)
        if not pattern:
            return self.current_line, self.current_col
        for index in range(self.scan_line, len(self.source_lines)):
            line = self.source_lines[index]
            if re.search(pattern, line):
                self.scan_line = index + 1
                return index + 1, len(line) - len(line.lstrip()) + 1
        if self.scan_line:
            return self.scan_line, 1
        return self.current_line, self.current_col

    def statement(self, stmt: Any) -> None:
        previous_location = self.current_line, self.current_col
        self.current_line, self.current_col = self.locate_statement(stmt)
        kind = stmt[0]
        if kind == "let":
            self.expression(stmt[2])
            self.emit("STORE_NAME", stmt[1])
        elif kind == "assign" and stmt[1][0] == "var":
            self.expression(stmt[2])
            self.emit("STORE_NAME", stmt[1][1])
        elif kind == "assign" and stmt[1][0] == "get":
            self.expression(stmt[1][1])
            self.expression(stmt[2])
            self.emit("SET_PROPERTY", stmt[1][2])
        elif kind == "assign" and stmt[1][0] == "index":
            self.expression(stmt[1][1])
            self.expression(stmt[1][2])
            self.expression(stmt[2])
            self.emit("SET_INDEX")
        elif kind == "assign" and stmt[1][0] == "slice":
            self.expression(stmt[1][1])
            self.emit("LOAD_CONST", None) if stmt[1][2] is None else self.expression(stmt[1][2])
            self.emit("LOAD_CONST", None) if stmt[1][3] is None else self.expression(stmt[1][3])
            self.expression(stmt[2])
            self.emit("SET_SLICE")
        elif kind == "import":
            self.emit("IMPORT_SPROUT", (stmt[1], stmt[2]))
            self.emit("STORE_NAME", stmt[2])
        elif kind == "importpython":
            self.emit("IMPORT_PYTHON", stmt[1])
            self.emit("STORE_NAME", stmt[2])
        elif kind == "test":
            pass
        elif kind == "say":
            for expr in stmt[1]:
                self.expression(expr)
            self.emit("CALL_BUILTIN", ("say", len(stmt[1])))
            self.emit("POP")
        elif kind == "expr":
            self.expression(stmt[1])
            self.emit("POP")
        elif kind == "if":
            self.expression(stmt[1])
            jump_false = self.emit("JUMP_IF_FALSE", None)
            self.emit("POP")
            for child in stmt[2]:
                self.statement(child)
            jump_end = self.emit("JUMP", None)
            else_start = len(self.code.instructions)
            self.patch(jump_false, else_start)
            self.emit("POP")
            for child in stmt[3]:
                self.statement(child)
            self.patch(jump_end, len(self.code.instructions))
        elif kind == "while":
            loop_start = len(self.code.instructions)
            breaks: list[int] = []
            continues: list[int] = []
            self.loop_stack.append((breaks, continues))
            self.expression(stmt[1])
            jump_false = self.emit("JUMP_IF_FALSE", None)
            self.emit("POP")
            for child in stmt[2]:
                self.statement(child)
            for index in continues:
                self.patch(index, loop_start)
            self.emit("JUMP", loop_start)
            loop_end = len(self.code.instructions)
            self.patch(jump_false, loop_end)
            self.emit("POP")
            for index in breaks:
                self.patch(index, loop_end)
            self.loop_stack.pop()
        elif kind == "for":
            self.expression(stmt[2])
            self.emit("ITER_START")
            loop_start = len(self.code.instructions)
            breaks = []
            continues = []
            self.loop_stack.append((breaks, continues))
            jump_done = self.emit("ITER_NEXT", None)
            self.emit("STORE_NAME", stmt[1])
            for child in stmt[3]:
                self.statement(child)
            for index in continues:
                self.patch(index, loop_start)
            self.emit("JUMP", loop_start)
            loop_end = len(self.code.instructions)
            self.patch(jump_done, loop_end)
            self.emit("POP")
            for index in breaks:
                self.patch(index, loop_end)
            self.loop_stack.pop()
        elif kind == "break":
            if not self.loop_stack:
                raise BytecodeUnsupported("break outside a loop")
            self.loop_stack[-1][0].append(self.emit("JUMP", None))
        elif kind == "continue":
            if not self.loop_stack:
                raise BytecodeUnsupported("continue outside a loop")
            self.loop_stack[-1][1].append(self.emit("JUMP", None))
        elif kind == "fn":
            params = stmt[2]
            child = Compiler(self.source_path)
            child.code = CodeObject(stmt[1], params=params, source_path=self.source_path)
            child.source_lines = self.source_lines
            child.scan_line = self.scan_line
            for body_stmt in stmt[3]:
                child.statement(body_stmt)
            self.scan_line = child.scan_line
            child.emit("LOAD_CONST", None, stmt[4], stmt[5])
            child.emit("RETURN", None, stmt[4], stmt[5])
            self.emit("MAKE_FUNCTION", (stmt[1], child.code))
            self.emit("STORE_NAME", stmt[1])
        elif kind == "class":
            superclass = stmt[2]
            if superclass:
                self.expression(("var", superclass))
            else:
                self.emit("LOAD_CONST", None)
            method_codes = []
            for method in stmt[3]:
                child = Compiler(self.source_path)
                child.code = CodeObject(f"{stmt[1]}.{method[1]}", params=method[2], source_path=self.source_path)
                child.source_lines = self.source_lines
                child.scan_line = max(self.scan_line, method[4])
                for body_stmt in method[3]:
                    child.statement(body_stmt)
                self.scan_line = child.scan_line
                child.emit("LOAD_CONST", None, method[4], method[5])
                child.emit("RETURN", None, method[4], method[5])
                method_codes.append((method[1], child.code))
            self.emit("MAKE_CLASS", (stmt[1], method_codes))
            self.emit("STORE_NAME", stmt[1])
        elif kind == "try":
            start = self.emit("TRY_START", (None, stmt[2]))
            for child in stmt[1]:
                self.statement(child)
            self.emit("TRY_END")
            jump_end = self.emit("JUMP", None)
            handler = len(self.code.instructions)
            self.patch(start, (handler, stmt[2]))
            for child in stmt[3]:
                self.statement(child)
            self.patch(jump_end, len(self.code.instructions))
        elif kind == "raise":
            self.expression(stmt[1])
            self.emit("RAISE")
        elif kind == "return":
            if stmt[1] is None:
                self.emit("LOAD_CONST", None)
            else:
                self.expression(stmt[1])
            self.emit("RETURN")
        else:
            raise BytecodeUnsupported(f"Statement '{kind}' is not supported by the experimental VM yet")
        self.current_line, self.current_col = previous_location

    def expression(self, expr: Any) -> None:
        kind = expr[0]
        if kind == "literal":
            self.emit("LOAD_CONST", expr[1])
        elif kind == "var":
            self.emit("LOAD_NAME", expr[1])
        elif kind == "array":
            for item in expr[1]:
                self.expression(item)
            self.emit("BUILD_ARRAY", len(expr[1]))
        elif kind == "dict":
            for key, value in expr[1]:
                self.expression(key)
                self.expression(value)
            self.emit("BUILD_DICT", len(expr[1]))
        elif kind == "seedfn":
            child = Compiler(self.source_path)
            child.code = CodeObject("<seedfn>", params=expr[1], source_path=self.source_path)
            child.source_lines = self.source_lines
            child.scan_line = max(self.scan_line, expr[3])
            child.current_line = expr[3]
            child.current_col = expr[4]
            for body_stmt in expr[2]:
                child.statement(body_stmt)
            child.emit("LOAD_CONST", None)
            child.emit("RETURN")
            self.emit("MAKE_FUNCTION", ("<seedfn>", child.code), expr[3], expr[4])
        elif kind == "unary":
            self.expression(expr[2])
            self.emit("UNARY", expr[1])
        elif kind == "binary":
            if expr[1] in {"and", "or"}:
                self.expression(expr[2])
                jump = self.emit("JUMP_IF_FALSE" if expr[1] == "and" else "JUMP_IF_TRUE", None)
                self.emit("POP")
                self.expression(expr[3])
                self.patch(jump, len(self.code.instructions))
            else:
                self.expression(expr[2])
                self.expression(expr[3])
                self.emit("BINARY", expr[1])
        elif kind == "index":
            self.expression(expr[1])
            self.expression(expr[2])
            self.emit("GET_INDEX")
        elif kind == "slice":
            self.expression(expr[1])
            self.emit("LOAD_CONST", None) if expr[2] is None else self.expression(expr[2])
            self.emit("LOAD_CONST", None) if expr[3] is None else self.expression(expr[3])
            self.emit("GET_SLICE")
        elif kind == "get":
            self.expression(expr[1])
            self.emit("GET_PROPERTY", expr[2])
        elif kind == "call":
            self.expression(expr[1])
            self.emit("BUILD_ARGS")
            for part in expr[2]:
                self.expression(part[1])
                self.emit("EXTEND_ARGS" if part[0] == "spread" else "ADD_ARG")
            self.emit("BUILD_KWARGS")
            for part in expr[3]:
                self.expression(part[1] if part[0] == "spread" else part[2])
                self.emit("UPDATE_KWARGS" if part[0] == "spread" else "SET_KWARG", None if part[0] == "spread" else part[1])
            self.emit("CALL_EX", None, expr[4], expr[5])
        elif kind == "super":
            self.emit("LOAD_SUPER_METHOD", expr[1])
        else:
            raise BytecodeUnsupported(f"Expression '{kind}' is not supported by the experimental VM yet")


class BytecodeVM:
    def __init__(
        self,
        source_path: str | None = None,
        argv: list[str] | None = None,
        debug: bool = False,
        breakpoints: set[tuple[str | None, int]] | None = None,
        debug_controller: Any = None,
    ):
        self.interpreter = Interpreter(source_path=source_path, argv=argv or [], module_search_paths=module_search_paths_for(source_path))
        self.globals = self.interpreter.globals
        self.stack: list[Any] = []
        self.ip = 0
        self.current_code: CodeObject | None = None
        self.handlers: list[tuple[int, str, Env, int]] = []
        self.instruction_count = 0
        self.call_counts: dict[str, int] = {}
        self.call_times: dict[str, float] = {}
        self.debug = debug
        self.breakpoints = breakpoints or set()
        self.source_cache: dict[str, list[str]] = {}
        self.debug_controller = debug_controller
        self.debug_frames: list[DebugFrame] = []

    def run(self, code: CodeObject) -> Any:
        env = Env(self.globals, is_scope_boundary=True)
        return self.run_code(code, env)

    def run_code(self, code: CodeObject, env: Env) -> Any:
        previous_stack = self.stack
        previous_ip = self.ip
        previous_code = self.current_code
        previous_handlers = self.handlers
        self.stack = []
        self.ip = 0
        self.current_code = code
        self.handlers = []
        frame = DebugFrame(code, env)
        self.debug_frames.append(frame)
        try:
            instructions = code.instructions
            while self.ip < len(instructions):
                instr = instructions[self.ip]
                self.ip += 1
                frame.instruction = instr
                frame.ip = self.ip - 1
                self.instruction_count += 1
                if self.debug_controller is not None:
                    self.debug_controller.before_instruction(self, instr, env)
                if self.debug:
                    self.debug_hook(instr, env)
                try:
                    result = self.execute(instr, env)
                except (SproutRaised, SproutError) as exc:
                    if not self.handlers:
                        if self.debug_controller is not None and hasattr(self.debug_controller, "on_exception"):
                            self.debug_controller.on_exception(self, exc)
                        raise
                    handler_ip, name, handler_env, stack_len = self.handlers.pop()
                    del self.stack[stack_len:]
                    handler_env.define(name, exc.value if isinstance(exc, SproutRaised) else str(exc))
                    self.ip = handler_ip
                    env = handler_env
                    continue
                if instr.op == "RETURN":
                    return result
                if instr.op == "HALT":
                    return None
            return None
        except SproutError as exc:
            instr = instructions[self.ip - 1] if instructions and self.ip else None
            if instr and instr.source and instr.line:
                if exc.line is None:
                    exc.path = exc.path or instr.source
                    exc.line = instr.line
                    exc.col = instr.col
                location = self.location_label(instr)
                if code.name == "<module>":
                    exc.add_frame(f"called at {location}")
                else:
                    exc.add_frame(f"at {code.name} ({location})")
            raise
        finally:
            self.debug_frames.pop()
            self.stack = previous_stack
            self.ip = previous_ip
            self.current_code = previous_code
            self.handlers = previous_handlers

    def location_label(self, instr: Instruction) -> str:
        path = instr.source or "<unknown>"
        if path != "<unknown>":
            try:
                path = os.path.relpath(path, os.getcwd())
            except ValueError:
                pass
        return f"{path}:{instr.line}:{instr.col}" if instr.col else f"{path}:{instr.line}"

    def debug_hook(self, instr: Instruction, env: Env) -> None:
        hit = not self.breakpoints
        if instr.line:
            source_key = os.path.abspath(instr.source) if instr.source else None
            hit = hit or (None, instr.line) in self.breakpoints or (source_key, instr.line) in self.breakpoints
        if not hit:
            return
        location = self.location_label(instr) if instr.line else "<unknown>"
        print(f"[debug] {self.current_code.name if self.current_code else '<module>'} ip={self.ip - 1} {instr.op} {format_arg(instr.arg) if instr.arg is not None else ''}".rstrip())
        print(f"[debug] location: {location}")
        line_text = self.source_line(instr)
        if line_text:
            print(f"[debug] source: {line_text}")
        print(f"[debug] stack: {format_value(self.stack)}")
        print(f"[debug] locals: {format_value(env.values)}")
        if sys.stdin.isatty():
            command = input("(sprout-debug) [enter/c/s/q] ").strip()
            if command == "q":
                raise SproutError("Debug session stopped")
            if command == "c":
                self.breakpoints.clear()

    def source_line(self, instr: Instruction) -> str:
        if not instr.source or not instr.line:
            return ""
        path = os.path.abspath(instr.source)
        if path not in self.source_cache:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self.source_cache[path] = fh.read().splitlines()
            except OSError:
                self.source_cache[path] = []
        lines = self.source_cache[path]
        return lines[instr.line - 1].strip() if 0 < instr.line <= len(lines) else ""

    def pop(self) -> Any:
        if not self.stack:
            raise SproutError("VM stack underflow")
        return self.stack.pop()

    def execute(self, instr: Instruction, env: Env) -> Any:
        op = instr.op
        if op == "LOAD_CONST":
            self.stack.append(instr.arg)
        elif op == "LOAD_NAME":
            self.stack.append(env.get(instr.arg))
        elif op == "STORE_NAME":
            env.assign(instr.arg, self.pop())
        elif op == "POP":
            self.pop()
        elif op == "BUILD_ARRAY":
            items = self.stack[-instr.arg:] if instr.arg else []
            if instr.arg:
                del self.stack[-instr.arg:]
            self.stack.append(list(items))
        elif op == "BUILD_DICT":
            values = self.stack[-instr.arg * 2:] if instr.arg else []
            if instr.arg:
                del self.stack[-instr.arg * 2:]
            out = {}
            for i in range(0, len(values), 2):
                out[values[i]] = values[i + 1]
            self.stack.append(out)
        elif op == "GET_INDEX":
            index = self.pop()
            obj = self.pop()
            self.stack.append(obj[int(index)] if isinstance(obj, list) else obj[index])
        elif op == "GET_SLICE":
            end = self.pop()
            start = self.pop()
            obj = self.pop()
            if not isinstance(obj, (list, str)):
                raise SproutError("Slice expects an array or string")
            start_value = None if start is None else int(start)
            end_value = None if end is None else int(end)
            self.stack.append(obj[start_value:end_value])
        elif op == "GET_PROPERTY":
            obj = self.pop()
            self.stack.append(obj.get(instr.arg) if isinstance(obj, VMInstance) else self.interpreter.get_property(obj, instr.arg))
        elif op == "SET_PROPERTY":
            value = self.pop()
            obj = self.pop()
            if isinstance(obj, VMInstance):
                obj.set(instr.arg, value)
            elif isinstance(obj, dict):
                obj[instr.arg] = value
            else:
                self.interpreter.assign(("get", ("literal", obj), instr.arg), value)
            self.stack.append(value)
        elif op == "SET_INDEX":
            value = self.pop()
            index = self.pop()
            obj = self.pop()
            if isinstance(obj, list):
                obj[int(index)] = value
            elif isinstance(obj, dict):
                obj[index] = value
            else:
                raise SproutError("Index assignment expects an array or dictionary")
            self.stack.append(value)
        elif op == "SET_SLICE":
            value = self.pop()
            end = self.pop()
            start = self.pop()
            obj = self.pop()
            if not isinstance(obj, list):
                raise SproutError("Slice assignment expects an array")
            if not isinstance(value, list):
                raise SproutError("Slice assignment value must be an array")
            start_value = None if start is None else int(start)
            end_value = None if end is None else int(end)
            obj[start_value:end_value] = value
            self.stack.append(value)
        elif op == "UNARY":
            value = self.pop()
            self.stack.append(-value if instr.arg == "-" else not truthy(value))
        elif op == "BINARY":
            right = self.pop()
            left = self.pop()
            self.stack.append(evaluate_binary_value(instr.arg, left, right))
        elif op == "JUMP":
            self.ip = instr.arg
        elif op == "JUMP_IF_FALSE":
            if not truthy(self.stack[-1]):
                self.ip = instr.arg
        elif op == "JUMP_IF_TRUE":
            if truthy(self.stack[-1]):
                self.ip = instr.arg
        elif op == "ITER_START":
            self.stack.append(iter(iterable_values(self.pop())))
        elif op == "ITER_NEXT":
            iterator = self.stack[-1]
            try:
                self.stack.append(next(iterator))
            except StopIteration:
                self.ip = instr.arg
        elif op == "MAKE_FUNCTION":
            name, code = instr.arg
            self.stack.append(VMFunction(name, code, env))
        elif op == "MAKE_CLASS":
            name, method_codes = instr.arg
            superclass = self.pop()
            if superclass is not None and not isinstance(superclass, VMClass):
                raise SproutError(f"Superclass '{superclass}' must be a VM class")
            method_env = env
            if superclass is not None:
                method_env = Env(env)
                method_env.define("super", superclass)
            methods = {
                method_name: VMFunction(method_name, method_code, method_env)
                for method_name, method_code in method_codes
            }
            self.stack.append(VMClass(name, methods, superclass))
        elif op == "LOAD_SUPER_METHOD":
            superclass = env.get("super")
            instance = env.get("self")
            if not isinstance(superclass, VMClass):
                raise SproutError("super is only available inside subclasses")
            if not isinstance(instance, VMInstance):
                raise SproutError("super needs a current instance")
            method = superclass.find_method(instr.arg)
            if not method:
                raise SproutError(f"Superclass {superclass.name} has no method '{instr.arg}'")
            self.stack.append(VMBoundMethod(method, instance))
        elif op == "IMPORT_SPROUT":
            path, alias = instr.arg
            self.stack.append(self.interpreter.import_sprout(path, alias))
        elif op == "IMPORT_PYTHON":
            self.stack.append(self.interpreter.import_python(instr.arg))
        elif op == "BUILD_ARGS":
            self.stack.append([])
        elif op == "ADD_ARG":
            value = self.pop()
            self.stack[-1].append(value)
        elif op == "EXTEND_ARGS":
            value = self.pop()
            if not isinstance(value, list):
                raise SproutError("Call positional spread expects an array")
            self.stack[-1].extend(value)
        elif op == "BUILD_KWARGS":
            self.stack.append({})
        elif op == "SET_KWARG":
            value = self.pop()
            kwargs = self.stack[-1]
            if instr.arg in kwargs:
                raise SproutError(f"Call got duplicate keyword '{instr.arg}'")
            kwargs[instr.arg] = value
        elif op == "UPDATE_KWARGS":
            value = self.pop()
            if not isinstance(value, dict):
                raise SproutError("Call keyword spread expects a dictionary")
            kwargs = self.stack[-1]
            for key, item in value.items():
                if not isinstance(key, str):
                    raise SproutError("Call keyword spread expects string keys")
                if key in kwargs:
                    raise SproutError(f"Call got duplicate keyword '{key}'")
                kwargs[key] = item
        elif op == "CALL_EX":
            kwargs = self.pop()
            args = self.pop()
            callee = self.pop()
            self.stack.append(call_value(self, callee, list(args), dict(kwargs)))
        elif op == "CALL":
            argc = instr.arg
            args = self.stack[-argc:] if argc else []
            if argc:
                del self.stack[-argc:]
            callee = self.pop()
            self.stack.append(call_value(self, callee, list(args), {}))
        elif op == "CALL_BUILTIN":
            name, argc = instr.arg
            args = self.stack[-argc:] if argc else []
            if argc:
                del self.stack[-argc:]
            callee = self.globals.get(name)
            self.stack.append(call_value(self, callee, list(args), {}))
        elif op == "RETURN":
            return self.pop()
        elif op == "TRY_START":
            handler_ip, name = instr.arg
            self.handlers.append((handler_ip, name, Env(env), len(self.stack)))
        elif op == "TRY_END":
            if self.handlers:
                self.handlers.pop()
        elif op == "RAISE":
            raise SproutRaised(self.pop())
        elif op == "HALT":
            return None
        else:
            raise SproutError(f"Unknown VM instruction {op}")
        return None


def call_value(vm: BytecodeVM, callee: Any, args: list[Any], kwargs: dict[str, Any]) -> Any:
    if isinstance(callee, (VMFunction, VMClass, VMBoundMethod)):
        return callee.call(vm, args, kwargs)
    if isinstance(callee, Builtin) and callee.name == "type" and len(args) == 1 and not kwargs:
        value = args[0]
        if isinstance(value, VMClass):
            return "class"
        if isinstance(value, VMInstance):
            return value.klass.name
        if isinstance(value, (VMFunction, VMBoundMethod)):
            return "function"
    if isinstance(callee, (Builtin, NativeMethod)) or hasattr(callee, "call"):
        return callee.call(vm.interpreter, args, kwargs)
    raise SproutError("Can only call functions")


def evaluate_binary_value(op: str, left: Any, right: Any) -> Any:
    try:
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right
        if op == "//":
            return left // right
        if op == "%":
            return left % right
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "in":
            return left in right
    except Exception as exc:
        raise native_runtime_error(f"operator '{op}'", exc) from None
    raise SproutError(f"Unknown operator {op}")


def compile_source(source: str, source_path: str | None = None) -> CodeObject:
    try:
        return Compiler(source_path, source).compile(parse_source(source))
    except SproutError as exc:
        attach_error_source(exc, source_path, source)
        raise


def compile_file(path: str) -> CodeObject:
    source, resolved = read_source_file(path)
    return compile_source(source, resolved)


def disassemble(code: CodeObject) -> str:
    lines = [f"== {code.name} =="]
    for index, instr in enumerate(code.instructions):
        arg = "" if instr.arg is None else f" {format_arg(instr.arg)}"
        location = f" ; {instr.source}:{instr.line}:{instr.col}" if instr.source and instr.line else ""
        lines.append(f"{index:04d} {instr.op}{arg}{location}")
        if instr.op == "MAKE_FUNCTION":
            _name, child = instr.arg
            lines.append(indent(disassemble(child)))
        elif instr.op == "MAKE_CLASS":
            _class_name, methods = instr.arg
            for _method_name, child in methods:
                lines.append(indent(disassemble(child)))
    return "\n".join(lines)


def format_arg(arg: Any) -> str:
    if isinstance(arg, CodeObject):
        return f"<code {arg.name}>"
    if isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], CodeObject):
        return f"{arg[0]} <code {arg[1].name}>"
    if isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[1], list):
        names = ",".join(name for name, _code in arg[1])
        return f"{arg[0]} methods={names}"
    if isinstance(arg, tuple) and len(arg) == 2 and isinstance(arg[0], str):
        return f"{arg[0]} {arg[1]}"
    if isinstance(arg, str):
        return arg
    return format_value(arg)


def indent(text: str) -> str:
    return "\n".join("  " + line for line in text.splitlines())


def run_file_vm(path: str, args: list[str] | None = None, fallback: bool = True) -> None:
    source, resolved = read_source_file(path)
    try:
        code = compile_source(source, resolved)
    except BytecodeUnsupported:
        if fallback:
            run_file(path, args or [])
            return
        raise
    try:
        BytecodeVM(resolved, argv=args or []).run(code)
    except SproutError as exc:
        attach_error_source(exc, resolved, source)
        raise
    except Exception as exc:
        error = native_runtime_error("VM program", exc)
        attach_error_source(error, resolved, source)
        raise error from None


def parse_breakpoint(text: str, default_path: str | None = None) -> tuple[str | None, int]:
    if ":" in text and not text.isdigit():
        path, line = text.rsplit(":", 1)
        return os.path.abspath(path), int(line)
    return (os.path.abspath(default_path) if default_path else None, int(text))


def debug_file(path: str, args: list[str] | None = None, breakpoints: list[str] | None = None) -> None:
    source, resolved = read_source_file(path)
    code = compile_source(source, resolved)
    parsed_breakpoints = {parse_breakpoint(item, resolved) for item in (breakpoints or [])}
    BytecodeVM(resolved, argv=args or [], debug=True, breakpoints=parsed_breakpoints).run(code)


def profile_file(path: str, args: list[str] | None = None) -> dict[str, Any]:
    source, resolved = read_source_file(path)
    started = time.perf_counter()
    code = compile_source(source, resolved)
    compile_seconds = time.perf_counter() - started
    vm = BytecodeVM(resolved, argv=args or [])
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        vm.run(code)
    run_seconds = time.perf_counter() - started
    return {
        "path": resolved,
        "compile_seconds": compile_seconds,
        "run_seconds": run_seconds,
        "total_seconds": compile_seconds + run_seconds,
        "instruction_count": vm.instruction_count,
        "call_counts": dict(sorted(vm.call_counts.items())),
        "call_times": dict(sorted(vm.call_times.items())),
    }


def benchmark_file(path: str, args: list[str] | None = None, repeat: int = 1) -> dict[str, Any]:
    source, resolved = read_source_file(path)
    compile_error = None
    code = None
    compile_seconds = None
    compile_started = time.perf_counter()
    try:
        code = compile_source(source, resolved)
    except BytecodeUnsupported as exc:
        compile_error = str(exc)
    finally:
        compile_seconds = time.perf_counter() - compile_started

    start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(repeat):
            run_file(path, args or [])
    tree_time = time.perf_counter() - start

    vm_time = None
    vm_instruction_count = None
    if code is not None:
        start = time.perf_counter()
        instruction_count = 0
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(repeat):
                vm = BytecodeVM(resolved, argv=args or [])
                vm.run(code)
                instruction_count += vm.instruction_count
        vm_time = time.perf_counter() - start
        vm_instruction_count = instruction_count

    ratio = None if vm_time in (None, 0) else tree_time / vm_time
    return {
        "path": resolved,
        "repeat": repeat,
        "compile_seconds": compile_seconds,
        "tree_walk_seconds": tree_time,
        "vm_seconds": vm_time,
        "vm_instruction_count": vm_instruction_count,
        "speed_ratio": ratio,
        "vm_supported": code is not None,
        "vm_unsupported": compile_error,
        "fallback_used": False,
    }
