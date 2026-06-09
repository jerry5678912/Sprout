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
- JSON syntax diagnostics powered by `sprout.py check --json` and semantic
  workspace diagnostics from the language server
- A status-bar interpreter selector for bundled, workspace, or custom Sprout interpreters
- **Sprout: Run Current File** in the Command Palette and editor title
- Application-layer completions and highlighting for `test`, `async def`,
  `await`, `taskgroup`, expectations, tasks, HTTP, SQLite, engineering helpers,
  and reusable game APIs
- Highlighting, snippets, symbols, hovers, and diagnostics for optional type
  annotations, generic functions/classes, interfaces, and `implements`
- VS Code debugging with breakpoints, call stacks, variable scopes, expression evaluation, continue, pause, step in, step over, and step out
- Native Testing view discovery and execution for Sprout test declarations
- LSP quick fixes for tab indentation and legacy compatibility names
- Conditional breakpoints, hit counts, and uncaught-error breakpoints
- **Sprout: Show Language Server Output** for startup, interpreter, document,
  diagnostic, completion, hover, navigation, rename, and crash logs
- **Sprout: Restart Language Server** to recover editor services without
  reloading VS Code

## Install From VS Code

1. Install Sprout with `python3 -m pip install sprout-language`.
2. Open VS Code's Extensions view.
3. Search for **Sprout Language** by `jerry5678912`.
4. Install the extension and open a `.sprout` file.
5. Click **Sprout: Auto** in the status bar if you want to choose a different
   interpreter.
6. Click the editor-title play icon to run the current file.

## Install The VSIX

From the Sprout repository:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.3.3.vsix
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
- `sprout.diagnostics.styleWarnings`: show yellow style warnings for tabs and legacy compatibility names.
- `sprout.diagnostics.typoChecking`: suggest corrections for mistyped Sprout keywords, built-ins, imports, and project symbols.
- `sprout.analysis.typeCheckingMode`: choose `off`, `basic`, `standard`, or `strict`.
- `sprout.analysis.diagnosticMode`: choose `workspace` or `openFilesOnly`.
- `sprout.analysis.indexing`: enable dependency-aware workspace indexing.
- `sprout.analysis.userFileIndexingLimit`: cap how many user `.sprout` files Sprout indexes before throttling.
- `sprout.analysis.useLibraryCodeForTypes`: analyze Sprout library source when inferring symbols and types.
- `sprout.analysis.exclude`: glob patterns excluded from Sprout workspace indexing.
- `sprout.analysis.languageServerMode`: choose `default`, `light`, or `off` analysis load.
- `sprout.analysis.diagnosticSeverityOverrides`: override individual diagnostic codes with `none`, `hint`, `information`, `warning`, or `error`.
- `sprout.pythonPath`: optional Python executable; empty selects `python` on Windows and `python3` elsewhere.
- `sprout.runnerPath`: selected `sprout.py` interpreter; use **Sprout: Select Interpreter** instead of editing this manually.

`basic` reports practical syntax, import, name, member, argument, assignment,
return, interface, and generic problems without requiring type annotations.
`standard` also reports deeper semantic warnings such as unreachable code and
override-signature problems. `strict` additionally reports missing parameter
and return annotations and promotes unknown names and members to errors. `off`
keeps syntax and import diagnostics. Unused imports, parameters, and variables
are tagged as unnecessary so VS Code can fade them as well as showing a
warning.

Example:

```json
{
  "sprout.analysis.typeCheckingMode": "strict",
  "sprout.analysis.diagnosticSeverityOverrides": {
    "SPROUT_UNUSED_IMPORT": "information",
    "SPROUT_MISSING_RETURN_TYPE": "none"
  }
}
```

## Select And Run

Click **Sprout: Auto** or **Sprout: Selected** in the VS Code status bar, or run
**Sprout: Select Interpreter** from the Command Palette. The selector can use
the interpreter bundled with the extension, a workspace checkout, or a custom
`sprout.py` file. Custom selections are validated with `sprout.py version`.

Open a saved `.sprout` file and click the play icon in the editor title, or run
**Sprout: Run Current File**. The program runs in an interactive integrated
terminal using the selected interpreter.

## Language Server

Sprout includes a production stdio language server at:

```sh
python3 tools/sprout_lsp.py
```

The extension starts the bundled server as one persistent process. It uses incremental document synchronization for diagnostics, completions, hover, definitions, references, rename, and signature help. If the server cannot start, the extension falls back to the older `sprout.py intel` providers.

Use **Sprout: Show Language Server Output** to verify whether the real language
server is running. The log shows the Python path, server path, Sprout runner
path, document open/change/save/close events, diagnostic counts, and editor
requests. Use **Sprout: Restart Language Server** after changing interpreter
settings or if IntelliSense stops responding. Use **Sprout: Show Analysis
Status** to inspect file counts, cache hits, dependency edges, and the latest
incremental reindex decision. Use **Sprout: Rebuild Workspace Index** to force
a fresh workspace graph rebuild.

Sprout uses VS Code's native diagnostic system for red error squiggles, yellow
warning squiggles, Problems panel entries, and faded unnecessary symbols. The
extension intentionally does not draw a custom second underline layer.

## Current Editor Status

Working and tested through the LSP behavior check:

- syntax diagnostics and semantic diagnostics
- diagnostics clearing after a document becomes blank
- keyword and code-word typo quick fixes such as `impo` -> `import`
- top-level completions for known symbols
- member completions for imports, modules, Python modules, local classes, and
  simple factory-created instances such as `player = player_mod.spawn(...)`
- hover, go to definition, references, rename, and signature help for simple
  known symbols

Partial or conservative:

- type inference is practical, not complete
- unknown-member diagnostics are strongest for modules and simple inferred
  class instances
- rename refuses or returns no edits when symbol identity is uncertain
- static fallback completions appear only when the language server cannot start

Repeat the editor check with:

```sh
python3 tools/check_vscode_editor_behavior.py
```

Manual workspace:

```sh
code examples/editor_test_workspace
```

Manual indentation/folding fixture:

```sh
code examples/editor_test_workspace/indentation_folding.sprout
```

## Indentation Guides

Sprout now owns folding ranges for `:`, `bloom`/`end`, and `{`/`}` blocks, and
the extension's folding algorithm does not include dedented top-level lines in
the previous block. If you still see the far-left active indent guide continue
through a blank gap into a dedented line, that appears to be VS Code's active
indent-guide rendering rather than Sprout folding the line into the block.

Example:

```sprout
def hello(times):
  for i in range(times):
    say "Hello"



k = 3
```

In this case:

- `k = 3` is still top-level code at column `0`
- Sprout folding does not include `k = 3` inside `hello`
- Sprout runtime does not execute `k = 3` as part of the function
- the remaining long vertical line is a visual guide artifact, not a block-ownership bug

Python may look cleaner here because its editor integration stays closer to
VS Code's native indentation path. Sprout's actual block structure is still
correct even when the active guide line looks too long across blank lines.

If you want to reduce that visual beam without hiding normal guides, you can
set this per-language in your own VS Code settings:

```json
{
  "[sprout]": {
    "editor.guides.highlightActiveIndentation": false
  }
}
```

That setting is optional and is not applied by the extension automatically.

## Debugging

The extension bundles `tools/sprout_dap.py`, Sprout's Debug Adapter Protocol server. To debug the active file:

1. Open a `.sprout` file.
2. Click beside a line number to set a breakpoint.
3. Press `F5`.
4. Select `Debug current Sprout file` if prompted.

The debugger shows Sprout call frames, locals, globals, program output, and evaluated expressions in VS Code's standard debugging views. The toolbar supports continue, pause, step over, step into, step out, restart, and stop.

Recent builds also reuse semantic signatures in debugger frame labels and local
scope names where Sprout can resolve them safely.

The debugger currently executes through Sprout's experimental bytecode VM. Normal Run commands continue to use the stable tree-walk interpreter unless VM mode is explicitly selected.

Right-click a breakpoint to add a Sprout expression condition. Hit counts support `3`, `>= 5`, and `% 2`. Enable **Uncaught Sprout errors** in the Breakpoints view to pause before an unhandled error exits.

## Testing

Open VS Code's Testing view to see Sprout tests grouped by file. Use the run button beside a file or individual test. Discovery and results use the structured commands:

```sh
python3 sprout.py test --list --json
python3 sprout.py test tests/example_test.sprout --filter "addition" --json
```

If a test has `##` documentation comments directly above it, the Testing view
shows that text as a tooltip.

## Quick Fixes

Sprout diagnostics offer lightbulb actions for safe style corrections:

- convert tab indentation to spaces
- replace `print`, `true`, `False`, and `None` with `say`, `True`, `false`, and `nil`
