# Sprout Polyglot Language Packs Experiment

This document describes the `experiment/polyglot-language-packs` branch. The
branch explores writing the same Sprout language using reviewed, data-only
vocabulary packs while preserving one canonical parser, AST, bytecode format,
and runtime.

This is an experiment, not a Sprout language release.

## Version Status

- Sprout language and runtime: `0.3.4`
- VS Code extension: `0.4.0`
- Bundled language-pack schema: `1`
- First complete reference pack: Simplified Chinese (`chinese-pack`)

Do not tag this branch as Sprout `0.4.0`, publish it to PyPI, or merge it into
`main` without a separate release review.

## Try The Experiment

Select a pack with the first meaningful statement in a source file:

```sprout
language "chinese-pack"

定义 打招呼(名字):
  输出 "你好，" + 名字

打招呼("小明")
```

Run it from this checkout:

```sh
python3 sprout.py run examples/polyglot/chinese_python_blocks.sprout
python3 sprout.py run examples/polyglot/chinese_guessing_game.sprout
python3 sprout.py run examples/polyglot/chinese_moonlit_dungeon.sprout --演示
```

The Panda3D example requires `panda3d`:

```sh
python3 -m pip install panda3d
python3 sprout.py run examples/polyglot/chinese_panda3d_crystal_hunt.sprout
```

## What Works

- Localized syntax, constants, operators, built-ins, and built-in methods
- Unicode function, class, variable, parameter, method, and exported names
- English fallback inside every language pack
- English and Chinese vocabulary mixed in the same source file
- Different packs in different imported modules
- Interpreter and bytecode VM execution
- Diagnostics, completion, hover, semantic highlighting, and formatting
- CLI, project defaults, package data, registry validation, and lockfiles
- Python-style, garden-style, and brace-style blocks

Strings, comments, paths, package names, module names, and user identifiers are
never translated.

## Important Boundaries

- A pack localizes registered Sprout concepts, not arbitrary natural language.
- Structural punctuation remains standard Sprout punctuation such as `:`,
  `()`, `[]`, `{}`, commas, and quotes.
- The bootstrap declaration is always written as
  `language "package-id"` because the pack must be selected before lexing.
- English remains valid in a localized file by design.
- Community packs are declarative JSON and cannot execute code.
- Translation services are never contacted during lexing, compilation,
  installation, testing, or execution.

## Language-Pack Commands

```sh
python3 sprout.py language list
python3 sprout.py language validate chinese-pack
python3 sprout.py language install ./my-pack.json
python3 sprout.py language update my-pack
python3 sprout.py language sync ./my-pack.json
```

`language sync` adds missing catalog entries as English fallback. Optional
generated translations remain marked `generated` until reviewed by a person.

## Test The VS Code Extension

Build and install the experimental extension without changing its version:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.4.0.vsix --force
```

Reload the VS Code window after installation. Keep the Sprout interpreter set
to `Auto` so the extension can select the current checkout.

## Acceptance Gate

Before pushing changes to this branch, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 sprout.py release-check
git diff --check
```

The current experiment passed this gate before its initial commit.

## More Detail

See [docs/POLYGLOT_LANGUAGE_PACKS.md](docs/POLYGLOT_LANGUAGE_PACKS.md) for pack
selection, validation, synchronization, and security details.
