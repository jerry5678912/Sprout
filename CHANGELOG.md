# Changelog

## Unreleased

- Added standard Python packaging with a `sprout` console entry point, wheel and
  source-distribution CI, and a trusted-publishing PyPI workflow.
- Completed the MIT license text and expanded security, conduct, architecture,
  contribution, issue, and pull-request documentation for public development.
- Made `release-check` portable when a POSIX shell is unavailable and expanded
  CI to cover error reporting, the debug adapter, and conformance tests.
- Reworked the README around accurate alpha status, installation, capabilities,
  documentation, and contribution paths.
- Added generic, data-carrying enums and guarded structural pattern matching
  with wildcard, literal, binding, variant, and array-rest patterns.
- Added exhaustiveness and duplicate-case diagnostics for typed enum matches.
- Added lazy resumable generators with `yield`, `.next()`, and `.collect()`.
- Added list and dictionary comprehensions with optional filters.
- Added union types, nullable shorthand, generic type aliases, qualified
  imported types, cross-module call checking, and `is`-based narrowing.
- Added asynchronous streams, `async for`, cancellation tokens, async timers,
  HTTP requests, file I/O, and queue receives.
- Expanded the experimental VM with direct imported-module execution, async
  functions, awaits, streams, enums, matches, comprehensions, type tests,
  task groups, and resumable generators without interpreter fallback.
- Expanded semantic indexing, completion, highlighting, snippets, diagnostics,
  disassembly, conformance coverage, and interpreter/VM parity tests.

## 0.3.0

- Added structured async functions, `await`, and lexical `taskgroup` scopes with
  failure propagation and best-effort sibling cancellation.
- Added async method support, editor completions/highlighting/snippets, semantic
  indexing, interpreter tests, and explicit experimental-VM fallback reporting.
- Added a checked-in language conformance corpus with machine-readable results
  and interpreter/VM parity expectations.
- Added seed-reproducible valid-program differential fuzzing and malformed-input
  lexer/parser fuzzing.
- Added a dedicated security regression suite and package extraction file-count
  and expanded-size limits.
- Fixed trailing string escapes so hostile input produces a Sprout diagnostic
  instead of an internal index error.
- Added optional variable, parameter, and return type annotations with a
  machine-readable `typecheck` command.
- Added generic functions/classes, structural interface declarations, and
  `implements` validation with runtime-erased interpreter/VM execution.
- Added typed signatures, diagnostics, highlighting, completions, snippets,
  examples, conformance coverage, and regression tests.
- Added standalone application directories and deterministic `.sproutapp` archives with embedded Sprout runtimes, resolved dependencies, assets, cross-platform launchers, and exact integrity manifests.
- Added an authenticated hosted package registry with package-scoped bearer tokens, token revocation, immutable publishing, and public search/install endpoints.
- Added server-side archive identity, path, symlink, expansion-size, bundle checksum, and per-file checksum validation.
- Added native VS Code Test Explorer discovery and per-test execution backed by structured test JSON.
- Added LSP quick fixes for tab indentation and Python-style constant aliases.
- Added conditional breakpoints, hit-count breakpoints, expression evaluation, and uncaught-error stopping.
- Added a Debug Adapter Protocol server with source breakpoints, stepping, pause/continue, call stacks, scopes, variable inspection, expression evaluation, and Debug Console output.
- Integrated the Sprout debugger with VS Code and bundled it in distributable VSIX packages.
- Promoted the stdio LSP foundation into a lifecycle-correct persistent server with incremental sync, workspace symbols, cancellation, safe rename preparation, and protocol error handling.
- Connected VS Code to the persistent language server with automatic command-based fallback and bundled the server in VSIX artifacts.
- Added categorized, source-aware syntax and runtime errors with code excerpts, carets, hints, and clean Sprout stack traces.
- Translated Python tracebacks into Sprout call stacks, preserving bridge boundaries and relevant bridged function locations without raw implementation noise.
- Expanded VM parity with slices, slice assignment, `seedfn`, inheritance, and `super`.
- Added parser-level handling for test declarations during ordinary VM execution.
- Added source locations to bytecode disassembly, debugging, and VM stack traces.
- Expanded benchmarks with compile time, instruction counts, and explicit fallback reporting.
- Added VM parity tests for successful and failing inheritance, slicing, and inline functions.
- Added lexical-scope-aware semantic binding with stable symbol identities.
- Made references and rename distinguish same-named locals and parameters in different functions.
- Connected imported module member references to their exported definitions.
- Added incremental in-memory workspace analysis with content and filesystem change detection.
- Added language-server and adversarial semantic regression tests.
- Added a cross-platform language installer, installation manifest, global launcher, and uninstall command.
- Added deterministic Sprout language ZIP and self-contained VS Code VSIX artifacts.
- Added Linux, macOS, and Windows CI plus tag-driven GitHub release automation.
- Added distribution regression tests, version consistency checks, and a saved capability audit.
- Added deterministic project builds with lockfiles, assets, dependency materialization, hashes, and optional VM bytecode inspection output.
- Added reproducible platform-independent `.sproutpkg` bundles.
- Added semantic-version constraints, dependency trees, conflict detection, installs, and updates.
- Added a local/JSON registry with search, package information, checksum verification, immutable versions, documentation metadata, and publishing.
- Added package quality checks and project release generation.
- Added ecosystem regression tests and package contribution documentation.

## 0.2.0

- Added first-class Sprout test declarations and the `sprout.py test` runner.
- Added task, future, timer, and message-queue foundations.
- Added HTTP client and route-based local server helpers.
- Added SQLite connections, queries, rows, and transactions.
- Added engineering/math and reusable game-application modules.
- Added project API documentation generation.
- Added application examples, regression tests, and VS Code support.

## 0.1.0

- Early Sprout language, tooling, VM, editor, and package-manager foundations.
