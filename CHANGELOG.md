# Changelog

## 0.3.5

- Added strict isolated interpreter/VM differential execution with normalized
  output, diagnostics, source locations, stack frames, timeout state, support
  state, and fallback detection.
- Added `sprout run --vm --no-fallback FILE` while preserving ordinary VM
  fallback behavior.
- Expanded the conformance corpus to 16 strict VM cases and added an explicit
  required/unsupported/not-applicable construct inventory.
- Fixed VM function and imported-error locations and stack frames to match the
  authoritative tree-walk interpreter.
- Replaced arithmetic-only fuzzing with six bounded valid-program families,
  guaranteed-malformed parser cases, classified JSON failures, and bounded
  mismatch reduction.
- Added repeated-median JSON benchmarks for startup, compilation, loops, calls,
  collections, object fields, exceptions, and imports.
- Hardened invalid assignment-target diagnostics and packaged all benchmark,
  conformance, and nested module fixtures.

## VS Code Extension 0.4.0

This extension release was paired with Sprout runtime `0.3.4`.

- Unified scalar/container type inference and dynamic object-shape inference so
  completions, hover details, and member diagnostics use the same bounded
  analysis facts.
- Added flow-sensitive replacement for straight-line assignments, branch joins
  with required versus conditional members, loop item inference, inferred
  unannotated returns, call-site parameter inference, constructor fields, and
  recursive/cross-module summary convergence.
- Added `SPROUT_POSSIBLY_MISSING_MEMBER`: hidden in basic mode, a warning in
  standard mode, and an error in strict mode. Conditional members remain
  available in completion with a clear label and lower ranking.
- Added inferred types, nilability, and member presence to semantic symbol
  output and richer hover details.
- Bounded recursive shapes and inferred unions, and invalidated cross-file facts
  through dependency signatures without adding an on-disk workspace cache.
- Made `sprout docs` reuse semantic workspace analysis instead of a separate
  regex-only scanner, so generated API docs stay aligned with Sprout
  signatures, class constructors, member docs, and source locations.
- Added test-doc metadata to structured `sprout test --list --json` output and
  surfaced it as VS Code Testing view tooltips.
- Reused semantic signatures in the debug adapter so Sprout stack frames and
  local scopes show friendlier function labels when symbol resolution is known.
- Updated README, manual, and extension docs to reflect current `standard`
  analysis mode support and the latest verified editor/runtime integrations.

## 0.3.4

- Added a VS Code **Sprout: Show Language Server Output** command with clear
  language-server startup, interpreter, document, diagnostic, and request logs.
- Added a VS Code **Sprout: Restart Language Server** command for recovering
  IntelliSense without reloading the whole editor.
- Tightened VS Code/LSP document lifecycle handling so open documents are
  tracked, duplicate `didOpen` notifications are avoided, blank documents clear
  diagnostics immediately, and stale fallback diagnostics are ignored.
- Added server-side LSP stderr logging for document sync, diagnostics,
  completions, hover, navigation, rename, and code actions.
- Added an editor test workspace and an automated editor-behavior check for
  diagnostics, completion, hover, definition, references, rename, and quick
  fixes.
- Updated editor documentation to describe tested, partial, fallback, and
  experimental behavior more honestly.

## Dev History

### Safe Navigation And Nil Coalescing

- Added `?.` safe property and method access with argument short-circuiting for
  nil receivers.
- Added right-associative `??` nil coalescing, preserving valid falsey values
  such as `false` and `0`.
- Added matching interpreter and strict VM execution, nil-aware type inference,
  semantic member completion, diagnostics, syntax highlighting, conformance,
  and structured fuzz coverage.

### Completion Label Cleanup

- Fixed VS Code completion kind mapping so Sprout LSP keywords, interfaces,
  enums, modules, and type parameters display with the right IntelliSense
  labels instead of misleading class/variable labels.

### Diagnostic Freshness

- Made VS Code diagnostics clear immediately when a Sprout document becomes
  blank.
- Ignored stale LSP and command fallback diagnostics when the editor document
  has changed since the check started.
- Reduced the editor diagnostic debounce so warnings update faster while typing.

### Native Diagnostic Rendering

- Removed the custom VS Code squiggle overlay so Sprout diagnostics render like
  Pylance through VS Code's native diagnostic system only.
- Kept code-word typo diagnostics yellow when a clear replacement is available,
  even in strict mode.
- Cleared diagnostics for blank Sprout documents so empty editors do not show
  stale red underlines.

### Earlier Diagnostic Expansion

- Added strong VS Code diagnostic decorations so Sprout errors, warnings, hints,
  and unused symbols are visibly underlined/faded even when a theme makes native
  squiggles subtle.
- Expanded code-word typo suggestions for keywords, built-ins, imports, local
  symbols, and module/class members.
- Added quick-fix data and LSP code actions for typo replacement, unused import
  removal, and safe unused-name prefixing.
- Improved fallback editor diagnostics to underline full words instead of one
  character.

## 0.3.3

- Added Pylance-style `off`, `basic`, and `strict` editor checking modes,
  per-rule severity overrides, live LSP reconfiguration, and unnecessary-symbol
  tags for faded unused imports, parameters, and variables.
- Added unknown-member, missing-annotation, keyword-argument, duplicate
  argument, and more precise import diagnostics.
- Added a VS Code interpreter selector, interpreter status item, validation,
  and an integrated-terminal command for running the current Sprout file.
- Published `sprout-language` 0.3.0 on PyPI and updated installation
  documentation for `pip` and `pipx`.
- Added standard Python packaging with a `sprout` console entry point, wheel and
  source-distribution CI, and a trusted-publishing PyPI workflow.
- Adopted Apache License 2.0 consistently across source releases, Python
  packaging, project templates, examples, and contribution documentation.
- Added project governance and contribution licensing guidance focused on
  stability, coordination, attribution, and maintainable language evolution.
- Set the VS Code extension publisher to the public Marketplace publisher ID.
- Expanded security, conduct, architecture, contribution, issue, and
  pull-request documentation for public development.
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
