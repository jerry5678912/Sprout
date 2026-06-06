# Sprout Language for VS Code

This is the VS Code language package for Sprout.

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

## Install The VSIX

From the Sprout repository:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.3.0.vsix
```

The VSIX contains the Sprout runner and core. Diagnostics and semantic IntelliSense work immediately as long as Python 3.9 or newer is available.

You can also open the Extensions view, choose `Install from VSIX...`, and select the generated file.

## Develop It Locally

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
- `sprout.pythonPath`: optional Python executable; empty selects `python` on Windows and `python3` elsewhere.
- `sprout.runnerPath`: optional explicit path to `sprout.py`; packaged releases already include the runner.

## LSP Foundation

Sprout also includes an early stdio language server at:

```sh
python3 tools/sprout_lsp.py
```

The bundled VS Code package uses direct extension providers backed by the same semantic analyzer through `sprout.py intel`. The stdio LSP server is also available for future editor clients.
