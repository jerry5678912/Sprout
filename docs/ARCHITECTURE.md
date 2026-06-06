# Sprout Architecture

This document is a map for contributors. The stable interpreter defines
language behavior; the experimental VM should match it for supported features.

## Execution Pipeline

```text
.sprout source
    |
    v
Lexer -> tokens -> Parser -> AST
                         | \
                         |  \-> Type checker / semantic analysis / LSP
                         |
                         +----> Stable tree-walk interpreter
                         |
                         +----> Bytecode compiler -> experimental VM
```

`sprout.py` is a compatibility launcher. Command dispatch lives in
`sprout_core/cli.py`.

## Language Front End

- `model.py` contains shared diagnostics, errors, tokens, and version metadata.
- `lexer.py` turns source text into located tokens.
- `parser.py` builds tuple-based AST nodes.

AST changes affect many systems. Search for the node's string tag in
`runtime.py`, `bytecode.py`, `typesystem.py`, `analysis.py`, and `tooling.py`
before considering a syntax implementation complete.

## Stable Runtime

`runtime.py` contains the reference interpreter, lexical environments,
functions, classes, modules, generators, enum values, pattern matching, built-in
methods, and Python interop.

Normal `sprout file.sprout` execution uses this path. New behavior should be
specified and tested here first.

`application.py` contains host-backed resources such as tasks, async streams,
HTTP, SQLite, and test expectations. These APIs translate host failures into
Sprout errors rather than exposing Python tracebacks.

## Bytecode VM

`bytecode.py` contains:

- AST-to-bytecode compilation;
- code objects and located instructions;
- stack and call-frame execution;
- resumable VM generators;
- imported-module VM execution;
- disassembly, debugging, profiling, and benchmarks.

The VM is optional and experimental. Unsupported behavior must fail clearly or
use an explicitly documented fallback; it must never silently produce different
results. Parity tests compare stable and VM output.

## Types and Semantic Tooling

`typesystem.py` implements gradual annotations, generics, interfaces, unions,
aliases, narrowing, imported types, and exhaustiveness checks.

`analysis.py` builds lexical scopes, stable symbol identities, project indexes,
references, definitions, hover data, completion data, and semantic tokens.

`tooling.py` exposes parse checking, linting, formatting, project/module search
paths, and JSON editor queries. `tools/sprout_lsp.py` presents semantic data over
LSP. `tools/sprout_dap.py` presents the VM debugger over DAP.

## Projects and Packages

- `package.py`: `sprout.toml`, local package metadata, templates, and doctor
- `ecosystem.py`: dependency resolution, lockfiles, builds, bundles, registries
- `registry_server.py`: authenticated hosted registry service
- `standalone.py`: portable application directories and `.sproutapp` bundles
- `distribution.py`: language installer, release ZIP, and VS Code VSIX

Package/archive code is security-sensitive. Paths must be normalized, symbolic
links rejected, checksums verified, and size/file limits enforced.

## Compatibility Contract

The conformance manifest under `sprout_core/conformance/` records stable,
user-visible behavior. A behavior change should update:

1. implementation;
2. focused regression tests;
3. interpreter/VM parity coverage;
4. conformance data when the behavior is public;
5. editor support;
6. manual, examples, and changelog.

## Generated and Release Files

- `docs/manual.html` is generated from `docs/MANUAL.md`.
- `dist/`, `build/`, `.sprout/`, and local playground projects are not committed.
- `python3 sprout.py language-package` builds the source/runtime ZIP.
- `python3 sprout.py vscode-package` builds the VSIX.
- `python3 -m build` builds Python wheel/source artifacts.
