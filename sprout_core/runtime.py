from __future__ import annotations

import difflib
import importlib
import importlib.util
import json
import math
import os
import random
import re
import statistics
import threading
import time
import traceback
import types
from dataclasses import dataclass
from typing import Any, Callable

from .lexer import Lexer
from .application import (
    AsyncStream,
    CancellationToken,
    Expectation,
    MessageQueue,
    NativeResource,
    RouteHttpServer,
    SQLiteDatabase,
    StructuredTaskGroup,
    StreamEnd,
    TaskFuture,
    convert_unit,
    http_request,
    http_request_async,
    mat_mul,
    submit_task,
    vec_add,
    vec_dot,
    vec_magnitude,
    vec_normalize,
    vec_sub,
)
from .model import BreakSignal, ContinueSignal, ReturnSignal, SproutError, SproutRaised
from .parser import Parser

class Env:
    def __init__(self, parent: Env | None = None, is_scope_boundary: bool = False):
        self.parent = parent
        self.is_scope_boundary = is_scope_boundary
        self.values: dict[str, Any] = {}

    def define(self, name: str, value: Any) -> None:
        self.values[name] = value

    def get(self, name: str) -> Any:
        env: Env | None = self
        while env:
            if name in env.values:
                return env.values[name]
            env = env.parent
        names = self.visible_names()
        suggestion = difflib.get_close_matches(name, names, n=1)
        hint = f". Did you mean '{suggestion[0]}'?" if suggestion else ""
        raise SproutError(f"Undefined variable '{name}'{hint}")

    def assign(self, name: str, value: Any) -> None:
        target = self.find_in_current_scope(name)
        if target:
            target.values[name] = value
            return
        self.nearest_scope_boundary().values[name] = value

    def find_in_current_scope(self, name: str) -> Env | None:
        env: Env | None = self
        while env:
            if name in env.values:
                return env
            if env.is_scope_boundary:
                return None
            env = env.parent
        return None

    def nearest_scope_boundary(self) -> Env:
        env: Env = self
        while env.parent and not env.is_scope_boundary:
            env = env.parent
        return env

    def visible_names(self) -> list[str]:
        names: list[str] = []
        env: Env | None = self
        while env:
            names.extend(env.values.keys())
            env = env.parent
        return sorted(set(names))


@dataclass
class Function:
    name: str
    params: list[tuple[str, Any, bool, bool]]
    body: list[Any]
    closure: Env
    source_path: str | None = None
    line: int | None = None
    col: int | None = None
    is_async: bool = False
    is_generator: bool = False

    def frame_label(self, display_name: str | None = None) -> str:
        name = display_name or self.name
        if self.source_path and self.line:
            try:
                path = os.path.relpath(self.source_path, os.getcwd())
            except ValueError:
                path = self.source_path
            if self.col:
                return f"{name} ({path}:{self.line}:{self.col})"
            return f"{name} ({path}:{self.line})"
        if self.line:
            if self.col:
                return f"{name} (<repl>:{self.line}:{self.col})"
            return f"{name} (<repl>:{self.line})"
        return name

    def call(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if self.is_generator:
            return self.invoke_generator(interpreter, args, kwargs or {})
        if self.is_async:
            return submit_task(lambda: self.invoke_async(interpreter, args, kwargs or {}))
        return self.invoke(interpreter, args, kwargs or {})

    def invoke_generator(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any]) -> GeneratorValue:
        env = Env(self.closure, is_scope_boundary=True)
        bound = bind_arguments(self.name, self.params, args, kwargs, interpreter, self.closure)
        for name, value in bound:
            env.define(name, value)
        return GeneratorValue(
            self.name,
            interpreter.generate_block(self.body, env, self.frame_label()),
            interpreter,
            env,
        )

    def invoke_async(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any]) -> Any:
        with interpreter.task_lock:
            return self.invoke(interpreter, args, kwargs)

    def invoke(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any]) -> Any:
        env = Env(self.closure, is_scope_boundary=True)
        bound = bind_arguments(self.name, self.params, args, kwargs, interpreter, self.closure)
        for name, value in bound:
            env.define(name, value)
        try:
            interpreter.execute_block(self.body, env)
        except ReturnSignal as signal:
            return signal.value
        except SproutError as exc:
            exc.add_frame(self.frame_label())
            raise
        return None


class BoundMethod:
    def __init__(self, function: Function, instance: SproutInstance):
        self.function = function
        self.instance = instance

    def call(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if self.function.is_generator:
            if not self.function.params:
                raise SproutError(f"{self.function.name} needs a self parameter")
            env = Env(self.function.closure, is_scope_boundary=True)
            env.define(self.function.params[0][0], self.instance)
            bound = bind_arguments(
                self.function.name,
                self.function.params[1:],
                args,
                kwargs or {},
                interpreter,
                self.function.closure,
            )
            for name, value in bound:
                env.define(name, value)
            return GeneratorValue(
                f"{self.instance.klass.name}.{self.function.name}",
                interpreter.generate_block(
                    self.function.body,
                    env,
                    self.function.frame_label(f"{self.instance.klass.name}.{self.function.name}"),
                ),
                interpreter,
                env,
            )
        if self.function.is_async:
            return submit_task(lambda: self.invoke_async(interpreter, args, kwargs or {}))
        return self.invoke(interpreter, args, kwargs or {})

    def invoke_async(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any]) -> Any:
        with interpreter.task_lock:
            return self.invoke(interpreter, args, kwargs)

    def invoke(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if not self.function.params:
            raise SproutError(f"{self.function.name} needs a self parameter")
        env = Env(self.function.closure, is_scope_boundary=True)
        env.define(self.function.params[0][0], self.instance)
        bound = bind_arguments(self.function.name, self.function.params[1:], args, kwargs, interpreter, self.function.closure)
        for name, value in bound:
            env.define(name, value)
        try:
            interpreter.execute_block(self.function.body, env)
        except ReturnSignal as signal:
            return signal.value
        except SproutError as exc:
            exc.add_frame(self.function.frame_label(f"{self.instance.klass.name}.{self.function.name}"))
            raise
        return None

    def __repr__(self) -> str:
        return f"<method {self.function.name}>"


class SproutClass:
    def __init__(self, name: str, methods: dict[str, Function], superclass: SproutClass | None = None):
        self.name = name
        self.methods = methods
        self.superclass = superclass

    def call(self, interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        instance = SproutInstance(self)
        init = self.find_method("init")
        if init:
            BoundMethod(init, instance).call(interpreter, args, kwargs or {})
        elif args or kwargs:
            raise SproutError(f"{self.name} expected 0 args, got {len(args) + len(kwargs or {})}")
        return instance

    def find_method(self, name: str) -> Function | None:
        if name in self.methods:
            return self.methods[name]
        if self.superclass:
            return self.superclass.find_method(name)
        return None

    def __repr__(self) -> str:
        if self.superclass:
            return f"<class {self.name} extends {self.superclass.name}>"
        return f"<class {self.name}>"


@dataclass
class SproutInterface:
    name: str
    methods: list[Any]
    type_params: list[str]

    def __repr__(self) -> str:
        return f"<interface {self.name}>"


class EnumConstructor:
    def __init__(self, enum_name: str, variant: str, fields: list[str]):
        self.enum_name = enum_name
        self.variant = variant
        self.fields = fields

    def call(self, _interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        kwargs = kwargs or {}
        if len(args) > len(self.fields):
            raise SproutError(f"{self.enum_name}.{self.variant} expected {len(self.fields)} fields")
        values = dict(zip(self.fields, args))
        for key, value in kwargs.items():
            if key not in self.fields:
                raise SproutError(f"{self.enum_name}.{self.variant} has no field '{key}'")
            if key in values:
                raise SproutError(f"{self.enum_name}.{self.variant} got multiple values for '{key}'")
            values[key] = value
        missing = [field for field in self.fields if field not in values]
        if missing:
            raise SproutError(f"{self.enum_name}.{self.variant} missing field '{missing[0]}'")
        return EnumValue(self.enum_name, self.variant, tuple((field, values[field]) for field in self.fields))

    def __repr__(self) -> str:
        return f"<enum constructor {self.enum_name}.{self.variant}>"


@dataclass(frozen=True)
class EnumValue:
    enum_name: str
    variant: str
    fields: tuple[tuple[str, Any], ...] = ()

    def get(self, name: str) -> Any:
        if name == "tag":
            return self.variant
        if name == "type":
            return self.enum_name
        for field, value in self.fields:
            if field == name:
                return value
        raise SproutError(f"{self.enum_name}.{self.variant} has no field '{name}'")

    def __repr__(self) -> str:
        if not self.fields:
            return f"{self.enum_name}.{self.variant}"
        values = ", ".join(format_value(value) for _name, value in self.fields)
        return f"{self.enum_name}.{self.variant}({values})"


class SproutEnum:
    def __init__(self, name: str, variants: list[Any]):
        self.name = name
        self.variants = {
            variant_name: [field for field, _annotation in fields]
            for variant_name, fields, _line, _col in variants
        }

    def get(self, name: str) -> Any:
        if name not in self.variants:
            raise SproutError(f"Enum {self.name} has no variant '{name}'")
        fields = self.variants[name]
        if not fields:
            return EnumValue(self.name, name)
        return EnumConstructor(self.name, name, fields)

    def __repr__(self) -> str:
        return f"<enum {self.name}>"


class GeneratorValue(NativeResource):
    def __init__(self, name: str, iterator: Any, interpreter: "Interpreter | None" = None, env: Env | None = None):
        self.name = name
        self.iterator = iter(iterator)
        self.interpreter = interpreter
        self.env = env
        self.finished = False

    def __iter__(self) -> GeneratorValue:
        return self

    def __next__(self) -> Any:
        if self.finished:
            raise StopIteration
        previous = self.interpreter.env if self.interpreter is not None else None
        if self.interpreter is not None and self.env is not None:
            self.interpreter.env = self.env
        try:
            return next(self.iterator)
        except StopIteration:
            self.finished = True
            raise
        finally:
            if self.interpreter is not None and previous is not None:
                self.interpreter.env = previous

    def get(self, name: str) -> Any:
        if name == "done":
            return self.finished
        methods = {
            "next": NativeMethod("generator.next", 0, self.next_value),
            "collect": NativeMethod("generator.collect", 0, lambda: list(self)),
        }
        if name in methods:
            return methods[name]
        return super().get(name)

    def next_value(self) -> Any:
        try:
            return next(self)
        except StopIteration:
            return None

    def __repr__(self) -> str:
        return f"<generator {self.name}>"


class SproutInstance:
    def __init__(self, klass: SproutClass):
        self.klass = klass
        self.fields: dict[str, Any] = {}

    def get(self, name: str) -> Any:
        if name in self.fields:
            return self.fields[name]
        method = self.klass.find_method(name)
        if method:
            return BoundMethod(method, self)
        raise SproutError(f"{self.klass.name} has no property '{name}'")

    def set(self, name: str, value: Any) -> None:
        self.fields[name] = value

    def __repr__(self) -> str:
        return f"<{self.klass.name} instance>"


class Builtin:
    def __init__(self, name: str, arity: int | None, fn: Callable[..., Any]):
        self.name = name
        self.arity = arity
        self.fn = fn

    def call(self, _interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if kwargs:
            raise SproutError(f"{self.name} does not accept keyword args")
        if self.arity is not None and len(args) != self.arity:
            raise SproutError(f"{self.name} expected {self.arity} args, got {len(args)}")
        try:
            return self.fn(*args)
        except (SproutError, SproutRaised):
            raise
        except Exception as exc:
            raise native_runtime_error(self.name, exc) from None

    def __repr__(self) -> str:
        return f"<builtin {self.name}>"


class NativeMethod:
    def __init__(self, name: str, arity: int | None, fn: Callable[..., Any]):
        self.name = name
        self.arity = arity
        self.fn = fn

    def call(self, _interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        if kwargs:
            raise SproutError(f"{self.name} does not accept keyword args")
        if self.arity is not None and len(args) != self.arity:
            raise SproutError(f"{self.name} expected {self.arity} args, got {len(args)}")
        try:
            return self.fn(*args)
        except (SproutError, SproutRaised):
            raise
        except Exception as exc:
            raise native_runtime_error(self.name, exc) from None

    def __repr__(self) -> str:
        return f"<method {self.name}>"


class PythonModule:
    def __init__(self, module: types.ModuleType):
        self.module = module

    def get(self, name: str) -> Any:
        if name.startswith("_"):
            raise SproutError("Private Python names are not available")
        try:
            return wrap_python_value(getattr(self.module, name), f"{self.module.__name__}.{name}")
        except AttributeError:
            raise SproutError(f"Python module {self.module.__name__} has no name '{name}'")

    def __repr__(self) -> str:
        return f"<python module {self.module.__name__}>"


class PythonCallable:
    def __init__(self, name: str, fn: Callable[..., Any]):
        self.name = name
        self.fn = fn

    def call(self, _interpreter: Interpreter, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        try:
            py_kwargs = {key: unwrap_sprout_value(value) for key, value in (kwargs or {}).items()}
            return wrap_python_value(self.fn(*[unwrap_sprout_value(arg) for arg in args], **py_kwargs), self.name)
        except Exception as exc:
            error = SproutError(
                f"Python bridge call '{self.name}' failed: {clean_native_message(exc)}",
                category="InteropError",
                hint="Check the values passed to the imported Python function.",
            )
            add_native_trace(error, exc, f"python bridge {self.name}")
            raise error from None

    def __repr__(self) -> str:
        return f"<python function {self.name}>"


class PythonObject:
    def __init__(self, value: Any, name: str = "python-object"):
        self.value = value
        self.name = name

    def get(self, name: str) -> Any:
        if name.startswith("_"):
            raise SproutError("Private Python names are not available")
        try:
            return wrap_python_value(getattr(self.value, name), f"{self.name}.{name}")
        except AttributeError:
            raise SproutError(f"Python object {self.name} has no name '{name}'")

    def set(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            raise SproutError("Private Python names are not available")
        try:
            setattr(self.value, name, unwrap_sprout_value(value))
        except Exception as exc:
            error = SproutError(
                f"Could not set Python bridge field '{self.name}.{name}': {clean_native_message(exc)}",
                category="InteropError",
            )
            add_native_trace(error, exc, f"python bridge {self.name}.{name}")
            raise error from None

    def __repr__(self) -> str:
        return f"<python object {self.name}>"


class SproutModule:
    def __init__(self, name: str, path: str, env: Env):
        self.name = name
        self.path = path
        self.env = env

    def get(self, name: str) -> Any:
        if name.startswith("_"):
            raise SproutError("Private Sprout module names start with '_'")
        return self.env.get(name)

    def __repr__(self) -> str:
        return f"<sprout module {self.name}>"


class Interpreter:
    @property
    def env(self) -> Env:
        return getattr(self._thread_state, "env", self.globals)

    @env.setter
    def env(self, value: Env) -> None:
        self._thread_state.env = value

    def __init__(
        self,
        source_path: str | None = None,
        argv: list[str] | None = None,
        module_cache: dict[str, SproutModule] | None = None,
        module_search_paths: list[str] | None = None,
    ):
        self.globals = Env(is_scope_boundary=True)
        self._thread_state = threading.local()
        self.env = self.globals
        self.source_path = os.path.abspath(source_path) if source_path else None
        self.current_dir = os.path.dirname(self.source_path) if self.source_path else os.getcwd()
        self.argv = argv or []
        self.module_cache = module_cache if module_cache is not None else {}
        self.module_search_paths = [os.path.abspath(path) for path in (module_search_paths or [])]
        self.task_lock = threading.RLock()
        self.install_builtins()

    def install_builtins(self) -> None:
        self.globals.define("print", Builtin("print", None, lambda *xs: print(*map(format_value, xs))))
        self.globals.define("say", self.globals.get("print"))
        self.globals.define("len", Builtin("len", 1, len))
        self.globals.define("push", Builtin("push", 2, self.builtin_push))
        self.globals.define("range", Builtin("range", 1, lambda n: list(range(int(n)))))
        self.globals.define("str", Builtin("str", 1, format_value))
        self.globals.define("int", Builtin("int", 1, lambda x: int(x)))
        self.globals.define("num", Builtin("num", 1, lambda x: float(x)))
        self.globals.define("type", Builtin("type", 1, type_name))
        self.globals.define("keys", Builtin("keys", 1, lambda d: list(require_dict(d).keys())))
        self.globals.define("values", Builtin("values", 1, lambda d: list(require_dict(d).values())))
        self.globals.define("items", Builtin("items", 1, lambda d: [[k, v] for k, v in require_dict(d).items()]))
        self.globals.define("has", Builtin("has", 2, lambda d, k: k in require_dict(d)))
        self.globals.define("get", Builtin("get", None, self.builtin_get))
        self.globals.define("sparkle", Builtin("sparkle", 1, lambda x: f"* {format_value(x)} *"))
        self.globals.define("whisper", Builtin("whisper", 1, lambda x: str(x).lower()))
        self.globals.define("shout", Builtin("shout", 1, lambda x: str(x).upper()))
        self.globals.define("mirror", Builtin("mirror", 1, self.builtin_mirror))
        self.globals.define("chant", Builtin("chant", 2, self.builtin_chant))
        self.globals.define("weave", Builtin("weave", 2, self.builtin_weave))
        self.globals.define("grow", Builtin("grow", 2, self.builtin_grow))
        self.globals.define("plant", Builtin("plant", 3, self.builtin_plant))
        self.globals.define("harvest", Builtin("harvest", 1, self.builtin_harvest))
        self.globals.define("prune", Builtin("prune", 2, self.builtin_prune))
        self.globals.define("sprinkle", Builtin("sprinkle", 2, self.builtin_sprinkle))
        self.globals.define("bundle", Builtin("bundle", 2, self.builtin_bundle))
        self.globals.define("first", Builtin("first", 1, lambda xs: xs[0]))
        self.globals.define("last", Builtin("last", 1, lambda xs: xs[-1]))
        self.globals.define("rest", Builtin("rest", 1, lambda xs: xs[1:]))
        self.globals.define("unique", Builtin("unique", 1, unique_values))
        self.globals.define("countby", Builtin("countby", 1, count_by))
        self.globals.define("zipbud", Builtin("zipbud", 2, self.builtin_zipbud))
        self.globals.define("dice", Builtin("dice", 1, lambda sides: random.randint(1, int(sides))))
        self.globals.define("choose", Builtin("choose", 1, self.builtin_choose))
        self.globals.define("clamp", Builtin("clamp", 3, lambda x, low, high: max(low, min(high, x))))
        self.globals.define("wrap", Builtin("wrap", 3, self.builtin_wrap))
        self.globals.define("dist", Builtin("dist", 4, lambda x1, y1, x2, y2: math.hypot(x2 - x1, y2 - y1)))
        self.globals.define("sleep", Builtin("sleep", 1, lambda seconds: time.sleep(float(seconds))))
        self.globals.define("now", Builtin("now", 0, time.time))
        self.globals.define("ask", Builtin("ask", 1, lambda prompt: input(format_value(prompt))))
        self.globals.define("clear", Builtin("clear", 0, lambda: print("\033[2J\033[H", end="")))
        self.globals.define("argv", self.argv)
        self.globals.define("readfile", Builtin("readfile", 1, self.builtin_readfile))
        self.globals.define("writefile", Builtin("writefile", 2, self.builtin_writefile))
        self.globals.define("appendfile", Builtin("appendfile", 2, self.builtin_appendfile))
        self.globals.define("exists", Builtin("exists", 1, self.builtin_exists))
        self.globals.define("isfile", Builtin("isfile", 1, self.builtin_isfile))
        self.globals.define("isdir", Builtin("isdir", 1, self.builtin_isdir))
        self.globals.define("listdir", Builtin("listdir", 1, self.builtin_listdir))
        self.globals.define("mkdir", Builtin("mkdir", 1, self.builtin_mkdir))
        self.globals.define("readjson", Builtin("readjson", 1, self.builtin_readjson))
        self.globals.define("writejson", Builtin("writejson", 2, self.builtin_writejson))
        self.globals.define("py_available", Builtin("py_available", 1, self.builtin_py_available))
        self.globals.define("py_import", Builtin("py_import", 1, self.builtin_py_import))
        self.globals.define("lines", Builtin("lines", 1, lambda text: str(text).splitlines()))
        self.globals.define("ensure", Builtin("ensure", 2, self.builtin_ensure))
        self.globals.define("fail", Builtin("fail", 1, self.builtin_fail))
        self.globals.define("expect", Builtin("expect", 1, Expectation))
        self.globals.define("task_spawn", Builtin("task_spawn", None, self.builtin_task_spawn))
        self.globals.define("task_after", Builtin("task_after", None, self.builtin_task_after))
        self.globals.define("task_wait_all", Builtin("task_wait_all", 1, self.builtin_task_wait_all))
        self.globals.define("queue_open", Builtin("queue_open", 0, MessageQueue))
        self.globals.define("stream_open", Builtin("stream_open", 0, AsyncStream))
        self.globals.define("cancel_token", Builtin("cancel_token", 0, CancellationToken))
        self.globals.define("sleep_async", Builtin("sleep_async", None, self.builtin_sleep_async))
        self.globals.define("http_request", Builtin("http_request", None, http_request))
        self.globals.define("http_get", Builtin("http_get", None, self.builtin_http_get))
        self.globals.define("http_post", Builtin("http_post", None, self.builtin_http_post))
        self.globals.define("http_request_async", Builtin("http_request_async", None, http_request_async))
        self.globals.define("http_get_async", Builtin("http_get_async", None, self.builtin_http_get_async))
        self.globals.define("http_post_async", Builtin("http_post_async", None, self.builtin_http_post_async))
        self.globals.define("http_server", Builtin("http_server", None, self.builtin_http_server))
        self.globals.define("readfile_async", Builtin("readfile_async", None, self.builtin_readfile_async))
        self.globals.define("writefile_async", Builtin("writefile_async", None, self.builtin_writefile_async))
        self.globals.define("sqlite_open", Builtin("sqlite_open", 1, self.builtin_sqlite_open))
        self.globals.define("sqlite_exec", Builtin("sqlite_exec", None, self.builtin_sqlite_exec))
        self.globals.define("sqlite_query", Builtin("sqlite_query", None, self.builtin_sqlite_query))
        self.globals.define("sqlite_begin", Builtin("sqlite_begin", 1, self.builtin_sqlite_begin))
        self.globals.define("sqlite_commit", Builtin("sqlite_commit", 1, self.builtin_sqlite_commit))
        self.globals.define("sqlite_rollback", Builtin("sqlite_rollback", 1, self.builtin_sqlite_rollback))
        self.globals.define("sqlite_close", Builtin("sqlite_close", 1, self.builtin_sqlite_close))
        self.install_standard_library()

    def define_builtin(self, name: str, arity: int | None, fn: Callable[..., Any]) -> None:
        self.globals.define(name, Builtin(name, arity, fn))

    def install_standard_library(self) -> None:
        builtins: dict[str, tuple[int | None, Callable[..., Any]]] = {
            "functions": (0, self.builtin_functions),
            "methods": (0, self.builtin_methods),
            "abs": (1, abs),
            "round": (None, round_number),
            "floor": (1, math.floor),
            "ceil": (1, math.ceil),
            "sqrt": (1, math.sqrt),
            "pow": (2, pow),
            "min": (None, lambda *xs: min(xs[0]) if len(xs) == 1 and isinstance(xs[0], list) else min(xs)),
            "max": (None, lambda *xs: max(xs[0]) if len(xs) == 1 and isinstance(xs[0], list) else max(xs)),
            "sum": (1, lambda xs: sum(require_list(xs))),
            "avg": (1, lambda xs: sum(require_list(xs)) / len(require_list(xs))),
            "median": (1, lambda xs: statistics.median(require_list(xs))),
            "sin": (1, math.sin),
            "cos": (1, math.cos),
            "tan": (1, math.tan),
            "asin": (1, math.asin),
            "acos": (1, math.acos),
            "atan": (1, math.atan),
            "atan2": (2, math.atan2),
            "log": (1, math.log),
            "log10": (1, math.log10),
            "exp": (1, math.exp),
            "radians": (1, math.radians),
            "degrees": (1, math.degrees),
            "hypot": (None, lambda *xs: math.hypot(*xs)),
            "sign": (1, lambda x: 1 if x > 0 else (-1 if x < 0 else 0)),
            "lerp": (3, lambda a, b, t: a + (b - a) * t),
            "between": (3, lambda x, low, high: low <= x <= high),
            "is_nil": (1, lambda x: x is None),
            "is_bool": (1, lambda x: isinstance(x, bool)),
            "is_number": (1, lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)),
            "is_string": (1, lambda x: isinstance(x, str)),
            "is_array": (1, lambda x: isinstance(x, list)),
            "is_dict": (1, lambda x: isinstance(x, dict)),
            "is_function": (1, lambda x: hasattr(x, "call")),
            "is_class": (1, lambda x: isinstance(x, SproutClass)),
            "is_instance": (1, lambda x: isinstance(x, SproutInstance)),
            "is_empty": (1, lambda x: len(x) == 0),
            "is_even": (1, lambda x: int(x) % 2 == 0),
            "is_odd": (1, lambda x: int(x) % 2 != 0),
            "array": (None, lambda *xs: list(xs)),
            "copy": (1, copy_value),
            "reverse": (1, lambda xs: list(reversed(require_list(xs))) if isinstance(xs, list) else str(xs)[::-1]),
            "sort": (1, lambda xs: sorted(require_list(xs))),
            "contains": (2, lambda haystack, needle: needle in haystack),
            "indexof": (2, index_of),
            "insert": (3, insert_value),
            "remove": (2, remove_value),
            "take": (2, lambda xs, n: xs[:int(n)]),
            "drop": (2, lambda xs, n: xs[int(n):]),
            "slice": (3, lambda xs, start, end: xs[int(start):int(end)]),
            "concat": (None, concat_values),
            "flatten": (1, flatten_values),
            "compact": (1, lambda xs: [x for x in require_list(xs) if x is not None]),
            "repeat": (2, lambda value, n: [copy_value(value) for _ in range(int(n))]),
            "fill": (2, lambda value, n: [value for _ in range(int(n))]),
            "enumerate": (1, lambda xs: [[i, value] for i, value in enumerate(require_list(xs))]),
            "chunks": (2, chunks),
            "trim": (1, lambda text: str(text).strip()),
            "ltrim": (1, lambda text: str(text).lstrip()),
            "rtrim": (1, lambda text: str(text).rstrip()),
            "upper": (1, lambda text: str(text).upper()),
            "lower": (1, lambda text: str(text).lower()),
            "title": (1, lambda text: str(text).title()),
            "replace": (3, lambda text, old, new: str(text).replace(str(old), str(new))),
            "startswith": (2, lambda text, prefix: str(text).startswith(str(prefix))),
            "endswith": (2, lambda text, suffix: str(text).endswith(str(suffix))),
            "substr": (3, lambda text, start, end: str(text)[int(start):int(end)]),
            "padleft": (3, lambda text, width, fill: str(text).rjust(int(width), str(fill)[0])),
            "padright": (3, lambda text, width, fill: str(text).ljust(int(width), str(fill)[0])),
            "chars": (1, lambda text: list(str(text))),
            "words": (1, lambda text: str(text).split()),
            "join": (2, lambda xs, sep: str(sep).join(format_value(x) for x in require_list(xs))),
            "dict": (None, dict_from_args),
            "merge": (None, merge_dicts),
            "pick": (2, pick_keys),
            "omit": (2, omit_keys),
            "frompairs": (1, from_pairs),
            "delkey": (2, delete_key),
            "json_parse": (1, lambda text: wrap_python_value(json.loads(str(text)))),
            "json_stringify": (1, lambda value: json.dumps(unwrap_sprout_value(value))),
            "cwd": (0, os.getcwd),
            "basename": (1, lambda path: os.path.basename(str(path))),
            "dirname": (1, lambda path: os.path.dirname(str(path))),
            "extname": (1, lambda path: os.path.splitext(str(path))[1]),
            "joinpath": (None, lambda *parts: os.path.join(*map(str, parts))),
            "rand": (0, random.random),
            "randint": (2, lambda low, high: random.randint(int(low), int(high))),
            "seed": (1, lambda value: random.seed(value)),
            "shuffle": (1, shuffle_values),
            "sample": (2, lambda xs, n: random.sample(require_list(xs), int(n))),
            "vec_add": (2, vec_add),
            "vec_sub": (2, vec_sub),
            "vec_dot": (2, vec_dot),
            "vec_magnitude": (1, vec_magnitude),
            "vec_normalize": (1, vec_normalize),
            "mat_mul": (2, mat_mul),
            "unit_convert": (3, convert_unit),
            "interpolate": (3, lambda a, b, t: float(a) + (float(b) - float(a)) * float(t)),
            "kinetic_energy": (2, lambda mass, speed: 0.5 * float(mass) * float(speed) ** 2),
            "force": (2, lambda mass, acceleration: float(mass) * float(acceleration)),
            "pressure": (2, lambda force_value, area: float(force_value) / float(area)),
        }
        for name, (arity, fn) in builtins.items():
            self.define_builtin(name, arity, fn)

    def builtin_push(self, arr: Any, value: Any) -> Any:
        if not isinstance(arr, list):
            raise SproutError("push expects an array")
        arr.append(value)
        return arr

    def builtin_get(self, d: Any, key: Any, default: Any = None) -> Any:
        return require_dict(d).get(key, default)

    def builtin_mirror(self, value: Any) -> Any:
        if isinstance(value, (list, str)):
            return value[::-1]
        return str(value)[::-1]

    def builtin_chant(self, value: Any, times: Any) -> Any:
        count = int(times)
        if isinstance(value, list):
            return value * count
        return str(value) * count

    def builtin_weave(self, values: Any, sep: Any) -> str:
        if not isinstance(values, list):
            raise SproutError("weave expects an array")
        return str(sep).join(format_value(value) for value in values)

    def builtin_grow(self, values: Any, value: Any) -> list[Any]:
        arr = require_list(values)
        arr.append(value)
        return arr

    def builtin_plant(self, values: Any, key: Any, value: Any) -> dict[Any, Any]:
        d = require_dict(values)
        d[key] = value
        return d

    def builtin_harvest(self, values: Any) -> Any:
        arr = require_list(values)
        if not arr:
            return None
        return arr.pop()

    def builtin_prune(self, values: Any, value: Any) -> list[Any]:
        arr = require_list(values)
        arr[:] = [item for item in arr if item != value]
        return arr

    def builtin_sprinkle(self, values: Any, separator: Any) -> list[Any]:
        arr = require_list(values)
        out = []
        for i, value in enumerate(arr):
            if i > 0:
                out.append(separator)
            out.append(value)
        return out

    def builtin_bundle(self, keys: Any, values: Any) -> list[list[Any]]:
        left = require_list(keys)
        right = require_list(values)
        return [[key, value] for key, value in zip(left, right)]

    def builtin_zipbud(self, keys: Any, values: Any) -> dict[Any, Any]:
        if not isinstance(keys, list) or not isinstance(values, list):
            raise SproutError("zipbud expects two arrays")
        return dict(zip(keys, values))

    def builtin_choose(self, values: Any) -> Any:
        if not isinstance(values, list):
            raise SproutError("choose expects an array")
        return random.choice(values)

    def builtin_wrap(self, value: Any, low: Any, high: Any) -> Any:
        width = high - low + 1
        if width <= 0:
            raise SproutError("wrap expects high >= low")
        return ((value - low) % width) + low

    def builtin_readfile(self, path: Any) -> str:
        try:
            with open(self.resolve_path(str(path)), "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None

    def builtin_writefile(self, path: Any, text: Any) -> Any:
        try:
            with open(self.resolve_path(str(path)), "w", encoding="utf-8") as fh:
                fh.write(format_value(text))
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None
        return None

    def builtin_appendfile(self, path: Any, text: Any) -> Any:
        try:
            with open(self.resolve_path(str(path)), "a", encoding="utf-8") as fh:
                fh.write(format_value(text))
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None
        return None

    def builtin_exists(self, path: Any) -> bool:
        return os.path.exists(self.resolve_path(str(path)))

    def builtin_isfile(self, path: Any) -> bool:
        return os.path.isfile(self.resolve_path(str(path)))

    def builtin_isdir(self, path: Any) -> bool:
        return os.path.isdir(self.resolve_path(str(path)))

    def builtin_listdir(self, path: Any) -> list[str]:
        try:
            return sorted(os.listdir(self.resolve_path(str(path))))
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None

    def builtin_mkdir(self, path: Any) -> None:
        try:
            os.makedirs(self.resolve_path(str(path)), exist_ok=True)
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None
        return None

    def builtin_readjson(self, path: Any) -> Any:
        resolved = self.resolve_path(str(path))
        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                return wrap_python_value(json.load(fh))
        except OSError as exc:
            raise SproutError(friendly_os_error(exc), category="FileError") from None
        except json.JSONDecodeError as exc:
            raise SproutError(
                f"Invalid JSON in '{resolved}' at line {exc.lineno}, column {exc.colno}: {exc.msg}",
                category="DataError",
                hint="Fix the JSON syntax near the reported position.",
            ) from None

    def builtin_writejson(self, path: Any, value: Any) -> None:
        try:
            with open(self.resolve_path(str(path)), "w", encoding="utf-8") as fh:
                json.dump(unwrap_sprout_value(value), fh, indent=2)
                fh.write("\n")
        except (OSError, TypeError) as exc:
            raise SproutError(str(exc))
        return None

    def builtin_py_available(self, module_name: Any) -> bool:
        try:
            return importlib.util.find_spec(str(module_name)) is not None
        except (ImportError, AttributeError, ValueError):
            return False

    def builtin_py_import(self, module_name: Any) -> PythonModule:
        return self.import_python(str(module_name))

    def builtin_ensure(self, condition: Any, message: Any) -> bool:
        if not truthy(condition):
            raise SproutRaised(message)
        return True

    def builtin_fail(self, message: Any) -> None:
        raise SproutRaised(message)

    def call_value(self, callable_value: Any, args: list[Any] | None = None) -> Any:
        if not hasattr(callable_value, "call"):
            raise SproutError("Task expects a callable value")
        with self.task_lock:
            return callable_value.call(self, args or [], {})

    def builtin_task_spawn(self, callable_value: Any, args: Any = None) -> Any:
        call_args = [] if args is None else require_list(args)
        return submit_task(lambda: self.call_value(callable_value, call_args))

    def builtin_task_after(self, seconds: Any, callable_value: Any, args: Any = None) -> Any:
        call_args = [] if args is None else require_list(args)
        return submit_task(lambda: self.call_value(callable_value, call_args), float(seconds))

    def builtin_task_wait_all(self, tasks: Any) -> list[Any]:
        out = []
        for task in require_list(tasks):
            if not hasattr(task, "result"):
                raise SproutError("task_wait_all expects task futures")
            out.append(task.result())
        return out

    def builtin_http_get(self, url: Any, headers: Any = None, timeout: Any = 10) -> Any:
        return http_request("GET", url, None, headers, timeout)

    def builtin_http_post(self, url: Any, data: Any = None, headers: Any = None, timeout: Any = 10) -> Any:
        return http_request("POST", url, data, headers, timeout)

    def builtin_sleep_async(self, seconds: Any, token: Any = None) -> TaskFuture:
        checked = token if isinstance(token, CancellationToken) else None
        if token is not None and checked is None:
            raise SproutError("sleep_async token must come from cancel_token()")
        return submit_task(lambda: None, float(seconds), checked)

    def builtin_http_get_async(
        self,
        url: Any,
        headers: Any = None,
        timeout: Any = 10,
        token: Any = None,
    ) -> TaskFuture:
        checked = token if isinstance(token, CancellationToken) else None
        return http_request_async("GET", url, None, headers, timeout, checked)

    def builtin_http_post_async(
        self,
        url: Any,
        data: Any = None,
        headers: Any = None,
        timeout: Any = 10,
        token: Any = None,
    ) -> TaskFuture:
        checked = token if isinstance(token, CancellationToken) else None
        return http_request_async("POST", url, data, headers, timeout, checked)

    def builtin_readfile_async(self, path: Any, token: Any = None) -> TaskFuture:
        checked = token if isinstance(token, CancellationToken) else None
        return submit_task(lambda: self.builtin_readfile(path), token=checked)

    def builtin_writefile_async(self, path: Any, value: Any, token: Any = None) -> TaskFuture:
        checked = token if isinstance(token, CancellationToken) else None
        return submit_task(lambda: self.builtin_writefile(path, value), token=checked)

    def builtin_http_server(self, routes: Any, host: Any = "127.0.0.1", port: Any = 0) -> RouteHttpServer:
        return RouteHttpServer(require_dict(routes), str(host), int(port))

    def builtin_sqlite_open(self, path: Any) -> SQLiteDatabase:
        raw = str(path)
        return SQLiteDatabase(raw if raw == ":memory:" else self.resolve_path(raw))

    def require_database(self, value: Any) -> SQLiteDatabase:
        if not isinstance(value, SQLiteDatabase):
            raise SproutError("Expected a SQLite database connection")
        return value

    def builtin_sqlite_exec(self, database: Any, sql: Any, params: Any = None) -> int:
        return self.require_database(database).execute(sql, params)

    def builtin_sqlite_query(self, database: Any, sql: Any, params: Any = None) -> list[dict[str, Any]]:
        return self.require_database(database).query(sql, params)

    def builtin_sqlite_begin(self, database: Any) -> None:
        return self.require_database(database).begin()

    def builtin_sqlite_commit(self, database: Any) -> None:
        return self.require_database(database).commit()

    def builtin_sqlite_rollback(self, database: Any) -> None:
        return self.require_database(database).rollback()

    def builtin_sqlite_close(self, database: Any) -> None:
        return self.require_database(database).close()

    def builtin_functions(self) -> list[str]:
        return sorted(name for name, value in self.globals.values.items() if hasattr(value, "call"))

    def builtin_methods(self) -> list[str]:
        return sorted(
            [
                "array.append",
                "array.pop",
                "array.len",
                "array.join",
                "dict.keys",
                "dict.values",
                "dict.items",
                "dict.get",
                "dict.has",
                "dict.set",
                "string.upper",
                "string.lower",
                "string.strip",
                "string.split",
                "string.contains",
            ]
        )

    def run(self, statements: list[Any]) -> None:
        for stmt in statements:
            self.execute(stmt)

    def execute_block(self, statements: list[Any], env: Env) -> None:
        previous = self.env
        self.env = env
        try:
            for stmt in statements:
                self.execute(stmt)
        finally:
            self.env = previous

    def execute(self, stmt: Any) -> None:
        kind = stmt[0]
        if kind == "let":
            self.env.define(stmt[1], self.evaluate(stmt[2]))
        elif kind == "import":
            self.env.define(stmt[2], self.import_sprout(stmt[1], stmt[2]))
        elif kind == "importpython":
            self.env.define(stmt[2], self.import_python(stmt[1]))
        elif kind in {"fn", "async_fn"}:
            self.env.define(
                stmt[1],
                Function(
                    stmt[1],
                    stmt[2],
                    stmt[3],
                    self.env,
                    self.source_path,
                    stmt[4],
                    stmt[5],
                    is_async=kind == "async_fn",
                    is_generator=contains_yield(stmt[3]),
                ),
            )
        elif kind == "test":
            return
        elif kind == "class":
            methods = {}
            self.env.define(stmt[1], None)
            superclass = None
            if stmt[2] is not None:
                superclass = self.env.get(stmt[2])
                if not isinstance(superclass, SproutClass):
                    raise SproutError(f"Superclass '{stmt[2]}' must be a class")
            method_env = self.env
            if superclass is not None:
                method_env = Env(self.env)
                method_env.define("super", superclass)
            for method in stmt[3]:
                methods[method[1]] = Function(
                    method[1],
                    method[2],
                    method[3],
                    method_env,
                    self.source_path,
                    method[4],
                    method[5],
                    is_async=method[0] == "async_fn",
                    is_generator=contains_yield(method[3]),
                )
            self.env.assign(stmt[1], SproutClass(stmt[1], methods, superclass))
        elif kind == "enum":
            self.env.define(stmt[1], SproutEnum(stmt[1], stmt[3]))
        elif kind == "interface":
            self.env.define(stmt[1], SproutInterface(stmt[1], stmt[3], stmt[2]))
        elif kind == "type_alias":
            return
        elif kind == "taskgroup":
            group = StructuredTaskGroup(
                lambda callable_value, args: submit_task(lambda: self.call_value(callable_value, args))
            )
            group_env = Env(self.env)
            group_env.define(stmt[1], group)
            try:
                self.execute_block(stmt[2], group_env)
                group.wait()
            except BaseException:
                group.cancel()
                group.settle()
                raise
        elif kind == "if":
            body = stmt[2] if truthy(self.evaluate(stmt[1])) else stmt[3]
            self.execute_block(body, Env(self.env))
        elif kind == "match":
            subject = self.evaluate(stmt[1])
            for pattern, guard, body, _line, _col in stmt[2]:
                bindings = match_pattern(pattern, subject)
                if bindings is None:
                    continue
                case_env = Env(self.env)
                for name, value in bindings.items():
                    case_env.define(name, value)
                previous = self.env
                self.env = case_env
                try:
                    if guard is not None and not truthy(self.evaluate(guard)):
                        continue
                    self.execute_block(body, case_env)
                    break
                finally:
                    self.env = previous
        elif kind == "while":
            while truthy(self.evaluate(stmt[1])):
                try:
                    self.execute_block(stmt[2], Env(self.env))
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
        elif kind == "for":
            loop_env = Env(self.env)
            for item in iterable_values(self.evaluate(stmt[2])):
                loop_env.assign(stmt[1], item)
                try:
                    self.execute_block(stmt[3], loop_env)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
        elif kind == "async_for":
            stream = self.evaluate(stmt[2])
            loop_env = Env(self.env)
            while True:
                item = async_next(stream)
                if item is StreamEnd:
                    break
                loop_env.assign(stmt[1], item)
                try:
                    self.execute_block(stmt[3], loop_env)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
        elif kind == "break":
            raise BreakSignal()
        elif kind == "continue":
            raise ContinueSignal()
        elif kind == "raise":
            raise SproutRaised(self.evaluate(stmt[1]))
        elif kind == "try":
            try:
                self.execute_block(stmt[1], Env(self.env))
            except SproutRaised as exc:
                catch_env = Env(self.env)
                catch_env.define(stmt[2], exc.value)
                self.execute_block(stmt[3], catch_env)
            except SproutError as exc:
                catch_env = Env(self.env)
                catch_env.define(stmt[2], str(exc))
                self.execute_block(stmt[3], catch_env)
        elif kind == "return":
            raise ReturnSignal(None if stmt[1] is None else self.evaluate(stmt[1]))
        elif kind == "yield":
            raise SproutError("yield may only be used inside a generator function")
        elif kind == "assign":
            self.assign(stmt[1], self.evaluate(stmt[2]))
        elif kind == "say":
            print(*map(format_value, (self.evaluate(arg) for arg in stmt[1])))
        elif kind == "expr":
            self.evaluate(stmt[1])
        else:
            raise SproutError(f"Unknown statement {kind}")

    def generate_block(self, statements: list[Any], env: Env, frame: str) -> Any:
        previous = self.env
        self.env = env
        try:
            try:
                yield from self.generate_statements(statements)
            except ReturnSignal:
                return
            except SproutError as exc:
                exc.add_frame(frame)
                raise
        finally:
            self.env = previous

    def generate_statements(self, statements: list[Any]) -> Any:
        for stmt in statements:
            kind = stmt[0]
            if kind == "yield":
                yield None if stmt[1] is None else self.evaluate(stmt[1])
            elif kind == "if":
                body = stmt[2] if truthy(self.evaluate(stmt[1])) else stmt[3]
                previous = self.env
                self.env = Env(previous)
                try:
                    yield from self.generate_statements(body)
                finally:
                    self.env = previous
            elif kind == "while":
                while truthy(self.evaluate(stmt[1])):
                    previous = self.env
                    self.env = Env(previous)
                    try:
                        try:
                            yield from self.generate_statements(stmt[2])
                        except ContinueSignal:
                            continue
                        except BreakSignal:
                            break
                    finally:
                        self.env = previous
            elif kind == "for":
                loop_env = Env(self.env)
                for item in iterable_values(self.evaluate(stmt[2])):
                    loop_env.assign(stmt[1], item)
                    previous = self.env
                    self.env = loop_env
                    try:
                        try:
                            yield from self.generate_statements(stmt[3])
                        except ContinueSignal:
                            continue
                        except BreakSignal:
                            break
                    finally:
                        self.env = previous
            elif kind == "async_for":
                stream = self.evaluate(stmt[2])
                loop_env = Env(self.env)
                while True:
                    item = async_next(stream)
                    if item is StreamEnd:
                        break
                    loop_env.assign(stmt[1], item)
                    previous = self.env
                    self.env = loop_env
                    try:
                        try:
                            yield from self.generate_statements(stmt[3])
                        except ContinueSignal:
                            continue
                        except BreakSignal:
                            break
                    finally:
                        self.env = previous
            elif kind == "match":
                subject = self.evaluate(stmt[1])
                for pattern, guard, body, _line, _col in stmt[2]:
                    bindings = match_pattern(pattern, subject)
                    if bindings is None:
                        continue
                    case_env = Env(self.env)
                    for name, value in bindings.items():
                        case_env.define(name, value)
                    previous = self.env
                    self.env = case_env
                    try:
                        if guard is not None and not truthy(self.evaluate(guard)):
                            continue
                        yield from self.generate_statements(body)
                        break
                    finally:
                        self.env = previous
            elif kind == "try":
                try:
                    yield from self.generate_statements(stmt[1])
                except SproutRaised as exc:
                    catch_env = Env(self.env)
                    catch_env.define(stmt[2], exc.value)
                    previous = self.env
                    self.env = catch_env
                    try:
                        yield from self.generate_statements(stmt[3])
                    finally:
                        self.env = previous
                except SproutError as exc:
                    catch_env = Env(self.env)
                    catch_env.define(stmt[2], str(exc))
                    previous = self.env
                    self.env = catch_env
                    try:
                        yield from self.generate_statements(stmt[3])
                    finally:
                        self.env = previous
            else:
                self.execute(stmt)

    def assign(self, target: Any, value: Any) -> None:
        if target[0] == "var":
            self.env.assign(target[1], value)
            return
        if target[0] == "index":
            arr = self.evaluate(target[1])
            index = self.evaluate(target[2])
            if isinstance(arr, list):
                arr[int(index)] = value
            elif isinstance(arr, dict):
                arr[index] = value
            else:
                raise SproutError("Index assignment expects an array or dictionary")
            return
        if target[0] == "slice":
            obj = self.evaluate(target[1])
            start = None if target[2] is None else int(self.evaluate(target[2]))
            end = None if target[3] is None else int(self.evaluate(target[3]))
            if not isinstance(obj, list):
                raise SproutError("Slice assignment expects an array")
            if not isinstance(value, list):
                raise SproutError("Slice assignment value must be an array")
            obj[start:end] = value
            return
        if target[0] == "get":
            obj = self.evaluate(target[1])
            if isinstance(obj, dict):
                obj[target[2]] = value
                return
            if isinstance(obj, SproutInstance):
                obj.set(target[2], value)
                return
            if isinstance(obj, PythonObject):
                obj.set(target[2], value)
                return
            raise SproutError("Property assignment expects a dictionary")
            return
        raise SproutError("Invalid assignment target")

    def import_python(self, module_name: str) -> PythonModule:
        try:
            return PythonModule(importlib.import_module(module_name))
        except ImportError as exc:
            raise SproutError(
                f"Could not import Python module '{module_name}': {clean_native_message(exc)}",
                category="ImportError",
                hint="Install the Python package or check the module name.",
            ) from None

    def resolve_path(self, path: str) -> str:
        return path if os.path.isabs(path) else os.path.abspath(os.path.join(self.current_dir, path))

    def resolve_module_path(self, path: str) -> str:
        candidates = [self.resolve_path(path)]
        if not os.path.isabs(path):
            candidates.extend(os.path.abspath(os.path.join(base, path)) for base in self.module_search_paths)
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[0]

    def import_sprout(self, path: str, alias: str) -> SproutModule:
        resolved = self.resolve_module_path(path)
        if not resolved.endswith(".sprout"):
            resolved += ".sprout"
        if resolved in self.module_cache:
            return self.module_cache[resolved]
        try:
            with open(resolved, "r", encoding="utf-8") as fh:
                source = fh.read()
        except OSError as exc:
            raise SproutError(
                f"Could not import Sprout module '{path}': {friendly_os_error(exc)}",
                category="ImportError",
                hint="Check the module path and the project's configured source folders.",
            ) from None

        module_env = Env(self.globals, is_scope_boundary=True)
        module = SproutModule(alias, resolved, module_env)
        self.module_cache[resolved] = module
        previous_dir = self.current_dir
        previous_source_path = self.source_path
        try:
            self.current_dir = os.path.dirname(resolved)
            self.source_path = resolved
            self.execute_block(Parser(Lexer(source).tokenize()).parse(), module_env)
        except SproutError as exc:
            attach_error_source(exc, resolved, source)
            raise
        finally:
            self.current_dir = previous_dir
            self.source_path = previous_source_path
        return module

    def location_label(self, line: int | None, col: int | None = None) -> str:
        if self.source_path and line:
            path = display_path(self.source_path)
            if col:
                return f"{path}:{line}:{col}"
            return f"{path}:{line}"
        if line:
            if col:
                return f"<repl>:{line}:{col}"
            return f"<repl>:{line}"
        return "<unknown>"

    def evaluate(self, expr: Any) -> Any:
        kind = expr[0]
        if kind == "literal":
            return expr[1]
        if kind == "var":
            return self.env.get(expr[1])
        if kind == "array":
            return [self.evaluate(item) for item in expr[1]]
        if kind == "dict":
            return {self.evaluate(key): self.evaluate(value) for key, value in expr[1]}
        if kind == "list_comp":
            out = []
            iterable = self.evaluate(expr[3])
            for item in iterable_values(iterable):
                local = Env(self.env)
                local.define(expr[2], item)
                previous = self.env
                self.env = local
                try:
                    if expr[4] is None or truthy(self.evaluate(expr[4])):
                        out.append(self.evaluate(expr[1]))
                finally:
                    self.env = previous
            return out
        if kind == "dict_comp":
            out = {}
            iterable = self.evaluate(expr[4])
            for item in iterable_values(iterable):
                local = Env(self.env)
                local.define(expr[3], item)
                previous = self.env
                self.env = local
                try:
                    if expr[5] is None or truthy(self.evaluate(expr[5])):
                        out[self.evaluate(expr[1])] = self.evaluate(expr[2])
                finally:
                    self.env = previous
            return out
        if kind == "seedfn":
            return Function("<seedfn>", expr[1], expr[2], self.env, self.source_path, expr[3], expr[4])
        if kind == "await":
            task = self.evaluate(expr[1])
            if not isinstance(task, TaskFuture):
                raise SproutError("await expects an async task")
            return task.result()
        if kind == "index":
            obj = self.evaluate(expr[1])
            index = self.evaluate(expr[2])
            try:
                return obj[int(index)] if isinstance(obj, list) else obj[index]
            except IndexError:
                raise SproutError(
                    f"Index {index} is outside the available range",
                    category="IndexError",
                    hint=f"This value contains {len(obj)} item(s).",
                ) from None
            except KeyError:
                raise SproutError(
                    f"Dictionary has no key {format_value(index)}",
                    category="KeyError",
                    hint="Check that the key exists before reading it.",
                ) from None
            except (TypeError, ValueError) as exc:
                raise SproutError(
                    f"Invalid index {format_value(index)}: {clean_native_message(exc)}",
                    category="TypeError",
                ) from None
        if kind == "slice":
            obj = self.evaluate(expr[1])
            start = None if expr[2] is None else int(self.evaluate(expr[2]))
            end = None if expr[3] is None else int(self.evaluate(expr[3]))
            if isinstance(obj, (list, str)):
                return obj[start:end]
            raise SproutError("Slice expects an array or string")
        if kind == "get":
            return self.get_property(self.evaluate(expr[1]), expr[2])
        if kind == "super":
            superclass = self.env.get("super")
            instance = self.env.get("self")
            if not isinstance(superclass, SproutClass):
                raise SproutError("super is only available inside subclasses")
            if not isinstance(instance, SproutInstance):
                raise SproutError("super needs a current instance")
            method = superclass.find_method(expr[1])
            if not method:
                raise SproutError(f"Superclass {superclass.name} has no method '{expr[1]}'")
            return BoundMethod(method, instance)
        if kind == "unary":
            op, right = expr[1], self.evaluate(expr[2])
            return -right if op == "-" else not truthy(right)
        if kind == "binary":
            return self.evaluate_binary(expr[1], expr[2], expr[3])
        if kind == "is_type":
            return value_matches_type(self.evaluate(expr[1]), expr[2])
        if kind == "call":
            callee = self.evaluate(expr[1])
            args = self.evaluate_call_args(expr[2])
            kwargs = self.evaluate_call_kwargs(expr[3])
            if not hasattr(callee, "call"):
                raise SproutError("Can only call functions")
            try:
                return callee.call(self, args, kwargs)
            except SproutError as exc:
                if exc.line is None:
                    exc.path = exc.path or self.source_path
                    exc.line = expr[4]
                    exc.col = expr[5]
                exc.add_frame(f"called at {self.location_label(expr[4], expr[5])}")
                raise
        raise SproutError(f"Unknown expression {kind}")

    def evaluate_call_args(self, parts: list[Any]) -> list[Any]:
        args = []
        for part in parts:
            if part[0] == "value":
                args.append(self.evaluate(part[1]))
            elif part[0] == "spread":
                spread = self.evaluate(part[1])
                if not isinstance(spread, list):
                    raise SproutError("Call positional spread expects an array")
                args.extend(spread)
            else:
                raise SproutError("Unknown call argument")
        return args

    def evaluate_call_kwargs(self, parts: list[Any]) -> dict[str, Any]:
        kwargs = {}
        for part in parts:
            if part[0] == "pair":
                name = part[1]
                if name in kwargs:
                    raise SproutError(f"Call got duplicate keyword '{name}'")
                kwargs[name] = self.evaluate(part[2])
            elif part[0] == "spread":
                spread = self.evaluate(part[1])
                if not isinstance(spread, dict):
                    raise SproutError("Call keyword spread expects a dictionary")
                for key, value in spread.items():
                    if not isinstance(key, str):
                        raise SproutError("Call keyword spread expects string keys")
                    if key in kwargs:
                        raise SproutError(f"Call got duplicate keyword '{key}'")
                    kwargs[key] = value
            else:
                raise SproutError("Unknown call keyword argument")
        return kwargs

    def get_property(self, obj: Any, name: str) -> Any:
        if isinstance(obj, SproutInstance):
            return obj.get(name)
        if isinstance(obj, (SproutEnum, EnumValue)):
            return obj.get(name)
        if isinstance(obj, SproutModule):
            return obj.get(name)
        if isinstance(obj, PythonModule):
            return obj.get(name)
        if isinstance(obj, PythonObject):
            return obj.get(name)
        if isinstance(obj, NativeResource):
            return obj.get(name)
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
            methods = {
                "keys": NativeMethod("dict.keys", 0, lambda: list(obj.keys())),
                "values": NativeMethod("dict.values", 0, lambda: list(obj.values())),
                "items": NativeMethod("dict.items", 0, lambda: [[k, v] for k, v in obj.items()]),
                "get": NativeMethod("dict.get", None, lambda key, default=None: obj.get(key, default)),
                "has": NativeMethod("dict.has", 1, lambda key: key in obj),
                "set": NativeMethod("dict.set", 2, lambda key, value: set_dict_value(obj, key, value)),
            }
            if name in methods:
                return methods[name]
        if isinstance(obj, list):
            methods = {
                "append": NativeMethod("list.append", 1, lambda value: append_list_value(obj, value)),
                "pop": NativeMethod("list.pop", 0, lambda: obj.pop()),
                "len": NativeMethod("list.len", 0, lambda: len(obj)),
                "join": NativeMethod("list.join", 1, lambda sep: str(sep).join(map(format_value, obj))),
            }
            if name in methods:
                return methods[name]
        if isinstance(obj, str):
            methods = {
                "upper": NativeMethod("str.upper", 0, obj.upper),
                "lower": NativeMethod("str.lower", 0, obj.lower),
                "strip": NativeMethod("str.strip", 0, obj.strip),
                "split": NativeMethod("str.split", 1, obj.split),
                "contains": NativeMethod("str.contains", 1, lambda needle: str(needle) in obj),
            }
            if name in methods:
                return methods[name]
        raise SproutError(f"{type_name(obj)} has no property '{name}'")

    def evaluate_binary(self, op: str, left_expr: Any, right_expr: Any) -> Any:
        if op == "and":
            left = self.evaluate(left_expr)
            return self.evaluate(right_expr) if truthy(left) else left
        if op == "or":
            left = self.evaluate(left_expr)
            return left if truthy(left) else self.evaluate(right_expr)
        left = self.evaluate(left_expr)
        right = self.evaluate(right_expr)
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
        except ZeroDivisionError:
            raise SproutError("Division by zero", category="MathError") from None
        except (TypeError, ValueError) as exc:
            raise SproutError(
                f"Operator '{op}' cannot use {type_name(left)} and {type_name(right)}: {clean_native_message(exc)}",
                category="TypeError",
                hint="Use compatible values or convert them before this operation.",
            ) from None
        raise SproutError(f"Unknown operator {op}")


def truthy(value: Any) -> bool:
    return value not in (False, None)


def bind_arguments(
    name: str,
    params: list[tuple[str, Any, bool, bool]],
    args: list[Any],
    kwargs: dict[str, Any],
    interpreter: Interpreter,
    closure: Env,
) -> list[tuple[str, Any]]:
    fixed_params = [(param, default) for param, default, variadic, kw_variadic in params if not variadic and not kw_variadic]
    rest_param = next((param for param, _default, variadic, _kw_variadic in params if variadic), None)
    kw_rest_param = next((param for param, _default, _variadic, kw_variadic in params if kw_variadic), None)
    fixed_names = [param for param, _default in fixed_params]
    required = sum(1 for _param, default in fixed_params if default is None)
    fixed_count = len(fixed_params)
    if len(args) > fixed_count and rest_param is None:
        if required == fixed_count:
            expected = str(fixed_count)
        else:
            expected = f"{required}-{fixed_count}"
        raise SproutError(f"{name} expected {expected} args, got {len(args)}")
    for key in kwargs:
        if key not in fixed_names and kw_rest_param is None:
            raise SproutError(f"{name} got unknown keyword '{key}'")
    for key in fixed_names[:len(args)]:
        if key in kwargs:
            raise SproutError(f"{name} got multiple values for '{key}'")
    bound: list[tuple[str, Any]] = []
    previous = interpreter.env
    interpreter.env = closure
    try:
        for i, (param, default) in enumerate(fixed_params):
            if i < len(args):
                value = args[i]
            elif param in kwargs:
                value = kwargs[param]
            elif default is not None:
                value = interpreter.evaluate(default)
            else:
                raise SproutError(f"{name} missing required argument '{param}'")
            bound.append((param, value))
        if rest_param is not None:
            bound.append((rest_param, args[fixed_count:]))
        if kw_rest_param is not None:
            extras = {}
            for key, value in kwargs.items():
                if key not in fixed_names:
                    extras[key] = value
            bound.append((kw_rest_param, extras))
    finally:
        interpreter.env = previous
    return bound


def require_dict(value: Any) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise SproutError("Expected a dictionary")
    return value


def require_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise SproutError("Expected an array")
    return value


def iterable_values(value: Any) -> Any:
    if isinstance(value, dict):
        return value.keys()
    if isinstance(value, (list, str, range, GeneratorValue)):
        return value
    if hasattr(value, "__iter__") and hasattr(value, "__next__"):
        return value
    raise SproutError(f"Cannot loop over {type_name(value)}")


def async_next(value: Any) -> Any:
    if isinstance(value, AsyncStream):
        return value.next_task().result()
    if isinstance(value, NativeResource):
        try:
            next_call = value.get("next")
            task = next_call.call(None, [], {})
            if isinstance(task, TaskFuture):
                return task.result()
        except SproutError:
            pass
    raise SproutError(f"Cannot async-loop over {type_name(value)}")


def contains_yield(statements: list[Any]) -> bool:
    for stmt in statements:
        if stmt[0] == "yield":
            return True
        if stmt[0] == "if" and (contains_yield(stmt[2]) or contains_yield(stmt[3])):
            return True
        if stmt[0] in {"while", "for", "async_for", "taskgroup"} and contains_yield(stmt[-1] if stmt[0] != "taskgroup" else stmt[2]):
            return True
        if stmt[0] == "try" and (contains_yield(stmt[1]) or contains_yield(stmt[3])):
            return True
        if stmt[0] == "match" and any(contains_yield(case[2]) for case in stmt[2]):
            return True
    return False


def match_pattern(pattern: Any, value: Any) -> dict[str, Any] | None:
    kind = pattern[0]
    if kind == "wildcard_pattern":
        return {}
    if kind == "binding_pattern":
        return {pattern[1]: value}
    if kind == "literal_pattern":
        return {} if value == pattern[1] else None
    if kind == "array_pattern":
        if not isinstance(value, list):
            return None
        fixed, rest = pattern[1], pattern[2]
        if (rest is None and len(value) != len(fixed)) or len(value) < len(fixed):
            return None
        bindings: dict[str, Any] = {}
        for child, item in zip(fixed, value):
            found = match_pattern(child, item)
            if found is None or any(name in bindings for name in found):
                return None
            bindings.update(found)
        if rest is not None:
            bindings[rest] = value[len(fixed):]
        return bindings
    if kind == "variant_pattern":
        if not isinstance(value, EnumValue):
            return None
        path, children = pattern[1], pattern[2]
        if len(path) == 1:
            matches = value.variant == path[0]
        else:
            matches = value.enum_name == path[-2] and value.variant == path[-1]
        if not matches or len(children) != len(value.fields):
            return None
        bindings: dict[str, Any] = {}
        for child, (_field, item) in zip(children, value.fields):
            found = match_pattern(child, item)
            if found is None or any(name in bindings for name in found):
                return None
            bindings.update(found)
        return bindings
    return None


def annotation_names(annotation: Any) -> set[str]:
    if annotation is None:
        return {"Any"}
    if annotation[0] == "union":
        out: set[str] = set()
        for member in annotation[1]:
            out.update(annotation_names(member))
        return out
    return {str(annotation[1])}


def value_matches_type(value: Any, annotation: Any) -> bool:
    names = annotation_names(annotation)
    if "Any" in names:
        return True
    actual = type_name(value)
    aliases = {
        "nil": "Nil",
        "bool": "Bool",
        "number": "Float" if isinstance(value, float) else "Int",
        "string": "String",
        "array": "List",
        "dictionary": "Dict",
    }
    normalized = aliases.get(actual, actual)
    if normalized in names:
        return True
    if "Number" in names and normalized in {"Int", "Float"}:
        return True
    if isinstance(value, EnumValue) and value.enum_name in names:
        return True
    if isinstance(value, SproutInstance) and value.klass.name in names:
        return True
    if isinstance(value, TaskFuture) and "Task" in names:
        return True
    if isinstance(value, GeneratorValue) and "Generator" in names:
        return True
    return False


def append_list_value(items: list[Any], value: Any) -> list[Any]:
    items.append(value)
    return items


def set_dict_value(items: dict[Any, Any], key: Any, value: Any) -> dict[Any, Any]:
    items[key] = value
    return items


def unique_values(values: Any) -> list[Any]:
    if not isinstance(values, list):
        raise SproutError("unique expects an array")
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def count_by(values: Any) -> dict[Any, int]:
    if not isinstance(values, list):
        raise SproutError("countby expects an array")
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def copy_value(value: Any) -> Any:
    if isinstance(value, list):
        return [copy_value(item) for item in value]
    if isinstance(value, dict):
        return {copy_value(k): copy_value(v) for k, v in value.items()}
    return value


def index_of(values: Any, needle: Any) -> int:
    try:
        return values.index(needle)
    except ValueError:
        return -1


def insert_value(values: Any, index: Any, value: Any) -> Any:
    arr = require_list(values)
    arr.insert(int(index), value)
    return arr


def remove_value(values: Any, value: Any) -> Any:
    arr = require_list(values)
    try:
        arr.remove(value)
    except ValueError:
        pass
    return arr


def round_number(*args: Any) -> Any:
    if len(args) == 1:
        return round(args[0])
    if len(args) == 2:
        return round(args[0], int(args[1]))
    raise SproutError(f"round expected 1 or 2 args, got {len(args)}")


def concat_values(*values: Any) -> Any:
    if all(isinstance(value, list) for value in values):
        out: list[Any] = []
        for value in values:
            out.extend(value)
        return out
    return "".join(format_value(value) for value in values)


def flatten_values(values: Any) -> list[Any]:
    out: list[Any] = []
    for value in require_list(values):
        if isinstance(value, list):
            out.extend(flatten_values(value))
        else:
            out.append(value)
    return out


def chunks(values: Any, size: Any) -> list[list[Any]]:
    arr = require_list(values)
    n = int(size)
    if n <= 0:
        raise SproutError("chunks expects size > 0")
    return [arr[i:i + n] for i in range(0, len(arr), n)]


def dict_from_args(*args: Any) -> dict[Any, Any]:
    if len(args) == 1 and isinstance(args[0], list):
        return from_pairs(args[0])
    if len(args) % 2 != 0:
        raise SproutError("dict expects pairs or an even number of arguments")
    return {args[i]: args[i + 1] for i in range(0, len(args), 2)}


def merge_dicts(*dicts: Any) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for value in dicts:
        out.update(require_dict(value))
    return out


def pick_keys(value: Any, keys: Any) -> dict[Any, Any]:
    d = require_dict(value)
    return {key: d[key] for key in require_list(keys) if key in d}


def omit_keys(value: Any, keys: Any) -> dict[Any, Any]:
    d = require_dict(value)
    banned = require_list(keys)
    return {key: val for key, val in d.items() if key not in banned}


def from_pairs(pairs: Any) -> dict[Any, Any]:
    out: dict[Any, Any] = {}
    for pair in require_list(pairs):
        if not isinstance(pair, list) or len(pair) != 2:
            raise SproutError("frompairs expects [key, value] pairs")
        out[pair[0]] = pair[1]
    return out


def delete_key(value: Any, key: Any) -> dict[Any, Any]:
    d = require_dict(value)
    if key in d:
        del d[key]
    return d


def shuffle_values(values: Any) -> list[Any]:
    arr = list(require_list(values))
    random.shuffle(arr)
    return arr


def wrap_python_value(value: Any, name: str = "python") -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [wrap_python_value(item, name) for item in value]
    if isinstance(value, tuple):
        return [wrap_python_value(item, name) for item in value]
    if isinstance(value, dict):
        return {wrap_python_value(k, name): wrap_python_value(v, name) for k, v in value.items()}
    if isinstance(value, types.ModuleType):
        return PythonModule(value)
    if callable(value):
        return PythonCallable(name, value)
    return PythonObject(value, name)


def unwrap_sprout_value(value: Any) -> Any:
    if isinstance(value, PythonModule):
        return value.module
    if isinstance(value, PythonObject):
        return value.value
    if isinstance(value, list):
        return [unwrap_sprout_value(item) for item in value]
    if isinstance(value, dict):
        return {unwrap_sprout_value(k): unwrap_sprout_value(v) for k, v in value.items()}
    return value


def type_name(value: Any) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "dictionary"
    if isinstance(value, SproutClass):
        return "class"
    if isinstance(value, SproutEnum):
        return "enum"
    if isinstance(value, EnumValue):
        return value.enum_name
    if isinstance(value, SproutInstance):
        return value.klass.name
    if isinstance(value, SproutModule):
        return "sprout-module"
    if isinstance(value, PythonModule):
        return "python-module"
    if isinstance(value, PythonCallable):
        return "python-function"
    if isinstance(value, PythonObject):
        return "python-object"
    if isinstance(value, NativeResource):
        return value.__class__.__name__
    if isinstance(value, Function):
        return "function"
    if isinstance(value, (Builtin, NativeMethod, BoundMethod)):
        return "function"
    return type(value).__name__


def format_value(value: Any) -> str:
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, list):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = [f"{format_value(key)}: {format_value(val)}" for key, val in value.items()]
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, (SproutClass, SproutEnum, EnumValue)):
        return repr(value)
    if isinstance(value, SproutInstance):
        return repr(value)
    if isinstance(value, SproutModule):
        return repr(value)
    if isinstance(value, PythonModule):
        return repr(value)
    if isinstance(value, PythonCallable):
        return repr(value)
    if isinstance(value, PythonObject):
        return repr(value)
    if isinstance(value, NativeResource):
        return repr(value)
    return str(value)


def format_error(exc: SproutError) -> str:
    message, parsed_line, parsed_col = split_error_location(str(exc))
    if exc.line is None:
        exc.line = parsed_line
    if exc.col is None:
        exc.col = parsed_col
    category = exc.category or classify_error(message)
    lines = [f"error: {category}: {message}"]
    if exc.path and exc.line:
        path = display_path(exc.path)
        location = f"{path}:{exc.line}"
        if exc.col:
            location += f":{exc.col}"
        lines.append(f"  --> {location}")
        source_line = exc.source_line or read_source_line(exc.path, exc.line)
        if source_line is not None:
            number = str(exc.line)
            gutter = " " * len(number)
            lines.extend(
                [
                    f"  {gutter} |",
                    f"  {number} | {source_line}",
                    f"  {gutter} | {' ' * max((exc.col or 1) - 1, 0)}^",
                ]
            )
    hint = exc.hint or error_hint(message)
    if hint:
        lines.append(f"  = hint: {hint}")
    if exc.frames:
        lines.append("stack:")
        for frame in exc.frames:
            if frame.startswith("called at "):
                lines.append(f"  {frame}")
            else:
                lines.append(f"  at {frame}")
    return "\n".join(lines)


ERROR_LOCATION = re.compile(r"^(.*) at (\d+):(\d+)$", re.DOTALL)


def split_error_location(message: str) -> tuple[str, int | None, int | None]:
    match = ERROR_LOCATION.match(message)
    if not match:
        return message, None, None
    return match.group(1), int(match.group(2)), int(match.group(3))


def attach_error_source(exc: SproutError, path: str | None, source: str | None = None) -> SproutError:
    message, line, col = split_error_location(str(exc))
    if line is not None:
        exc.message = message
        exc.line = exc.line or line
        exc.col = exc.col or col
    return exc.attach_source(path, source)


def display_path(path: str) -> str:
    try:
        relative = os.path.relpath(path, os.getcwd())
        if relative == ".." or relative.startswith(f"..{os.sep}"):
            return os.path.abspath(path)
        return relative
    except ValueError:
        return path


def read_source_line(path: str, line: int) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for number, text in enumerate(fh, start=1):
                if number == line:
                    return text.rstrip("\r\n")
    except OSError:
        return None
    return None


def classify_error(message: str) -> str:
    lower = message.lower()
    if (
        lower.startswith("expected")
        or lower.startswith("unexpected")
        or lower.startswith("unterminated")
        or "indentation" in lower
        or "parameter" in lower and "must be last" in lower
    ):
        return "SyntaxError"
    if lower.startswith("undefined variable"):
        return "NameError"
    if "could not import" in lower or lower.startswith("no sprout.toml"):
        return "ImportError"
    if "no such file" in lower or "file not found" in lower or "is a directory" in lower:
        return "FileError"
    if "python bridge" in lower:
        return "InteropError"
    if (
        "expected" in lower
        or "expects" in lower
        or "can only" in lower
        or "cannot loop" in lower
        or "must be" in lower
    ):
        return "TypeError"
    if "division by zero" in lower or "modulo by zero" in lower:
        return "MathError"
    if "has no property" in lower or "has no method" in lower:
        return "PropertyError"
    return "RuntimeError"


def error_hint(message: str) -> str | None:
    lower = message.lower()
    if "line ending after" in lower:
        return "End the statement with a newline or ';'. Move the next statement onto a new line."
    if "expected an indented block" in lower:
        return "Indent the block body one level beneath the line ending in ':'."
    if "unexpected indentation" in lower:
        return "Remove the extra indentation, or add a block opener ending in ':'."
    if "inconsistent indentation" in lower:
        return "Use the same number of spaces as the surrounding block."
    if "expected expression" in lower:
        return "Check for a missing value, an extra operator, or an unmatched bracket."
    if "unterminated string" in lower:
        return "Add a closing double quote before the end of the string."
    if lower.startswith("undefined variable"):
        return "Define the name before using it, or check its spelling and scope."
    if "can only call functions" in lower:
        return "Only functions, classes, and callable values can be followed by '(...)'."
    if "division by zero" in lower or "modulo by zero" in lower:
        return "Check that the divisor is not zero before performing this operation."
    if "no such file" in lower or "file not found" in lower:
        return "Check the path. Relative paths start from the current Sprout file or project."
    if "has no property" in lower or "has no method" in lower:
        return "Check the member name and the value's type."
    if "missing required argument" in lower or "expected" in lower and "args, got" in lower:
        return "Check the function signature and the arguments supplied at this call."
    return None


def clean_native_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or "the native operation failed"


def friendly_os_error(exc: OSError) -> str:
    filename = getattr(exc, "filename", None)
    shown = f"'{filename}'" if filename else "the requested path"
    if isinstance(exc, FileNotFoundError):
        return f"File not found: {shown}"
    if isinstance(exc, IsADirectoryError):
        return f"Expected a file but found a directory: {shown}"
    if isinstance(exc, PermissionError):
        return f"Permission denied: {shown}"
    return clean_native_message(exc)


def native_runtime_error(name: str, exc: Exception) -> SproutError:
    if isinstance(exc, ZeroDivisionError):
        error = SproutError("Division by zero", category="MathError")
    elif isinstance(exc, IndexError):
        error = SproutError(f"{name} could not access that index", category="IndexError")
    elif isinstance(exc, KeyError):
        error = SproutError(f"{name} could not find key {exc}", category="KeyError")
    elif isinstance(exc, OSError):
        error = SproutError(friendly_os_error(exc), category="FileError")
    elif isinstance(exc, (TypeError, ValueError)):
        error = SproutError(f"{name} received an invalid value: {clean_native_message(exc)}", category="TypeError")
    else:
        error = SproutError(
            f"{name} failed during a native operation: {clean_native_message(exc)}",
            category="InternalError",
            hint="The native failure was translated below. Report the Sprout stack if this looks like a language bug.",
        )
    add_native_trace(error, exc, f"native {name}")
    return error


def add_native_trace(error: SproutError, exc: Exception, boundary: str) -> None:
    extracted = traceback.extract_tb(exc.__traceback__)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    translated: list[str] = []
    for frame in extracted:
        path = os.path.abspath(frame.filename)
        if path.startswith(project_root + os.sep):
            module = os.path.splitext(os.path.basename(path))[0]
            translated.append(f"Sprout runtime {module}.{frame.name}")
        else:
            translated.append(f"bridged {frame.name} ({display_path(frame.filename)}:{frame.lineno})")
    for frame in translated[-5:]:
        error.add_frame(frame)
    error.add_frame(boundary)
