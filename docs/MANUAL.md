# The Sprout Programming Language Manual

Version: 0.3.2
Implementation: modular Python tree-walk interpreter in `sprout_core/`, launched by `sprout.py`  
File extension: `.sprout`

Sprout is a small, dynamic programming language with a garden-flavored personality. It is designed to be easy to read, easy to experiment with, and practical enough for scripts, terminal games, multi-file projects, and Python standard-library interop.

Sprout is not a clone of Python, Rust, or C++. It borrows familiar ideas from Python, such as dynamic values, lists, dictionaries, classes, default arguments, keyword arguments, slicing, modules, exceptions, indentation blocks, and `for ... in` loops, while keeping its own syntax and playful aliases like `sprout`, `bloom`, `pluck`, `whirl`, `each`, and `say`.

Sprout also includes early game/engineering modules. PixelGarden is the fun terminal/ASCII 2D engine. StarBloom3D is the fun terminal/ASCII 3D engine. Window2D is an optional Pygame-backed real window wrapper, and PandaWindow3D is an optional Panda3D-backed real 3D window wrapper.

## 1. Quick Start

From the Sprout folder:

```sh
python3 sprout.py examples/fibonacci.sprout
```

Install the public `sprout-language` package from PyPI:

```sh
python3 -m pip install sprout-language
sprout version
```

For an isolated command-line installation:

```sh
pipx install sprout-language
```

From a cloned or extracted Sprout source release, you can instead run:

```sh
python3 install.py
~/.local/bin/sprout version
```

The default Unix installation prefix is `~/.local`. Select a custom prefix with `python3 install.py --prefix PATH`.

Start the REPL:

```sh
python3 sprout.py
```

Run a script with arguments:

```sh
python3 sprout.py examples/adventure.sprout Jerry
```

Run a 3D wireframe demo:

```sh
python3 sprout.py examples/engine3d_demo.sprout
python3 sprout.py examples/engine3d_solid_demo.sprout
python3 sprout.py examples/engine3d_obj_demo.sprout
python3 sprout.py examples/engine3d_camera_demo.sprout
python3 sprout.py examples/starbloom3d_demo.sprout
```

Run terminal 2D demos:

```sh
python3 sprout.py examples/geom2d_demo.sprout
python3 sprout.py examples/canvas2d_demo.sprout
python3 sprout.py examples/pixelgarden_demo.sprout
```

Run real window demos after installing optional Python libraries:

```sh
python3 -m pip install pygame
python3 sprout.py examples/window2d_demo.sprout

python3 -m pip install panda3d
python3 sprout.py examples/panda3d_window_demo.sprout
```

Sprout also has command-line tooling:

```sh
python3 sprout.py help
python3 sprout.py run examples/fibonacci.sprout
python3 sprout.py run examples/project
python3 sprout.py check examples/tictactoe.sprout
python3 sprout.py check examples/fibonacci.sprout --json
python3 sprout.py lint examples/seedfn.sprout
python3 sprout.py fmt examples/seedfn.sprout
python3 sprout.py stdlib
python3 sprout.py examples
python3 sprout.py version
```

`check` parses a file without running it. It is useful for editor integration, quick syntax checks, and CI scripts.

`stdlib` prints the current built-in function count and names.

Inside a script, command-line arguments are available through the global array `argv`.

```sprout
name = "Sproutling"
if len(argv) > 0:
  name = argv[0]
say "hello", name
```

## 2. A First Program

```sprout
def fib(n):
  if n <= 1:
    return n
  return fib(n - 1) + fib(n - 2)

values = []
for i in range(8):
  values.append(fib(i))

say values
```

Output:

```text
[0, 1, 1, 2, 3, 5, 8, 13]
```

## 3. Program Structure

Sprout programs are plain text files. Statements usually end at a newline. Semicolons are also accepted.

```sprout
name = "Ada"
say "hello", name

score = 10; say score
```

Sprout supports three block styles.

The recommended general style is Python-like: put `:` after the statement and indent the block.

```sprout
if score > 5:
  say "winning"
else:
  say "still growing"
```

The garden style uses `bloom` to open a block and `end` to close it. This makes Sprout feel less like Python and less full of punctuation:

```sprout
def cheer(name) bloom
  if name == "Sprout" bloom
    return sparkle("keep growing")
  end
  return "hello " + name
end
```

The older brace style still works, so old examples and experiments do not break:

```sprout
if score > 5 {
  say "old style still works"
}
```

Comments begin with `#` and continue to the end of the line.

```sprout
# This is a comment.
say "leaf"
```

The REPL supports multiline blocks. When a block is open, the prompt changes from `sprout>` to `......>`.

## 4. Keywords

Current reserved words:

```text
False None True and as break bloom catch class continue def each elif else
extends false fn for if import importpython in let nil none not or pluck
raise return say sprout super true try whirl while
```

Keyword aliases:

- `def`, `fn`, and `bloom` define functions.
- `return` and `pluck` return a value.
- `let` and `sprout` declare variables.
- `while` and `whirl` start while loops.
- `for` and `each` start iterable loops.
- `nil`, `none`, and `None` mean no value.
- `true` / `True` and `false` / `False` are booleans.

## 5. Values and Types

Sprout is dynamically typed. Variables do not have declared types.

Core value kinds:

- `nil`
- booleans
- numbers
- strings
- arrays
- dictionaries
- functions
- classes
- instances
- Sprout modules
- Python modules, Python functions, and wrapped Python objects

Use `type(value)` to inspect a value:

```sprout
say type(nil)          # nil
say type(true)         # bool
say type(42)           # number
say type("leaf")       # string
say type([1, 2])       # array
say type({"x": 1})     # dictionary
```

Class instances report their class name:

```sprout
class Hero {}
hero = Hero()
say type(hero)         # Hero
```

## 6. Variables

Sprout supports explicit declarations:

```sprout
let score = 10
sprout name = "Mina"
```

It also supports Python-style assignment:

```sprout
score = 10
score = score + 1
```

Assignment updates an existing variable in the current function or module scope. If none exists there, Sprout creates it in that nearest function or module scope. Reading a variable still uses lexical lookup, so functions can read values from outer scopes without accidentally overwriting them.

```sprout
name = "global"

def local_name() {
  name = "local"
  return name
}

say local_name(), name
# local global
```

Blocks do not trap new variables. A variable assigned inside an `if`, `while`, `for`, `try`, or `catch` block remains available in the surrounding function or module.

## 7. Numbers

Numbers are Python-backed `int` or `float` values.

```sprout
say 2 + 3
say 10 / 4
say 10 // 4
say 10 % 4
```

Operators:

```text
+  addition
-  subtraction
*  multiplication
/  division
// floor division
%  remainder
-x unary negation
```

## 8. Strings

Strings use double quotes:

```sprout
name = "Sprout"
say "hello " + name
```

Escapes:

```text
\n newline
\t tab
\" quote
\\ backslash
```

String methods:

```sprout
text = "  Leaf  "
say text.upper()
say text.lower()
say text.strip()
say "a,b,c".split(",")
say text.contains("ea")
```

Strings support indexing and slicing:

```sprout
word = "sprout"
say word[0]
say word[0:3]   # spr
say word[3:]    # out
say word[:2]    # sp
```

## 9. Booleans, Nil, and Truthiness

Booleans:

```sprout
true
false
True
False
```

No value:

```sprout
nil
none
None
```

Only `false` and `nil` are falsey. Everything else is truthy, including `0`, empty strings, and empty arrays.

```sprout
if [] {
  say "empty arrays are truthy"
}
```

Logical operators:

```sprout
if hp > 0 and not stunned {
  say "move"
}

name = player_name or "unknown"
```

`and` and `or` short-circuit and return values, not just booleans.

## 10. Arrays

Arrays are ordered and mutable.

```sprout
items = ["seed", "leaf"]
items.append("bloom")
say items
```

Indexing:

```sprout
say items[0]
items[1] = "root"
```

Slicing:

```sprout
nums = [0, 1, 2, 3, 4]
say nums[1:4]
say nums[:2]
say nums[2:]

nums[1:4] = ["a", "b"]
say nums
```

Array methods:

```sprout
items.append(value)
items.pop()
items.len()
items.join(", ")
```

Related built-ins:

```sprout
push(items, value)
first(items)
last(items)
rest(items)
unique(items)
countby(items)
weave(items, ", ")
choose(items)
```

## 11. Dictionaries

Dictionaries store key/value pairs. String and number keys are the most common.

```sprout
hero = {"name": "Mina", "hp": 10}
say hero["name"]
say hero.name
```

Mutation:

```sprout
hero["hp"] = 9
hero.x = 4
hero.set("y", 2)
```

Dictionary methods:

```sprout
hero.keys()
hero.values()
hero.items()
hero.has("hp")
hero.get("missing")
hero.get("missing", "fallback")
hero.set("level", 3)
```

Dictionary built-ins:

```sprout
keys(hero)
values(hero)
items(hero)
has(hero, "hp")
get(hero, "hp")
get(hero, "missing", "fallback")
zipbud(["name", "hp"], ["Mina", 10])
```

## 12. Operators

Comparison:

```text
== != < <= > >=
```

Membership:

```sprout
if "key" in inventory {
  say "door opens"
}
```

Logical:

```text
and or not !
```

Unary:

```text
-x
!x
not x
```

Property access:

```sprout
thing.name
thing.method()
```

Call:

```sprout
function(arg)
function(name="Mina")
```

Index and slice:

```sprout
items[0]
items[1:3]
items[:3]
items[3:]
```

## 13. Control Flow

### If / Elif / Else

```sprout
if score >= 90 {
  say "A"
} elif score >= 80 {
  say "B"
} else {
  say "keep growing"
}
```

`else if` is accepted too because `else` can be followed by `if`.

### While / Whirl

```sprout
i = 0
while i < 3 {
  say i
  i = i + 1
}
```

`whirl` is an alias:

```sprout
whirl hp > 0 {
  hp = hp - 1
}
```

### For / Each

```sprout
for n in range(5) {
  say n
}

each name in ["Ada", "Lin"] {
  say name
}
```

Loops can iterate arrays, strings, `range(...)` results, and dictionaries. Dictionary iteration yields keys.

```sprout
scores = {"Ada": 98, "Lin": 84}
for name in scores {
  say name, scores[name]
}
```

### Break and Continue

```sprout
for n in range(10) {
  if n == 2 {
    continue
  }
  if n == 5 {
    break
  }
  say n
}
```

## 14. Functions

Define functions with `def`, `fn`, or `bloom`.

```sprout
def add(a, b):
  return a + b

fn twice(x):
  return x * 2

bloom cheer(name):
  pluck "go " + name
```

`return` and `pluck` both return values.

Functions are lexically scoped. A function can refer to variables from the scope where it was defined.

Use `seedfn` for tiny inline functions. A `seedfn` captures variables from the scope where it was created.

```sprout
double = seedfn x: x * 2
add = seedfn a, b: a + b
tag = seedfn (name, prefix="seed"): prefix + ":" + name

base = 10
boost = seedfn x: x + base

say double(5), add(2, 3), tag("leaf"), boost(4)
```

### Default Arguments

```sprout
def spawn(name, hp=10, x=0, y=0) {
  return {"name": name, "hp": hp, "x": x, "y": y}
}

say spawn("Mina")
say spawn("Boss", 20, 5, 2)
```

Parameters after a default must also have defaults.

Valid:

```sprout
def ok(a, b=1, c=2) {}
```

Invalid:

```sprout
def bad(a=1, b) {}
```

### Keyword Arguments

```sprout
hero = spawn(name="Mina", y=3)
boss = spawn("Boss", hp=20, x=5, y=2)
```

Positional arguments must come before keyword arguments.

Invalid:

```sprout
spawn(name="Mina", 10)
```

Duplicate argument values are errors:

```sprout
spawn("Ada", name="Lin")
```

### Variadic Arguments

Use `*name` as the final parameter to collect extra positional arguments into an array.

```sprout
def debug(label, *values) {
  return label + ": " + values.join(" | ")
}

say debug("player", "Mina", "hp", 13)
# player: Mina | hp | 13
```

Variadic parameters can follow regular and default parameters. `*name` collects extra positional arguments into an array. `**name` collects extra keyword arguments into a dictionary.

```sprout
def entity(kind, **opts) {
  return kind + " hp=" + str(opts.hp)
}

say entity("drone", hp=6, speed=3)
```

You can combine them:

```sprout
def command(name, *args, **opts) {
  return name + " " + args.join("/") + " mode=" + opts.mode
}
```

`**name` must be last. If `*name` is present, it must appear before `**name`.

### Call-Site Spreading

Use `*array` in a call to expand an array into positional arguments. Use `**dict` to expand a dictionary into keyword arguments.

```sprout
def spawn(name, x=0, y=0, **opts) {
  return name + " @(" + str(x) + "," + str(y) + ") hp=" + str(opts.hp)
}

pos = [4, 9]
opts = {"hp": 12, "team": "blue"}

say spawn("bot", *pos, **opts)
# bot @(4,9) hp=12
```

Spreading is useful for wrapper functions:

```sprout
def forward_spawn(name, *args, **opts) {
  return spawn(name, *args, **opts)
}
```

Rules:

- Positional spreads must expand arrays.
- Keyword spreads must expand dictionaries.
- Keyword-spread dictionary keys must be strings.
- Duplicate keywords are errors.
- Positional values and positional spreads must come before keyword arguments and keyword spreads.

## 15. Classes and Objects

Classes are callable values that create instances.

```sprout
class Hero {
  def init(self, name, hp=10) {
    self.name = name
    self.hp = hp
  }

  def hurt(self, amount=1) {
    self.hp = clamp(self.hp - amount, 0, 10)
  }

  def status(self) {
    return self.name + " hp=" + str(self.hp)
  }
}

hero = Hero("Mina")
hero.hurt(amount=3)
say hero.status()
```

The method named `init` is the constructor. It runs automatically when the class is called.

Methods are ordinary Sprout functions that conventionally take `self` as the first parameter. When called as `hero.status()`, Sprout binds `self` automatically.

Fields are created by assignment:

```sprout
self.hp = 10
hero.level = 2
```

### Inheritance

Use `extends` to inherit methods and constructors.

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

Method lookup checks the class first, then its superclass chain.

Use `super.method(...)` inside a subclass method to call the parent implementation bound to the current instance.

```sprout
class Player extends Entity {
  def init(self, name, x=0, y=0, hp=10) {
    super.init(name, x=x, y=y)
    self.hp = hp
  }

  def status(self) {
    return super.status() + " hp=" + str(self.hp)
  }
}
```

## 16. Modules

Sprout supports native file imports:

```sprout
import "modules/gamekit.sprout" as game

hero = game.make_player("Ada")
say game.status(hero)
```

The imported file runs once and produces a module object. Public names are accessed as properties. Names beginning with `_` are private through module property access.

Relative imports are resolved from the current script or module directory.

If no alias is provided, Sprout derives one from the file name:

```sprout
import "modules/gamekit.sprout"
gamekit.make_player("Ada")
```

## 17. Python Library Interop

Use `importpython` to import Python modules.

```sprout
importpython math
say math.sqrt(81)
say math.pi
```

Quoted module names also work:

```sprout
importpython "statistics" as stats
say stats.mean([1, 2, 3])
```

Use `as` for an alias:

```sprout
importpython random as pyrandom
pyrandom.seed(7)
say pyrandom.randint(1, 10)
```

Sprout can call Python functions, read module constants, construct Python objects, call object methods, read object fields, and set public object fields.

```sprout
importpython datetime as dt

day = dt.date(year=2026, month=6, day=4)
say day.isoformat()
say day.year
```

Keyword arguments are passed through to Python:

Dynamic optional imports are available through functions:

```sprout
say py_available("pygame")
pg = py_import("pygame")
```

`py_available(module_name)` returns `true` if Python can import the module. `py_import(module_name)` imports by string and returns a Python module object. This is useful for optional modules like Pygame and Panda3D wrappers, where a Sprout module should load cleanly even if the Python package is not installed yet.

```sprout
day = dt.date(year=2026, month=6, day=4)
```

Python results are wrapped:

- Python `None`, booleans, numbers, and strings become normal Sprout values.
- Python lists and tuples become Sprout arrays.
- Python dictionaries become Sprout dictionaries.
- Python modules become `python-module` values.
- Python callables become `python-function` values.
- Other Python objects become `python-object` values.

Private Python names beginning with `_` are not available.

## 18. Recoverable Errors

Sprout has catchable errors:

```sprout
try {
  raise "manual problem"
} catch err {
  say "caught:", err
}
```

`raise value` raises any Sprout value.

`ensure(condition, message)` raises `message` if the condition is falsey.

```sprout
def load_hp(value) {
  ensure(value >= 0, "hp cannot be negative")
  ensure(value <= 10, "hp cannot be over 10")
  return value
}
```

`fail(message)` always raises.

```sprout
fail("save file corrupt")
```

`try/catch` catches both explicit Sprout raises and runtime `SproutError` failures, including file errors.

```sprout
try {
  text = readfile("missing.txt")
} catch err {
  say "file problem:", err
}
```

`return`, `break`, and `continue` are control flow and are not caught as normal errors.

Uncaught errors use Sprout's source-aware reporter. It prints an error category, the file and position, the relevant source line, a caret, a practical hint when available, and the Sprout call stack. This is useful when a larger game, tool, or multi-file program fails inside nested function calls.

```sprout
def load_config(path) {
  return readfile(path)
}

def boot_game() {
  return load_config("data/missing_config.txt")
}

boot_game()
```

Example output:

```text
error: FileError: File not found: '.../data/missing_config.txt'
  --> examples/stacktrace.sprout:2:18
    |
  2 |   text = readfile(path)
    |                  ^
  = hint: Check the path. Relative paths start from the current Sprout file or project.
stack:
  called at examples/stacktrace.sprout:2:18
  at load_config (examples/stacktrace.sprout:1:5)
  called at examples/stacktrace.sprout:7:21
  at boot_game (examples/stacktrace.sprout:6:5)
```

Sprout translates Python and native tracebacks into Sprout tracebacks during normal program execution; it does not discard them. Errors from native helpers and `importpython` calls retain Sprout call sites, named bridge boundaries, and relevant bridged function locations. `SPROUT_DEBUG_PYTHON=1 sprout program.sprout` additionally exposes the original raw traceback for language developers diagnosing an unexpected internal Sprout failure.

## 19. Files and Command-Line Programs

Global:

```sprout
argv
```

File helpers:

```sprout
readfile(path)
writefile(path, text)
appendfile(path, text)
exists(path)
isfile(path)
isdir(path)
listdir(path)
mkdir(path)
readjson(path)
writejson(path, value)
lines(text)
```

Paths are relative to the running script or module.

Example:

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

`writefile` and `appendfile` convert values through Sprout display formatting.
`writejson` writes real JSON from Sprout values, and `readjson` converts JSON back into Sprout arrays, dictionaries, strings, numbers, booleans, and `nil`.

## 20. Built-In Functions

Sprout currently exposes **183 callable global functions**. Use `functions()` to inspect them from Sprout itself, and `methods()` to inspect built-in method names.

```sprout
say len(functions())
say functions()
say methods()
```

Authoritative current global function list:

```text
abs, acos, appendfile, array, asin, ask
atan, atan2, avg, basename, between, bundle
ceil, chant, chars, choose, chunks, clamp
clear, compact, concat, contains, copy, cos
countby, cwd, degrees, delkey, dice, dict
dirname, dist, drop, endswith, ensure, enumerate
exists, exp, extname, fail, fill, first
flatten, floor, frompairs, functions, get, grow
harvest, has, hypot, indexof, insert, int
is_array, is_bool, is_class, is_dict, is_empty, is_even
is_function, is_instance, is_nil, is_number, is_odd, is_string
isdir, isfile, items, join, joinpath, json_parse
json_stringify, keys, last, len, lerp, lines
listdir, log, log10, lower, ltrim, max
median, merge, methods, min, mirror, mkdir
now, num, omit, padleft, padright, pick
plant, pow, print, prune, push, py_available
py_import, radians, rand, randint, range, readfile
readjson, remove, repeat, replace, rest, reverse
round, rtrim, sample, say, seed, shout
shuffle, sign, sin, sleep, slice, sort
sparkle, sprinkle, sqrt, startswith, str, substr
sum, take, tan, title, trim, type
unique, upper, values, weave, whisper, words
wrap, writefile, writejson, zipbud
```

### Output and Input

```sprout
say(...)
print(...)
ask(prompt)
clear()
```

`say` and `print` print formatted values separated by spaces.

`ask(prompt)` prints a prompt and reads a line from standard input.

`clear()` clears ANSI-compatible terminals.

### Conversion and Introspection

```sprout
len(value)
str(value)
int(value)
num(value)
type(value)
```

`num` converts to floating point.

### Arrays and Dictionaries

```sprout
push(array, value)
grow(array, value)
harvest(array)
prune(array, value)
sprinkle(array, separator)
bundle(keys, values)
first(array)
last(array)
rest(array)
unique(array)
countby(array)
weave(array, separator)
zipbud(keys, values)

keys(dictionary)
values(dictionary)
items(dictionary)
has(dictionary, key)
plant(dictionary, key, value)
get(dictionary, key)
get(dictionary, key, fallback)
```

### Ranges and Randomness

```sprout
range(n)
dice(sides)
choose(array)
```

`range(n)` returns `[0, 1, ... n-1]`.

`dice(sides)` returns a random integer from `1` through `sides`.

`choose(array)` returns a random element.

### Strings and Fun Helpers

```sprout
sparkle(value)
whisper(value)
shout(value)
mirror(value)
chant(value, times)
grow(array, value)
plant(dictionary, key, value)
harvest(array)
prune(array, value)
sprinkle(array, separator)
bundle(keys, values)
```

Examples:

```sprout
say sparkle("welcome")      # * welcome *
say whisper("LOUD")         # loud
say shout("small")          # SMALL
say mirror("desserts")      # stressed
say chant("ha", 3)          # hahaha
say grow(["leaf"], "bud")   # [leaf, bud]
```

If `chant` receives an array, it repeats the array.

The garden-named collection helpers are useful aliases for common script operations:

- `grow(array, value)` appends a value and returns the same array.
- `plant(dictionary, key, value)` sets a dictionary key and returns the same dictionary.
- `harvest(array)` removes and returns the last item, or returns `nil` for an empty array.
- `prune(array, value)` removes every matching value and returns the same array.
- `sprinkle(array, separator)` returns a new array with the separator between items.
- `bundle(keys, values)` returns key/value pair arrays like `[["x", 4], ["y", 9]]`.

### Game Helpers

```sprout
clamp(value, low, high)
wrap(value, low, high)
dist(x1, y1, x2, y2)
sleep(seconds)
now()
```

Examples:

```sprout
hp = clamp(hp - 1, 0, 10)
x = wrap(x + 1, 0, 9)
distance = dist(player.x, player.y, monster.x, monster.y)
```

`wrap` includes both bounds. `wrap(10, 0, 9)` returns `0`.

`now()` returns a timestamp from Python's `time.time()`.

### Validation

```sprout
ensure(condition, message)
fail(message)
```

### Math and Number Helpers

```sprout
abs(x)
round(x)
round(x, digits)
floor(x)
ceil(x)
sqrt(x)
pow(x, y)
min(...)
max(...)
sum(array)
avg(array)
median(array)
sin(x)
cos(x)
tan(x)
asin(x)
acos(x)
atan(x)
atan2(y, x)
log(x)
log10(x)
exp(x)
radians(x)
degrees(x)
hypot(...)
sign(x)
lerp(a, b, t)
between(x, low, high)
```

`min` and `max` accept either many arguments or one array.

### Type Predicates

```sprout
is_nil(value)
is_bool(value)
is_number(value)
is_string(value)
is_array(value)
is_dict(value)
is_function(value)
is_class(value)
is_instance(value)
is_empty(value)
is_even(value)
is_odd(value)
```

### Extra Array Helpers

```sprout
array(...)
copy(value)
reverse(array_or_string)
sort(array)
contains(haystack, needle)
indexof(haystack, needle)
insert(array, index, value)
remove(array, value)
take(array_or_string, n)
drop(array_or_string, n)
slice(array_or_string, start, end)
concat(...)
flatten(array)
compact(array)
repeat(value, n)
fill(value, n)
enumerate(array)
chunks(array, size)
```

`copy` recursively copies arrays and dictionaries.

`concat` joins arrays when all arguments are arrays; otherwise it joins display-formatted text.

### Extra String Helpers

```sprout
trim(text)
ltrim(text)
rtrim(text)
upper(text)
lower(text)
title(text)
replace(text, old, new)
startswith(text, prefix)
endswith(text, suffix)
substr(text, start, end)
padleft(text, width, fill)
padright(text, width, fill)
chars(text)
words(text)
join(array, separator)
```

### Extra Dictionary Helpers

```sprout
dict(...)
merge(...)
pick(dictionary, keys)
omit(dictionary, keys)
frompairs(pairs)
delkey(dictionary, key)
```

`dict("name", "Mina", "hp", 10)` creates a dictionary from alternating keys and values.

`frompairs([["name", "Mina"], ["hp", 10]])` creates a dictionary from pairs.

### JSON Helpers

```sprout
json_parse(text)
json_stringify(value)
readjson(path)
writejson(path, value)
```

These use Python's `json` module through the interpreter. `json_parse` and `json_stringify` work with text. `readjson` and `writejson` work with files relative to the current Sprout script or module.

### Path Helpers

```sprout
cwd()
basename(path)
dirname(path)
extname(path)
joinpath(...)
```

### Random Helpers

```sprout
rand()
randint(low, high)
seed(value)
shuffle(array)
sample(array, n)
```

`shuffle` returns a shuffled copy. `sample` returns `n` random elements without replacement.

## 21. Built-In Methods

### Array Methods

```sprout
array.append(value)
array.pop()
array.len()
array.join(separator)
```

`append` returns the array. `pop` returns the removed value.

### Dictionary Methods

```sprout
dict.keys()
dict.values()
dict.items()
dict.get(key)
dict.get(key, fallback)
dict.has(key)
dict.set(key, value)
```

`set` returns the dictionary.

### String Methods

```sprout
string.upper()
string.lower()
string.strip()
string.split(separator)
string.contains(needle)
```

## 22. PixelGarden and Sprout2D Terminal Helpers

The current terminal/ASCII 2D engine is named PixelGarden:

```sprout
import "modules/pixelgarden.sprout" as pix
```

PixelGarden combines the lower-level geometry and terminal canvas modules into a playful terminal engine. The older lower-level modules still exist:

```sprout
import "modules/geom2d.sprout" as g2d
import "modules/canvas2d.sprout" as c2d
```

It uses plain dictionaries for vectors, rectangles, and circles. That makes values easy to print, save as JSON, inspect in a debugger, and pass between scripts.

### 2D Vector API

```sprout
g2d.vec2(x=0, y=0)
g2d.vadd(a, b)
g2d.vsub(a, b)
g2d.vscale(v, amount)
g2d.dot(a, b)
g2d.length(v)
g2d.normalize(v)
g2d.distance(a, b)
g2d.angle(v)
g2d.from_angle(theta, size=1)
g2d.lerp_vec(a, b, t)
g2d.midpoint(a, b)
g2d.move_toward(current, target, max_delta)
g2d.clamp_vec(v, min_v, max_v)
```

Example:

```sprout
player = g2d.vec2(1, 2)
target = g2d.vec2(7, 5)
step = g2d.move_toward(player, target, 2)
say step
```

### 2D Shapes and Collision

```sprout
g2d.rect(x=0, y=0, w=1, h=1)
g2d.circle(x=0, y=0, r=1)
g2d.rect_center(rect)
g2d.point_in_rect(point, rect)
g2d.rects_overlap(a, b)
g2d.point_in_circle(point, circle)
g2d.circle_overlap(a, b)
g2d.nearest_point_on_rect(point, rect)
g2d.circle_rect_overlap(circle, rect)
g2d.bounds(points)
```

These helpers are intended as practical foundations for terminal games, collision tests, simulation prototypes, robotics sketches, and future 2D rendering/window APIs.

### 2D Terminal Canvas API

Sprout2D also includes a tiny terminal canvas module:

```sprout
import "modules/canvas2d.sprout" as c2d
```

Canvas values are dictionaries with `width`, `height`, `fill`, and `rows`.

```sprout
c2d.make_canvas(width, height, fill=" ")
c2d.clear(canvas, fill=nil)
c2d.plot(canvas, x, y, char="#")
c2d.line(canvas, x0, y0, x1, y1, char="#")
c2d.stroke_rect(canvas, rect, char="#")
c2d.fill_rect(canvas, rect, char="#")
c2d.circle(canvas, circle, char="#")
c2d.fill_circle(canvas, circle, char="#")
c2d.text(canvas, x, y, value)
c2d.sprite(canvas, x, y, rows)
c2d.camera(position=g2d.vec2(0, 0), zoom=1)
c2d.world_to_screen(point, camera, canvas)
c2d.plot_world(canvas, point, camera, char="#")
c2d.frame_to_text(canvas)
```

Example:

```sprout
canvas = c2d.make_canvas(24, 10, ".")
c2d.stroke_rect(canvas, g2d.rect(0, 0, 24, 10), "#")
c2d.text(canvas, 12, 8, "Sprout2D")
say c2d.frame_to_text(canvas)
```

The canvas module is terminal-first. It is not a full window or GPU renderer, but it gives Sprout drawing primitives, simple sprites, text drawing, and camera-style world-to-screen conversion.

PixelGarden convenience API:

```sprout
pix.canvas(width, height, fill=" ")
pix.vec2(x=0, y=0)
pix.rect(x=0, y=0, w=1, h=1)
pix.circle_shape(x=0, y=0, r=1)
pix.stroke_rect(canvas, rect, char="#")
pix.fill_rect(canvas, rect, char="#")
pix.circle(canvas, shape, char="#")
pix.text(canvas, x, y, value)
pix.sprite(canvas, x, y, rows)
pix.frame_to_text(canvas)
```

## 23. StarBloom3D Terminal Rendering

The current terminal/ASCII 3D engine is named StarBloom3D:

```sprout
import "modules/starbloom3d.sprout" as star
```

The older lower-level module still exists:

```sprout
import "modules/engine3d.sprout" as s3d
```

It is a software 3D engine that works in any terminal. It does not require OpenGL, a window, or third-party packages. It is useful for learning, prototypes, ASCII games, engineering sketches, and testing Sprout's math/graphics capabilities. It supports OBJ model loading, oriented cameras, wireframe rendering, and filled shaded triangles.

### Basic Render Pipeline

```sprout
import "modules/engine3d.sprout" as s3d

cam = s3d.camera(s3d.vec3(0, 0, -6), fov=20)
shape = s3d.cube(size=2.4)
shape = s3d.rotate_mesh(shape, ax=radians(20), ay=radians(35), az=radians(5))
shape = s3d.translate_mesh(shape, s3d.vec3(0, 0, 7))

frame = s3d.render_wireframe(shape, cam, width=50, height=22, char="*")
say s3d.frame_to_text(frame)
```

Solid shaded rendering:

```sprout
light = s3d.normalize(s3d.vec3(0 - 1, 1, 0 - 1))
frame = s3d.render_solid(shape, cam, width=56, height=24, light_dir=light)
say s3d.frame_to_text(frame)
```

### Vector API

```sprout
s3d.vec3(x=0, y=0, z=0)
s3d.vadd(a, b)
s3d.vsub(a, b)
s3d.vscale(v, amount)
s3d.dot(a, b)
s3d.cross(a, b)
s3d.length(v)
s3d.normalize(v)
```

Vectors are dictionaries with `x`, `y`, and `z` fields.

### Mesh API

```sprout
s3d.mesh(vertices, edges)
s3d.cube(size=2)
s3d.obj_mesh(text)
s3d.load_obj(path)
s3d.parse_face_index(token)
s3d.unique_edges(edges)
s3d.translate_mesh(mesh, offset)
s3d.scale_mesh(mesh, amount)
s3d.rotate_mesh(mesh, ax=0, ay=0, az=0)
s3d.bounds(mesh)
```

Meshes are dictionaries with:

- `vertices`: array of vec3 values
- `edges`: array of `[startIndex, endIndex]` pairs
- `faces`: array of triangle `[a, b, c]` index triples

`obj_mesh(text)` parses a small Wavefront OBJ string. `load_obj(path)` reads an OBJ file and returns a Sprout3D mesh. Supported OBJ records are `v x y z` vertices and `f ...` faces. Faces with more than three vertices are triangulated with a fan. Face tokens like `3`, `3/1`, and `3/1/2` are accepted, with only the vertex index used.

### Camera and Projection

```sprout
s3d.camera(position, fov=18, near=0.1)
s3d.look_at_camera(position, target, up=s3d.vec3(0, 1, 0), fov=18, near=0.1)
s3d.orbit_camera(target, radius=8, yaw=0, pitch=0, fov=18, near=0.1)
s3d.world_to_camera(point, camera)
s3d.project(point, camera, width, height)
```

`camera(position)` is the original simple perspective camera looking down positive `z`. `look_at_camera(position, target)` creates an oriented camera aimed at a point. `orbit_camera(target, radius, yaw, pitch)` is useful for model viewers, game debug cameras, and engineering inspection views.

### Framebuffer and Drawing

```sprout
s3d.make_frame(width, height, fill=" ")
s3d.make_zbuffer(width, height)
s3d.plot(frame, x, y, char="#")
s3d.line(frame, x0, y0, x1, y1, char="#")
s3d.draw_triangle(frame, zbuffer, p0, p1, p2, char="#")
s3d.render_wireframe(mesh, camera, width=48, height=22, char="#")
s3d.render_solid(mesh, camera, width=48, height=22, light_dir=s3d.vec3(0, 0, -1), ramp=" .:-=+*#%@")
s3d.frame_to_text(frame)
```

The framebuffer is a dictionary with `width`, `height`, and `rows`. `rows` is a 2D array of characters.

Lighting and triangle helpers:

```sprout
s3d.face_normal(a, b, c)
s3d.shade_char(light, ramp=" .:-=+*#%@")
```

Current limitation: StarBloom3D and `engine3d.sprout` are terminal/ASCII only. They do not yet have materials beyond character ramps, textures, skeletal animation, physics, or realtime window output.

## 24. Window2D and PandaWindow3D

Sprout also includes optional real-window wrappers that use Python graphics libraries.

Window2D uses Pygame:

```sprout
import "modules/window2d.sprout" as w2d

if not w2d.available() {
  say "install pygame with python3 -m pip install pygame"
} else {
  win = w2d.window(640, 360, "Sprout Window2D")
  clock = w2d.clock(win)
  while not w2d.should_close(win) {
    w2d.fill(win, w2d.color(20, 24, 35))
    w2d.circle(win, 320, 180, 40, w2d.color(250, 220, 90))
    w2d.flip(win)
    w2d.tick(clock, 60)
  }
  w2d.quit()
}
```

PandaWindow3D uses Panda3D:

```sprout
import "modules/panda3d_window.sprout" as p3d

if not p3d.available() {
  say "install Panda3D with python3 -m pip install panda3d"
} else {
  world = p3d.window("Sprout PandaWindow3D")
  cube = p3d.load_model(world, "models/box")
  p3d.place(cube, 0, 6, 0)
  p3d.run(world)
}
```

These modules are real window-backed wrappers, but they require their Python packages to be installed. They are separate from the fun terminal engines so terminal demos keep working anywhere.

## 25. Standard Examples

The project includes these examples:

```text
examples/fibonacci.sprout        recursion and loops
examples/lists.sprout            arrays and mutation
examples/guess.sprout            if/else
examples/garden.sprout           garden-flavored style
examples/pythonish.sprout        Python-like style
examples/special.sprout          special helper functions
examples/pythonlibs.sprout       Python standard-library interop
examples/minigame.sprout         small terminal game simulation
examples/adventure.sprout        multi-file data-driven game sketch
examples/fileio.sprout           file I/O
examples/oopgame.sprout          classes and methods
examples/errors.sprout           try/catch and validation
examples/stacktrace.sprout       uncaught runtime stack traces
examples/scopes.sprout           function-local assignment and scope behavior
examples/python_blocks.sprout    Python-style indentation blocks
examples/garden_blocks.sprout    garden-style bloom/end blocks
examples/seedfn.sprout           inline seedfn functions and closure capture
examples/variadic.sprout         variadic `*rest` and `**options` function arguments
examples/slices_defaults.sprout  slicing and default args
examples/keywordargs.sprout      keyword args and Python kwargs
examples/inheritance.sprout      class inheritance
examples/super.sprout            parent method calls with super
examples/tictactoe.sprout        interactive terminal Tic-Tac-Toe game
examples/stdlib100.sprout        expanded 100+ function standard library
examples/geom2d_demo.sprout      Sprout2D vectors, movement, and collision helpers
examples/canvas2d_demo.sprout    Sprout2D terminal canvas drawing primitives
examples/pixelgarden_demo.sprout PixelGarden fun terminal 2D engine
examples/engine3d_demo.sprout    Sprout3D wireframe cube renderer
examples/engine3d_solid_demo.sprout Sprout3D shaded z-buffer renderer
examples/engine3d_obj_demo.sprout Sprout3D OBJ model loading
examples/engine3d_camera_demo.sprout Sprout3D oriented camera renderer
examples/starbloom3d_demo.sprout StarBloom3D fun terminal 3D engine
examples/window2d_demo.sprout    optional Pygame-backed window demo
examples/panda3d_window_demo.sprout optional Panda3D-backed window demo
examples/project                 sprout.toml project, source folders, and module paths
```

## 26. Projects, Tooling, and Language Server

Sprout has an early project system based on `sprout.toml`.

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

[tool.sprout]
style_warnings = true
```

Run a project directory:

```sh
python3 sprout.py run examples/project
```

When a project is active, Sprout resolves imports from:

```text
current file directory
project root
paths.source
paths.modules
local dependency paths from dependencies
```

That means larger projects can use clean imports:

```sprout
import "game/player.sprout" as player
import "engine/math/vector.sprout" as vec
```

`check` supports machine-readable JSON for editors and CI:

```sh
python3 sprout.py check file.sprout --json
python3 sprout.py check file.sprout --json --warnings
```

The JSON payload includes `ok`, `path`, `diagnostics`, and `symbols`.

`lint` is an early warning system. Warnings do not stop programs from running.

```sh
python3 sprout.py lint file.sprout
python3 sprout.py lint file.sprout --json
```

Current lint foundations include syntax diagnostics, unknown imports, duplicate names, unreachable code after simple terminators, suspicious shadowing, tabs, and style hints that are practical to detect.

`fmt` is intentionally conservative:

```sh
python3 sprout.py fmt file.sprout
python3 sprout.py fmt file.sprout --write
python3 sprout.py fmt .
python3 sprout.py fmt . --write
```

It trims trailing whitespace, expands tabs to spaces, preserves comments, and avoids risky rewrites.

Sprout keeps local path packages for development:

```sh
python3 sprout.py pkg init
python3 sprout.py pkg list
python3 sprout.py pkg add ./local-package
python3 sprout.py pkg info local_package
python3 sprout.py pkg remove local_package
```

Package dependencies are stored in `[dependencies]`. Local `path` entries work alongside registry version constraints. The full build, registry, publishing, and distribution workflow is documented in section 31.

Project templates create working folders with `sprout.toml`, `src/main.sprout`, `modules/`, `tests/`, and a README:

```sh
python3 sprout.py new cli my_tool
python3 sprout.py new game2d my_game
python3 sprout.py new game3d my_3d_demo
python3 sprout.py new library my_lib
```

The current templates are dogfood-hardened:

- `cli` includes help text, command dispatch, argument parsing, and useful output.
- `game2d` includes a deterministic movement/update/render loop with walls, coins, and score.
- `game3d` renders a projected terminal wireframe scene.
- `library` includes a module, docs, and a runnable test file under `tests/`.

Release-readiness helpers:

```sh
python3 sprout.py doctor
python3 sprout.py release-docs
python3 sprout.py release-check
```

Sprout includes a production stdio Language Server Protocol implementation:

```sh
python3 tools/sprout_lsp.py
```

The server supports incremental UTF-16 document synchronization, versioned diagnostics, semantic completions, hover information, go-to definition, find references, safe rename preparation and edits, signature help, document symbols, workspace symbols, workspace folders, watched-file invalidation, request cancellation, and proper initialize/shutdown/exit lifecycle handling.

Semantic names are bound through lexical scopes rather than text matching alone. A parameter named `value` in one function is distinct from a parameter named `value` in another function. Definitions, references, and rename operations use stable symbol identities, including imported Sprout module members.

The workspace index is incremental in a running language-server process. Unchanged files reuse their parsed analysis, open documents are reanalyzed only when their text changes, and changed files refresh their exports and import links. VS Code uses this persistent server by default and automatically falls back to command-based tooling if it cannot start. The cache is currently in memory and is rebuilt when the language-server process restarts.
The current semantic tooling layer also builds a workspace index for functions, classes, methods, modules, variables, imports, module exports, references, rename edits, and function signatures.

Editor-style JSON queries are available through `intel`:

```sh
python3 sprout.py intel file.sprout --kind completions --line 20 --col 8
python3 sprout.py intel file.sprout --kind hover --line 14 --col 6
python3 sprout.py intel file.sprout --kind definition --line 14 --col 6
python3 sprout.py intel file.sprout --kind references --line 20 --col 3
python3 sprout.py intel file.sprout --kind signature --line 17 --col 17
python3 sprout.py intel file.sprout --kind diagnostics --line 1 --col 1
```

Documentation comments start with `##` immediately before a function or class. They appear in semantic hover help and completion descriptions:

```sprout
## Create a player with optional hit points.
def spawn(name, hp=10):
  return Player(name, hp)
```

## 27. Experimental Bytecode VM

Sprout has two execution paths:

1. Stable tree-walk interpreter.
2. Experimental bytecode VM.

The tree-walk interpreter remains the source of truth and continues to run the full current language. The VM is an incremental foundation for future performance, debugging, profiling, and optimization work.

VM commands:

```sh
python3 sprout.py compile examples/vm_supported.sprout
python3 sprout.py dis examples/vm_supported.sprout
python3 sprout.py run --vm examples/vm_expanded.sprout
python3 sprout.py bench examples/vm_expanded.sprout
python3 sprout.py debug examples/vm_expanded.sprout --break 21
python3 sprout.py profile examples/vm_expanded.sprout
```

`dis` prints readable instructions:

```text
0000 MAKE_FUNCTION square <code square>
0001 STORE_NAME square
0002 LOAD_CONST 1
0003 LOAD_CONST 2
0004 BUILD_ARRAY 2
```

The current VM supports:

- literals
- variables and assignment
- arithmetic and comparisons
- logical `and` / `or` / `not`
- arrays and dictionaries
- indexing
- property and index assignment
- function calls
- keyword arguments
- default arguments
- variadic arguments
- call-site `*args` / `**kwargs` spread
- `say`
- simple `if`
- simple `while`
- simple `for`
- `break` and `continue`
- function definitions and returns
- plain classes, instances, methods, and `self`
- simple inheritance method lookup
- Sprout imports
- Python imports and Python calls through the existing bridge
- `raise`
- `try` / `catch`

The VM now covers the current parser's core statement and expression forms, including `seedfn`, slices, slice assignment, inheritance, and `super`. Test declarations compile as no-ops during ordinary VM execution, just as they do during ordinary interpreter execution; `sprout.py test` remains responsible for discovering and running tests.

Every emitted instruction keeps source file, line, column, and code-object context. The disassembler prints source locations, breakpoints use those locations, and uncaught VM errors report both the failing function location and its call site.

The VM remains experimental. Imported Sprout module bodies compile through the
VM, but advanced Python/native-resource edge cases may still differ, and the VM
is not yet consistently faster than the tree-walk interpreter. `bench` reports
measured compile time, execution times, instruction count, support state, and
fallback state rather than claiming a speedup.

`bench` measures honestly. It reports tree-walk time, VM time, speed ratio, number of runs, and whether the VM supported the program. It does not claim the VM is always faster.

`debug` is the terminal debugger. It can stop at breakpoints for bytecode instructions that preserve source positions:

```sh
python3 sprout.py debug examples/vm_expanded.sprout --break 21
python3 sprout.py debug examples/vm_expanded.sprout --break examples/vm_expanded.sprout:21
```

At a stop, it prints the current instruction, source location, source line when known, value stack, and locals. In an interactive terminal, press Enter to step, `c` to continue, or `q` to stop.

The VS Code extension also bundles Sprout's Debug Adapter Protocol server. It provides:

- source-line breakpoints
- stop on entry
- continue and pause
- step in, step over, and step out
- Sprout call stacks
- local and global variable scopes
- variable inspection
- expression evaluation in the Debug Console
- program output in the VS Code Debug Console
- conditional breakpoints using Sprout expressions
- hit-count breakpoints
- uncaught-error breakpoints

To use it:

1. Open a `.sprout` program in VS Code.
2. Click beside a line number to add a breakpoint.
3. Press `F5`.
4. Choose `Debug current Sprout file` if VS Code asks for a configuration.

The terminal and VS Code debuggers currently use the experimental bytecode VM. Programs that contain VM-unsupported behavior should still be run with the stable interpreter.

When a `.sprout` file is active, the extension displays **Sprout: Auto** or
**Sprout: Selected** in the status bar. Click it, or run **Sprout: Select
Interpreter**, to choose the bundled interpreter, a workspace source checkout,
or a custom `sprout.py`. Custom interpreters are validated before use. Run
**Sprout: Run Current File** or click the editor-title play icon to execute the
saved file in an interactive terminal.

Right-click a breakpoint to add a condition or hit count. A hit count can be `3`, `>= 5`, or `% 2`. The **Uncaught Sprout errors** checkbox in the Breakpoints view pauses before an unhandled error terminates the program.

`profile` is a VM profiler foundation:

```sh
python3 sprout.py profile examples/vm_expanded.sprout
```

It reports compile time, run time, total time, VM instruction count, function call counts, and time spent in VM functions.

## 28. Editor Support

Sprout includes a local VS Code language package:

```text
editor/vscode-sprout
```

For normal user installation:

1. Install Sprout with `python3 -m pip install sprout-language`.
2. Open the VS Code Extensions view.
3. Search for **Sprout Language** by `jerry5678912` and install it.
4. Open a `.sprout` file.
5. Click **Sprout: Auto** to select an interpreter when needed.
6. Click the editor-title play icon or run **Sprout: Run Current File**.

It provides:

- `.sprout` file recognition
- syntax highlighting
- `#` line comments
- bracket and quote pairing
- basic indentation after `{`, `:`, and `bloom`
- native Test Explorer discovery and execution for Sprout `test` declarations
- safe lightbulb quick fixes for tab indentation and Python-style `True`, `False`, and `None`
- conditional breakpoints, hit counts, and uncaught-error stopping
- snippets for functions, classes, loops, errors, Python imports, and Sprout3D scenes
- semantic completions for local variables, functions, classes, methods, imports, module exports, Python module members, and project symbols when `sprout.py` is available
- static fallback completions for the full current keyword set, all built-ins, dot methods, bundled Sprout modules, Sprout2D APIs, Sprout3D APIs, PixelGarden, StarBloom3D, Window2D, and PandaWindow3D
- hover help with symbol type, signature, `##` documentation, and source location
- go-to definition, find references, rename symbol, and signature help foundations
- red syntax diagnostics powered by `sprout.py check`
- yellow style warnings for tabs and Python-style constants like `True` / `False` / `None`

Build and install the self-contained VSIX:

```sh
python3 sprout.py vscode-package
code --install-extension dist/sprout-language-0.3.2.vsix
```

The VSIX contains the Sprout runner and core, so semantic editor services work without a separate runner path.

For extension development:

```sh
cd editor/vscode-sprout
code .
```

Press `F5` to launch an Extension Development Host.

Completion examples:

- Type `def` for a function snippet.
- Type `defbloom` for a garden-style `bloom` / `end` function snippet.
- Type `defbraces` for an old-compatible brace function snippet.
- Type `defrest` for a variadic `*rest` function snippet.
- Type `defopts` for a keyword-rest `**opts` function snippet.
- Type keywords like `elif`, `each`, `whirl`, `try`, `catch`, `raise`, `sprout`, `pluck`, or `end` for syntax snippets/completions.
- Type built-ins like `sparkle`, `grow`, `json_parse`, `py_import`, `functions`, or `methods` for call snippets.
- Type `callspread` for a call using `*args` and `**opts`.
- Type `game.` after importing Gamekit as `game` for game helper completions.
- Type `g2d.` after importing Sprout2D as `g2d` for 2D geometry completions.
- Type `c2d.` after importing the Sprout2D canvas module as `c2d` for drawing completions.
- Type `s3d.` after importing Sprout3D as `s3d` for engine completions.
- Type `pix.` after importing PixelGarden as `pix` for fun terminal 2D completions.
- Type `star.` after importing StarBloom3D as `star` for fun terminal 3D completions.
- Type `w2d.` after importing Window2D as `w2d` for Pygame-backed window completions.
- Type `p3d.` after importing PandaWindow3D as `p3d` for Panda3D-backed completions.
- Type `player.` after `player = Player("Mina")` to complete fields and methods found from the `Player` class.
- Hover names like `clamp`, `spawn`, `Player`, or `render_solid` for signature and documentation help.
- Use VS Code's Go to Definition, Find References, Rename Symbol, and signature help commands for Sprout symbols when `sprout.py` is available.
- Syntax errors appear as red VS Code diagnostics. Style warnings appear as yellow diagnostics. Set `sprout.runnerPath` if the extension cannot find `sprout.py`, `sprout.pythonPath` if your Python executable is not `python3`, `sprout.diagnostics.enabled` to `false` to disable checking, or `sprout.diagnostics.styleWarnings` to `false` to hide yellow warnings.

## 29. Dogfooding Real Projects

Sprout includes real dogfood projects under `examples/dogfood`. Each one uses a normal `sprout.toml` project layout.

```sh
python3 sprout.py run examples/dogfood/cli_tool add docs:2 tests:3 release:5
python3 sprout.py run examples/dogfood/game2d
python3 sprout.py run examples/dogfood/math_utility
python3 sprout.py run examples/dogfood/python_interop
python3 sprout.py run examples/dogfood/package_app
```

The dogfood set covers:

- CLI argument parsing and command dispatch.
- 2D movement, collision, rendering, and score state.
- Engineering/math calculations.
- Python standard-library interop.
- Multi-file project and local package dependency resolution.

Run dogfood regression tests with:

```sh
python3 tests/dogfood.py
```

Notes and pain points from dogfooding live in `docs/DOGFOOD.md`.

## 30. Application Development Layer

### Testing

Sprout test files use named `test` declarations:

```sprout
def add(a, b):
  return a + b

test "addition":
  expect(add(2, 3)).to_equal(5)
```

Run tests with:

```sh
python3 sprout.py test
python3 sprout.py test tests/
python3 sprout.py test tests/application_test.sprout --verbose
```

The runner discovers `.sprout` files, runs setup declarations before test blocks, reports failures, prints a summary, and returns a non-zero exit code when tests fail.

Expectation methods:

```sprout
expect(value).to_equal(expected)
expect(value).not_to_equal(expected)
expect(value).to_be_true()
expect(value).to_be_false()
expect(value).to_contain(item)
```

### Tasks, Futures, and Queues

Sprout has structured async syntax:

```sprout
async def fetch(label, delay):
  sleep(delay)
  return "finished " + label

result = await fetch("first", 0.05)
say result

taskgroup jobs:
  jobs.spawn(fetch, "second", 0.05)
  jobs.spawn(fetch, "third", 0.05)
```

Calling an `async def` function returns a task immediately. `await` waits for that
task and returns its result or raises its error. `await` may be used at the top
level or inside a function.

A `taskgroup` creates a lexical structured-concurrency scope. Tasks started with
`group.spawn(function, arguments...)` belong to that scope. Sprout waits for all
of them before leaving the block. If one task fails, the group requests
cancellation of its siblings and propagates the failure. Groups also expose
`wait()`, `cancel()`, `settle()`, and `count`.

The older explicit task helpers remain available:

```sprout
def work(value):
  return value * value

task = task_spawn(work, [5])
say task.done
say task.result()

later = task_after(0.1, work, [6])
say task_wait_all([task, later])

messages = queue_open()
messages.send("ready")
say messages.receive()
```

Tasks use a scheduler with future-like results and delayed execution. Sprout
function execution is currently serialized through a runtime lock so interpreter
state remains correct. This provides concurrency for waiting and orchestration,
not CPU-parallel Sprout execution.

Structured async functions, `await`, task groups, streams, and `async for`
execute directly in the VM. Unsupported edge cases still produce an explicit
experimental-VM diagnostic rather than silently changing behavior.

### HTTP

HTTP client:

```sprout
response = http_get("https://example.com")
say response.status
say response.ok
say response.text
```

JSON responses:

```sprout
data = response.json()
```

Request helpers:

```sprout
http_get(url, headers=nil, timeout=10)
http_post(url, data=nil, headers=nil, timeout=10)
http_request(method, url, data=nil, headers=nil, timeout=10)
```

Small route-based local server:

```sprout
server = http_server({
  "/": "hello",
  "/health": {"body": {"ok": true}}
})
server.start()
say server.url
server.stop()
```

### SQLite

```sprout
db = sqlite_open("app.db")
sqlite_exec(db, "create table if not exists notes (text)")
sqlite_exec(db, "insert into notes values (?)", ["hello"])
rows = sqlite_query(db, "select * from notes")
say rows
sqlite_close(db)
```

Transactions:

```sprout
sqlite_begin(db)
sqlite_exec(db, "insert into notes values (?)", ["draft"])
sqlite_commit(db)
# sqlite_rollback(db) is also available.
```

Rows are returned as Sprout dictionaries.

### Engineering

Native engineering helpers:

```sprout
vec_add(a, b)
vec_sub(a, b)
vec_dot(a, b)
vec_magnitude(vector)
vec_normalize(vector)
mat_mul(a, b)
unit_convert(value, source, target)
interpolate(a, b, t)
kinetic_energy(mass, speed)
force(mass, acceleration)
pressure(force, area)
```

The higher-level module is `examples/modules/engineering.sprout`.

### Game Application Structure

`examples/modules/appgame.sprout` provides game state, entities, scenes, normalized input state, rectangle collision, timers, text/JSON asset loading, and a deterministic fixed-step loop.

This module complements PixelGarden, StarBloom3D, Window2D, and PandaWindow3D rather than replacing them.

### Documentation Generation

Write `##` comments immediately above functions or classes:

```sprout
## Creates a player with optional hit points.
def player(name, hp=10):
  return {"name": name, "hp": hp}
```

Generate project documentation:

```sh
python3 sprout.py docs .
python3 sprout.py docs . --html
```

Output is written to `docs/API.md` and optionally `docs/API.html`.

Standard-library groups can be inspected with:

```sh
python3 sprout.py stdlib --groups
```

Application examples live under `examples/application`.

## 31. Build, Distribution, And Package Registry

Sprout projects can now produce deterministic build images and portable package bundles:

```sh
python3 sprout.py build
python3 sprout.py build --vm
python3 sprout.py build project/
python3 sprout.py package
python3 sprout.py package project/
```

Builds validate project metadata, source, and dependencies; write `sprout.lock`; copy configured source, module, documentation, and asset folders; materialize dependencies; and generate a hash-based `build-manifest.json`. VM builds also include readable experimental bytecode for the main file.

Packages use semantic versions and constraints:

```toml
[package]
name = "physics_tools"
version = "1.2.0"
description = "Engineering helpers"
author = "Ada Example"
license = "Apache-2.0"

[dependencies]
vectors = "^2.0.0"
geometry = { path = "../geometry", version = "~1.4.0" }
```

Supported constraints include exact versions, `*`, `latest`, `^`, `~`, comparisons, and comma-separated ranges. Resolution is deterministic, dependency conflicts are errors, and exact results are stored in `sprout.lock`.

Use `SPROUT_REGISTRY` or `--registry PATH` to select a registry:

```sh
python3 sprout.py pkg search physics
python3 sprout.py pkg install physics_tools@^1.0.0
python3 sprout.py pkg update
python3 sprout.py pkg tree
python3 sprout.py pkg docs physics_tools
python3 sprout.py pkg publish
```

The registry is a lightweight JSON index with immutable, versioned `.sproutpkg` bundles. Registry metadata includes SHA-256 checksums and installs verify bundle integrity. Registries may be local or hosted.

Create a package-scoped token and run a hosted service:

```sh
python3 sprout.py registry token publisher --root ./registry --packages physics_tools
python3 sprout.py registry serve --root ./registry --host 127.0.0.1 --port 8787
```

Set `SPROUT_REGISTRY_TOKEN` or pass `--token` when publishing to HTTP/HTTPS. Raw tokens are printed once and only their SHA-256 digests are stored. Tokens can be listed and revoked:

```sh
python3 sprout.py registry token list --root ./registry
python3 sprout.py registry token revoke publisher --root ./registry
```

Hosted publishing enforces package permissions, immutable versions, archive path and symlink safety, upload and expansion limits, package identity, and bundle/per-file checksums. Public deployments should put the built-in service behind an HTTPS reverse proxy.

Publishing validates metadata, source, dependencies, tests, and documentation. `release` performs the same quality checks, generates API documentation, creates a bundle, and writes `dist/release.json`:

```sh
python3 sprout.py release
python3 sprout.py release --publish --registry ./registry
```

Aliases are available through `search`, `info`, and `list-installed`. Full ecosystem details are in `docs/ECOSYSTEM.md`.

Standalone application distribution embeds the Sprout runtime, resolved dependencies, project files, and assets:

```sh
python3 sprout.py app build .
python3 sprout.py app verify dist/my_app-0.1.0-standalone
python3 sprout.py app run dist/my_app-0.1.0-standalone -- argument
python3 sprout.py app package .
```

The generated directory includes Unix and Windows launchers plus an exact SHA-256 integrity manifest. The deterministic `.sproutapp` archive can be extracted on another machine and run without installing Sprout. Python 3.9 or newer remains the host runtime for this distribution generation.

## 32. Installing And Releasing Sprout

Install the public package from PyPI:

```sh
python3 -m pip install sprout-language
sprout version
```

The release page is:

```text
https://pypi.org/project/sprout-language/
```

For an isolated command installation, use:

```sh
pipx install sprout-language
```

Install Sprout from a checkout or extracted source release for development:

```sh
python3 -m pip install .
sprout version

# Or use the standalone source-release installer:
python3 install.py
python3 install.py --prefix /custom/prefix
python3 install.py --force
```

The installer copies the runtime and supporting files under the prefix and creates a `sprout` launcher under its `bin` directory. The equivalent CLI commands are:

```sh
python3 sprout.py install
python3 sprout.py install --prefix /custom/prefix
python3 sprout.py uninstall --prefix /custom/prefix
```

Create language release artifacts:

```sh
python3 sprout.py language-package
python3 sprout.py vscode-package
```

The first command creates a source/runtime ZIP. The second creates a self-contained VSIX with the Sprout runner included. CI validates Python 3.9 and 3.12 on Linux, macOS, and Windows. Tags such as `v0.3.2` must match the runtime version before the release workflow publishes artifacts.

The capability baseline used to plan this work is recorded in `docs/CAPABILITY_AUDIT.md`.

## 33. Conformance, Fuzzing, and Security

The checked-in conformance corpus is a stable language behavior contract:

```sh
python3 sprout.py conformance
python3 sprout.py conformance --json
```

Cases live under `sprout_core/conformance/` and declare expected output, exit status,
diagnostic fragments, and whether interpreter/VM parity is required.

The deterministic fuzzer generates both valid and malformed programs:

```sh
python3 sprout.py fuzz
python3 sprout.py fuzz --iterations 500 --seed 20260606
python3 sprout.py fuzz --iterations 100 --seed 42 --json
```

Valid generated programs must produce the same exit status and output in the
stable interpreter and experimental VM. Malformed inputs may produce Sprout
diagnostics, but may not crash the lexer/parser with internal exceptions. The
reported seed makes every run reproducible.

Security regression tests are separate from ordinary behavior tests:

```sh
python3 tests/security.py
```

They cover hostile source input, raw Python traceback leakage, package path
traversal, symbolic links, file-count and expanded-size limits, and forged
manifest hashes. Package downloads are capped at 64 MiB, and extracted package
archives are capped at 10,000 files and 256 MiB expanded size.

## 34. Optional Typed Abstractions

Sprout's normal execution remains dynamic. Optional annotations add static
checks without changing runtime values:

```sprout
interface Greeter:
  def greet(self, name: String) -> String

class FriendlyGreeter implements Greeter:
  def greet(self, name: String) -> String:
    return "hello " + name

class Box[T]:
  def init(self, value: T):
    self.value = value

  def get(self) -> T:
    return self.value

def identity[T](value: T) -> T:
  return value

let answer: Int = identity(42)
```

Check a file or project:

```sh
python3 sprout.py typecheck file.sprout
python3 sprout.py typecheck . --json
```

Supported forms include typed variables, parameters and returns, generic
functions/classes, interface method signatures, and `implements` declarations.
Built-in types are `Any`, `Nil`, `Bool`, `Int`, `Float`, `Number`, `String`,
`List[T]`, `Array[T]`, `Dict[K, V]`, `Task[T]`, and `Generator[T]`. User
classes, interfaces, enums, and qualified imported types are also valid types.

The checker reports unknown types, wrong generic arity, incompatible annotated
assignments, argument and return mismatches, and missing or incompatible
interface methods. VS Code/LSP diagnostics include these errors. Typed syntax is
runtime-erased and works in both execution engines.

Union types use `|`, nullable shorthand uses `?`, and aliases may be generic:

```sprout
type Identifier = Int | String
type Maybe[T] = T | Nil

let id: Identifier = "user-4"
let label: String? = nil
```

The checker follows Sprout imports, validates imported function calls and
qualified types, narrows unions after `value is Type`, and checks typed enum
matches for missing variants and duplicate cases. This remains gradual:
unannotated or unresolved values become `Any`. Overloads, protocols beyond
interfaces, and whole-program type inference are not implemented.

## 35. Enums, Matching, Generators, and Comprehensions

### Enums

Enums define a closed family of variants. Variants may carry typed fields:

```sprout
enum Result[T]:
  Ok(value: T)
  Error(message: String)

answer = Result.Ok(42)
failure = Result.Error("offline")
```

Payload-free variants do not require parentheses:

```sprout
enum State:
  Ready
  Running
  Stopped

state = State.Ready
```

Enum values are immutable. Their fields are readable by name, and the enum and
variant names appear in hover, completion, symbols, and navigation.

### Match and Case

`match` evaluates one value and selects the first matching case:

```sprout
match answer:
  case Result.Ok(value) if value > 0:
    say "positive", value
  case Result.Ok(_):
    say "zero or negative"
  case Result.Error(message):
    say "error", message
```

Patterns include:

- Enum variants: `Result.Ok(value)` and `State.Ready`
- Bindings: `case value:`
- Wildcards: `case _:`
- Literals: `case 0:` or `case "quit":`
- Arrays: `case [first, second]:`
- Array rest: `case [head, *tail]:`
- Guards: `case pattern if condition:`

When the checker knows the matched enum type, every variant must be covered
unless a wildcard or general binding case is present.

### Generators

Any function containing `yield` is a lazy generator:

```sprout
def count_to(limit: Int) -> Generator[Int]:
  for value in range(limit):
    yield value

numbers = count_to(3)
say numbers.next()
say numbers.collect()
```

`.next()` resumes until the next yielded value. `.collect()` consumes the
remaining values into an array. Generators preserve local state across pauses
and may yield inside conditions, loops, `try` / `catch`, and match cases.

### Comprehensions

List and dictionary comprehensions create collections from iterables:

```sprout
squares = [value * value for value in range(6)]
even_squares = [value * value for value in range(8) if value % 2 == 0]
lookup = {str(value): value + 1 for value in range(3)}
```

The loop variable belongs to the comprehension scope.

### Async Streams and I/O

`stream_open()` creates an asynchronous stream with `.send(value)` and
`.close()`. Consume it with `async for`:

```sprout
async def publish(stream):
  for value in ["seed", "leaf", "bloom"]:
    await sleep_async(0.01)
    stream.send(value)
  stream.close()

stream = stream_open()
publisher = publish(stream)
async for value in stream:
  say value
await publisher
```

Application helpers include:

- `cancel_token()` with `.cancel()` and `.cancelled`
- `sleep_async(seconds, token=nil)`
- `http_request_async(...)`, `http_get_async(...)`, and `http_post_async(...)`
- `readfile_async(path)` and `writefile_async(path, text)`
- `queue.receive_async()` for message queues

Cancellation is cooperative. It prevents or interrupts operations at supported
checkpoints; it cannot forcibly stop an arbitrary Python call already executing.

## 36. Current Limitations

Sprout is usable for scripts, examples, terminal games, multi-file projects, and Python library experiments, but it is still young.

Known limitations:

- Files support Python-style indentation blocks and garden-style `bloom` / `end` blocks. Brace blocks still work for older Sprout code.
- Inheritance, `super`, and structural interfaces exist, but there are no access modifiers.
- Uncaught runtime errors include Sprout function/method stack traces with source file, line, and column locations for call sites and function definitions.
- Sprout-defined functions support `*rest` positional arguments, `**options` keyword-rest arguments, and call-site `*args` / `**opts` spreading.
- Built-in Sprout functions generally reject keyword arguments unless documented.
- Hosted registries and authenticated publishing exist, but package signatures and a public trust service do not yet exist.
- The optional checker is gradual and project-aware, but it does not yet support
  overloads, protocol composition, or complete whole-program inference.
- The bytecode VM exists, but it is experimental and not feature-complete. There is no native-code compiler or JIT.
- The dedicated test runner controls test declarations independently of normal
  program execution.
- Async I/O uses a bounded host thread pool. It is useful for application I/O,
  but it is not a CPU-parallel runtime.
- The HTTP server is intentionally small and route-based. It is not yet a production web framework.
- PixelGarden and StarBloom3D are terminal software engines.
- Window2D and PandaWindow3D are thin wrappers and require external Python packages.
- Python interop depends on the Python runtime executing `sprout.py`.

## 37. Accuracy Notes

This manual describes the current `sprout.py` implementation in this project. It is not a promise of future compatibility. If behavior changes, update this manual, examples, tests, and VS Code grammar together.

The smoke test suite is:

```sh
tests/smoke.sh
```

The interpreter compile check is:

```sh
PYTHONPYCACHEPREFIX=/tmp/sprout-pycache python3 -m py_compile sprout.py
```

The editor grammar JSON check is:

```sh
python3 -m json.tool editor/vscode-sprout/syntaxes/sprout.tmLanguage.json
```
