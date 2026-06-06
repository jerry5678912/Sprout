from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from .lexer import Lexer
from .model import Diagnostic, SproutError
from .parser import Parser


ANY = ("type", "Any", [], 0, 0)
NIL = ("type", "Nil", [], 0, 0)
BUILTIN_TYPES = {
    "Any", "Nil", "Bool", "Int", "Float", "Number", "String",
    "List", "Array", "Dict", "Task",
}
GENERIC_ARITY = {"List": 1, "Array": 1, "Dict": 2, "Task": 1}


@dataclass
class FunctionType:
    name: str
    params: list[tuple[str, Any, bool, bool]]
    metadata: dict[str, Any]
    line: int
    col: int
    async_function: bool = False


@dataclass
class ClassType:
    name: str
    methods: dict[str, FunctionType] = field(default_factory=dict)
    type_params: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    line: int = 1
    col: int = 1


@dataclass
class InterfaceType:
    name: str
    methods: dict[str, FunctionType]
    type_params: list[str]
    line: int
    col: int


def type_name(annotation: Any) -> str:
    if annotation is None:
        return "Any"
    name = str(annotation[1])
    arguments = annotation[2]
    if not arguments:
        return name
    return f"{name}[{', '.join(type_name(item) for item in arguments)}]"


def same_type(left: Any, right: Any) -> bool:
    return type_name(left) == type_name(right)


def compatible(actual: Any, expected: Any, type_vars: dict[str, Any] | None = None) -> bool:
    if expected is None or actual is None:
        return True
    actual_name = type_name(actual)
    expected_name = type_name(expected)
    if actual_name == "Any" or expected_name == "Any":
        return True
    variables = type_vars if type_vars is not None else {}
    if expected[1] in variables:
        if variables[expected[1]] is None:
            variables[expected[1]] = actual
            return True
        return compatible(actual, variables[expected[1]], variables)
    if actual_name == expected_name:
        return True
    if expected_name == "Number" and actual_name in {"Int", "Float"}:
        return True
    if actual[1] in {"List", "Array"} and expected[1] in {"List", "Array"}:
        if not actual[2] or not expected[2]:
            return True
        return compatible(actual[2][0], expected[2][0], variables)
    if actual[1] == expected[1] and len(actual[2]) == len(expected[2]):
        return all(compatible(a, e, variables) for a, e in zip(actual[2], expected[2]))
    return False


def common_type(values: list[Any]) -> Any:
    if not values:
        return ANY
    first = values[0]
    if all(same_type(first, item) for item in values[1:]):
        return first
    if all(type_name(item) in {"Int", "Float", "Number"} for item in values):
        return ("type", "Number", [], 0, 0)
    return ANY


class TypeChecker:
    def __init__(self, path: str):
        self.path = path
        self.diagnostics: list[Diagnostic] = []
        self.functions: dict[str, FunctionType] = {}
        self.classes: dict[str, ClassType] = {}
        self.interfaces: dict[str, InterfaceType] = {}

    def error(self, message: str, line: int = 1, col: int = 1, code: str = "SPROUT_TYPE") -> None:
        self.diagnostics.append(Diagnostic("error", message, self.path, line, col, code))

    def collect(self, program: list[Any]) -> None:
        for stmt in program:
            kind = stmt[0]
            if kind in {"fn", "async_fn"}:
                self.functions[stmt[1]] = FunctionType(
                    stmt[1], stmt[2], stmt[6] if len(stmt) > 6 else {},
                    stmt[4], stmt[5], kind == "async_fn",
                )
            elif kind == "class":
                methods = {
                    method[1]: FunctionType(
                        method[1], method[2], method[6] if len(method) > 6 else {},
                        method[4], method[5], method[0] == "async_fn",
                    )
                    for method in stmt[3]
                }
                self.classes[stmt[1]] = ClassType(
                    stmt[1], methods, stmt[4] if len(stmt) > 4 else [],
                    stmt[5] if len(stmt) > 5 else [],
                    stmt[6] if len(stmt) > 6 else 1,
                    stmt[7] if len(stmt) > 7 else 1,
                )
            elif kind == "interface":
                methods = {
                    method[0]: FunctionType(method[0], method[1], method[2], method[3], method[4])
                    for method in stmt[3]
                }
                self.interfaces[stmt[1]] = InterfaceType(stmt[1], methods, stmt[2], stmt[4], stmt[5])

    def validate_annotation(self, annotation: Any, type_params: set[str]) -> None:
        if annotation is None:
            return
        name, arguments, line, col = annotation[1], annotation[2], annotation[3], annotation[4]
        known = BUILTIN_TYPES | set(self.classes) | set(self.interfaces) | type_params
        if name not in known:
            self.error(f"Unknown type '{name}'", line, col, "SPROUT_UNKNOWN_TYPE")
        expected_arity = GENERIC_ARITY.get(name)
        if name in self.classes:
            expected_arity = len(self.classes[name].type_params)
        elif name in self.interfaces:
            expected_arity = len(self.interfaces[name].type_params)
        if expected_arity is not None and len(arguments) != expected_arity:
            self.error(
                f"Type '{name}' expects {expected_arity} type argument(s), got {len(arguments)}",
                line, col, "SPROUT_GENERIC_ARITY",
            )
        if expected_arity is None and arguments:
            self.error(f"Type '{name}' is not generic", line, col, "SPROUT_NOT_GENERIC")
        for argument in arguments:
            self.validate_annotation(argument, type_params)

    def infer(self, expr: Any, env: dict[str, Any]) -> Any:
        if not isinstance(expr, tuple):
            return ANY
        kind = expr[0]
        if kind == "literal":
            value = expr[1]
            name = (
                "Nil" if value is None else "Bool" if isinstance(value, bool)
                else "Int" if isinstance(value, int) else "Float" if isinstance(value, float)
                else "String" if isinstance(value, str) else "Any"
            )
            return ("type", name, [], 0, 0)
        if kind == "var":
            return env.get(expr[1], ANY)
        if kind == "array":
            item = common_type([self.infer(value, env) for value in expr[1]])
            return ("type", "List", [item], 0, 0)
        if kind == "dict":
            keys = common_type([self.infer(key, env) for key, _value in expr[1]])
            values = common_type([self.infer(value, env) for _key, value in expr[1]])
            return ("type", "Dict", [keys, values], 0, 0)
        if kind == "unary":
            return ("type", "Bool", [], 0, 0) if expr[1] == "!" else self.infer(expr[2], env)
        if kind == "binary":
            if expr[1] in {"==", "!=", "<", "<=", ">", ">=", "in", "and", "or"}:
                return ("type", "Bool", [], 0, 0)
            left = self.infer(expr[2], env)
            right = self.infer(expr[3], env)
            if type_name(left) == "String" or type_name(right) == "String":
                return ("type", "String", [], 0, 0)
            return common_type([left, right])
        if kind in {"index", "slice"}:
            container = self.infer(expr[1], env)
            if container[1] in {"List", "Array"} and container[2]:
                return container if kind == "slice" else container[2][0]
            if container[1] == "Dict" and len(container[2]) == 2:
                return container[2][1]
            return ANY
        if kind == "await":
            task = self.infer(expr[1], env)
            return task[2][0] if task[1] == "Task" and task[2] else ANY
        if kind == "call":
            callee = expr[1]
            args = [self.infer(part[1], env) for part in expr[2] if part[0] == "value"]
            if callee[0] == "var":
                name = callee[1]
                if name in self.functions:
                    return self.check_call(self.functions[name], args, expr[4], expr[5])
                if name in self.classes:
                    klass = self.classes[name]
                    initializer = klass.methods.get("init")
                    if initializer:
                        metadata = dict(initializer.metadata)
                        parameter_types = dict(metadata.get("parameter_types", {}))
                        if initializer.params:
                            parameter_types.pop(initializer.params[0][0], None)
                        metadata["parameter_types"] = parameter_types
                        constructor = FunctionType(
                            name,
                            initializer.params[1:] if initializer.params else [],
                            metadata,
                            initializer.line,
                            initializer.col,
                        )
                        self.check_call(constructor, args, expr[4], expr[5])
                    elif args:
                        self.error(
                            f"{name} expects 0 argument(s), got {len(args)}",
                            expr[4], expr[5], "SPROUT_ARGUMENT_COUNT",
                        )
                    return (
                        "type",
                        name,
                        [ANY for _parameter in klass.type_params],
                        0,
                        0,
                    )
            if callee[0] == "get":
                owner = self.infer(callee[1], env)
                klass = self.classes.get(owner[1])
                method = klass.methods.get(callee[2]) if klass else None
                if method:
                    metadata = dict(method.metadata)
                    parameter_types = dict(metadata.get("parameter_types", {}))
                    params = method.params[1:] if method.params else []
                    if method.params:
                        parameter_types.pop(method.params[0][0], None)
                    metadata["parameter_types"] = parameter_types
                    bound = FunctionType(
                        f"{owner[1]}.{callee[2]}",
                        params,
                        metadata,
                        method.line,
                        method.col,
                        method.async_function,
                    )
                    return self.check_call(bound, args, expr[4], expr[5])
            return ANY
        return ANY

    def check_call(self, function: FunctionType, args: list[Any], line: int, col: int) -> Any:
        metadata = function.metadata or {}
        annotations = metadata.get("parameter_types", {})
        fixed = [param for param in function.params if not param[2] and not param[3]]
        required = sum(1 for _name, default, _var, _kw in fixed if default is None)
        has_rest = any(param[2] for param in function.params)
        if len(args) < required or (not has_rest and len(args) > len(fixed)):
            self.error(
                f"{function.name} expects {required}..{len(fixed)} argument(s), got {len(args)}",
                line, col, "SPROUT_ARGUMENT_COUNT",
            )
        substitutions: dict[str, Any] = {
            name: None for name in metadata.get("type_params", [])
        }
        for actual, param in zip(args, fixed):
            expected = annotations.get(param[0])
            if expected is not None and not compatible(actual, expected, substitutions):
                self.error(
                    f"Argument '{param[0]}' expects {type_name(expected)}, got {type_name(actual)}",
                    line, col, "SPROUT_ARGUMENT_TYPE",
                )
        result = metadata.get("return_type") or ANY
        if result[1] in substitutions and substitutions[result[1]] is not None:
            result = substitutions[result[1]]
        if function.async_function:
            return ("type", "Task", [result], 0, 0)
        return result

    def check_function(
        self,
        function: FunctionType,
        body: list[Any],
        outer: dict[str, Any],
        inherited_type_params: set[str] | None = None,
    ) -> None:
        metadata = function.metadata or {}
        type_params = set(inherited_type_params or set()) | set(metadata.get("type_params", []))
        parameter_types = metadata.get("parameter_types", {})
        for annotation in parameter_types.values():
            self.validate_annotation(annotation, type_params)
        expected_return = metadata.get("return_type")
        self.validate_annotation(expected_return, type_params)
        env = dict(outer)
        for name, _default, _variadic, _kw_variadic in function.params:
            env[name] = parameter_types.get(name, ANY)
        self.check_statements(body, env, expected_return)

    def check_statements(self, statements: list[Any], env: dict[str, Any], expected_return: Any = None) -> None:
        for stmt in statements:
            kind = stmt[0]
            if kind == "let":
                actual = self.infer(stmt[2], env)
                annotation = stmt[3] if len(stmt) > 3 else None
                self.validate_annotation(annotation, set())
                if annotation is not None and not compatible(actual, annotation):
                    self.error(
                        f"Variable '{stmt[1]}' expects {type_name(annotation)}, got {type_name(actual)}",
                        stmt[4], stmt[5], "SPROUT_ASSIGNMENT_TYPE",
                    )
                env[stmt[1]] = annotation or actual
            elif kind == "assign" and stmt[1][0] == "var":
                actual = self.infer(stmt[2], env)
                expected = env.get(stmt[1][1])
                if expected is not None and not compatible(actual, expected):
                    self.error(
                        f"Assignment to '{stmt[1][1]}' expects {type_name(expected)}, got {type_name(actual)}",
                        code="SPROUT_ASSIGNMENT_TYPE",
                    )
                elif expected is None:
                    env[stmt[1][1]] = actual
            elif kind == "return":
                actual = NIL if stmt[1] is None else self.infer(stmt[1], env)
                if expected_return is not None and not compatible(actual, expected_return):
                    self.error(
                        f"Return expects {type_name(expected_return)}, got {type_name(actual)}",
                        code="SPROUT_RETURN_TYPE",
                    )
            elif kind == "expr":
                self.infer(stmt[1], env)
            elif kind == "say":
                for expr in stmt[1]:
                    self.infer(expr, env)
            elif kind == "if":
                self.infer(stmt[1], env)
                self.check_statements(stmt[2], dict(env), expected_return)
                self.check_statements(stmt[3], dict(env), expected_return)
            elif kind == "while":
                self.infer(stmt[1], env)
                self.check_statements(stmt[2], dict(env), expected_return)
            elif kind == "for":
                loop_env = dict(env)
                loop_env[stmt[1]] = ANY
                self.check_statements(stmt[3], loop_env, expected_return)
            elif kind == "try":
                self.check_statements(stmt[1], dict(env), expected_return)
                catch_env = dict(env)
                catch_env[stmt[2]] = ANY
                self.check_statements(stmt[3], catch_env, expected_return)
            elif kind == "taskgroup":
                group_env = dict(env)
                group_env[stmt[1]] = ANY
                self.check_statements(stmt[2], group_env, expected_return)

    def check_interfaces(self) -> None:
        for klass in self.classes.values():
            type_params = set(klass.type_params)
            for interface_name in klass.interfaces:
                interface = self.interfaces.get(interface_name)
                if interface is None:
                    self.error(
                        f"Class '{klass.name}' implements unknown interface '{interface_name}'",
                        klass.line, klass.col, "SPROUT_UNKNOWN_INTERFACE",
                    )
                    continue
                for name, required in interface.methods.items():
                    actual = klass.methods.get(name)
                    if actual is None:
                        self.error(
                            f"Class '{klass.name}' is missing interface method '{name}'",
                            klass.line, klass.col, "SPROUT_INTERFACE_METHOD",
                        )
                        continue
                    if len(actual.params) != len(required.params):
                        self.error(
                            f"Method '{klass.name}.{name}' does not match interface parameter count",
                            actual.line, actual.col, "SPROUT_INTERFACE_SIGNATURE",
                        )
                        continue
                    required_types = required.metadata.get("parameter_types", {})
                    actual_types = actual.metadata.get("parameter_types", {})
                    for required_param, actual_param in zip(required.params, actual.params):
                        required_annotation = required_types.get(required_param[0])
                        actual_annotation = actual_types.get(actual_param[0])
                        if not same_type(required_annotation or ANY, actual_annotation or ANY):
                            self.error(
                                f"Method '{klass.name}.{name}' parameter '{actual_param[0]}' "
                                f"must be {type_name(required_annotation)}, got {type_name(actual_annotation)}",
                                actual.line, actual.col, "SPROUT_INTERFACE_SIGNATURE",
                            )
                    required_return = required.metadata.get("return_type")
                    actual_return = actual.metadata.get("return_type")
                    if not same_type(required_return or ANY, actual_return or ANY):
                        self.error(
                            f"Method '{klass.name}.{name}' must return {type_name(required_return)}, "
                            f"got {type_name(actual_return)}",
                            actual.line, actual.col, "SPROUT_INTERFACE_SIGNATURE",
                        )
            for method in klass.methods.values():
                metadata = method.metadata or {}
                local_types = type_params | set(metadata.get("type_params", []))
                for annotation in metadata.get("parameter_types", {}).values():
                    self.validate_annotation(annotation, local_types)
                self.validate_annotation(metadata.get("return_type"), local_types)

    def check(self, program: list[Any]) -> list[Diagnostic]:
        self.collect(program)
        for interface in self.interfaces.values():
            local_types = set(interface.type_params)
            for method in interface.methods.values():
                method_types = local_types | set(method.metadata.get("type_params", []))
                for annotation in method.metadata.get("parameter_types", {}).values():
                    self.validate_annotation(annotation, method_types)
                self.validate_annotation(method.metadata.get("return_type"), method_types)
        self.check_interfaces()
        global_env: dict[str, Any] = {
            **{name: ("type", name, [], 0, 0) for name in self.classes},
        }
        for stmt in program:
            if stmt[0] in {"fn", "async_fn"}:
                function = self.functions[stmt[1]]
                self.check_function(function, stmt[3], global_env)
            elif stmt[0] == "class":
                klass = self.classes[stmt[1]]
                for method_stmt in stmt[3]:
                    self.check_function(
                        klass.methods[method_stmt[1]],
                        method_stmt[3],
                        global_env,
                        set(klass.type_params),
                    )
        self.check_statements(
            [stmt for stmt in program if stmt[0] not in {"fn", "async_fn", "class", "interface"}],
            global_env,
        )
        return self.diagnostics


def typecheck_source(source: str, path: str) -> list[Diagnostic]:
    try:
        program = Parser(Lexer(source).tokenize()).parse()
    except SproutError as exc:
        return [Diagnostic("error", str(exc), path, exc.line, exc.col, "SPROUT_SYNTAX")]
    return TypeChecker(path).check(program)


def source_files(target: str) -> list[Path]:
    path = Path(target).resolve()
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise SproutError(f"Typecheck target does not exist: {target}")
    return sorted(
        item for item in path.rglob("*.sprout")
        if not any(part in {".git", ".sprout", "build", "dist"} for part in item.parts)
    )


def typecheck_path(target: str, *, json_mode: bool = False) -> int:
    diagnostics: list[Diagnostic] = []
    files = source_files(target)
    for path in files:
        diagnostics.extend(typecheck_source(path.read_text(encoding="utf-8"), str(path)))
    payload = {
        "ok": not diagnostics,
        "files": len(files),
        "diagnostics": [diagnostic.to_json() for diagnostic in diagnostics],
    }
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif diagnostics:
        for diagnostic in diagnostics:
            location = f"{diagnostic.path}:{diagnostic.line or 1}:{diagnostic.col or 1}"
            print(f"error: {location}: {diagnostic.message}")
    else:
        print(f"typecheck ok {len(files)} file(s)")
    return 0 if not diagnostics else 1
