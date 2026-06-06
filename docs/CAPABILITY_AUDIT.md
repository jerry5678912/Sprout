# Sprout Capability Audit

Audit date: 2026-06-06

This document records the capabilities found in the Sprout 0.3.0 working tree before the professional release and installation milestone began.

## Executive Summary

Sprout is a functioning language platform with a stable tree-walk interpreter, an experimental bytecode VM, project-aware editor tooling, local and JSON-backed package infrastructure, application libraries, project templates, documentation, and broad regression coverage.

The largest remaining foundations are reliable installation and releases, complete VM parity, incremental semantic analysis, a production LSP/editor workflow, secure public package hosting, standalone application distribution, and advanced type and async systems.

## Capability Matrix

| Capability | Status |
| --- | --- |
| Variables, collections, functions, closures, and recursion | Exists |
| Defaults, keyword arguments, variadics, and call spreading | Exists |
| Classes, instances, single inheritance, and `super` | Exists |
| Exceptions, Sprout modules, and Python interop | Exists |
| Stable tree-walk interpreter | Exists |
| Bytecode VM | Experimental with broad parser-level coverage |
| Terminal debugger and profiler | Partial |
| Formatter, linter, semantic analysis, and IntelliSense | Exists |
| Stdio language server | Foundation |
| VS Code semantic tooling | Exists |
| Project templates and `sprout.toml` | Exists |
| Builds, bundles, dependency resolution, and lockfiles | Exists |
| Local writable and HTTP-readable JSON registry | Exists |
| HTTP, SQLite, task, engineering, test, and game APIs | Exists |
| Static types, interfaces, and generics | Missing |
| Native `async` / `await` | Missing |
| Pattern matching, generators, and comprehensions | Missing |
| Hosted authenticated package registry | Missing |
| Automated CI, tagged releases, and language installer | Missing at audit time |

## Existing Capabilities

The runtime exposes 175 callable global functions and 15 built-in dot methods. Major groups cover core values and I/O, collections, strings, dictionaries, files and JSON, math and statistics, random and time, testing, tasks, HTTP, SQLite, engineering, games, and graphics.

The VM supports common expressions, variables, assignments, collections, calls, functions, loops, classes, methods, imports, Python interop, exceptions, `seedfn`, slices, slice assignment, inheritance, and `super`. Test declarations are accepted as ordinary-execution no-ops. Imported Sprout module bodies and the dedicated test runner still use stable interpreter infrastructure.

Tooling includes JSON diagnostics, safe formatting, practical lint warnings, semantic completions, hover, definition, references, rename, signature help, document symbols, semantic highlighting, and a stdio LSP foundation.

The project and package system includes deterministic builds, `.sproutpkg` bundles, semantic-version constraints, conflict detection, `sprout.lock`, package publishing and installation, local registries, and remote read-only JSON registries.

## Major Missing Capabilities

- Reliable language installation, a global launcher, CI, and tagged release artifacts
- Full VM parity and consistent source maps
- Incremental and scope-precise semantic analysis
- Full LSP services, VS Code debugging, code actions, and extension-host tests
- Hosted package accounts, ownership, signatures, trust policy, and revocation
- Standalone application bundles that include their runtime
- Static typing, interfaces, and generics
- Native async functions and awaiting
- Pattern matching, generators, and comprehensions
- Production networking and broader security/conformance testing

## Top 10 Highest-Impact Future Milestones

1. Professional release and installation pipeline
2. Accurate incremental semantic engine
3. VM parity, performance, and source maps
4. Production LSP implementation
5. VS Code debugger and developer workflows
6. Secure hosted package registry
7. Standalone application distribution
8. Structured async language model
9. Conformance, fuzzing, and security testing
10. Optional typed abstraction system
