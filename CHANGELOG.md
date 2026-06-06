# Changelog

## 0.3.0

- Added categorized, source-aware syntax and runtime errors with code excerpts, carets, hints, and clean Sprout stack traces.
- Prevented Python tracebacks from leaking during normal execution and translated native, file, math, and Python-interop failures into Sprout errors.
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
