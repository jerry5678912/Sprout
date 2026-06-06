# Sprout Build And Package Ecosystem

Sprout 0.3 provides reproducible builds, portable package bundles, dependency lockfiles, and local or hosted registries.

## Package Metadata

Projects keep runtime metadata under `[project]`. Publishable libraries may add `[package]`; package values override matching project values during publishing.

```toml
[project]
name = "physics_tools"
version = "1.2.0"
main = "src/main.sprout"
authors = ["Ada Example"]
description = "Engineering helpers"
license = "MIT"

[package]
name = "physics_tools"
version = "1.2.0"
description = "Engineering helpers"
author = "Ada Example"
license = "MIT"

[paths]
source = ["src"]
modules = ["modules"]
assets = ["assets"]

[dependencies]
vectors = "^2.0.0"
local_geometry = { path = "../local_geometry", version = "~1.4.0" }
```

Supported constraints are exact versions, `*`, `latest`, `^`, `~`, comparison operators, and comma-separated ranges such as `>=1.2.0,<2.0.0`.

## Build And Bundle

```sh
python3 sprout.py build
python3 sprout.py build --vm
python3 sprout.py build path/to/project
python3 sprout.py package
```

Builds validate source and dependencies, write `sprout.lock`, copy configured source/module/asset folders, materialize dependencies, and generate `build-manifest.json` with file hashes. `--vm` also compiles the main file and writes readable experimental bytecode.

`package` creates `dist/NAME-VERSION.sproutpkg`. Files are sorted and archive timestamps are fixed so unchanged inputs produce the same bundle bytes.

## Registry

Set the registry for a shell:

```sh
export SPROUT_REGISTRY="$HOME/.sprout/registry"
```

Every registry contains an `index.json` plus versioned bundles under `packages/`. Registry records include SHA-256 checksums, installs verify bundle integrity, and an existing package version cannot be republished. HTTP/HTTPS registries support public search/install and authenticated publishing.

```sh
python3 sprout.py pkg search physics
python3 sprout.py pkg install physics_tools@^1.0.0
python3 sprout.py pkg update
python3 sprout.py pkg update physics_tools
python3 sprout.py pkg tree
python3 sprout.py pkg docs physics_tools
python3 sprout.py list-installed
```

Convenience aliases are:

```sh
python3 sprout.py search physics
python3 sprout.py info physics_tools
python3 sprout.py list-installed
```

Installed packages live under `.sprout/packages/` and are recorded in `sprout.toml`. Their requested constraint is preserved for deterministic updates.

## Hosted Registry

Create a package-scoped publishing token:

```sh
python3 sprout.py registry token physics-publisher \
  --root ./registry-data \
  --packages physics_tools
```

The command prints the secret once. The registry stores only its SHA-256 digest. Set the token for publishing:

```sh
export SPROUT_REGISTRY_TOKEN="sprout_..."
export SPROUT_REGISTRY="https://packages.example.com"
python3 sprout.py pkg publish
```

Run the registry service:

```sh
python3 sprout.py registry serve --root ./registry-data --host 127.0.0.1 --port 8787
```

For public deployment, keep the service on a private interface and place it behind an HTTPS reverse proxy. The built-in server intentionally does not manage TLS certificates.

Token administration:

```sh
python3 sprout.py registry token list --root ./registry-data
python3 sprout.py registry token revoke physics-publisher --root ./registry-data
```

Hosted publishing enforces bearer authentication, package scopes, immutable versions, bundle and per-file checksums, manifest identity, archive path safety, symlink rejection, and upload/expanded-size limits.

## Publishing

```sh
python3 sprout.py pkg publish
python3 sprout.py pkg publish path/to/package --registry ./registry
python3 sprout.py pkg publish --registry https://packages.example.com --token "sprout_..."
```

Publishing checks:

- valid package name and semantic version
- existing main file
- description, author, and license
- parseable Sprout source
- passing Sprout tests when `tests/` exists
- README or documentation
- resolvable, conflict-free dependencies

Publishing generates API docs when needed, creates the bundle, stores it under a versioned registry path, and updates machine-readable registry metadata.

## Releases

```sh
python3 sprout.py release
python3 sprout.py release --publish --registry ./registry
```

`release` runs package quality checks, generates Markdown and HTML API documentation, creates the bundle, and writes `dist/release.json`. `--publish` also publishes the package.

## Standalone Applications

Application bundles include the Sprout runtime and resolved dependencies:

```sh
python3 sprout.py app build path/to/project
python3 sprout.py app verify path/to/project/dist/name-version-standalone
python3 sprout.py app run path/to/project/dist/name-version-standalone -- arg1
python3 sprout.py app package path/to/project
```

The build contains:

- `app/`: validated project source, assets, and materialized dependencies
- `runtime/`: the matching Sprout runtime
- `launcher.py`: runtime bootstrap
- an executable macOS/Linux launcher
- a Windows `.cmd` launcher
- `standalone-manifest.json`: exact file list and SHA-256 hashes

`app package` writes a deterministic `.sproutapp` archive. A recipient needs Python 3.9 or newer but does not need a separate Sprout installation. `app verify` rejects missing, changed, or unexpected files.

## Generated Files

- `sprout.lock`: exact resolved dependency versions and sources
- `build/`: validated build images
- `dist/*.sproutpkg`: portable package bundles
- `dist/release.json`: release metadata
- `dist/*-standalone/`: runnable standalone application directories
- `dist/*.sproutapp`: portable standalone application archives
- `.sprout/packages/`: installed registry packages

Applications should normally commit `sprout.lock`. Generated build, distribution, and installation folders should normally stay out of Git.
