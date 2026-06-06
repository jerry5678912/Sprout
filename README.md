# Sprout

Sprout is a tiny programming language with a now-modular Python implementation. It is designed to feel readable, compact, friendly for experiments, and a little weird in a good way.

Sprout aims for about **55% Python closeness**: familiar expressions, `def`, `for ... in`, dictionaries, lists, truthy values, dot methods, indentation blocks, and optional semicolons, while keeping its own garden-flavored words like `bloom`, `sprout`, `pluck`, `whirl`, `each`, and `say`.

Sprout can also call Python standard-library modules with `importpython`, including module functions, constants, classes, returned objects, fields, and methods. That makes it much more useful while the language grows.

## Run It

Install Sprout from a source checkout or downloaded release:

```sh
python3 install.py
~/.local/bin/sprout version
```

If `~/.local/bin` is on `PATH`, the `sprout` command works from any folder. Use `--prefix PATH` for a custom installation and `--force` to replace an existing installation.

Without installing, run directly from the repository:

```sh
python3 sprout.py examples/fibonacci.sprout
```

Try the no-brace block styles:

```sh
python3 sprout.py examples/python_blocks.sprout
python3 sprout.py examples/garden_blocks.sprout
python3 sprout.py examples/seedfn.sprout
```

Full language manual:

- [docs/MANUAL.md](docs/MANUAL.md)
- [docs/manual.html](docs/manual.html)

Try Python library access:

```sh
python3 sprout.py examples/pythonlibs.sprout
```

Try the dogfood projects built with normal Sprout project structure:

```sh
python3 sprout.py run examples/dogfood/cli_tool add docs:2 tests:3 release:5
python3 sprout.py run examples/dogfood/game2d
python3 sprout.py run examples/dogfood/math_utility
python3 sprout.py run examples/dogfood/python_interop
python3 sprout.py run examples/dogfood/package_app
```

Try a tiny terminal game simulation:

```sh
python3 sprout.py examples/minigame.sprout
```

Try a multi-file adventure with a Sprout module, command-line args, and a map file:

```sh
python3 sprout.py examples/adventure.sprout Jerry
```

Try native classes for game objects:

```sh
python3 sprout.py examples/oopgame.sprout
```

Try an interactive terminal game:

```sh
python3 sprout.py examples/tictactoe.sprout
```

Try the expanded standard library:

```sh
python3 sprout.py examples/stdlib100.sprout
```

Try Sprout2D geometry and collision helpers:

```sh
python3 sprout.py examples/geom2d_demo.sprout
python3 sprout.py examples/canvas2d_demo.sprout
python3 sprout.py examples/pixelgarden_demo.sprout
```

Try the Sprout3D terminal renderer:

```sh
python3 sprout.py examples/engine3d_demo.sprout
python3 sprout.py examples/engine3d_solid_demo.sprout
python3 sprout.py examples/engine3d_obj_demo.sprout
python3 sprout.py examples/engine3d_camera_demo.sprout
python3 sprout.py examples/starbloom3d_demo.sprout
```

Try real window-backed wrappers after installing their Python libraries:

```sh
python3 -m pip install pygame
python3 sprout.py examples/window2d_demo.sprout

python3 -m pip install panda3d
python3 sprout.py examples/panda3d_window_demo.sprout
```

Start the REPL:

```sh
python3 sprout.py
```

CLI tooling:

```sh
python3 sprout.py help
python3 sprout.py run examples/fibonacci.sprout
python3 sprout.py run examples/project
python3 sprout.py check examples/tictactoe.sprout
python3 sprout.py check examples/fibonacci.sprout --json
python3 sprout.py lint examples/seedfn.sprout
python3 sprout.py fmt examples/seedfn.sprout
python3 sprout.py compile examples/vm_supported.sprout
python3 sprout.py dis examples/vm_supported.sprout
python3 sprout.py run --vm examples/vm_expanded.sprout
python3 sprout.py bench examples/vm_expanded.sprout
python3 sprout.py debug examples/vm_expanded.sprout --break 21
python3 sprout.py profile examples/vm_expanded.sprout
python3 sprout.py pkg init
python3 sprout.py new cli my_tool
python3 sprout.py doctor
python3 sprout.py install
python3 sprout.py language-package
python3 sprout.py vscode-package
python3 sprout.py stdlib
python3 sprout.py examples
python3 sprout.py version
```

## Project Tooling

Sprout now has an early project and tooling foundation.

Projects use `sprout.toml`:

```toml
[project]
name = "sprout-demo-project"
version = "0.1.0"
main = "src/main.sprout"
authors = []
description = "A Sprout project"
license = "MIT"

[paths]
source = ["src"]
modules = ["modules"]

[dependencies]
local_tools = { path = "packages/local_tools", version = "0.1.0" }
```

Run a project directory:

```sh
python3 sprout.py run examples/project
```

Inside that project, imports can resolve through the current file directory, configured source/module paths, and local dependency paths:

```sprout
import "game/player.sprout" as player
import "engine/math/vector.sprout" as vec
```

Tooling commands:

```sh
python3 sprout.py check file.sprout --json
python3 sprout.py lint file.sprout --json
python3 sprout.py fmt file.sprout
python3 sprout.py fmt file.sprout --write
python3 sprout.py intel file.sprout --kind completions --line 20 --col 8
```

There is also a stdio LSP foundation at `tools/sprout_lsp.py` with workspace diagnostics, semantic completions, hover, definition, references, rename, signature help, and document symbols.

## Builds, Packages, And Templates

Sprout 0.3 adds deterministic builds, portable `.sproutpkg` bundles, semantic-version constraints, lockfiles, and a local/JSON registry foundation.

```sh
python3 sprout.py pkg init
python3 sprout.py pkg list
python3 sprout.py pkg add ./local-package
python3 sprout.py pkg info local_package
python3 sprout.py pkg remove local_package
python3 sprout.py build
python3 sprout.py build --vm
python3 sprout.py package
```

Use a registry by setting `SPROUT_REGISTRY` or passing `--registry PATH`:

```sh
python3 sprout.py pkg search physics
python3 sprout.py pkg install physics_tools@^1.0.0
python3 sprout.py pkg update
python3 sprout.py pkg tree
python3 sprout.py pkg publish
python3 sprout.py pkg docs physics_tools
```

`build/` contains a validated project image, assets, dependencies, hashes, metadata, and `sprout.lock`. `dist/` contains reproducible package bundles and release metadata. The registry is writable locally and readable from local JSON or HTTP-hosted JSON; publishing to a hosted service is intentionally deferred.

Create working projects from templates:

```sh
python3 sprout.py new cli my_tool
python3 sprout.py new game2d my_game
python3 sprout.py new game3d my_3d_demo
python3 sprout.py new library my_lib
```

The templates are now dogfood-hardened:

- `cli` includes help text, command dispatch, argument reading, and useful output.
- `game2d` includes a movement/update/render loop with walls, coins, and score.
- `game3d` renders a small projected wireframe scene in the terminal.
- `library` includes a module, docs, and a test file under `tests/`.

Release-readiness helpers:

```sh
python3 sprout.py doctor
python3 sprout.py release-docs
python3 sprout.py release-check
python3 sprout.py release
python3 sprout.py language-package
python3 sprout.py vscode-package
```

See [docs/ECOSYSTEM.md](docs/ECOSYSTEM.md) for package metadata, constraints, registry layout, publishing checks, and distribution commands.

## Language Releases

`language-package` creates `dist/sprout-VERSION.zip` with the installer, runtime, tools, documentation, examples, editor sources, and tests.

`vscode-package` creates `dist/sprout-language-VERSION.vsix`. The VSIX includes the Sprout runner and core, so diagnostics and IntelliSense work without separately configuring `sprout.runnerPath`.

GitHub Actions runs the test matrix on macOS, Linux, and Windows. Pushing a matching version tag, such as `v0.3.0`, verifies the release and publishes the ZIP and VSIX as GitHub release assets.

## Experimental Bytecode VM

Sprout now has two execution paths:

- Stable tree-walk interpreter: the default and source of truth.
- Experimental bytecode VM: a foundation for future performance, debugging, and profiling work.

Use the VM tools like this:

```sh
python3 sprout.py compile examples/vm_supported.sprout
python3 sprout.py dis examples/vm_supported.sprout
python3 sprout.py run --vm examples/vm_supported.sprout
python3 sprout.py bench examples/vm_supported.sprout
```

The current VM supports literals, variables, assignment, property and index assignment, arithmetic, comparisons, logical operators, arrays, dictionaries, indexing, function calls, keyword arguments, default arguments, variadic arguments, call-site spread, `say`, `if`, `while`, `for`, `break`, `continue`, plain classes/instances/methods, simple inheritance lookup, Sprout imports, Python imports, `raise`, and `try` / `catch`. The default interpreter still handles the full language. Unsupported VM features, such as `super`, either fall back in `run --vm` or report a clear experimental unsupported message in `compile` / `dis`.

`debug` is a terminal debugger foundation. It can stop at source-line breakpoints for bytecode instructions that have source positions, show the current instruction, source line, stack, locals, and continue/step in an interactive terminal. `profile` reports compile time, run time, VM instruction count, and VM function call counts/times.

## Dogfooding And Stability

Sprout includes real dogfood projects in `examples/dogfood`:

- `cli_tool`: CLI command parsing and formatted planning output.
- `game2d`: deterministic 2D game simulation with collision and score.
- `math_utility`: engineering-style beam calculations.
- `python_interop`: Python standard-library calls through `importpython`.
- `package_app`: multi-file project using a local package dependency.

Run the dogfood regression tests:

```sh
python3 tests/dogfood.py
```

Notes from dogfooding live in [docs/DOGFOOD.md](docs/DOGFOOD.md).

## Application Layer

Sprout now includes foundations for testing, tasks, HTTP, SQLite, engineering utilities, documentation generation, and reusable game application structure.

Run Sprout tests:

```sh
python3 sprout.py test
python3 sprout.py test tests/
python3 sprout.py test tests/application_test.sprout --verbose
```

Test syntax:

```sprout
test "addition":
  expect(add(2, 3)).to_equal(5)
```

Application examples:

```sh
python3 sprout.py run examples/application/async_demo.sprout
python3 sprout.py run examples/application/http_server_demo.sprout
python3 sprout.py run examples/application/sqlite_demo.sprout
python3 sprout.py run examples/application/engineering_demo.sprout
python3 sprout.py run examples/application/game_app_demo.sprout
```

Key APIs:

- Tasks and queues: `task_spawn`, `task_after`, `task_wait_all`, `queue_open`
- HTTP: `http_get`, `http_post`, `http_request`, `http_server`
- SQLite: `sqlite_open`, `sqlite_exec`, `sqlite_query`, transactions, `sqlite_close`
- Engineering: vector/matrix functions, unit conversion, interpolation, force, pressure, and energy
- Game structure: `examples/modules/appgame.sprout`
- Engineering module: `examples/modules/engineering.sprout`

Generate project API documentation from `##` comments:

```sh
python3 sprout.py docs .
python3 sprout.py docs . --html
```

Inspect standard-library groups:

```sh
python3 sprout.py stdlib --groups
```

The task foundation runs work on a scheduler and supports delayed tasks, futures, and queues. Sprout function execution is serialized through a runtime lock in this first version so shared interpreter state remains correct.

## Language Tour

```sprout
importpython math

def fib(n):
  if n <= 1:
    return n
  return fib(n - 1) + fib(n - 2)

values = []
i = 0
while i < 8:
  values.append(fib(i))
  i = i + 1

say values
say math.sqrt(81)
```

The same style can be more Sprout-like:

```sprout
bloom cheer(name, mood):
  pluck name + " feels " + mood

sprout crew = ["Ada", "Lin", "Sam"]
crew.append("Mina")

sprout moods = {
  "Ada": "electric",
  "Lin": "steady",
  "Sam": "curious",
  "Mina": "bright"
}

each name in crew bloom
  say cheer(name, moods[name])
end
```

## Features

- Numbers, strings, booleans, `nil` / `None`, and arrays
- Dictionaries with string or number keys
- Native classes, inheritance, instances, fields, constructors, and methods
- Parent method calls with `super.method(...)`
- Default, keyword, variadic `*rest`, keyword-rest `**options`, and call-site spread `*args` / `**opts` arguments
- `let` / `sprout` declarations, plus Python-style assignment
- Function-local assignment, with block assignments visible inside the surrounding function or module
- Assignment to variables, array slots, and dictionary slots
- Inline `seedfn` functions with lexical scope
- Python-style `:` indentation blocks
- Garden-style `bloom` / `end` blocks
- Old-compatible brace blocks
- `fn` / `def` / `bloom` functions with lexical scope
- `return`
- `if` / `elif` / `else`
- `while` / `whirl`
- `for` / `each` loops over arrays, strings, ranges, and dictionary keys
- `break` and `continue`
- Recoverable errors with `try` / `catch`, `raise`, `ensure`, and `fail`
- Uncaught runtime errors with Sprout call stacks
- Native Sprout imports with `import "modules/gamekit.sprout" as game`
- Python library imports with `importpython math` or `importpython random as pyrandom`
- Command-line args through `argv`
- File helpers: `readfile`, `writefile`, `appendfile`, `exists`, `isfile`, `isdir`, `listdir`, `mkdir`, `readjson`, `writejson`, `lines`
- Operators: `+ - * / // %`, comparisons, equality, membership `in`, `and`, `or`, unary `!` / `not`
- Array and string slicing with `items[1:4]`, `items[:2]`, and `items[2:]`
- Built-ins: `say`, `print`, `len`, `push`, `range`, `str`, `int`, `num`, `type`, `keys`, `values`, `items`, `has`, `get`, `argv`, `ask`, `clear`, `ensure`, `fail`
- Special Sprout helpers: `sparkle`, `whisper`, `shout`, `mirror`, `chant`, `weave`, `grow`, `plant`, `harvest`, `prune`, `sprinkle`, `bundle`, `first`, `last`, `rest`, `unique`, `countby`, `zipbud`, `dice`
- Game helpers: `choose`, `clamp`, `wrap`, `dist`, `sleep`, `now`
- Expanded standard library with `functions()` reporting 175 callable global functions
- PixelGarden terminal engine for fun ASCII 2D drawing, sprites, text, simple cameras, vectors, bounds, and collision checks
- StarBloom3D terminal engine for fun ASCII 3D wireframe/solid software rendering
- Window2D optional Pygame-backed module for real 2D windows
- PandaWindow3D optional Panda3D-backed module for real 3D windows
- Dot methods on arrays, dictionaries, and strings
- `#` line comments
- Semicolons are optional when statements are separated by newlines

## Syntax Notes

Statements can end with newlines or semicolons.

```sprout
name = "Sprout"
say "hello", name
```

The recommended general block style uses `:` and indentation.

```sprout
if len(name) > 3:
  say "leafy"
else:
  say "small"
```

Garden-style blocks use `bloom` and `end`.

```sprout
def cheer(name) bloom
  if name == "Sprout" bloom
    return sparkle("keep growing")
  end
  return "hello " + name
end
```

Brace blocks still work for older Sprout code.

```sprout
if len(name) > 3 {
  say "old style"
}
```

Arrays are mutable.

```sprout
xs = [1, 2, 3]
xs[0] = 99
xs.append(100)
say xs
```

Dictionaries are mutable too.

```sprout
profile = {"name": "Ada", "score": 98}
profile.rank = "captain"
say profile.name, profile["score"], profile.keys()
```

Loops feel familiar:

```sprout
for n in range(5):
  if n == 2 or not n in [0, 1, 3, 4]:
    continue
  say n * n
```

Special Sprout helpers give the language some personality:

```sprout
say sparkle("welcome")
say mirror("desserts")
say chant("ha", 3)

names = ["Ada", "Lin", "Ada", "Mina"]
grow(names, "Kai")
say unique(names)
say countby(names)
say weave(unique(names), " + ")

scores = zipbud(["Ada", "Lin"], [98, 84])
plant(scores, "Kai", 77)
say scores

bag = ["seed", "leaf", "seed", "stone"]
say harvest(bag)
say prune(bag, "seed")
say sprinkle(["sun", "rain", "soil"], " -> ").join("")
say bundle(["x", "y"], [4, 9])
```

Python libraries are imported with `importpython`:

```sprout
importpython math
importpython random as pyrandom
importpython datetime as dt

pyrandom.seed(7)
say math.sqrt(81)
say math.sin(math.pi / 2)
say pyrandom.randint(1, 10)

say py_available("math")
say py_import("math").sqrt(16)

day = dt.date(year=2026, month=6, day=4)
say day.isoformat(), day.year
```

Your own Sprout files can be imported too:

```sprout
import "modules/gamekit.sprout" as game

hero = game.make_player("Ada")
game.move(hero, "east", 8, 5)
say game.status(hero)
```

Scripts receive command-line arguments through `argv`:

```sprout
name = "Sproutling"
if len(argv) > 0 {
  name = argv[0]
}
say "hello", name
```

File helpers make small tools and data-driven games possible:

```sprout
map_text = readfile("data/tiny_map.txt")
rows = lines(map_text)
say first(rows)

writefile("/tmp/save.txt", "hp=10")
appendfile("/tmp/save.txt", "\nx=4")
say exists("/tmp/save.txt")

mkdir("/tmp/sprout-save")
writejson("/tmp/sprout-save/profile.json", {"name": "Mina", "hp": 10})
profile = readjson("/tmp/sprout-save/profile.json")
say profile.name
say listdir("/tmp/sprout-save")
```

Game-ish helpers are built in:

```sprout
player = {"x": 5, "y": 2, "hp": 10}
player.x = wrap(player.x + 1, 0, 9)
player.hp = clamp(player.hp - 1, 0, 10)
say "distance", dist(player.x, player.y, 0, 0)
say "move", choose(["north", "east", "south", "west"])
```

Classes make larger programs and games easier to organize:

```sprout
class Hero {
  def init(self, name, x, y) {
    self.name = name
    self.x = x
    self.y = y
    self.hp = 10
  }

  def move(self, direction) {
    if direction == "east" {
      self.x = wrap(self.x + 1, 0, 9)
    }
  }

  def status(self) {
    return self.name + " @(" + str(self.x) + "," + str(self.y) + ")"
  }
}

hero = Hero("Mina", 5, 2)
hero.move("east")
say hero.status()
```

Classes can inherit methods and constructors:

```sprout
class Entity {
  def init(self, name, x=0, y=0) {
    self.name = name
    self.x = x
    self.y = y
  }

  def status(self) {
    return self.name + " @(" + str(self.x) + "," + str(self.y) + ")"
  }
}

class Player extends Entity {
  def collect(self, item="coin") {
    return self.name + " collected " + item
  }
}

hero = Player("Mina", x=2, y=3)
say hero.status()
say hero.collect(item="key")
```

Functions and methods can have defaults:

```sprout
def spawn(name, hp=10, x=0, y=0) {
  return {"name": name, "hp": hp, "x": x, "y": y}
}

say spawn("Mina")
say spawn("Boss", 20, 5, 2)
say spawn(name="Scout", y=3)
```

Keyword arguments work for Sprout functions, constructors, methods, and Python library calls:

```sprout
importpython datetime as dt

class Potion {
  def init(self, name="leaf", power=1) {
    self.name = name
    self.power = power
  }

  def label(self, prefix="potion") {
    return prefix + ":" + self.name
  }
}

potion = Potion(power=4, name="sun")
say potion.label(prefix="loot")

day = dt.date(year=2026, month=6, day=4)
say day.isoformat()
```

Arrays and strings support slices:

```sprout
letters = "sprout"
say letters[0:3], letters[3:], letters[:2]

items = ["a", "b", "c", "d", "e"]
say items[1:4]
items[1:4] = ["X", "Y"]
say items
```

Interactive terminal scripts can ask for input:

```sprout
name = ask("name? ")
say "hello", name
```

Recoverable errors keep programs alive:

```sprout
def load_hp(value) {
  ensure(value >= 0, "hp cannot be negative")
  ensure(value <= 10, "hp cannot be over 10")
  return value
}

try {
  hp = load_hp(-2)
} catch err {
  say "save problem:", err
}

try {
  raise "manual error"
} catch err {
  say "caught", err
}
```

Uncaught errors show Sprout call stacks:

```text
error: [Errno 2] No such file or directory: '.../missing_config.txt'
stack:
  called at examples/stacktrace.sprout:2:18
  at load_config (examples/stacktrace.sprout:1:5)
  called at examples/stacktrace.sprout:8:21
  at boot_game (examples/stacktrace.sprout:6:5)
  called at examples/stacktrace.sprout:12:19
  at main (examples/stacktrace.sprout:11:5)
```

## Project Layout

- `sprout.py`: small compatibility launcher and public API re-export
- `sprout_core/model.py`: shared data types, diagnostics, project metadata, errors, and constants
- `sprout_core/lexer.py`: tokenization
- `sprout_core/parser.py`: parsing into AST tuples
- `sprout_core/runtime.py`: interpreter, runtime values, built-ins, Python bridge, and formatting of runtime values/errors
- `sprout_core/bytecode.py`: experimental bytecode compiler, disassembler, VM, and benchmark support
- `sprout_core/tooling.py`: project loading, module search paths, check/lint/fmt helpers, symbol collection, and JSON diagnostics
- `sprout_core/analysis.py`: semantic workspace indexing, completions, hovers, definitions, references, rename edits, signatures, and editor diagnostics
- `sprout_core/cli.py`: command-line interface and REPL
- `tools/sprout_lsp.py`: stdio LSP foundation backed by the semantic workspace index
- `examples/`: sample Sprout programs
- `examples/modules/`: importable Sprout modules
- `examples/data/`: tiny data files for demos
- `tests/`: smoke test script
- `editor/vscode-sprout/`: local VS Code language package with highlighting, snippets, completions, and hover help

## Editor Support

Yes, Sprout can be used in a code editor. This project includes a local VS Code language package:

[editor/vscode-sprout](editor/vscode-sprout)

It recognizes `.sprout` files, highlights keywords and special helpers, supports `#` comments, auto-closes braces/quotes, indents after `{`, `:`, and `bloom`, provides snippets, and runs `sprout.py check` diagnostics in the editor. When the extension can find `sprout.py`, it also asks Sprout's semantic analyzer for project-aware completions, hover help, go-to definition, find references, rename edits, and signature help. If the runner is missing, it falls back to static completions for the full current keyword set, all built-ins, dot methods, bundled Sprout modules, Sprout2D APIs, Sprout3D APIs, PixelGarden, StarBloom3D, Window2D, and PandaWindow3D. Red underlines show syntax errors. Yellow underlines show style warnings for tabs and Python-style constants like `True` / `False` / `None`.

Build and install the self-contained VSIX:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.3.0.vsix
```

Quick local development flow:

```sh
cd editor/vscode-sprout
code .
```

Then press `F5` in VS Code to launch an Extension Development Host and open a `.sprout` file.

Completion examples:

- Type `def` for a function snippet.
- Type `defbloom` for a garden-style `bloom` / `end` function snippet.
- Type `defbraces` for an old-compatible brace function snippet.
- Type `defrest` for a `*rest` variadic function snippet.
- Type `defopts` for a `**opts` keyword-rest function snippet.
- Type keywords like `elif`, `each`, `whirl`, `try`, `catch`, `raise`, `sprout`, `pluck`, or `end` for syntax snippets/completions.
- Type built-ins like `sparkle`, `grow`, `json_parse`, `py_import`, `functions`, or `methods` for call snippets.
- Type `callspread` for a call using `*args` and `**opts`.
- Type `game.` after `import "modules/gamekit.sprout" as game` for gamekit completions.
- Type `g2d.` after `import "modules/geom2d.sprout" as g2d` for Sprout2D API completions.
- Type `c2d.` after `import "modules/canvas2d.sprout" as c2d` for Sprout2D canvas completions.
- Type `s3d.` after `import "modules/engine3d.sprout" as s3d` for Sprout3D API completions.
- Type `pix.` after `import "modules/pixelgarden.sprout" as pix` for PixelGarden completions.
- Type `star.` after `import "modules/starbloom3d.sprout" as star` for StarBloom3D completions.
- Type `w2d.` after `import "modules/window2d.sprout" as w2d` for Pygame-backed Window2D completions.
- Type `p3d.` after `import "modules/panda3d_window.sprout" as p3d` for Panda3D-backed completions.
- Type `player.` on a variable created from a local `Player` class to complete that class's methods and fields.
- Hover functions or classes with `##` documentation comments to see their signature, docs, and source location.
- Use VS Code's Go to Definition, Find References, Rename Symbol, and signature help commands for Sprout symbols when `sprout.py` is available.
- Syntax errors appear as VS Code diagnostics. Set `sprout.runnerPath` if the extension cannot find `sprout.py`, set `sprout.diagnostics.enabled` to `false` to turn checking off, or set `sprout.diagnostics.styleWarnings` to `false` to hide yellow style warnings.

## Current Python-Closeness Snapshot

Sprout now covers a meaningful middle slice of Python:

- Similar: dynamic typing, numbers, strings, lists, dictionaries, classes, inheritance, `super`, instances, methods, functions, default, keyword, variadic, keyword-rest, and spread-call arguments, returns, conditions, `elif`, loops, `break`, `continue`, recoverable errors, truthiness, indexing, slicing, calls, dot-style methods, command-line args, file I/O helpers, and multi-file programs.
- Similar via bridge: Python standard-library modules can be imported with `importpython`.
- Different: Sprout has its own garden-style `bloom` / `end` blocks, old-compatible brace blocks, and no comprehensions yet.

Good next work includes hosted-registry authentication, signed packages, stronger sandboxing, and broader VM coverage.
