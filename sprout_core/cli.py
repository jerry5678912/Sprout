from __future__ import annotations

import os
import sys
from typing import Any

from .bytecode import BytecodeUnsupported, benchmark_file, compile_file as compile_bytecode_file, debug_file, disassemble, profile_file, run_file_vm
from .lexer import Lexer
from .model import SPROUT_VERSION, SproutError, SproutRaised
from .package import doctor, ensure_release_docs, new_project, pkg_add, pkg_info, pkg_init, pkg_list, pkg_remove, release_check
from .parser import Parser
from .runtime import Interpreter, attach_error_source, format_error, format_value, native_runtime_error
from .testing import run_tests
from .docsgen import generate_docs
from .ecosystem import (
    build_project,
    package_project,
    pkg_docs,
    pkg_install,
    pkg_list_installed,
    pkg_publish,
    pkg_registry_info,
    pkg_search,
    pkg_tree,
    pkg_update,
    release_project,
)
from .distribution import (
    install_language,
    package_language,
    package_vscode_extension,
    uninstall_language,
)
from .application import STANDARD_LIBRARY_GROUPS
from .tooling import builtin_function_names, check_file, example_files, format_file, intelligence_file, lint_file, print_help, run_file

def brace_balance(source: str) -> int:
    balance = 0
    in_string = False
    escape = False
    in_comment = False
    for ch in source:
        if in_comment:
            if ch == "\n":
                in_comment = False
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == "#":
            in_comment = True
        elif ch == '"':
            in_string = True
        elif ch == "{":
            balance += 1
        elif ch == "}":
            balance -= 1
    return balance


def repl(argv: list[str] | None = None) -> None:
    interpreter = Interpreter(argv=argv)
    print("Sprout REPL. Type Ctrl-D to exit. Multiline blocks are welcome.")
    pending: list[str] = []
    while True:
        try:
            prompt = "......> " if pending else "sprout> "
            line = input(prompt)
        except EOFError:
            print()
            break
        if not line.strip() and not pending:
            continue
        pending.append(line)
        source = "\n".join(pending)
        balance = brace_balance(source)
        if balance > 0:
            continue
        if balance < 0:
            print("error: unexpected '}'", file=sys.stderr)
            pending = []
            continue
        try:
            interpreter.run(Parser(Lexer(source).tokenize()).parse())
        except SproutError as exc:
            attach_error_source(exc, "<repl>", source)
            print(format_error(exc), file=sys.stderr)
        except SproutRaised as exc:
            print(format_error(SproutError(
                f"Uncaught value: {format_value(exc.value)}",
                category="RaisedError",
                hint="Handle this value with try/catch, or remove the raise.",
                path="<repl>",
            )), file=sys.stderr)
        pending = []


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 1:
            repl()
        elif argv[1] in {"help", "--help", "-h"}:
            print_help()
        elif argv[1] in {"version", "--version", "-V"}:
            print(f"Sprout {SPROUT_VERSION}")
        elif argv[1] == "run":
            if len(argv) < 3:
                print("usage: sprout.py run [--vm] FILE.sprout|DIR [args]", file=sys.stderr)
                return 2
            if argv[2] == "--vm":
                if len(argv) < 4:
                    print("usage: sprout.py run --vm FILE.sprout [args]", file=sys.stderr)
                    return 2
                run_file_vm(argv[3], argv[4:])
            else:
                run_file(argv[2], argv[3:])
        elif argv[1] == "compile":
            if len(argv) < 3:
                print("usage: sprout.py compile FILE.sprout", file=sys.stderr)
                return 2
            code = compile_bytecode_file(argv[2])
            print(f"compiled {argv[2]}: {len(code.instructions)} instructions")
        elif argv[1] == "dis":
            if len(argv) < 3:
                print("usage: sprout.py dis FILE.sprout", file=sys.stderr)
                return 2
            print(disassemble(compile_bytecode_file(argv[2])))
        elif argv[1] == "bench":
            if len(argv) < 3:
                print("usage: sprout.py bench FILE.sprout [--repeat N]", file=sys.stderr)
                return 2
            repeat = 1
            if "--repeat" in argv[3:]:
                index = argv.index("--repeat")
                repeat = int(argv[index + 1])
            result = benchmark_file(argv[2], repeat=repeat)
            print(f"path: {result['path']}")
            print(f"repeat: {result['repeat']}")
            print(f"compile: {result['compile_seconds']:.6f}s")
            print(f"tree-walk: {result['tree_walk_seconds']:.6f}s")
            if result["vm_seconds"] is None:
                print(f"vm: unsupported ({result['vm_unsupported']})")
            else:
                print(f"vm: {result['vm_seconds']:.6f}s")
                print(f"ratio tree/vm: {result['speed_ratio']:.3f}x")
                print(f"vm instructions: {result['vm_instruction_count']}")
            print(f"vm supported: {str(result['vm_supported']).lower()}")
            print(f"fallback used: {str(result['fallback_used']).lower()}")
        elif argv[1] == "debug":
            if len(argv) < 3:
                print("usage: sprout.py debug FILE.sprout [--break LINE|FILE:LINE]", file=sys.stderr)
                return 2
            breaks = []
            i = 3
            while i < len(argv):
                if argv[i] == "--break" and i + 1 < len(argv):
                    breaks.append(argv[i + 1])
                    i += 2
                else:
                    i += 1
            debug_file(argv[2], breakpoints=breaks)
        elif argv[1] == "profile":
            if len(argv) < 3:
                print("usage: sprout.py profile FILE.sprout", file=sys.stderr)
                return 2
            result = profile_file(argv[2])
            print(f"path: {result['path']}")
            print(f"compile: {result['compile_seconds']:.6f}s")
            print(f"run: {result['run_seconds']:.6f}s")
            print(f"total: {result['total_seconds']:.6f}s")
            print(f"instructions: {result['instruction_count']}")
            print("functions:")
            for name, count in result["call_counts"].items():
                seconds = result["call_times"].get(name, 0.0)
                print(f"  {name}: calls={count} time={seconds:.6f}s")
        elif argv[1] == "test":
            target = None
            for value in argv[2:]:
                if not value.startswith("--"):
                    target = value
                    break
            return run_tests(target, verbose="--verbose" in argv[2:])
        elif argv[1] == "docs":
            target = "."
            for value in argv[2:]:
                if not value.startswith("--"):
                    target = value
                    break
            if target != "." and not os.path.exists(target):
                return pkg_docs(target, registry=option_value(argv, "--registry"))
            return generate_docs(target, html_mode="--html" in argv[2:])
        elif argv[1] == "build":
            target = positional_value(argv[2:], ".")
            build_project(target, vm="--vm" in argv[2:], registry=option_value(argv, "--registry"))
        elif argv[1] == "package":
            target = positional_value(argv[2:], ".")
            package_project(target, vm="--vm" in argv[2:], registry=option_value(argv, "--registry"))
        elif argv[1] == "pkg":
            if len(argv) < 3:
                print("usage: sprout.py pkg init|list|add|remove|info|search|install|update|publish|docs|tree [...]", file=sys.stderr)
                return 2
            cmd = argv[2]
            if cmd == "init":
                return pkg_init()
            if cmd == "list":
                return pkg_list()
            if cmd == "add" and len(argv) >= 4:
                return pkg_add(argv[3])
            if cmd == "remove" and len(argv) >= 4:
                return pkg_remove(argv[3])
            if cmd == "info" and len(argv) >= 4:
                try:
                    return pkg_info(argv[3])
                except SproutError:
                    return pkg_registry_info(argv[3], option_value(argv, "--registry"))
            if cmd == "search":
                return pkg_search(positional_value(argv[3:], ""), option_value(argv, "--registry"))
            if cmd == "install" and len(argv) >= 4:
                return pkg_install(argv[3], registry=option_value(argv, "--registry"))
            if cmd == "update":
                return pkg_update(positional_value(argv[3:], "") or None, registry=option_value(argv, "--registry"))
            if cmd == "publish":
                return pkg_publish(positional_value(argv[3:], "."), option_value(argv, "--registry"))
            if cmd == "docs" and len(argv) >= 4:
                return pkg_docs(argv[3], registry=option_value(argv, "--registry"))
            if cmd == "tree":
                return pkg_tree(registry=option_value(argv, "--registry"))
            print("usage: sprout.py pkg init|list|add PATH|remove NAME|info NAME|search QUERY|install NAME[@VERSION]|update|publish [DIR]|docs NAME|tree", file=sys.stderr)
            return 2
        elif argv[1] == "search":
            return pkg_search(positional_value(argv[2:], ""), option_value(argv, "--registry"))
        elif argv[1] == "info":
            if len(argv) < 3:
                print("usage: sprout.py info PACKAGE [--registry PATH]", file=sys.stderr)
                return 2
            return pkg_registry_info(argv[2], option_value(argv, "--registry"))
        elif argv[1] == "list-installed":
            return pkg_list_installed()
        elif argv[1] == "new":
            if len(argv) < 4:
                print("usage: sprout.py new cli|game2d|game3d|library NAME", file=sys.stderr)
                return 2
            return new_project(argv[2], argv[3])
        elif argv[1] == "doctor":
            return doctor()
        elif argv[1] == "release-check":
            return release_check()
        elif argv[1] == "release":
            target = positional_value(argv[2:], ".")
            return release_project(
                target,
                registry=option_value(argv, "--registry"),
                publish="--publish" in argv[2:],
            )
        elif argv[1] == "release-docs":
            return ensure_release_docs()
        elif argv[1] == "install":
            install_language(prefix=option_value(argv, "--prefix"), force="--force" in argv[2:])
        elif argv[1] == "uninstall":
            return uninstall_language(prefix=option_value(argv, "--prefix"))
        elif argv[1] == "language-package":
            package_language(option_value(argv, "--output"))
        elif argv[1] == "vscode-package":
            package_vscode_extension(option_value(argv, "--output"))
        elif argv[1] == "check":
            if len(argv) < 3:
                print("usage: sprout.py check FILE.sprout|DIR [--json] [--warnings]", file=sys.stderr)
                return 2
            return check_file(argv[2], json_mode="--json" in argv[3:], include_warnings="--warnings" in argv[3:])
        elif argv[1] == "lint":
            if len(argv) < 3:
                print("usage: sprout.py lint FILE.sprout|DIR [--json]", file=sys.stderr)
                return 2
            return lint_file(argv[2], json_mode="--json" in argv[3:])
        elif argv[1] == "fmt":
            if len(argv) < 3:
                print("usage: sprout.py fmt FILE.sprout [--write]", file=sys.stderr)
                return 2
            return format_file(argv[2], write="--write" in argv[3:])
        elif argv[1] == "intel":
            if len(argv) < 3:
                print("usage: sprout.py intel FILE.sprout --kind completions|hover|definition|references|signature|symbols|diagnostics --line N --col N [--source TEMP.sprout]", file=sys.stderr)
                return 2
            options = {argv[i]: argv[i + 1] for i in range(3, len(argv) - 1, 2) if argv[i].startswith("--")}
            return intelligence_file(
                argv[2],
                options.get("--kind", "completions"),
                int(options.get("--line", "1")),
                int(options.get("--col", "1")),
                source_path=options.get("--source"),
            )
        elif argv[1] == "stdlib":
            if "--groups" in argv[2:]:
                for group, names in STANDARD_LIBRARY_GROUPS.items():
                    print(f"{group}: {', '.join(names)}")
            else:
                names = builtin_function_names()
                print(f"{len(names)} functions")
                for name in names:
                    print(name)
        elif argv[1] == "examples":
            for path in example_files():
                print(path)
        elif len(argv) >= 2:
            run_file(argv[1], argv[2:])
        else:
            print_help()
            return 2
        return 0
    except BytecodeUnsupported as exc:
        print(f"error: experimental VM does not support this yet: {exc}", file=sys.stderr)
        return 1
    except SproutError as exc:
        print(format_error(exc), file=sys.stderr)
        return 1
    except SproutRaised as exc:
        print(format_error(SproutError(
            f"Uncaught value: {format_value(exc.value)}",
            category="RaisedError",
            hint="Handle this value with try/catch, or remove the raise.",
        )), file=sys.stderr)
        return 1
    except (OSError, IndexError, TypeError) as exc:
        if os.environ.get("SPROUT_DEBUG_PYTHON") == "1":
            raise
        print(format_error(native_runtime_error("command", exc)), file=sys.stderr)
        return 1
    except Exception:
        if os.environ.get("SPROUT_DEBUG_PYTHON") == "1":
            raise
        print(format_error(SproutError(
            "Sprout encountered an unexpected internal runtime failure.",
            category="InternalError",
            hint="Run again with SPROUT_DEBUG_PYTHON=1 when reporting this as a Sprout bug.",
        )), file=sys.stderr)
        return 1


def option_value(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise SproutError(f"{name} needs a value")
    return argv[index + 1]


def positional_value(values: list[str], default: str) -> str:
    skip_next = False
    for value in values:
        if skip_next:
            skip_next = False
            continue
        if value in {"--registry", "--prefix", "--output"}:
            skip_next = True
            continue
        if value.startswith("--"):
            continue
        return value
    return default
