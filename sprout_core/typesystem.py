from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from .lexer import Lexer
from .model import Diagnostic, SproutError, resolve_module_file
from .parser import Parser


ANY = ("type", "Any", [], 0, 0)
NIL = ("type", "Nil", [], 0, 0)
BUILTIN_TYPES = {
    "Any", "Nil", "Bool", "Int", "Float", "Number", "String",
    "List", "Array", "Dict", "Task", "Generator",
}
GENERIC_ARITY = {"List": 1, "Array": 1, "Dict": 2, "Task": 1, "Generator": 1}
MAX_INFERRED_UNION_MEMBERS = 8


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
    superclass: str | None = None
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


@dataclass
class EnumType:
    name: str
    variants: dict[str, list[tuple[str, Any]]]
    type_params: list[str]
    line: int
    col: int


@dataclass
class AliasType:
    name: str
    type_params: list[str]
    target: Any
    line: int
    col: int


@dataclass
class ModuleType:
    path: str
    checker: "TypeChecker"


def type_name(annotation: Any) -> str:
    if annotation is None:
        return "Any"
    if isinstance(annotation, ModuleType):
        return f"module[{annotation.path}]"
    if annotation[0] == "union":
        return " | ".join(type_name(member) for member in annotation[1])
    name = str(annotation[1])
    arguments = annotation[2]
    if not arguments:
        return name
    return f"{name}[{', '.join(type_name(item) for item in arguments)}]"


def function_signature_string(name: str, params: list[tuple[str, Any, bool, bool]]) -> str:
    parts: list[str] = []
    for param_name, default, var_param, kw_param in params:
        prefix = "**" if kw_param else "*" if var_param else ""
        if default is None:
            parts.append(f"{prefix}{param_name}")
        else:
            parts.append(f"{prefix}{param_name}=...")
    return f"{name}({', '.join(parts)})"


def _closest_parameter_name(name: str, candidates: list[str]) -> str | None:
    pool = [candidate for candidate in candidates if candidate and candidate != name]
    if not pool or len(name) < 2:
        return None
    prefix_matches = [candidate for candidate in pool if candidate.startswith(name)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    best = sorted(pool, key=lambda candidate: (levenshtein_distance(name, candidate), len(candidate), candidate))
    return best[0] if best and levenshtein_distance(name, best[0]) <= 2 else None


def levenshtein_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def same_type(left: Any, right: Any) -> bool:
    return type_name(left) == type_name(right)


def compatible(actual: Any, expected: Any, type_vars: dict[str, Any] | None = None) -> bool:
    if expected is None or actual is None:
        return True
    if isinstance(actual, ModuleType) or isinstance(expected, ModuleType):
        return isinstance(actual, ModuleType) and isinstance(expected, ModuleType) and actual.path == expected.path
    if actual[0] == "union" and expected[0] == "union":
        return all(any(compatible(member, option, type_vars) for option in expected[1]) for member in actual[1])
    if expected[0] == "union":
        return any(compatible(actual, member, type_vars) for member in expected[1])
    if actual[0] == "union":
        return all(compatible(member, expected, type_vars) for member in actual[1])
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
    if actual_name == expected_name or actual_name.split(".")[-1] == expected_name.split(".")[-1]:
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
    members = []
    seen = set()
    for value in values:
        key = type_name(value)
        if key not in seen:
            seen.add(key)
            members.append(value)
    return ("union", members, 0, 0) if len(members) > 1 else ANY


def without_nil(annotation: Any) -> Any:
    if annotation is None or isinstance(annotation, ModuleType):
        return annotation
    if same_type(annotation, NIL):
        return ANY
    if annotation[0] != "union":
        return annotation
    remaining = [member for member in annotation[1] if not same_type(member, NIL)]
    if not remaining:
        return ANY
    if len(remaining) == 1:
        return remaining[0]
    return ("union", remaining, 0, 0)


def only_nil(annotation: Any) -> Any:
    if annotation is None or isinstance(annotation, ModuleType):
        return NIL
    if same_type(annotation, NIL):
        return NIL
    if annotation[0] != "union":
        return NIL
    matches = [member for member in annotation[1] if same_type(member, NIL)]
    return NIL if matches else ANY


def statements_contain_yield(statements: list[Any]) -> bool:
    for stmt in statements:
        kind = stmt[0]
        if kind == "yield":
            return True
        if kind == "if" and (statements_contain_yield(stmt[2]) or statements_contain_yield(stmt[3])):
            return True
        if kind in {"while", "for", "async_for"} and statements_contain_yield(stmt[-1]):
            return True
        if kind == "try" and (statements_contain_yield(stmt[1]) or statements_contain_yield(stmt[3])):
            return True
        if kind == "taskgroup" and statements_contain_yield(stmt[2]):
            return True
        if kind == "match" and any(statements_contain_yield(case[2]) for case in stmt[2]):
            return True
    return False


class TypeChecker:
    def __init__(self, path: str, module_cache: dict[str, "TypeChecker"] | None = None):
        self.path = path
        self.diagnostics: list[Diagnostic] = []
        self.functions: dict[str, FunctionType] = {}
        self.classes: dict[str, ClassType] = {}
        self.interfaces: dict[str, InterfaceType] = {}
        self.enums: dict[str, EnumType] = {}
        self.aliases: dict[str, AliasType] = {}
        self.modules: dict[str, ModuleType] = {}
        self.global_env: dict[str, Any] = {}
        self.yield_types: list[Any] = []
        self.suppress_diagnostics = False
        self.module_cache = module_cache if module_cache is not None else {}
        self.module_cache[os.path.abspath(path)] = self

    def error(
        self,
        message: str,
        line: int = 1,
        col: int = 1,
        code: str = "SPROUT_TYPE",
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.suppress_diagnostics:
            return
        self.diagnostics.append(Diagnostic("error", message, self.path, line, col, code, data=data))

    def warning(
        self,
        message: str,
        line: int = 1,
        col: int = 1,
        code: str = "SPROUT_TYPE_WARNING",
        data: dict[str, Any] | None = None,
    ) -> None:
        if self.suppress_diagnostics:
            return
        self.diagnostics.append(Diagnostic("warning", message, self.path, line, col, code, data=data))

    def is_compatible(self, actual: Any, expected: Any, type_vars: dict[str, Any] | None = None) -> bool:
        return compatible(self.expand_alias(actual), self.expand_alias(expected), type_vars)

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
                    stmt[1],
                    methods,
                    stmt[4] if len(stmt) > 4 else [],
                    stmt[2],
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
            elif kind == "enum":
                self.enums[stmt[1]] = EnumType(
                    stmt[1],
                    {variant[0]: variant[1] for variant in stmt[3]},
                    stmt[2],
                    stmt[4],
                    stmt[5],
                )
            elif kind == "type_alias":
                self.aliases[stmt[1]] = AliasType(stmt[1], stmt[2], stmt[3], stmt[4], stmt[5])
            elif kind == "import":
                self.collect_import(stmt[1], stmt[2], stmt[3] if len(stmt) > 3 else 1, stmt[4] if len(stmt) > 4 else 1)

    def collect_import(self, import_path: str, alias: str, line: int = 1, col: int = 1) -> None:
        try:
            from .tooling import module_search_paths_for
            search_paths = module_search_paths_for(self.path)
        except Exception:
            search_paths = []
        resolved = resolve_module_file(import_path, os.path.dirname(os.path.abspath(self.path)), search_paths)
        if resolved is None:
            self.error(f"Could not resolve imported module '{import_path}'", line, col, "SPROUT_IMPORT")
            return
        checker = self.module_cache.get(resolved)
        if checker is None:
            try:
                source = Path(resolved).read_text(encoding="utf-8")
                program = Parser(Lexer(source).tokenize()).parse()
            except (OSError, SproutError) as exc:
                self.error(f"Could not analyze imported module '{import_path}': {exc}", line, col, "SPROUT_IMPORT")
                return
            checker = TypeChecker(resolved, self.module_cache)
            checker.collect(program)
            imported_env = checker.prepare_global_env(program)
            checker.infer_program_summaries(program, imported_env)
        self.modules[alias] = ModuleType(resolved, checker)

    def substitute(self, annotation: Any, values: dict[str, Any]) -> Any:
        if annotation is None or isinstance(annotation, ModuleType):
            return annotation
        if annotation[0] == "union":
            return ("union", [self.substitute(item, values) for item in annotation[1]], annotation[2], annotation[3])
        if annotation[1] in values:
            return values[annotation[1]]
        return (
            "type",
            annotation[1],
            [self.substitute(item, values) for item in annotation[2]],
            annotation[3],
            annotation[4],
        )

    def expand_alias(self, annotation: Any) -> Any:
        if annotation is None or isinstance(annotation, ModuleType):
            return annotation
        if annotation[0] == "union":
            return ("union", [self.expand_alias(item) for item in annotation[1]], annotation[2], annotation[3])
        alias = self.aliases.get(annotation[1])
        if alias is None:
            return (
                "type",
                annotation[1],
                [self.expand_alias(item) for item in annotation[2]],
                annotation[3],
                annotation[4],
            )
        substitutions = dict(zip(alias.type_params, annotation[2]))
        return self.expand_alias(self.substitute(alias.target, substitutions))

    def validate_annotation(self, annotation: Any, type_params: set[str]) -> None:
        if annotation is None:
            return
        if annotation[0] == "union":
            for member in annotation[1]:
                self.validate_annotation(member, type_params)
            return
        name, arguments, line, col = annotation[1], annotation[2], annotation[3], annotation[4]
        if "." in name:
            module_name, export_name = name.rsplit(".", 1)
            module = self.modules.get(module_name)
            if module is None:
                self.error(f"Unknown module type prefix '{module_name}'", line, col, "SPROUT_UNKNOWN_TYPE")
            elif export_name not in module.checker.classes and export_name not in module.checker.interfaces and export_name not in module.checker.enums and export_name not in module.checker.aliases:
                self.error(f"Module '{module_name}' exports no type '{export_name}'", line, col, "SPROUT_UNKNOWN_TYPE")
            for argument in arguments:
                self.validate_annotation(argument, type_params)
            return
        known = BUILTIN_TYPES | set(self.classes) | set(self.interfaces) | set(self.enums) | set(self.aliases) | type_params
        if name not in known:
            self.error(f"Unknown type '{name}'", line, col, "SPROUT_UNKNOWN_TYPE")
        expected_arity = GENERIC_ARITY.get(name)
        if name in self.classes:
            expected_arity = len(self.classes[name].type_params)
        elif name in self.interfaces:
            expected_arity = len(self.interfaces[name].type_params)
        elif name in self.enums:
            expected_arity = len(self.enums[name].type_params)
        elif name in self.aliases:
            expected_arity = len(self.aliases[name].type_params)
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
        if kind == "list_comp":
            local = dict(env)
            iterable = self.infer(expr[3], env)
            local[expr[2]] = self.iterable_item_type(iterable)
            return ("type", "List", [self.infer(expr[1], local)], 0, 0)
        if kind == "dict_comp":
            local = dict(env)
            iterable = self.infer(expr[4], env)
            local[expr[3]] = self.iterable_item_type(iterable)
            return ("type", "Dict", [self.infer(expr[1], local), self.infer(expr[2], local)], 0, 0)
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
        if kind == "is_type":
            self.validate_annotation(expr[2], set())
            return ("type", "Bool", [], 0, 0)
        if kind == "call":
            callee = expr[1]
            args = [self.infer(part[1], env) for part in expr[2] if part[0] == "value"]
            kwargs = {
                part[1]: self.infer(part[2], env)
                for part in expr[3]
                if part[0] == "pair"
            }
            if callee[0] == "var":
                name = callee[1]
                if name == "get":
                    if len(args) >= 3:
                        base, default = args[0], args[2]
                        expanded = self.expand_alias(base)
                        if not isinstance(expanded, ModuleType) and expanded[1] == "Dict" and len(expanded[2]) == 2:
                            return common_type([expanded[2][1], default])
                        return common_type([ANY, default])
                    if len(args) >= 1:
                        base = self.expand_alias(args[0])
                        if not isinstance(base, ModuleType) and base[1] == "Dict" and len(base[2]) == 2:
                            return common_type([base[2][1], NIL])
                        return ANY
                if name in self.functions:
                    return self.check_call(self.functions[name], args, expr[4], expr[5], kwargs)
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
                        self.check_call(constructor, args, expr[4], expr[5], kwargs)
                    elif args or kwargs:
                        self.error(
                            f"{name} expects 0 argument(s), got {len(args) + len(kwargs)}",
                            expr[4], expr[5], "SPROUT_ARGUMENT_COUNT",
                        )
                    return (
                        "type",
                        name,
                        [ANY for _parameter in klass.type_params],
                        0,
                        0,
                    )
            if callee[0] == "get" and callee[1][0] == "var":
                owner_name = callee[1][1]
                member_name = callee[2]
                if owner_name in self.enums:
                    enum = self.enums[owner_name]
                    fields = enum.variants.get(member_name)
                    if fields is not None:
                        synthetic = FunctionType(
                            f"{owner_name}.{member_name}",
                            [(field, None, False, False) for field, _annotation in fields],
                            {
                                "parameter_types": dict(fields),
                                "return_type": (
                                    "type",
                                    owner_name,
                                    [("type", parameter, [], 0, 0) for parameter in enum.type_params],
                                    0,
                                    0,
                                ),
                                "type_params": enum.type_params,
                            },
                            expr[4],
                            expr[5],
                        )
                        return self.check_call(synthetic, args, expr[4], expr[5], kwargs)
                module = self.modules.get(owner_name)
                if module:
                    return self.infer_module_call(module, member_name, args, expr[4], expr[5], kwargs)
            if callee[0] == "get":
                owner = self.infer(callee[1], env)
                if isinstance(owner, ModuleType):
                    return self.infer_module_call(owner, callee[2], args, expr[4], expr[5], kwargs)
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
                    return self.check_call(bound, args, expr[4], expr[5], kwargs)
            return ANY
        if kind == "get":
            if expr[1][0] == "var" and expr[1][1] in self.enums:
                enum = self.enums[expr[1][1]]
                if expr[2] in enum.variants:
                    return (
                        "type",
                        enum.name,
                        [ANY for _parameter in enum.type_params],
                        0,
                        0,
                    )
            owner = self.infer(expr[1], env)
            if isinstance(owner, ModuleType):
                return owner.checker.export_type(expr[2])
            return ANY
        return ANY

    def iterable_item_type(self, annotation: Any) -> Any:
        annotation = self.expand_alias(annotation)
        if isinstance(annotation, ModuleType):
            return ANY
        if annotation[0] == "union":
            return common_type([self.iterable_item_type(item) for item in annotation[1]])
        if annotation[1] in {"List", "Array", "Generator"} and annotation[2]:
            return annotation[2][0]
        if annotation[1] == "Dict" and annotation[2]:
            return annotation[2][0]
        if annotation[1] == "String":
            return ("type", "String", [], 0, 0)
        return ANY

    def export_type(self, name: str) -> Any:
        if name in self.global_env:
            return self.global_env[name]
        if name in self.classes:
            return ("type", name, [], 0, 0)
        if name in self.enums:
            return ("type", name, [], 0, 0)
        return ANY

    def infer_export_call(
        self,
        name: str,
        args: list[Any],
        line: int,
        col: int,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if name in self.functions:
            return self.check_call(self.functions[name], args, line, col, kwargs)
        if name in self.classes:
            return ("type", name, [], 0, 0)
        return ANY

    def infer_module_call(
        self,
        module: ModuleType,
        name: str,
        args: list[Any],
        line: int,
        col: int,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        before = len(module.checker.diagnostics)
        result = module.checker.infer_export_call(name, args, line, col, kwargs)
        for diagnostic in module.checker.diagnostics[before:]:
            self.diagnostics.append(
                Diagnostic(
                    diagnostic.severity,
                    diagnostic.message,
                    self.path,
                    line,
                    col,
                    diagnostic.code,
                )
            )
        del module.checker.diagnostics[before:]
        return result

    def prepare_global_env(self, program: list[Any]) -> dict[str, Any]:
        env: dict[str, Any] = {
            **{name: ("type", name, [], 0, 0) for name in self.classes},
            **{name: ("type", name, [], 0, 0) for name in self.enums},
            **self.modules,
        }
        for stmt in program:
            if stmt[0] == "let":
                env[stmt[1]] = stmt[3] or self.infer(stmt[2], env)
            elif stmt[0] == "assign" and stmt[1][0] == "var":
                env.setdefault(stmt[1][1], self.infer(stmt[2], env))
        self.global_env = env
        return env

    def check_call(
        self,
        function: FunctionType,
        args: list[Any],
        line: int,
        col: int,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        metadata = function.metadata or {}
        annotations = metadata.get("parameter_types", {})
        fixed = [param for param in function.params if not param[2] and not param[3]]
        keyword_args = kwargs or {}
        fixed_names = [param[0] for param in fixed]
        function_signature = metadata.get("signature") or function_signature_string(function.name, function.params)
        positional_names = set(fixed_names[:len(args)])
        required_names = {
            name for name, default, _var, _kw in fixed
            if default is None
        }
        has_rest = any(param[2] for param in function.params)
        has_keyword_rest = any(param[3] for param in function.params)
        unknown_keywords = sorted(set(keyword_args) - set(fixed_names))
        if unknown_keywords and not has_keyword_rest:
            unknown_name = unknown_keywords[0]
            suggested = _closest_parameter_name(unknown_name, fixed_names)
            self.error(
                (
                    f"{function.name} has no parameter named '{unknown_name}'. Did you mean '{suggested}'?"
                    if suggested else f"{function.name} has no parameter named '{unknown_name}'"
                ),
                line,
                col,
                "SPROUT_UNKNOWN_ARGUMENT",
                {
                    "kind": "unknown-keyword",
                    "function": function.name,
                    "signature": function_signature,
                    "parameter": unknown_name,
                    "replacement": suggested,
                    "suggestion": suggested,
                },
            )
        duplicate_keywords = sorted(positional_names & set(keyword_args))
        if duplicate_keywords:
            duplicate = duplicate_keywords[0]
            self.error(
                f"{function.name} got multiple values for '{duplicate}'",
                line,
                col,
                "SPROUT_DUPLICATE_ARGUMENT",
                {
                    "kind": "duplicate-argument",
                    "function": function.name,
                    "signature": function_signature,
                    "parameter": duplicate,
                },
            )
        supplied_names = positional_names | set(keyword_args)
        missing = [name for name in fixed_names if name in required_names and name not in supplied_names]
        if missing:
            self.error(
                (
                    f"{function.name} is missing required argument '{missing[0]}'"
                    if len(missing) == 1
                    else f"{function.name} is missing required arguments {', '.join(repr(name) for name in missing)}"
                ),
                line, col, "SPROUT_ARGUMENT_COUNT",
                {
                    "kind": "missing-arguments",
                    "function": function.name,
                    "signature": function_signature,
                    "missing": missing,
                    "parameter": missing[0],
                },
            )
        if not has_rest and len(args) > len(fixed):
            self.error(
                f"{function.name} expects at most {len(fixed)} positional argument(s), got {len(args)}",
                line, col, "SPROUT_ARGUMENT_COUNT",
                {
                    "kind": "too-many-positional",
                    "function": function.name,
                    "signature": function_signature,
                    "expectedMax": len(fixed),
                    "actualCount": len(args),
                },
            )
        substitutions: dict[str, Any] = {
            name: None for name in metadata.get("type_params", [])
        }
        inferred_parameters = metadata.setdefault("_inferred_parameter_types", {})
        for actual, param in zip(args, fixed):
            name = param[0]
            previous = inferred_parameters.get(name)
            inferred_parameters[name] = self.merge_inferred_type(previous, actual)
        for name, actual in keyword_args.items():
            if name in fixed_names:
                inferred_parameters[name] = self.merge_inferred_type(inferred_parameters.get(name), actual)
        for actual, param in zip(args, fixed):
            expected = annotations.get(param[0])
            if expected is not None and not self.is_compatible(actual, expected, substitutions):
                self.error(
                    f"Argument '{param[0]}' expects {type_name(expected)}, got {type_name(actual)}",
                    line, col, "SPROUT_ARGUMENT_TYPE",
                    {
                        "kind": "argument-type",
                        "function": function.name,
                        "signature": function_signature,
                        "parameter": param[0],
                        "expectedType": type_name(expected),
                        "actualType": type_name(actual),
                    },
                )
        fixed_by_name = {param[0]: param for param in fixed}
        for name, actual in keyword_args.items():
            param = fixed_by_name.get(name)
            if param is None:
                continue
            expected = annotations.get(name)
            if expected is not None and not self.is_compatible(actual, expected, substitutions):
                self.error(
                    f"Argument '{name}' expects {type_name(expected)}, got {type_name(actual)}",
                    line, col, "SPROUT_ARGUMENT_TYPE",
                    {
                        "kind": "argument-type",
                        "function": function.name,
                        "signature": function_signature,
                        "parameter": name,
                        "expectedType": type_name(expected),
                        "actualType": type_name(actual),
                    },
                )
        result = metadata.get("return_type") or metadata.get("_inferred_return_type") or ANY
        result = self.substitute(
            result,
            {name: value or ANY for name, value in substitutions.items()},
        )
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
        is_generator = statements_contain_yield(body)
        expected_yield = ANY
        if is_generator and function.async_function:
            self.error(
                "Async generators are not supported yet; use stream_open() with async for",
                function.line,
                function.col,
                "SPROUT_ASYNC_GENERATOR_UNSUPPORTED",
            )
        if is_generator and expected_return is not None:
            expanded_return = self.expand_alias(expected_return)
            if (
                isinstance(expanded_return, ModuleType)
                or expanded_return[0] != "type"
                or expanded_return[1] != "Generator"
                or len(expanded_return[2]) != 1
            ):
                self.error(
                    f"Generator function '{function.name}' must return Generator[T]",
                    function.line,
                    function.col,
                    "SPROUT_GENERATOR_RETURN_TYPE",
                )
            else:
                expected_yield = expanded_return[2][0]
        env = dict(outer)
        for name, _default, _variadic, _kw_variadic in function.params:
            env[name] = parameter_types.get(name, metadata.get("_inferred_parameter_types", {}).get(name, ANY))
        self.yield_types.append(expected_yield if is_generator else None)
        try:
            self.check_statements(body, env, None if is_generator else expected_return)
        finally:
            self.yield_types.pop()

    def statement_location(self, stmt: Any) -> tuple[int, int]:
        if not isinstance(stmt, tuple):
            return (1, 1)
        kind = stmt[0]
        mapping = {
            "let": (4, 5),
            "type_alias": (4, 5),
            "importpython": (3, 4),
            "import": (3, 4),
            "test": (3, 4),
            "fn": (4, 5),
            "async_fn": (4, 5),
            "taskgroup": (3, 4),
            "class": (6, 7),
            "enum": (4, 5),
            "interface": (4, 5),
            "match": (3, 4),
            "yield": (2, 3),
        }
        line_index, col_index = mapping.get(kind, (None, None))
        if line_index is not None and len(stmt) > col_index:
            return int(stmt[line_index]), int(stmt[col_index])
        if kind in {"return", "raise", "expr"} and len(stmt) > 1 and isinstance(stmt[1], tuple):
            expr = stmt[1]
            if len(expr) > 3 and isinstance(expr[-2], int) and isinstance(expr[-1], int):
                return int(expr[-2]), int(expr[-1])
        if kind == "assign" and len(stmt) > 1 and isinstance(stmt[1], tuple):
            target = stmt[1]
            if target and target[0] == "var":
                return (1, 1)
        return (1, 1)

    def statement_terminates(self, stmt: Any) -> bool:
        if not isinstance(stmt, tuple):
            return False
        kind = stmt[0]
        if kind in {"return", "raise", "break", "continue"}:
            return True
        if kind == "if":
            return bool(stmt[2]) and bool(stmt[3]) and self.block_terminates(stmt[2]) and self.block_terminates(stmt[3])
        if kind == "match":
            cases = stmt[2]
            return bool(cases) and all(self.block_terminates(case[2]) for case in cases)
        if kind == "try":
            return self.block_terminates(stmt[1]) and self.block_terminates(stmt[3])
        return False

    def block_terminates(self, statements: list[Any]) -> bool:
        return bool(statements) and self.statement_terminates(statements[-1])

    def check_statements(self, statements: list[Any], env: dict[str, Any], expected_return: Any = None) -> None:
        terminated = False
        for stmt in statements:
            if terminated:
                line, col = self.statement_location(stmt)
                self.warning(
                    "Unreachable code",
                    line,
                    col,
                    "SPROUT_UNREACHABLE",
                )
                continue
            kind = stmt[0]
            if kind == "let":
                actual = self.infer(stmt[2], env)
                annotation = stmt[3] if len(stmt) > 3 else None
                self.validate_annotation(annotation, set())
                if annotation is not None and not self.is_compatible(actual, annotation):
                    self.error(
                        f"Variable '{stmt[1]}' expects {type_name(annotation)}, got {type_name(actual)}",
                        stmt[4], stmt[5], "SPROUT_ASSIGNMENT_TYPE",
                    )
                env[stmt[1]] = annotation or actual
            elif kind == "assign" and stmt[1][0] == "var":
                actual = self.infer(stmt[2], env)
                expected = env.get(stmt[1][1])
                if expected is not None and not self.is_compatible(actual, expected):
                    self.error(
                        f"Assignment to '{stmt[1][1]}' expects {type_name(expected)}, got {type_name(actual)}",
                        code="SPROUT_ASSIGNMENT_TYPE",
                    )
                elif expected is None:
                    env[stmt[1][1]] = actual
            elif kind == "return":
                actual = NIL if stmt[1] is None else self.infer(stmt[1], env)
                if expected_return is not None and not self.is_compatible(actual, expected_return):
                    self.error(
                        f"Return expects {type_name(expected_return)}, got {type_name(actual)}",
                        code="SPROUT_RETURN_TYPE",
                    )
                terminated = True
            elif kind == "raise":
                self.infer(stmt[1], env)
                terminated = True
            elif kind == "expr":
                self.infer(stmt[1], env)
            elif kind == "say":
                for expr in stmt[1]:
                    self.infer(expr, env)
            elif kind == "if":
                self.infer(stmt[1], env)
                then_env = dict(env)
                else_env = dict(env)
                self.apply_narrowing(stmt[1], then_env, else_env)
                self.check_statements(stmt[2], then_env, expected_return)
                self.check_statements(stmt[3], else_env, expected_return)
                env.update(self.merge_branch_envs(env, then_env, else_env))
            elif kind == "while":
                self.infer(stmt[1], env)
                self.check_statements(stmt[2], dict(env), expected_return)
            elif kind == "for":
                loop_env = dict(env)
                loop_env[stmt[1]] = self.iterable_item_type(self.infer(stmt[2], env))
                self.check_statements(stmt[3], loop_env, expected_return)
            elif kind == "async_for":
                loop_env = dict(env)
                loop_env[stmt[1]] = self.iterable_item_type(self.infer(stmt[2], env))
                self.check_statements(stmt[3], loop_env, expected_return)
            elif kind == "try":
                try_env = dict(env)
                self.check_statements(stmt[1], try_env, expected_return)
                catch_env = dict(env)
                catch_env[stmt[2]] = ANY
                self.check_statements(stmt[3], catch_env, expected_return)
                env.update(self.merge_branch_envs(env, try_env, catch_env))
            elif kind == "taskgroup":
                group_env = dict(env)
                group_env[stmt[1]] = ANY
                self.check_statements(stmt[2], group_env, expected_return)
            elif kind == "match":
                subject_type = self.infer(stmt[1], env)
                covered: set[str] = set()
                wildcard = False
                case_envs: list[dict[str, Any]] = []
                for pattern, guard, body, line, col in stmt[2]:
                    case_env = dict(env)
                    bindings, variant, catches_all = self.pattern_bindings(pattern, subject_type)
                    case_env.update(bindings)
                    if guard is not None:
                        self.infer(guard, case_env)
                    elif catches_all:
                        wildcard = True
                    elif variant:
                        if variant in covered:
                            self.warning(
                                f"Duplicate match case for variant '{variant}'",
                                line,
                                col,
                                "SPROUT_DUPLICATE_CASE",
                            )
                        covered.add(variant)
                    self.check_statements(body, case_env, expected_return)
                    case_envs.append(case_env)
                expanded = self.expand_alias(subject_type)
                if not isinstance(expanded, ModuleType) and expanded[0] == "type" and expanded[1] in self.enums:
                    missing = sorted(set(self.enums[expanded[1]].variants) - covered)
                    if missing and not wildcard:
                        self.error(
                            f"Non-exhaustive match for {expanded[1]}; missing: {', '.join(missing)}",
                            stmt[3],
                            stmt[4],
                            "SPROUT_NON_EXHAUSTIVE_MATCH",
                        )
                if case_envs:
                    env.update(self.merge_many_envs(env, case_envs))
            elif kind == "yield":
                if not self.yield_types or self.yield_types[-1] is None:
                    self.error(
                        "yield may only be used inside a generator function",
                        stmt[2],
                        stmt[3],
                        "SPROUT_YIELD_OUTSIDE_GENERATOR",
                    )
                    continue
                actual = NIL if stmt[1] is None else self.infer(stmt[1], env)
                expected = self.yield_types[-1]
                if not self.is_compatible(actual, expected):
                    self.error(
                        f"Generator yield expects {type_name(expected)}, got {type_name(actual)}",
                        stmt[2],
                        stmt[3],
                        "SPROUT_YIELD_TYPE",
                    )
            if not terminated and self.statement_terminates(stmt):
                terminated = True

    def merge_env_value(self, left: Any, right: Any) -> Any:
        if left is None:
            return right
        if right is None:
            return left
        if same_type(left, right):
            return left
        return common_type([left, right])

    def merge_inferred_type(self, left: Any, right: Any) -> Any:
        return self.bounded_inferred_union([left, right])

    def inferred_common_type(self, values: list[Any]) -> Any:
        return self.bounded_inferred_union(values)

    def bounded_inferred_union(self, values: list[Any]) -> Any:
        flattened: list[Any] = []

        def add(value: Any) -> None:
            if value is None:
                return
            if not isinstance(value, ModuleType) and value[0] == "union":
                for member in value[1]:
                    add(member)
            else:
                flattened.append(value)

        for value in values:
            add(value)
        concrete = [value for value in flattened if type_name(value) != "Any"]
        candidates = concrete or flattened or [ANY]
        unique: dict[str, Any] = {}
        for value in candidates:
            unique.setdefault(type_name(value), value)
            if len(unique) >= MAX_INFERRED_UNION_MEMBERS:
                break
        members = list(unique.values())
        if len(members) == 1:
            return members[0]
        if members and all(type_name(item) in {"Int", "Float", "Number"} for item in members):
            return ("type", "Number", [], 0, 0)
        return ("union", members, 0, 0)

    def infer_summary_statements(
        self,
        statements: list[Any],
        env: dict[str, Any],
    ) -> list[Any]:
        returns: list[Any] = []
        for stmt in statements:
            kind = stmt[0]
            if kind == "let":
                actual = self.infer(stmt[2], env)
                env[stmt[1]] = stmt[3] or actual
            elif kind == "assign" and stmt[1][0] == "var":
                env[stmt[1][1]] = self.infer(stmt[2], env)
            elif kind == "return":
                returns.append(NIL if stmt[1] is None else self.infer(stmt[1], env))
            elif kind == "yield":
                returns.append(self.infer(stmt[1], env))
            elif kind == "expr":
                self.infer(stmt[1], env)
            elif kind == "say":
                for expr in stmt[1]:
                    self.infer(expr, env)
            elif kind == "if":
                then_env = dict(env)
                else_env = dict(env)
                self.apply_narrowing(stmt[1], then_env, else_env)
                returns.extend(self.infer_summary_statements(stmt[2], then_env))
                returns.extend(self.infer_summary_statements(stmt[3], else_env))
                env.update(self.merge_branch_envs(env, then_env, else_env))
            elif kind in {"for", "async_for"}:
                loop_env = dict(env)
                loop_env[stmt[1]] = self.iterable_item_type(self.infer(stmt[2], env))
                returns.extend(self.infer_summary_statements(stmt[3], loop_env))
                env.update(self.merge_branch_envs(env, env, loop_env))
            elif kind == "while":
                loop_env = dict(env)
                returns.extend(self.infer_summary_statements(stmt[2], loop_env))
                env.update(self.merge_branch_envs(env, env, loop_env))
            elif kind == "try":
                try_env = dict(env)
                catch_env = dict(env)
                catch_env[stmt[2]] = ANY
                returns.extend(self.infer_summary_statements(stmt[1], try_env))
                returns.extend(self.infer_summary_statements(stmt[3], catch_env))
                env.update(self.merge_branch_envs(env, try_env, catch_env))
            elif kind == "match":
                branches = []
                subject = self.infer(stmt[1], env)
                for pattern, guard, body, _line, _col in stmt[2]:
                    branch = dict(env)
                    bindings, _variant, _all = self.pattern_bindings(pattern, subject)
                    branch.update(bindings)
                    if guard is not None:
                        self.infer(guard, branch)
                    returns.extend(self.infer_summary_statements(body, branch))
                    branches.append(branch)
                if branches:
                    env.update(self.merge_many_envs(env, branches))
        return returns

    def infer_program_summaries(self, program: list[Any], global_env: dict[str, Any]) -> None:
        definitions: list[tuple[FunctionType, list[Any], set[str]]] = []
        for stmt in program:
            if stmt[0] in {"fn", "async_fn"}:
                definitions.append((self.functions[stmt[1]], stmt[3], set()))
            elif stmt[0] == "class":
                klass = self.classes[stmt[1]]
                for method in stmt[3]:
                    definitions.append((klass.methods[method[1]], method[3], set(klass.type_params)))
        previous_suppression = self.suppress_diagnostics
        self.suppress_diagnostics = True
        try:
            for _iteration in range(12):
                before = [
                    (
                        type_name(function.metadata.get("_inferred_return_type")),
                        tuple(sorted(
                            (name, type_name(value))
                            for name, value in function.metadata.get("_inferred_parameter_types", {}).items()
                        )),
                    )
                    for function, _body, _types in definitions
                ]
                top_env = dict(global_env)
                self.infer_summary_statements(
                    [
                        stmt for stmt in program
                        if stmt[0] not in {"fn", "async_fn", "class", "interface", "enum", "type_alias"}
                    ],
                    top_env,
                )
                for function, body, _inherited in definitions:
                    metadata = function.metadata or {}
                    env = dict(global_env)
                    annotations = metadata.get("parameter_types", {})
                    inferred_parameters = metadata.get("_inferred_parameter_types", {})
                    for name, _default, _variadic, _kw_variadic in function.params:
                        env[name] = annotations.get(name, inferred_parameters.get(name, ANY))
                    returns = self.infer_summary_statements(body, env)
                    if returns:
                        metadata["_inferred_return_type"] = self.inferred_common_type(returns)
                after = [
                    (
                        type_name(function.metadata.get("_inferred_return_type")),
                        tuple(sorted(
                            (name, type_name(value))
                            for name, value in function.metadata.get("_inferred_parameter_types", {}).items()
                        )),
                    )
                    for function, _body, _types in definitions
                ]
                if after == before:
                    break
        finally:
            self.suppress_diagnostics = previous_suppression

    def merge_branch_envs(self, baseline: dict[str, Any], left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged = dict(baseline)
        for name in set(left) | set(right):
            left_value = left.get(name, baseline.get(name))
            right_value = right.get(name, baseline.get(name))
            if left_value is None and right_value is None:
                continue
            merged[name] = self.merge_env_value(left_value, right_value)
        return merged

    def merge_many_envs(self, baseline: dict[str, Any], envs: list[dict[str, Any]]) -> dict[str, Any]:
        merged = dict(baseline)
        for name in set().union(*(env.keys() for env in envs)):
            values = [env.get(name, baseline.get(name)) for env in envs]
            values = [value for value in values if value is not None]
            if not values:
                continue
            current = values[0]
            for value in values[1:]:
                current = self.merge_env_value(current, value)
            merged[name] = current
        return merged

    def narrow_nil_truthiness(self, name: str, then_env: dict[str, Any], else_env: dict[str, Any]) -> None:
        current = self.expand_alias(then_env.get(name, ANY))
        if isinstance(current, ModuleType):
            return
        if current[0] == "union" and any(same_type(member, NIL) for member in current[1]):
            then_env[name] = without_nil(current)
            else_env[name] = only_nil(current)

    def apply_narrowing(self, condition: Any, then_env: dict[str, Any], else_env: dict[str, Any]) -> None:
        if not isinstance(condition, tuple):
            return
        kind = condition[0]
        if kind == "is_type":
            target, narrowed = condition[1], condition[2]
            if target[0] != "var":
                return
            name = target[1]
            then_env[name] = narrowed
            current = self.expand_alias(else_env.get(name, ANY))
            if not isinstance(current, ModuleType) and current[0] == "union":
                remaining = [member for member in current[1] if not same_type(member, narrowed)]
                if remaining:
                    else_env[name] = remaining[0] if len(remaining) == 1 else ("union", remaining, 0, 0)
            return
        if kind == "var":
            self.narrow_nil_truthiness(condition[1], then_env, else_env)
            return
        if kind == "unary" and condition[1] == "!":
            swapped_then = dict(else_env)
            swapped_else = dict(then_env)
            self.apply_narrowing(condition[2], swapped_then, swapped_else)
            then_env.update(swapped_else)
            else_env.update(swapped_then)
            return
        if kind != "binary" or condition[1] not in {"==", "!="}:
            return
        left, right = condition[2], condition[3]
        variable = None
        if left[0] == "var" and right[0] == "literal" and right[1] is None:
            variable = left[1]
        elif right[0] == "var" and left[0] == "literal" and left[1] is None:
            variable = right[1]
        if not variable:
            return
        current = self.expand_alias(then_env.get(variable, ANY))
        if isinstance(current, ModuleType):
            return
        if condition[1] == "!=":
            self.narrow_nil_truthiness(variable, then_env, else_env)
        else:
            then_env[variable] = only_nil(current)
            else_env[variable] = without_nil(current)

    def pattern_bindings(self, pattern: Any, subject: Any) -> tuple[dict[str, Any], str | None, bool]:
        kind = pattern[0]
        if kind == "wildcard_pattern":
            return {}, None, True
        if kind == "binding_pattern":
            return {pattern[1]: subject}, None, True
        if kind == "literal_pattern":
            return {}, None, False
        if kind == "array_pattern":
            item_type = self.iterable_item_type(subject)
            bindings: dict[str, Any] = {}
            for child in pattern[1]:
                child_bindings, _variant, _all = self.pattern_bindings(child, item_type)
                bindings.update(child_bindings)
            if pattern[2]:
                bindings[pattern[2]] = ("type", "List", [item_type], 0, 0)
            return bindings, None, False
        if kind == "variant_pattern":
            expanded = self.expand_alias(subject)
            enum_name = pattern[1][-2] if len(pattern[1]) > 1 else (
                expanded[1] if not isinstance(expanded, ModuleType) and expanded[0] == "type" else ""
            )
            variant_name = pattern[1][-1]
            enum = self.enums.get(enum_name)
            fields = enum.variants.get(variant_name, []) if enum else []
            if enum is None:
                self.error(
                    f"Unknown enum in pattern '{'.'.join(pattern[1])}'",
                    pattern[-2],
                    pattern[-1],
                    "SPROUT_PATTERN_TYPE",
                )
            elif len(fields) != len(pattern[2]):
                self.error(
                    f"Pattern {enum_name}.{variant_name} expects {len(fields)} field(s), got {len(pattern[2])}",
                    pattern[-2],
                    pattern[-1],
                    "SPROUT_PATTERN_ARITY",
                )
            bindings = {}
            substitutions = {}
            if enum and not isinstance(expanded, ModuleType) and expanded[0] == "type":
                substitutions = dict(zip(enum.type_params, expanded[2]))
            for child, (_field, annotation) in zip(pattern[2], fields):
                field_type = self.substitute(annotation or ANY, substitutions)
                child_bindings, _variant, _all = self.pattern_bindings(child, field_type)
                bindings.update(child_bindings)
            return bindings, variant_name, False
        return {}, None, False

    def check_interfaces(self) -> None:
        for klass in self.classes.values():
            type_params = set(klass.type_params)
            if klass.superclass:
                parent = self.classes.get(klass.superclass)
                if parent is None:
                    self.error(
                        f"Class '{klass.name}' extends unknown superclass '{klass.superclass}'",
                        klass.line,
                        klass.col,
                        "SPROUT_UNKNOWN_SUPERCLASS",
                    )
                else:
                    for name, actual in klass.methods.items():
                        parent_method = parent.methods.get(name)
                        if parent_method is None:
                            continue
                        if len(actual.params) != len(parent_method.params):
                            self.error(
                                f"Method '{klass.name}.{name}' does not match superclass parameter count",
                                actual.line,
                                actual.col,
                                "SPROUT_OVERRIDE_SIGNATURE",
                            )
                            continue
                        parent_types = parent_method.metadata.get("parameter_types", {})
                        actual_types = actual.metadata.get("parameter_types", {})
                        for parent_param, actual_param in zip(parent_method.params, actual.params):
                            parent_annotation = parent_types.get(parent_param[0])
                            actual_annotation = actual_types.get(actual_param[0])
                            if not same_type(parent_annotation or ANY, actual_annotation or ANY):
                                self.error(
                                    f"Method '{klass.name}.{name}' parameter '{actual_param[0]}' "
                                    f"must be {type_name(parent_annotation)}, got {type_name(actual_annotation)}",
                                    actual.line,
                                    actual.col,
                                    "SPROUT_OVERRIDE_SIGNATURE",
                                )
                        parent_return = parent_method.metadata.get("return_type")
                        actual_return = actual.metadata.get("return_type")
                        if not same_type(parent_return or ANY, actual_return or ANY):
                            self.error(
                                f"Method '{klass.name}.{name}' must return {type_name(parent_return)}, "
                                f"got {type_name(actual_return)}",
                                actual.line,
                                actual.col,
                                "SPROUT_OVERRIDE_SIGNATURE",
                            )
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
        for alias in self.aliases.values():
            self.validate_annotation(alias.target, set(alias.type_params))
        for enum in self.enums.values():
            for fields in enum.variants.values():
                for _field, annotation in fields:
                    self.validate_annotation(annotation, set(enum.type_params))
        for interface in self.interfaces.values():
            local_types = set(interface.type_params)
            for method in interface.methods.values():
                method_types = local_types | set(method.metadata.get("type_params", []))
                for annotation in method.metadata.get("parameter_types", {}).values():
                    self.validate_annotation(annotation, method_types)
                self.validate_annotation(method.metadata.get("return_type"), method_types)
        self.check_interfaces()
        global_env = self.prepare_global_env(program)
        self.infer_program_summaries(program, global_env)
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
            [stmt for stmt in program if stmt[0] not in {"fn", "async_fn", "class", "interface", "enum", "type_alias"}],
            global_env,
        )
        return self.diagnostics


def typecheck_source(
    source: str,
    path: str,
    *,
    language_default: str | None = None,
    program: list[Any] | None = None,
) -> list[Diagnostic]:
    if program is None:
        try:
            program = Parser(
                Lexer(source, default_language_pack=language_default).tokenize()
            ).parse()
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
    from .tooling import project_for_path

    diagnostics: list[Diagnostic] = []
    files = source_files(target)
    for path in files:
        project = project_for_path(str(path))
        diagnostics.extend(
            typecheck_source(
                path.read_text(encoding="utf-8"),
                str(path),
                language_default=project.language_default if project else None,
            )
        )
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
