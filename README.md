# Sprout

[![CI](https://github.com/jerry5678912/Sprout/actions/workflows/ci.yml/badge.svg)](https://github.com/jerry5678912/Sprout/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sprout-language.svg)](https://pypi.org/project/sprout-language/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](ROADMAP.md)

Sprout is an independent, general-purpose programming language with a stable
tree-walk interpreter, an experimental bytecode VM, gradual typing, async I/O,
project/package tooling, a language server, and a VS Code extension.

Its syntax is deliberately approachable:

```sprout
enum Result[T]:
  Ok(value: T)
  Error(message: String)

def squares(limit: Int) -> Generator[Int]:
  for value in range(limit):
    yield value * value

match Result.Ok(squares(4).collect()):
  case Result.Ok(values):
    say "values:", values
  case Result.Error(message):
    say "error:", message
```

Sprout is implemented in Python 3.9+ but parses and executes its own syntax,
maintains its own runtime model, emits Sprout bytecode, and provides Sprout
diagnostics and stack traces. Python libraries are available through an
explicit `importpython` bridge.

> **Project status:** Sprout is alpha software. It is suitable for experiments,
> learning, tools, small applications, and language development. APIs and
> package formats may still evolve before 1.0.

## Quick Start

Install the public package from [PyPI](https://pypi.org/project/sprout-language/):

```sh
python3 -m pip install sprout-language
sprout version
```

For an isolated command-line installation:

```sh
pipx install sprout-language
sprout version
```

Clone the repository to run bundled examples or contribute:

```sh
git clone https://github.com/jerry5678912/Sprout.git
cd Sprout
python3 sprout.py examples/advanced_features.sprout
```

Development and source-release installation remain available:

```sh
python3 -m pip install -e .
python3 install.py
~/.local/bin/sprout version
```

## What Exists

- Language: functions, closures, classes, inheritance, exceptions, modules,
  enums, guarded pattern matching, generators, comprehensions, and async syntax.
- Types: gradual annotations, generics, interfaces, unions, aliases, narrowing,
  imported types, and enum exhaustiveness diagnostics.
- Runtime: stable interpreter plus an optional experimental bytecode VM,
  debugger, profiler, disassembler, and benchmark tools.
- Application APIs: files, JSON, HTTP, SQLite, tasks, queues, async streams,
  engineering helpers, terminal graphics, Pygame, and Panda3D bridges.
- Tooling: formatter, linter, tests, project templates, package management,
  reproducible builds, standalone bundles, LSP, semantic highlighting, and
  VS Code debugging.
- Quality: conformance tests, interpreter/VM parity tests, fuzzing, security
  regressions, smoke tests, and CI on Linux, macOS, and Windows.

## Try It

```sh
sprout examples/advanced_features.sprout
sprout run examples/project
sprout test tests/application_test.sprout
sprout typecheck examples/typed_abstractions.sprout
sprout run --vm examples/vm_expanded.sprout
sprout bench examples/vm_expanded.sprout
```

Explore larger dogfood projects:

```sh
sprout run examples/dogfood/cli_tool add docs:2 tests:3 release:5
sprout run examples/dogfood/game2d
sprout run examples/dogfood/math_utility
sprout run examples/dogfood/python_interop
sprout run examples/dogfood/package_app
```

Window-backed examples require optional host libraries:

```sh
python3 -m pip install pygame panda3d
sprout examples/window2d_demo.sprout
sprout examples/panda3d_window_demo.sprout
```

## Documentation

- [Language manual](docs/MANUAL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Ecosystem and package format](docs/ECOSYSTEM.md)
- [Capability audit](docs/CAPABILITY_AUDIT.md)
- [Project governance](GOVERNANCE.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md), which
documents the repository layout, test matrix, language-change checklist, and
pull-request expectations. Bugs and feature proposals should use the GitHub
issue templates. Security reports must follow [SECURITY.md](SECURITY.md).

Useful first checks:

```sh
python3 tests/advanced_language.py
python3 tests/typesystem.py
python3 tests/lsp.py
python3 sprout.py conformance
tests/smoke.sh
```

## License

Sprout is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE)
for project attribution information. Contributions are accepted under the same
license and workflow described in [CONTRIBUTING.md](CONTRIBUTING.md).

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
license = "Apache-2.0"

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

The production stdio server at `tools/sprout_lsp.py` provides incremental document synchronization, versioned diagnostics, semantic completions, hover, definition, references, safe rename preparation and edits, signature help, document symbols, workspace symbols, workspace-folder updates, cancellation, and correct initialize/shutdown lifecycle handling.

The semantic engine uses lexical scopes and stable symbol identities. Parameters and local variables with the same spelling in different functions remain separate symbols, repeated assignments stay attached to their original binding, and imported module member references connect to their exported definitions. The language server keeps an in-memory workspace index and reanalyzes only files whose contents or filesystem signatures changed. The VS Code extension starts one persistent server process and falls back to command-based providers only when the server cannot start.

Sprout Intelligence 0.4 uses one bounded fact model for inferred scalar types,
container element types, nilability, class/module identity, and dynamic object
members. Facts flow through unannotated functions, call sites, loops,
constructors, branches, recursion, and imported Sprout modules. Straight-line
assignments replace earlier shapes; control-flow joins preserve shared fields as
required and branch-only fields as conditional. Hover and completion expose
these same facts, so editor features do not maintain separate guesses.

Editor type checking supports `off`, `basic`, `standard`, and `strict` modes
through `sprout.analysis.typeCheckingMode`. Basic mode reports practical name,
member, call, assignment, return, import, interface, generic, and pattern
errors. Standard mode adds deeper flow and override checks such as unreachable
code, override-signature diagnostics, and possibly missing dynamic members.
Strict mode additionally requires parameter and return annotations, promotes
possibly missing members to errors, and treats unknown names and members as
errors. Per-rule severity overrides are available through
`sprout.analysis.diagnosticSeverityOverrides`. Unused imports, parameters, and
variables are tagged so VS Code can fade them.

This cache lasts for the language-server process. A persistent on-disk index is not implemented yet.

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

`build/` contains a validated project image, assets, dependencies, hashes, metadata, and `sprout.lock`. `dist/` contains reproducible package bundles and release metadata. Registries may be local or hosted; hosted publishing uses package-scoped bearer tokens and immutable releases.

Run a hosted registry:

```sh
python3 sprout.py registry token publisher --root ./registry --packages my_package
python3 sprout.py registry serve --root ./registry --host 127.0.0.1 --port 8787
```

Public deployments should place the service behind an HTTPS reverse proxy. See [docs/ECOSYSTEM.md](docs/ECOSYSTEM.md) for token administration and security guarantees.

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

## Standalone Applications

Build a runnable application directory that includes the Sprout runtime, resolved dependencies, source, assets, cross-platform launchers, and an integrity manifest:

```sh
python3 sprout.py app build .
python3 sprout.py app verify dist/my_app-0.1.0-standalone
python3 sprout.py app run dist/my_app-0.1.0-standalone -- argument
python3 sprout.py app package .
```

`app package` creates a deterministic `.sproutapp` archive. Recipients extract it and run the app-named launcher on macOS/Linux or the `.cmd` launcher on Windows. Sprout does not need to be installed. This distribution generation still requires Python 3.9 or newer on the recipient machine; it does not claim to be a native single executable.

## Language Releases

`language-package` creates `dist/sprout-VERSION.zip` with the installer, runtime, tools, documentation, examples, editor sources, and tests.

`vscode-package` creates `dist/sprout-language-VERSION.vsix`. The VSIX includes the Sprout runner and core, so diagnostics and IntelliSense work without separately configuring `sprout.runnerPath`.

GitHub Actions runs the test matrix on macOS, Linux, and Windows. Pushing a matching runtime version tag, such as `v0.3.4`, verifies the language release and publishes the ZIP and VSIX as GitHub release assets. The VS Code extension is versioned independently in `editor/vscode-sprout/package.json`.

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

The current VM supports literals, variables, assignment, property/index/slice assignment, arithmetic, comparisons, logical operators, arrays, dictionaries, indexing, slicing, function calls, `seedfn`, keyword arguments, default arguments, variadic arguments, call-site spread, `say`, `if`, `while`, `for`, `break`, `continue`, classes, methods, inheritance, `super`, Sprout imports, Python imports, `raise`, and `try` / `catch`. Test declarations compile as no-ops during ordinary execution, matching the stable interpreter; the dedicated test runner still controls test execution.

Bytecode instructions carry source file, line, column, and function context. `dis`, the terminal debugger, and VM runtime errors expose this information. `bench` reports compile time, interpreter time, VM time, instruction count, support status, and whether fallback was used. The VM is still experimental and is not guaranteed to be faster yet.

`debug` remains available as a terminal debugger. The VS Code extension also includes a Debug Adapter Protocol server for graphical breakpoints, call stacks, scopes, variables, expression evaluation, continue, pause, step in, step over, and step out. Open a `.sprout` file, add a breakpoint, and press `F5` or choose **Run and Debug: Debug current Sprout file**. Both debuggers execute through the experimental VM.

VS Code conditional breakpoints evaluate Sprout expressions in the current frame. Hit-count breakpoints accept a number such as `3`, comparisons such as `>= 5`, or `% 2` for every second hit. Enable **Uncaught Sprout errors** in the Breakpoints view to pause before an unhandled error exits.

`profile` reports compile time, run time, VM instruction count, and VM function call counts/times.

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

Sprout now includes foundations for testing, structured async tasks, HTTP,
SQLite, engineering utilities, documentation generation, and reusable game
application structure.

Run Sprout tests:

```sh
python3 sprout.py test
python3 sprout.py test tests/
python3 sprout.py test tests/application_test.sprout --verbose
python3 sprout.py test --list --json
python3 sprout.py test tests/application_test.sprout --filter "expectation helpers" --json
```

The VS Code extension discovers these tests in the native Testing view. Individual tests and files can be run without parsing terminal text.

Test syntax:

```sprout
test "addition":
  expect(add(2, 3)).to_equal(5)
```

Application examples:

```sh
python3 sprout.py run examples/application/async_demo.sprout
python3 sprout.py run examples/application/structured_async.sprout
python3 sprout.py run examples/application/http_server_demo.sprout
python3 sprout.py run examples/application/sqlite_demo.sprout
python3 sprout.py run examples/application/engineering_demo.sprout
python3 sprout.py run examples/application/game_app_demo.sprout
```

Key APIs:

- Structured async: `async def`, `await`, and lexical `taskgroup` scopes
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

The docs generator now reuses Sprout's semantic workspace analysis, so signatures,
class constructors, member docs, and source locations stay aligned with the CLI,
LSP, and VS Code tooling.

Inspect standard-library groups:

```sh
python3 sprout.py stdlib --groups
```

Async functions return task values. `await` unwraps their result, while
`taskgroup` waits for all tasks started in its lexical scope and propagates
failures. The scheduler also supports delayed tasks, futures, and queues through
the original helper API. Sprout function execution is serialized through a
runtime lock so shared interpreter state remains correct; this is structured
concurrency, not CPU-parallel execution. The experimental VM reports an explicit
unsupported-feature diagnostic only for constructs it still cannot compile;
structured async functions, `await`, task groups, streams, and async iteration
execute directly in the VM.

## Conformance, Fuzzing, And Security

Run the checked-in language conformance corpus:

```sh
python3 sprout.py conformance
python3 sprout.py conformance --json
```

The corpus in `sprout_core/conformance/` verifies stable interpreter behavior, clean diagnostics, structured
async behavior, and interpreter/VM parity for supported features.

Run deterministic grammar and differential fuzzing:

```sh
python3 sprout.py fuzz
python3 sprout.py fuzz --iterations 500 --seed 20260606
python3 sprout.py fuzz --iterations 100 --seed 42 --json
```

Each seed generates valid programs for interpreter/VM comparison and malformed
programs that must never crash the parser with an internal exception. A failed
seed can be replayed exactly.

Security regression tests cover hostile source input, package traversal,
symlinks, archive file-count and expansion limits, forged package hashes, and
raw Python traceback leakage:

```sh
python3 tests/security.py
```

## Optional Typed Abstractions

Sprout remains dynamically executed, but code may opt into gradual static
checking:

```sprout
interface Greeter:
  def greet(self, name: String) -> String

class FriendlyGreeter implements Greeter:
  def greet(self, name: String) -> String:
    return "hello " + name

def identity[T](value: T) -> T:
  return value

let message: String = FriendlyGreeter().greet("Mina")
let answer: Int = identity(42)
```

Run the checker on one file or an entire project:

```sh
python3 sprout.py typecheck examples/typed_abstractions.sprout
python3 sprout.py typecheck . --json
```

The checker validates known types, generic arity, annotated assignments,
function arguments and returns, and structural interface method requirements.
Annotations and interfaces are erased for execution, so the stable interpreter
and experimental VM run the same program without runtime type overhead.

Built-in types are `Any`, `Nil`, `Bool`, `Int`, `Float`, `Number`, `String`,
`List[T]`/`Array[T]`, `Dict[K, V]`, `Task[T]`, and `Generator[T]`. User classes,
interfaces, enums, qualified imported types, union types such as `Int | String`,
nullable shorthand such as `String?`, and generic aliases are supported. The
checker follows Sprout imports, validates imported calls, narrows unions after
`is` checks, and checks enum match exhaustiveness where the matched type is
known. It remains gradual: unannotated or unresolved values become `Any`.

## Advanced Language Features

Sprout includes data-carrying enums, structural pattern matching, lazy
generators, comprehensions, and asynchronous streams:

```sprout
type Maybe[T] = T | Nil

enum Result[T]:
  Ok(value: T)
  Error(message: String)

def numbers(limit: Int) -> Generator[Int]:
  for value in range(limit):
    yield value

def describe(result: Result[Int]) -> String:
  match result:
    case Result.Ok(value) if value > 0:
      return "ok " + str(value)
    case Result.Ok(_):
      return "zero"
    case Result.Error(message):
      return "error " + message

squares = [value * value for value in numbers(8) if value % 2 == 0]
```

Patterns support enum variants, literals, bindings, `_`, guards, and array
destructuring with a final `*rest`. Generator functions are lazy and expose
`.next()` and `.collect()`. Dictionary comprehensions use
`{key: value for item in iterable if condition}`.

Async application helpers include `sleep_async`, async HTTP requests, async
file reads/writes, cancellation tokens, message-queue receives, `stream_open`,
and `async for`. These run in both the stable interpreter and experimental VM.

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

- Numbers, strings, booleans, `nil`, and arrays
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
- `async for` loops over asynchronous streams
- `break` and `continue`
- Generic enums and guarded structural `match` / `case` patterns
- Lazy generator functions with `yield`, `.next()`, and `.collect()`
- List and dictionary comprehensions with optional filters
- Gradual unions, nullable types, generic type aliases, imported types, and `is` narrowing
- Recoverable errors with `try` / `catch`, `raise`, `ensure`, and `fail`
- Uncaught runtime errors with Sprout call stacks
- Named Sprout imports with `import gamekit as game`, plus quoted relative file paths
- Python library imports with `importpython math` or `importpython random as pyrandom`
- Command-line args through `argv`
- File helpers: `readfile`, `writefile`, `appendfile`, `exists`, `isfile`, `isdir`, `listdir`, `mkdir`, `readjson`, `writejson`, `lines`
- Operators: `+ - * / // %`, comparisons, equality, membership `in`, `and`, `or`, unary `!` / `not`
- Array and string slicing with `items[1:4]`, `items[:2]`, and `items[2:]`
- Built-ins: `say`, `len`, `push`, `range`, `str`, `int`, `num`, `type`, `keys`, `values`, `items`, `has`, `get`, `argv`, `ask`, `clear`, `ensure`, `fail`
- Special Sprout helpers: `sparkle`, `whisper`, `shout`, `mirror`, `chant`, `weave`, `grow`, `plant`, `harvest`, `prune`, `sprinkle`, `bundle`, `first`, `last`, `rest`, `unique`, `countby`, `zipbud`, `dice`
- Game helpers: `choose`, `clamp`, `wrap`, `dist`, `sleep`, `now`
- Expanded standard library with `functions()` reporting 183 callable global functions
- PixelGarden terminal engine with reusable sprites, layers, animation, world-space cameras, drawing, vectors, bounds, and collision checks
- StarBloom3D terminal engine with reusable scenes and objects, mesh transforms and composition, primitives, OBJ loading, and wireframe/solid rendering
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
import gamekit as game

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

Uncaught errors use Sprout's source-aware error reporter. It shows the error
category, exact file location, source line, caret, practical hint, and Sprout
call stack:

```text
error: FileError: File not found: '.../missing_config.txt'
  --> examples/stacktrace.sprout:2:18
    |
  2 |   text = readfile(path)
    |                  ^
  = hint: Check the path. Relative paths start from the current Sprout file or project.
stack:
  called at examples/stacktrace.sprout:2:18
  at load_config (examples/stacktrace.sprout:1:5)
  called at examples/stacktrace.sprout:8:21
  at boot_game (examples/stacktrace.sprout:6:5)
  called at examples/stacktrace.sprout:12:19
  at main (examples/stacktrace.sprout:11:5)
```

Normal execution translates Python and native tracebacks into Sprout tracebacks
instead of discarding them. Native operations and Python interop become errors
such as `MathError`, `FileError`, `TypeError`, and `InteropError`; their stack
retains Sprout call sites, bridge boundaries, and relevant external function
locations. Language developers can set `SPROUT_DEBUG_PYTHON=1` to additionally
expose the original raw traceback while debugging Sprout itself.

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
- `tools/sprout_lsp.py`: production stdio LSP server backed by the semantic workspace index
- `examples/`: sample Sprout programs
- `sprout_core/stdlib/`: packaged Sprout standard-library modules
- `examples/modules/`: compatibility copies and module examples
- `examples/data/`: tiny data files for demos
- `tests/`: smoke test script
- `editor/vscode-sprout/`: local VS Code language package with highlighting, snippets, completions, and hover help

## Editor Support

Install `sprout-language` from PyPI, then search the VS Code Extensions view for
**Sprout Language** by `jerry5678912`:

```sh
python3 -m pip install sprout-language
sprout version
```

Open a `.sprout` file after installing the extension. Click **Sprout: Auto** in
the status bar to select an interpreter, then click the editor-title play icon
or run **Sprout: Run Current File** from the Command Palette.

The extension source is included in this repository:

[editor/vscode-sprout](editor/vscode-sprout)

It recognizes `.sprout` files, highlights keywords and special helpers,
supports `#` comments, auto-closes braces/quotes, indents after `{`, `:`, and
`bloom`, provides snippets, and runs semantic diagnostics in the editor. When
the extension can find `sprout.py`, it starts Sprout's language server for
project-aware completions, hover help, go-to definition, find references,
rename edits, signature help, quick fixes, and Problems panel diagnostics. If
the server cannot start, it falls back to static completions and command-based
queries. Diagnostics use VS Code's native red/yellow squiggles and unnecessary
symbol fading; Sprout does not draw a custom second underline layer.

Use **Sprout: Show Language Server Output** to see the Python path, server path,
runner path, document open/change events, diagnostic counts, requests, crashes,
and fallback mode. Use **Sprout: Restart Language Server** to restart editor
services without reloading VS Code.

Current editor support is a real foundation, not Pyright/Pylance. The checked
behavior covers syntax diagnostics, unknown-name diagnostics, typo quick fixes
such as `impo` -> `import`, symbol/member completions, hover, simple
definitions, simple references, safe rename, signature help, interpreter
detection, run button support, debugging, Testing view integration, and
analysis-status reporting. Type inference and member diagnostics remain
conservative.

The interpreter selector supports the bundled, workspace, or a custom
`sprout.py` interpreter. Programs run in an interactive integrated terminal.

Build and install the self-contained VSIX:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.4.0.vsix
```

Quick local development flow:

```sh
cd editor/vscode-sprout
code .
```

Then press `F5` in VS Code to launch an Extension Development Host and open a `.sprout` file.

Repeat the editor behavior check and open the manual test workspace:

```sh
python3 tools/check_vscode_editor_behavior.py
code examples/editor_test_workspace
```

The editor behavior check now verifies diagnostics, quick fixes, member
completions, hover, imported-module definitions, references, rename, signature
help, and analysis-status payloads against the same workspace the manual VS
Code walkthrough uses.

Recent cross-surface integrations now reuse the same semantic engine for:

- generated API docs from `sprout docs`
- debugger frame labels and local-scope naming
- VS Code test discovery metadata and test doc-comment tooltips

Completion examples:

- Type `def` for a function snippet.
- Type `defbloom` for a garden-style `bloom` / `end` function snippet.
- Type `defbraces` for an old-compatible brace function snippet.
- Type `defrest` for a `*rest` variadic function snippet.
- Type `defopts` for a `**opts` keyword-rest function snippet.
- Type keywords like `elif`, `each`, `whirl`, `try`, `catch`, `raise`, `sprout`, `pluck`, or `end` for syntax snippets/completions.
- Type built-ins like `sparkle`, `grow`, `json_parse`, `py_import`, `functions`, or `methods` for call snippets.
- Type `callspread` for a call using `*args` and `**opts`.
- Type `game.` after `import gamekit as game` for gamekit completions.
- Type `g2d.` after `import geom2d as g2d` for Sprout2D API completions.
- Type `c2d.` after `import canvas2d as c2d` for Sprout2D canvas completions.
- Type `s3d.` after `import engine3d as s3d` for Sprout3D API completions.
- Type `pix.` after `import pixelgarden as pix` for PixelGarden completions.
- Type `star.` after `import starbloom3d as star` for StarBloom3D completions.
- Type `w2d.` after `import window2d as w2d` for Pygame-backed Window2D completions.
- Type `p3d.` after `import panda3d_window as p3d` for Panda3D-backed completions.
- Type `player.` on a variable created from a local `Player` class to complete that class's methods and fields.
- Hover functions or classes with `##` documentation comments to see their signature, docs, and source location.
- Use VS Code's Go to Definition, Find References, Rename Symbol, and signature help commands for Sprout symbols when `sprout.py` is available.
- Syntax and semantic errors appear as VS Code diagnostics. Set `sprout.analysis.typeCheckingMode` to `off`, `basic`, `standard`, or `strict`; use `sprout.analysis.diagnosticSeverityOverrides` to customize individual rules. Set `sprout.runnerPath` if the extension cannot find `sprout.py`, `sprout.diagnostics.enabled` to `false` to disable diagnostics, or `sprout.diagnostics.styleWarnings` to `false` to hide style warnings.

## Current Python-Closeness Snapshot

Sprout now covers a meaningful middle slice of Python:

- Similar: dynamic typing, numbers, strings, lists, dictionaries, classes, inheritance, `super`, instances, methods, functions, default, keyword, variadic, keyword-rest, and spread-call arguments, returns, conditions, `elif`, loops, `break`, `continue`, recoverable errors, truthiness, indexing, slicing, calls, dot-style methods, command-line args, file I/O helpers, and multi-file programs.
- Similar via bridge: Python standard-library modules can be imported with `importpython`.
- Different: Sprout has its own garden-style `bloom` / `end` blocks, old-compatible brace blocks, data-carrying enums, and explicit `match` blocks.

Good next work includes conformance and fuzz testing, optional typed
abstractions, signed packages, stronger sandboxing, and native single-file
freezing.
