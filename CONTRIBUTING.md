# Contributing to Sprout

Thank you for improving Sprout. Contributions may include runtime fixes,
language tooling, tests, documentation, examples, package infrastructure, or
carefully designed language changes.

Sprout is an alpha language. Compatibility matters: avoid changing syntax or
runtime behavior accidentally, and describe deliberate changes clearly.
Read [GOVERNANCE.md](GOVERNANCE.md) for the project's priorities and
decision-making principles.

## Before You Start

- Search existing issues and pull requests.
- Open an issue before a large language, runtime, VM, package-format,
  standard-library, ecosystem, or architecture change.
- Check [ROADMAP.md](ROADMAP.md) and coordinate with existing work instead of
  starting a duplicate implementation.
- Keep security reports private as described in [SECURITY.md](SECURITY.md).
- Do not include generated `build/`, `dist/`, `.sprout/`, credentials, or local
  editor files.

## Development Setup

Requirements:

- Python 3.9 or newer
- Node.js 20 or newer for VS Code extension checks
- A POSIX shell for `tests/smoke.sh` on macOS/Linux

Clone and verify the checkout:

```sh
git clone https://github.com/jerry5678912/Sprout.git
cd Sprout
python3 sprout.py version
python3 sprout.py doctor
python3 tests/tooling.py
```

No third-party Python runtime dependency is required for core Sprout. Optional
graphics examples use Pygame or Panda3D.

For an editable command installation:

```sh
python3 -m pip install -e .
sprout version
```

## Repository Map

- `sprout_core/lexer.py`, `parser.py`, `model.py`: language syntax and AST data
- `sprout_core/runtime.py`: stable reference interpreter and built-ins
- `sprout_core/bytecode.py`: experimental compiler, VM, debugger, and profiler
- `sprout_core/typesystem.py`: gradual static checker
- `sprout_core/analysis.py`: semantic workspace model and IntelliSense
- `sprout_core/tooling.py`: check, lint, format, and editor query commands
- `sprout_core/application.py`: testing, async, HTTP, and SQLite host APIs
- `sprout_core/ecosystem.py`: builds, packages, dependencies, and registries
- `tools/sprout_lsp.py`, `tools/sprout_dap.py`: LSP and Debug Adapter servers
- `editor/vscode-sprout/`: VS Code extension
- `tests/`: structured Python and Sprout regression tests
- `sprout_core/conformance/`: stable behavior contract
- `docs/`: manual, architecture, ecosystem, and audit documents

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing execution,
semantic analysis, imports, or package resolution.

## Choosing Tests

Run focused tests while developing:

```sh
python3 tests/advanced_language.py   # enums, match, generators, async
python3 tests/vm.py                  # interpreter/VM parity
python3 tests/typesystem.py          # annotations and diagnostics
python3 tests/intellisense.py        # semantic analysis
python3 tests/lsp.py                 # language server protocol
python3 tests/debug_adapter.py       # VS Code debugger protocol
python3 tests/ecosystem.py           # builds, packages, registry
python3 tests/security.py            # hostile inputs and archive safety
```

Before opening a pull request:

```sh
python3 sprout.py conformance
python3 tools/check_editor_coverage.py
tests/smoke.sh
python3 sprout.py doctor
python3 sprout.py release-check
```

`tests/smoke.sh` and some integration tests bind temporary localhost servers.
Windows contributors can run the structured Python tests directly; CI runs the
full matrix across Linux, macOS, and Windows.

## Language Change Checklist

A syntax or behavior change normally requires all of these:

1. Lexer/parser implementation and precise source locations
2. Stable interpreter behavior
3. VM implementation or an explicit unsupported diagnostic
4. Type checker and semantic-analysis support where applicable
5. Formatter/linter behavior
6. VS Code grammar, semantic tokens, snippets, and completions
7. Interpreter/VM parity tests
8. A conformance case for stable public behavior
9. Manual, README, examples, and changelog updates

Do not add syntax only to one execution path.

## Code Style

- Support Python 3.9.
- Prefer existing repository patterns and standard-library modules.
- Keep user-facing failures as `SproutError`; do not leak raw Python tracebacks.
- Preserve file, line, column, function, and module context in diagnostics.
- Add comments only where the implementation is not self-explanatory.
- Keep unrelated refactors out of focused fixes.

Run:

```sh
PYTHONPYCACHEPREFIX=/tmp/sprout-pycache python3 -m compileall -q sprout.py install.py sprout_core tools tests
git diff --check
```

## Documentation

The Markdown manual is authoritative:

```sh
python3 tools/build_manual.py
```

Commit both `docs/MANUAL.md` and the generated `docs/manual.html` when the
manual changes.

## Pull Requests

A useful pull request:

- explains the problem and user-visible behavior;
- links the relevant issue when one exists;
- includes regression tests;
- lists the commands that were run;
- updates compatibility notes and documentation;
- avoids generated artifacts unless the repository tracks them.

Maintainers may ask to split large changes so language semantics, runtime work,
and editor work remain reviewable.

## Licensing Contributions

Sprout is licensed under the Apache License 2.0. By submitting a contribution,
you agree that it may be distributed under that license and confirm that you
have the right to submit it. Apache License 2.0 includes copyright terms,
attribution requirements, and an express patent grant for submitted
contributions.

- Preserve applicable copyright, attribution, and `NOTICE` information.
- Do not add code, assets, or dependencies with incompatible license terms.
- Identify third-party work clearly and include its required notices.
- Ask in an issue before introducing a dependency with unclear licensing.

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the complete project terms.

## Packages and Releases

Package projects need valid semantic versions, documentation, tests, and a
license. Validate them with:

```sh
python3 sprout.py test
python3 sprout.py build
python3 sprout.py package
python3 sprout.py release
```

For language releases:

```sh
python3 -m build
python3 -m twine check dist/*.whl dist/*.tar.gz
python3 sprout.py language-package
python3 sprout.py vscode-package
python3 sprout.py release-check
```

Release tags must exactly match `python3 sprout.py version`.
