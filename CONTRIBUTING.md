# Contributing to Sprout

Thanks for helping Sprout grow.

## Setup

```sh
python3 sprout.py help
python3 tests/ecosystem.py
python3 tests/distribution.py
tests/smoke.sh
```

Keep changes small, add tests, and update docs when behavior changes.

Pull requests run on Python 3.9 and 3.12 across Linux, macOS, and Windows. Release tags must match `python3 sprout.py version`.

Build release artifacts locally with:

```sh
python3 sprout.py language-package
python3 sprout.py vscode-package
```

## Contributing Packages

Packages need a valid semantic version, description, author, license, working main file, documentation, and passing Sprout tests. Run:

```sh
python3 sprout.py test
python3 sprout.py build
python3 sprout.py package
python3 sprout.py release
```

Use version constraints deliberately. Commit `sprout.toml`, source, tests, and docs. Commit `sprout.lock` for applications; libraries may omit it when they intentionally support a range of dependency versions.

Do not publish credentials, generated `.sprout/packages/`, `build/`, or `dist/` contents.
