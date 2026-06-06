# Sprout Language for VS Code

This is a local VS Code language package for Sprout.

It adds:

- `.sprout` file recognition
- Syntax highlighting
- Comment toggling with `#`
- Auto-closing braces, brackets, parentheses, and strings
- Basic indentation after `{`, `:`, and `bloom`
- Snippets for functions, variadic/functions with options, classes, subclasses, loops, errors, Python imports, and Sprout3D scenes
- Semantic completions for local variables, functions, classes, methods, imports, module exports, Python module members, and project symbols when `sprout.py` is available
- Static fallback completions for Sprout keywords, built-ins, dot methods, bundled modules, Sprout2D, Sprout3D, PixelGarden, StarBloom3D, Window2D, and PandaWindow3D
- Hover help with signatures, `##` documentation comments, and source locations
- Go to Definition, Find References, Rename Symbol, and signature help foundations
- JSON syntax diagnostics powered by `sprout.py check --json`
- Application-layer completions and highlighting for `test`, expectations, tasks, HTTP, SQLite, engineering helpers, and reusable game APIs

## Use It Locally

From VS Code:

1. Open the Extensions view.
2. Choose `Install from VSIX...` if you package it later, or use this folder as the source while developing an extension.

For quick local extension development:

```sh
cd editor/vscode-sprout
code .
```

Then press `F5` in VS Code to launch an Extension Development Host.

Open any `.sprout` file there and the highlighting, snippets, completions, and hover help should activate.

Completion examples:

- Type `def` to insert a function block.
- Type `defrest` to insert a variadic function with `*values`.
- Type `defopts` to insert a function with `**opts`.
- Type `seedfn` to insert a tiny inline function.
- Type `game.`, `g2d.`, `c2d.`, `pix.`, `star.`, `w2d.`, or `p3d.` after matching imports for module completions.
- Type `s3d.` after importing Sprout3D as `s3d` to complete engine helpers like `vec3`, `look_at_camera`, and `render_solid`.
- Type `player.` after `player = Player("Mina")` to complete fields and methods discovered from your code.

Documentation comments use `##` immediately before a class or function:

```sprout
## Create a named player.
def spawn(name, hp=10):
  return Player(name, hp)
```

Those comments appear in hover help and completion descriptions.

## Diagnostics Settings

- `sprout.diagnostics.enabled`: turn editor diagnostics on or off.
- `sprout.diagnostics.styleWarnings`: show yellow style warnings for tabs and Python-style constants.
- `sprout.pythonPath`: Python executable used to run `sprout.py`.
- `sprout.runnerPath`: explicit path to `sprout.py` if the extension cannot find it automatically.

When installing this extension folder manually, copy the Sprout runner beside it too:

```sh
cp sprout.py ~/.vscode/extensions/sprout-language-0.1.0/
cp -R sprout_core ~/.vscode/extensions/sprout-language-0.1.0/
```

## LSP Foundation

Sprout also includes an early stdio language server at:

```sh
python3 tools/sprout_lsp.py
```

The bundled VS Code package uses direct extension providers backed by the same semantic analyzer through `sprout.py intel`. The stdio LSP server is also available for future editor clients.
