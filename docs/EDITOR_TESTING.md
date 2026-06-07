# Sprout VS Code Editor Testing

This file is the current honest checklist for Sprout editor support. It is not
a claim that Sprout is Pylance-grade. It is a small, repeatable way to check
whether the real VS Code extension is talking to the Sprout language server.

## Test Workspace

Open this folder in VS Code:

```sh
code examples/editor_test_workspace
```

Then open `src/main.sprout` and `src/diagnostics.sprout`.

## Expected Working Behavior

- The status bar shows `Sprout: Auto` or `Sprout: Selected`.
- Run **Sprout: Show Language Server Output** and see startup logs.
- Run **Sprout: Restart Language Server** and see fresh startup logs.
- `src/main.sprout` has syntax and semantic highlighting.
- Hover over `add`, `Player`, `spawn`, or `player` and get conservative symbol
  information.
- `player.` in `src/main.sprout` offers known members such as `name`, `hp`,
  `greet`, and `hurt`.
- Signature help appears for calls like `player_mod.spawn(` and `math_tools.add(`.
- Go to definition works for `add`, `spawn`, `Player`, and simple local names.
- Go to definition on `player_mod` opens `src/player.sprout`.
- Find references works for simple local symbols and imported module members.
- Rename works for local variables, parameters, functions, and classes when
  the analyzer knows the symbol identity.
- `src/diagnostics.sprout` shows diagnostics for `player.nmae`,
  `unknown_name`, and `impo`.
- The quick-fix lightbulb offers a replacement for `impo` -> `import`.
- Deleting all text from a Sprout document clears diagnostics quickly.

## Known Partial Areas

- This is a lightweight Sprout language server, not Pyright or Pylance.
- Type inference is practical and conservative, not complete.
- Extension Host UI tests are not yet part of CI.
- Static fallback completions still appear if the language server cannot start.
  Use **Sprout: Show Language Server Output** to tell whether fallback mode is
  active.

## Automated Check

Run:

```sh
python3 tools/check_vscode_editor_behavior.py
```

That script validates the LSP behavior VS Code depends on. It does not replace
manual VS Code testing, but it catches broken diagnostics, completion, hover,
definition, references, rename, signature-help, analysis-status payloads, and
quick-fix payloads.
