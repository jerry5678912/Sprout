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
- VS Code debugging with breakpoints, call stacks, variable scopes, expression evaluation, continue, pause, step in, step over, and step out
- Native Testing view discovery and execution for Sprout test declarations
- LSP quick fixes for tab indentation and Python-style boolean/nil aliases
- Conditional breakpoints, hit counts, and uncaught-error breakpoints

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

## Language Server

Sprout includes a production stdio language server at:

```sh
python3 tools/sprout_lsp.py
```

The extension starts the bundled server as one persistent process. It uses incremental document synchronization for diagnostics, completions, hover, definitions, references, rename, and signature help. If the server cannot start, the extension falls back to the older `sprout.py intel` providers.

## Debugging

The extension bundles `tools/sprout_dap.py`, Sprout's Debug Adapter Protocol server. To debug the active file:

1. Open a `.sprout` file.
2. Click beside a line number to set a breakpoint.
3. Press `F5`.
4. Select `Debug current Sprout file` if prompted.

The debugger shows Sprout call frames, locals, globals, program output, and evaluated expressions in VS Code's standard debugging views. The toolbar supports continue, pause, step over, step into, step out, restart, and stop.

The debugger currently executes through Sprout's experimental bytecode VM. Normal Run commands continue to use the stable tree-walk interpreter unless VM mode is explicitly selected.

Right-click a breakpoint to add a Sprout expression condition. Hit counts support `3`, `>= 5`, and `% 2`. Enable **Uncaught Sprout errors** in the Breakpoints view to pause before an unhandled error exits.

## Testing

Open VS Code's Testing view to see Sprout tests grouped by file. Use the run button beside a file or individual test. Discovery and results use the structured commands:

```sh
python3 sprout.py test --list --json
python3 sprout.py test tests/example_test.sprout --filter "addition" --json
```

## Quick Fixes

Sprout diagnostics offer lightbulb actions for safe style corrections:

- convert tab indentation to spaces
- replace `True`, `False`, and `None` with `true`, `false`, and `nil`
