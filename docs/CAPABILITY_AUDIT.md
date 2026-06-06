# Sprout Capability Audit

Audit date: 2026-06-06

This document began as the Sprout 0.3.0 baseline audit and now tracks the
verified state after completing its ten highest-impact milestones.

## Executive Summary

Sprout is a functioning language platform with installation and release
artifacts, a stable tree-walk interpreter, an experimental bytecode VM,
incremental semantic tooling, a persistent LSP, VS Code debugging, hosted package
infrastructure, standalone application bundles, structured async syntax,
conformance/security gates, and optional gradual types.

The ten milestones from this audit are complete. Remaining work is narrower:
direct VM async execution, richer cross-module typing, additional language
constructs, package signing/trust governance, and production hardening.

## Capability Matrix

| Capability | Status |
| --- | --- |
| Variables, collections, functions, closures, and recursion | Exists |
| Defaults, keyword arguments, variadics, and call spreading | Exists |
| Classes, instances, single inheritance, and `super` | Exists |
| Exceptions, Sprout modules, and Python interop | Exists |
| Stable tree-walk interpreter | Exists |
| Bytecode VM | Experimental with broad parser-level coverage |
| Terminal debugger, profiler, and VS Code debugger | Exists |
| Formatter, linter, semantic analysis, and IntelliSense | Exists |
| Persistent stdio language server | Exists |
| VS Code semantic tooling | Exists |
| Project templates and `sprout.toml` | Exists |
| Builds, bundles, dependency resolution, and lockfiles | Exists |
| Local and authenticated hosted package registries | Exists |
| HTTP, SQLite, task, engineering, test, and game APIs | Exists |
| Optional types, structural interfaces, and generics | Exists as gradual file-local checker |
| Native `async` / `await` and structured task groups | Exists in stable interpreter; VM fallback |
| Pattern matching, generators, and comprehensions | Missing |
| Hosted authenticated package registry | Exists |
| Automated CI, tagged releases, and language installer | Exists |

## Existing Capabilities

The runtime exposes 175 callable global functions and 15 built-in dot methods. Major groups cover core values and I/O, collections, strings, dictionaries, files and JSON, math and statistics, random and time, testing, tasks, HTTP, SQLite, engineering, games, and graphics.

The VM supports common expressions, variables, assignments, collections, calls, functions, loops, classes, methods, imports, Python interop, exceptions, `seedfn`, slices, slice assignment, inheritance, and `super`. Test declarations are accepted as ordinary-execution no-ops. Imported Sprout module bodies and the dedicated test runner still use stable interpreter infrastructure.

Tooling includes JSON diagnostics, safe formatting, practical lint warnings,
incremental semantic completions, hover, definition, references, rename,
signature help, document/workspace symbols, semantic highlighting, a persistent
stdio LSP, and a VS Code debug adapter.

The project and package system includes deterministic builds, `.sproutpkg`
bundles, semantic-version constraints, conflict detection, `sprout.lock`,
authenticated immutable publishing, local and hosted registries, and standalone
`.sproutapp` bundles with embedded Sprout runtimes.

## Major Missing Capabilities

- Direct VM execution for structured async functions and imported module bodies
- Package signatures, publisher identity governance, and public trust policy
- Additional debugger workflows such as logpoints, data breakpoints, and test coverage
- Cross-module type inference, unions, aliases, narrowing, and overloads
- Pattern matching, generators, and comprehensions
- Production-grade networking and third-party security auditing

## Top 10 Highest-Impact Future Milestones

1. Professional release and installation pipeline (completed)
2. Accurate incremental semantic engine (completed)
3. VM parity, performance, and source maps (completed)
4. Production LSP implementation (completed)
5. VS Code debugger and developer workflows (completed)
6. Secure hosted package registry (completed)
7. Standalone application distribution (completed)
8. Structured async language model (completed)
9. Conformance, fuzzing, and security testing (completed)
10. Optional typed abstraction system (completed)
