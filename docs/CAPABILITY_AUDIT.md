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

The ten milestones from this audit are complete. A subsequent advanced-language
milestone added enums, pattern matching, generators, comprehensions,
cross-module union typing, asynchronous streams, and direct VM execution for
those constructs. Remaining work is narrower: package signing/trust governance,
deeper inference and protocols, native runtime performance, and production
hardening.

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
| Optional types, structural interfaces, unions, aliases, and generics | Exists as gradual project-aware checker |
| Native `async` / `await`, async streams, and structured task groups | Exists in interpreter and VM |
| Pattern matching, generators, and comprehensions | Exists |
| Hosted authenticated package registry | Exists |
| Automated CI, tagged releases, and language installer | Exists |

## Existing Capabilities

The runtime exposes 183 callable global functions and 15 built-in dot methods. Major groups cover core values and I/O, collections, strings, dictionaries, files and JSON, math and statistics, random and time, testing, tasks, HTTP, SQLite, engineering, games, and graphics.

The VM supports common expressions, variables, assignments, collections,
calls, functions, loops, classes, methods, imports, Python interop, exceptions,
`seedfn`, slices, inheritance, enums, pattern matching, generators,
comprehensions, asynchronous functions/streams, and structured task groups.
Test declarations are accepted as ordinary-execution no-ops.

Tooling includes JSON diagnostics, safe formatting, practical lint warnings,
incremental semantic completions, hover, definition, references, rename,
signature help, document/workspace symbols, semantic highlighting, a persistent
stdio LSP, and a VS Code debug adapter.

The project and package system includes deterministic builds, `.sproutpkg`
bundles, semantic-version constraints, conflict detection, `sprout.lock`,
authenticated immutable publishing, local and hosted registries, and standalone
`.sproutapp` bundles with embedded Sprout runtimes.

## Major Missing Capabilities

- Package signatures, publisher identity governance, and public trust policy
- Additional debugger workflows such as logpoints, data breakpoints, and test coverage
- Deeper generic inference, overloads, protocols, and control-flow analysis
- Native-code or lower-level VM performance beyond the Python-hosted runtime
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
