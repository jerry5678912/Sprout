const vscode = require("vscode");
const childProcess = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { SproutLanguageClient } = require("./lsp-client");
const { createSproutTestController } = require("./test-controller");
const {
  computeSproutFoldingRanges,
  computeSproutFoldingRangesFromLines,
} = require("./folding");

let languageClient;
let interpreterStatus;
let lspOutputChannel;

const DIAGNOSTIC_DEBOUNCE_MS = 220;
const DIAGNOSTIC_CLEAR_DEBOUNCE_MS = 120;
const LSP_HEARTBEAT_MS = 2500;
const IMPORT_COMPLETION_CACHE_MS = 10_000;
const IMPORT_PATH_COMPLETION_CACHE_MS = 1500;
const IMPORT_ALIAS_DEFAULT_KIND = "sprout";
const importedModuleSymbolCache = new Map();
const importPathCandidateCache = new Map();
const installedRunnerCache = new Map();

function findDebugAdapter(context, runner) {
  const candidates = [
    path.join(context.extensionPath, "tools", "sprout_dap.py"),
    runner ? path.join(path.dirname(runner), "tools", "sprout_dap.py") : ""
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate));
}

function whitespaceOnlyWithIndent(text) {
  return typeof text === "string" && text.trim() === "" && /^[ \t]+$/.test(text);
}

function sproutIndentLog(message) {
  if (!lspOutputChannel) return;
  lspOutputChannel.appendLine(`[${new Date().toISOString()}] [Sprout Indent] ${message}`);
}

function previousNonEmptyLine(document, lineNumber) {
  for (let line = lineNumber - 1; line >= 0; line -= 1) {
    const text = document.lineAt(line).text;
    if (text.trim() !== "") return { line, text };
  }
  return null;
}

function sproutIndentUnit(editor) {
  const size = Number(editor?.options?.tabSize) || 2;
  const useSpaces = editor?.options?.insertSpaces !== false;
  return useSpaces ? " ".repeat(Math.max(1, size)) : "\t";
}

function leadingWhitespace(text) {
  return String(text || "").match(/^\s*/)?.[0] || "";
}

function opensSproutBlock(text) {
  return /^.*(\{|:|\bbloom)\s*$/.test(String(text || "").trimEnd());
}

async function handleSproutSmartEnter() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "sprout") return false;
  if (editor.selections.length !== 1 || !editor.selection.isEmpty) return false;
  const position = editor.selection.active;
  const line = editor.document.lineAt(position.line);
  const beforeCursor = line.text.slice(0, position.character);
  const currentIndent = leadingWhitespace(line.text);
  const indentUnit = sproutIndentUnit(editor);
  let insertText = "\n";
  let targetColumn = 0;
  const blankLine = line.text.trim() === "";
  const blankPrefix = beforeCursor.trim() === "";
  const previous = previousNonEmptyLine(editor.document, position.line);
  const previousIndent = previous ? leadingWhitespace(previous.text).length : 0;

  if (blankLine && blankPrefix && previousIndent > 0) {
    sproutIndentLog(`Smart enter escaping blank line ${position.line + 1}; cursor=${position.character + 1}; line=${JSON.stringify(line.text)} prevNonEmpty=${JSON.stringify(previous.text)}`);
    const edited = await editor.edit((editBuilder) => {
      editBuilder.replace(new vscode.Range(position.line, 0, position.line, line.text.length), "\n");
    }, { undoStopBefore: true, undoStopAfter: true });
    if (!edited) {
      sproutIndentLog("Smart enter failed to escape blank line");
      return true;
    }
    const target = new vscode.Position(position.line + 1, 0);
    editor.selection = new vscode.Selection(target, target);
    editor.revealRange(new vscode.Range(target, target));
    return true;
  }

  if (opensSproutBlock(beforeCursor)) {
    insertText += currentIndent + indentUnit;
    targetColumn = (currentIndent + indentUnit).length;
  } else {
    insertText += currentIndent;
    targetColumn = currentIndent.length;
  }

  sproutIndentLog(`Smart enter inserting at line ${position.line + 1}, col ${position.character + 1}; before=${JSON.stringify(beforeCursor)} nextIndent=${JSON.stringify(insertText.slice(1))}`);
  const edited = await editor.edit((editBuilder) => {
    editBuilder.insert(position, insertText);
  }, { undoStopBefore: true, undoStopAfter: true });
  if (!edited) {
    sproutIndentLog("Smart enter insertion failed");
    return true;
  }
  const target = new vscode.Position(position.line + 1, targetColumn);
  editor.selection = new vscode.Selection(target, target);
  editor.revealRange(new vscode.Range(target, target));
  return true;
}

const semanticTokenTypes = [
  "class",
  "function",
  "method",
  "variable",
  "parameter",
  "property",
  "number",
  "string",
  "keyword"
];

const semanticLegend = new vscode.SemanticTokensLegend(semanticTokenTypes, []);

const entries = [
  ["say", "Print values to the terminal.", "say ${1:value}"],
  ["argv", "Array of command-line arguments passed to the current Sprout script.", "argv"],
  ["def", "Define a Sprout function.", "def ${1:name}(${2:args}):\n  ${3}"],
  ["defrest", "Define a Sprout function with a *rest parameter.", "def ${1:name}(${2:label}, *${3:values}):\n  ${4}"],
  ["defopts", "Define a Sprout function with a **options parameter.", "def ${1:name}(${2:kind}, **${3:opts}):\n  ${4}"],
  ["defbloom", "Define a garden-style Sprout function.", "def ${1:name}(${2:args}) bloom\n  ${3}\nend"],
  ["defbraces", "Define a legacy brace-style Sprout function.", "def ${1:name}(${2:args}) {\n  ${3}\n}"],
  ["callspread", "Call a function with *args and **opts spread values.", "${1:fn}(*${2:args}, **${3:opts})"],
  ["class", "Define a Sprout class.", "class ${1:Name}:\n  def init(self${2:, value}):\n    ${3}"],
  ["enum", "Define a tagged enum.", "enum ${1:Result}[${2:T}]:\n  ${3:Ok}(value: ${2:T})\n  ${4:Error}(message: String)"],
  ["match", "Match values and destructure enum variants.", "match ${1:value}:\n  case ${2:Result.Ok}(${3:item}):\n    ${4}"],
  ["interface", "Define a structural interface.", "interface ${1:Named}:\n  def ${2:name}(self) -> ${3:String}"],
  ["implements", "Declare that a class satisfies an interface.", "class ${1:Thing} implements ${2:Named}:\n  ${3}"],
  ["if", "Run a block when a condition is truthy.", "if ${1:condition}:\n  ${2}"],
  ["else", "Fallback branch for if.", "else:\n  ${1}"],
  ["while", "Loop while a condition is truthy.", "while ${1:condition}:\n  ${2}"],
  ["for", "Loop over arrays, strings, ranges, or dictionary keys.", "for ${1:item} in ${2:items}:\n  ${3}"],
  ["try", "Catch Sprout errors and raised values.", "try:\n  ${1}\ncatch ${2:err}:\n  ${3:say err}"],
  ["test", "Define a Sprout test case.", "test \"${1:name}\":\n  expect(${2:actual}).to_equal(${3:expected})"],
  ["import", "Import a Sprout standard-library or project module.", "import ${1:pixelgarden} as ${2:pix}"],
  ["importpython", "Import a Python standard-library module.", "importpython ${1:math}"],
  ["super", "Call a parent class method from a subclass.", "super.${1:method}(${2})"],
  ["return", "Return a value from a function.", "return ${1:value}"],
  ["pluck", "Sprout-flavored return.", "pluck ${1:value}"],
  ["end", "End a garden-style bloom block."],
  ["True", "Boolean true."],
  ["false", "Boolean false."],
  ["nil", "No value."],
  ["len", "Return the length of an array, string, or dictionary.", "len(${1:value})"],
  ["range", "Create an array of numbers from 0 to n - 1.", "range(${1:n})"],
  ["str", "Convert a value to Sprout text.", "str(${1:value})"],
  ["int", "Convert a value to an integer.", "int(${1:value})"],
  ["num", "Convert a value to a number.", "num(${1:value})"],
  ["type", "Return a readable Sprout type name.", "type(${1:value})"],
  ["keys", "Return dictionary keys.", "keys(${1:dict})"],
  ["values", "Return dictionary values.", "values(${1:dict})"],
  ["items", "Return dictionary key/value pairs.", "items(${1:dict})"],
  ["has", "Check whether a dictionary has a key.", "has(${1:dict}, ${2:key})"],
  ["get", "Read a dictionary key with an optional default.", "get(${1:dict}, ${2:key}, ${3:nil})"],
  ["readfile", "Read a UTF-8 text file.", "readfile(${1:path})"],
  ["writefile", "Write a UTF-8 text file.", "writefile(${1:path}, ${2:text})"],
  ["appendfile", "Append UTF-8 text to a file.", "appendfile(${1:path}, ${2:text})"],
  ["exists", "Check whether a path exists.", "exists(${1:path})"],
  ["isfile", "Check whether a path is a file.", "isfile(${1:path})"],
  ["isdir", "Check whether a path is a directory.", "isdir(${1:path})"],
  ["listdir", "List a directory in sorted order.", "listdir(${1:path})"],
  ["mkdir", "Create a directory and missing parent directories.", "mkdir(${1:path})"],
  ["readjson", "Read a JSON file into Sprout values.", "readjson(${1:path})"],
  ["writejson", "Write Sprout values as a JSON file.", "writejson(${1:path}, ${2:value})"],
  ["py_available", "Check whether a Python module can be imported.", "py_available(${1:module_name})"],
  ["py_import", "Import a Python module by string.", "py_import(${1:module_name})"],
  ["lines", "Split text into lines.", "lines(${1:text})"],
  ["ask", "Prompt the user for terminal input.", "ask(${1:prompt})"],
  ["ensure", "Raise an error if a condition is false.", "ensure(${1:condition}, ${2:message})"],
  ["fail", "Raise a Sprout error.", "fail(${1:message})"],
  ["functions", "List callable global functions.", "functions()"],
  ["methods", "List built-in dot methods.", "methods()"],
  ["choose", "Choose a random item from an array.", "choose(${1:items})"],
  ["clamp", "Clamp a number to a range.", "clamp(${1:value}, ${2:min}, ${3:max})"],
  ["wrap", "Wrap an integer into an inclusive range.", "wrap(${1:value}, ${2:min}, ${3:max})"],
  ["dist", "2D distance helper.", "dist(${1:x1}, ${2:y1}, ${3:x2}, ${4:y2})"],
  ["grow", "Append a value to an array and return the array.", "grow(${1:array}, ${2:value})"],
  ["plant", "Set a dictionary key and return the dictionary.", "plant(${1:dict}, ${2:key}, ${3:value})"],
  ["harvest", "Pop and return the last array item, or nil if empty.", "harvest(${1:array})"],
  ["prune", "Remove every matching value from an array.", "prune(${1:array}, ${2:value})"],
  ["sprinkle", "Return an array with a separator between items.", "sprinkle(${1:array}, ${2:separator})"],
  ["bundle", "Zip two arrays into key/value pair arrays.", "bundle(${1:keys}, ${2:values})"],
  ["radians", "Convert degrees to radians.", "radians(${1:degrees})"],
  ["degrees", "Convert radians to degrees.", "degrees(${1:radians})"],
  ["sqrt", "Square root.", "sqrt(${1:value})"],
  ["sin", "Sine.", "sin(${1:radians})"],
  ["cos", "Cosine.", "cos(${1:radians})"],
  ["json_parse", "Parse JSON text into Sprout values.", "json_parse(${1:text})"],
  ["json_stringify", "Convert Sprout values to JSON text.", "json_stringify(${1:value})"]
  ,["expect", "Create a fluent test expectation.", "expect(${1:value}).to_equal(${2:expected})"]
  ,["task_spawn", "Run a callable as a scheduled task.", "task_spawn(${1:function}, ${2:args})"]
  ,["task_after", "Run a callable after a delay.", "task_after(${1:seconds}, ${2:function}, ${3:args})"]
  ,["task_wait_all", "Wait for task futures and return their results.", "task_wait_all(${1:tasks})"]
  ,["queue_open", "Create a message queue.", "queue_open()"]
  ,["stream_open", "Create an asynchronous stream.", "stream_open()"]
  ,["cancel_token", "Create a cooperative cancellation token.", "cancel_token()"]
  ,["sleep_async", "Create a non-blocking timer task.", "sleep_async(${1:seconds})"]
  ,["readfile_async", "Read a file on a scheduled task.", "readfile_async(${1:path})"]
  ,["writefile_async", "Write a file on a scheduled task.", "writefile_async(${1:path}, ${2:text})"]
  ,["http_get", "Perform an HTTP GET request.", "http_get(${1:url})"]
  ,["http_post", "Perform an HTTP POST request.", "http_post(${1:url}, ${2:data})"]
  ,["http_request", "Perform a configurable HTTP request.", "http_request(${1:method}, ${2:url})"]
  ,["http_get_async", "Perform an HTTP GET request asynchronously.", "http_get_async(${1:url})"]
  ,["http_post_async", "Perform an HTTP POST request asynchronously.", "http_post_async(${1:url}, ${2:data})"]
  ,["http_request_async", "Perform a configurable HTTP request asynchronously.", "http_request_async(${1:method}, ${2:url})"]
  ,["http_server", "Create a small route-based HTTP server.", "http_server(${1:routes})"]
  ,["sqlite_open", "Open a SQLite database.", "sqlite_open(${1:path})"]
  ,["sqlite_exec", "Execute a SQLite statement.", "sqlite_exec(${1:db}, ${2:sql}, ${3:params})"]
  ,["sqlite_query", "Query SQLite rows as dictionaries.", "sqlite_query(${1:db}, ${2:sql}, ${3:params})"]
  ,["sqlite_begin", "Begin a SQLite transaction.", "sqlite_begin(${1:db})"]
  ,["sqlite_commit", "Commit a SQLite transaction.", "sqlite_commit(${1:db})"]
  ,["sqlite_rollback", "Roll back a SQLite transaction.", "sqlite_rollback(${1:db})"]
  ,["sqlite_close", "Close a SQLite database.", "sqlite_close(${1:db})"]
  ,["vec_add", "Add numeric vectors.", "vec_add(${1:a}, ${2:b})"]
  ,["vec_sub", "Subtract numeric vectors.", "vec_sub(${1:a}, ${2:b})"]
  ,["vec_dot", "Calculate a vector dot product.", "vec_dot(${1:a}, ${2:b})"]
  ,["vec_magnitude", "Calculate vector magnitude.", "vec_magnitude(${1:value})"]
  ,["vec_normalize", "Normalize a vector.", "vec_normalize(${1:value})"]
  ,["mat_mul", "Multiply matrices.", "mat_mul(${1:a}, ${2:b})"]
  ,["unit_convert", "Convert supported engineering units.", "unit_convert(${1:value}, ${2:source}, ${3:target})"]
  ,["interpolate", "Linearly interpolate numbers.", "interpolate(${1:a}, ${2:b}, ${3:t})"]
  ,["kinetic_energy", "Calculate kinetic energy.", "kinetic_energy(${1:mass}, ${2:speed})"]
  ,["force", "Calculate force.", "force(${1:mass}, ${2:acceleration})"]
  ,["pressure", "Calculate pressure.", "pressure(${1:force}, ${2:area})"]
];

const keywordEntries = [
  ["async", "Define an asynchronous Sprout function.", "async def ${1:name}(${2:args}):\n  ${3}"],
  ["await", "Wait for an asynchronous Sprout task and return its value.", "await ${1:task}"],
  ["taskgroup", "Run child tasks in a structured scope that waits before exit.", "taskgroup ${1:tasks}:\n  ${1:tasks}.spawn(${2:function}${3:, arg})"],
  ["enum", "Define immutable tagged variants.", "enum ${1:Result}[${2:T}]:\n  Ok(value: ${2:T})\n  Error(message: String)"],
  ["match", "Pattern match a value.", "match ${1:value}:\n  case ${2:Result.Ok}(${3:item}):\n    ${4}\n  case _:\n    ${5}"],
  ["case", "Add a pattern branch.", "case ${1:pattern}:\n  ${2}"],
  ["yield", "Yield the next value from a lazy generator.", "yield ${1:value}"],
  ["is", "Test and narrow a runtime type.", "is ${1:Type}"],
  ["def", "Define a Python-style Sprout function.", "def ${1:name}(${2:args}):\n  ${3}"],
  ["fn", "Define a Sprout function.", "fn ${1:name}(${2:args}):\n  ${3}"],
  ["bloom", "Define a garden-flavored function or open a garden block.", "bloom ${1:name}(${2:args}):\n  ${3}"],
  ["seedfn", "Create a tiny inline Sprout function.", "seedfn ${1:x}: ${2:x}"],
  ["defbloom", "Define a garden-style Sprout function.", "def ${1:name}(${2:args}) bloom\n  ${3}\nend"],
  ["defbraces", "Define an old-compatible brace-style function.", "def ${1:name}(${2:args}) {\n  ${3}\n}"],
  ["class", "Define a Sprout class.", "class ${1:Name}:\n  def init(self${2:, value}):\n    ${3}"],
  ["interface", "Define a structural interface.", "interface ${1:Named}:\n  def ${2:name}(self) -> ${3:String}"],
  ["implements", "Declare that a class satisfies an interface.", "class ${1:Thing} implements ${2:Named}:\n  ${3}"],
  ["extends", "Define a class that inherits from another class.", "class ${1:Child} extends ${2:Parent}:\n  def init(self${3:, value}):\n    super.init(${4:value})\n    ${5}"],
  ["if", "Run a block when a condition is truthy.", "if ${1:condition}:\n  ${2}"],
  ["elif", "Add another conditional branch.", "elif ${1:condition}:\n  ${2}"],
  ["else", "Fallback branch for if.", "else:\n  ${1}"],
  ["while", "Loop while a condition is truthy.", "while ${1:condition}:\n  ${2}"],
  ["whirl", "Garden-flavored while loop.", "whirl ${1:condition}:\n  ${2}"],
  ["for", "Loop over arrays, strings, ranges, or dictionary keys.", "for ${1:item} in ${2:items}:\n  ${3}"],
  ["async for", "Consume an asynchronous stream.", "async for ${1:item} in ${2:stream}:\n  ${3}"],
  ["each", "Garden-flavored for loop.", "each ${1:item} in ${2:items} bloom\n  ${3}\nend"],
  ["try", "Catch Sprout errors and raised values.", "try:\n  ${1}\ncatch ${2:err}:\n  ${3:say err}"],
  ["test", "Define a Sprout test case.", "test \"${1:name}\":\n  expect(${2:actual}).to_equal(${3:expected})"],
  ["catch", "Handle a Sprout try block error.", "catch ${1:err}:\n  ${2}"],
  ["raise", "Raise a value as a recoverable Sprout error.", "raise ${1:value}"],
  ["return", "Return a value from a function.", "return ${1:value}"],
  ["pluck", "Garden-flavored return.", "pluck ${1:value}"],
  ["break", "Exit the nearest loop.", "break"],
  ["continue", "Skip to the next loop iteration.", "continue"],
  ["import", "Import a Sprout standard-library or project module.", "import ${1:pixelgarden} as ${2:pix}"],
  ["importpython", "Import a Python module through Sprout's Python bridge.", "importpython ${1:math}"],
  ["as", "Give an import an alias.", "as ${1:alias}"],
  ["let", "Declare a variable.", "let ${1:name} = ${2:value}"],
  ["sprout", "Garden-flavored variable declaration.", "sprout ${1:name} = ${2:value}"],
  ["super", "Call a parent class method from a subclass.", "super.${1:method}(${2})"],
  ["and", "Boolean and operator.", "and"],
  ["or", "Boolean or operator.", "or"],
  ["not", "Boolean not operator.", "not ${1:value}"],
  ["in", "Membership operator.", "in ${1:values}"],
  ["end", "End a garden-style bloom block.", "end"],
  ["True", "Boolean true.", "True"],
  ["false", "Boolean false.", "false"],
  ["nil", "No value.", "nil"],
  ["none", "No value alias.", "none"]
];

const methodEntries = [
  ["append", "Append an item to an array.", "append(${1:value})"],
  ["pop", "Remove and return the last array item.", "pop()"],
  ["len", "Return the array length.", "len()"],
  ["join", "Join array values with a separator.", "join(${1:separator})"],
  ["keys", "Return dictionary keys.", "keys()"],
  ["values", "Return dictionary values.", "values()"],
  ["items", "Return dictionary key/value pairs.", "items()"],
  ["get", "Read a dictionary key with an optional default.", "get(${1:key}, ${2:nil})"],
  ["has", "Check whether a dictionary has a key.", "has(${1:key})"],
  ["set", "Set a dictionary key.", "set(${1:key}, ${2:value})"],
  ["split", "Split a string by a separator.", "split(${1:separator})"],
  ["contains", "Check whether a string contains text.", "contains(${1:needle})"],
  ["upper", "Uppercase a string.", "upper()"],
  ["lower", "Lowercase a string.", "lower()"],
  ["strip", "Trim a string.", "strip()"]
];

const engineEntries = [
  ["vec3", "Create a 3D vector.", "vec3(${1:x}, ${2:y}, ${3:z})"],
  ["cube", "Create a cube mesh.", "cube(size=${1:2})"],
  ["mesh", "Create a mesh dictionary.", "mesh(${1:vertices}, ${2:edges}, ${3:faces})"],
  ["load_obj", "Load a Wavefront OBJ file.", "load_obj(${1:path})"],
  ["translate_mesh", "Move a mesh by a vector.", "translate_mesh(${1:mesh}, ${2:offset})"],
  ["rotate_mesh", "Rotate a mesh around x/y/z axes.", "rotate_mesh(${1:mesh}, ax=${2:0}, ay=${3:0}, az=${4:0})"],
  ["look_at_camera", "Create an oriented camera aimed at a target.", "look_at_camera(${1:position}, ${2:target}, fov=${3:24})"],
  ["orbit_camera", "Create an orbit/debug camera.", "orbit_camera(${1:target}, radius=${2:8}, yaw=${3:0}, pitch=${4:0})"],
  ["render_wireframe", "Render mesh edges into an ASCII frame.", "render_wireframe(${1:mesh}, ${2:camera}, width=${3:56}, height=${4:24}, char=${5:\"#\"})"],
  ["render_solid", "Render filled shaded triangles with a z-buffer.", "render_solid(${1:mesh}, ${2:camera}, width=${3:56}, height=${4:24})"],
  ["frame_to_text", "Convert a frame to terminal text.", "frame_to_text(${1:frame})"]
];

const geometryEntries = [
  ["vec2", "Create a 2D vector.", "vec2(${1:x}, ${2:y})"],
  ["rect", "Create a rectangle dictionary.", "rect(${1:x}, ${2:y}, ${3:w}, ${4:h})"],
  ["circle", "Create a circle dictionary.", "circle(${1:x}, ${2:y}, ${3:r})"],
  ["vadd", "Add two 2D vectors.", "vadd(${1:a}, ${2:b})"],
  ["vsub", "Subtract two 2D vectors.", "vsub(${1:a}, ${2:b})"],
  ["vscale", "Scale a 2D vector.", "vscale(${1:v}, ${2:amount})"],
  ["dot", "2D vector dot product.", "dot(${1:a}, ${2:b})"],
  ["length", "2D vector length.", "length(${1:v})"],
  ["normalize", "Normalize a 2D vector.", "normalize(${1:v})"],
  ["distance", "Distance between two 2D points.", "distance(${1:a}, ${2:b})"],
  ["lerp_vec", "Interpolate between two 2D vectors.", "lerp_vec(${1:a}, ${2:b}, ${3:t})"],
  ["move_toward", "Move a point toward a target by a maximum distance.", "move_toward(${1:current}, ${2:target}, ${3:max_delta})"],
  ["point_in_rect", "Test whether a point is inside a rectangle.", "point_in_rect(${1:point}, ${2:rect})"],
  ["rects_overlap", "Test whether two rectangles overlap.", "rects_overlap(${1:a}, ${2:b})"],
  ["circle_overlap", "Test whether two circles overlap.", "circle_overlap(${1:a}, ${2:b})"],
  ["circle_rect_overlap", "Test whether a circle overlaps a rectangle.", "circle_rect_overlap(${1:circle}, ${2:rect})"],
  ["bounds", "Create rectangle bounds around an array of points.", "bounds(${1:points})"]
];

const canvasEntries = [
  ["make_canvas", "Create a 2D terminal canvas.", "make_canvas(${1:width}, ${2:height}, fill=${3:\" \"})"],
  ["clear", "Clear a canvas to its fill character.", "clear(${1:canvas})"],
  ["plot", "Draw one character at a canvas position.", "plot(${1:canvas}, ${2:x}, ${3:y}, char=${4:\"#\"})"],
  ["line", "Draw a line on a canvas.", "line(${1:canvas}, ${2:x0}, ${3:y0}, ${4:x1}, ${5:y1}, char=${6:\"#\"})"],
  ["stroke_rect", "Draw a rectangle outline.", "stroke_rect(${1:canvas}, ${2:rect}, char=${3:\"#\"})"],
  ["fill_rect", "Draw a filled rectangle.", "fill_rect(${1:canvas}, ${2:rect}, char=${3:\"#\"})"],
  ["circle", "Draw a circle outline.", "circle(${1:canvas}, ${2:circle}, char=${3:\"#\"})"],
  ["fill_circle", "Draw a filled circle.", "fill_circle(${1:canvas}, ${2:circle}, char=${3:\"#\"})"],
  ["text", "Draw text onto a canvas.", "text(${1:canvas}, ${2:x}, ${3:y}, ${4:value})"],
  ["sprite", "Draw non-space characters from string rows.", "sprite(${1:canvas}, ${2:x}, ${3:y}, ${4:rows})"],
  ["sprite_asset", "Create a reusable sprite asset.", "sprite_asset(${1:rows}, transparent=${2:\" \"})"],
  ["draw_sprite", "Draw a reusable sprite with optional flips.", "draw_sprite(${1:canvas}, ${2:asset}, ${3:x}, ${4:y})"],
  ["composite", "Composite one transparent canvas layer onto another.", "composite(${1:canvas}, ${2:layer})"],
  ["camera", "Create a simple 2D camera.", "camera(${1:position}, zoom=${2:1})"],
  ["world_to_screen", "Convert a world point through a 2D camera.", "world_to_screen(${1:point}, ${2:camera}, ${3:canvas})"],
  ["plot_world", "Draw a world-space point through a 2D camera.", "plot_world(${1:canvas}, ${2:point}, ${3:camera}, char=${4:\"#\"})"],
  ["line_world", "Draw a world-space line through a 2D camera.", "line_world(${1:canvas}, ${2:start}, ${3:finish}, ${4:camera})"],
  ["sprite_world", "Draw a sprite at a world-space position.", "sprite_world(${1:canvas}, ${2:asset}, ${3:position}, ${4:camera})"],
  ["animation", "Create a frame animation.", "animation(${1:frames}, fps=${2:8})"],
  ["animation_frame", "Select an animation frame for an elapsed time.", "animation_frame(${1:animation}, ${2:seconds})"],
  ["frame_to_text", "Convert a canvas to terminal text.", "frame_to_text(${1:canvas})"]
];

const pixelGardenEntries = [
  ["canvas", "Create a PixelGarden terminal canvas.", "canvas(${1:width}, ${2:height}, fill=${3:\" \"})"],
  ["vec2", "Create a 2D vector.", "vec2(${1:x}, ${2:y})"],
  ["rect", "Create a rectangle.", "rect(${1:x}, ${2:y}, ${3:w}, ${4:h})"],
  ["circle_shape", "Create a circle shape.", "circle_shape(${1:x}, ${2:y}, ${3:r})"],
  ["stroke_rect", "Draw a rectangle outline.", "stroke_rect(${1:canvas}, ${2:rect}, char=${3:\"#\"})"],
  ["fill_rect", "Draw a filled rectangle.", "fill_rect(${1:canvas}, ${2:rect}, char=${3:\"#\"})"],
  ["circle", "Draw a circle outline.", "circle(${1:canvas}, ${2:shape}, char=${3:\"#\"})"],
  ["text", "Draw text.", "text(${1:canvas}, ${2:x}, ${3:y}, ${4:value})"],
  ["sprite", "Draw a text sprite.", "sprite(${1:canvas}, ${2:x}, ${3:y}, ${4:rows})"],
  ["sprite_asset", "Create a reusable PixelGarden sprite.", "sprite_asset(${1:rows})"],
  ["draw_sprite", "Draw a sprite with optional horizontal or vertical flipping.", "draw_sprite(${1:canvas}, ${2:asset}, ${3:x}, ${4:y})"],
  ["layer", "Create a transparent drawing layer.", "layer(${1:width}, ${2:height})"],
  ["composite", "Composite a PixelGarden layer.", "composite(${1:canvas}, ${2:layer})"],
  ["camera", "Create a PixelGarden world camera.", "camera(${1:position}, zoom=${2:1})"],
  ["line_world", "Draw a line in world coordinates.", "line_world(${1:canvas}, ${2:start}, ${3:finish}, ${4:camera})"],
  ["sprite_world", "Draw a sprite in world coordinates.", "sprite_world(${1:canvas}, ${2:asset}, ${3:position}, ${4:camera})"],
  ["animation", "Create a PixelGarden frame animation.", "animation(${1:frames}, fps=${2:8})"],
  ["animation_frame", "Get the active animation frame.", "animation_frame(${1:animation}, ${2:seconds})"],
  ["frame_to_text", "Convert a canvas to terminal text.", "frame_to_text(${1:canvas})"]
];

const window2dEntries = [
  ["available", "Check whether pygame is installed.", "available()"],
  ["window", "Open a Pygame-backed window.", "window(${1:width}, ${2:height}, title=${3:\"Sprout Window2D\"})"],
  ["color", "Create an RGBA color array.", "color(${1:r}, ${2:g}, ${3:b})"],
  ["clock", "Create a Pygame clock.", "clock(${1:window})"],
  ["poll", "Poll window events.", "poll(${1:window})"],
  ["should_close", "Return whether the window should close.", "should_close(${1:window})"],
  ["fill", "Fill the window surface.", "fill(${1:window}, ${2:color})"],
  ["flip", "Present the window.", "flip(${1:window})"],
  ["tick", "Limit/update the clock.", "tick(${1:clock}, ${2:fps})"],
  ["rect", "Draw a rectangle.", "rect(${1:window}, ${2:x}, ${3:y}, ${4:w}, ${5:h}, ${6:color})"],
  ["circle", "Draw a circle.", "circle(${1:window}, ${2:x}, ${3:y}, ${4:radius}, ${5:color})"],
  ["line", "Draw a line.", "line(${1:window}, ${2:x0}, ${3:y0}, ${4:x1}, ${5:y1}, ${6:color})"],
  ["quit", "Quit pygame.", "quit()"]
];

const pandaEntries = [
  ["available", "Check whether Panda3D is installed.", "available()"],
  ["window", "Open a Panda3D ShowBase window.", "window(${1:title})"],
  ["vec3", "Create a Panda3D Vec3.", "vec3(${1:x}, ${2:y}, ${3:z})"],
  ["point3", "Create a Panda3D Point3.", "point3(${1:x}, ${2:y}, ${3:z})"],
  ["color", "Create a Panda3D Vec4 color.", "color(${1:r}, ${2:g}, ${3:b}, ${4:a})"],
  ["load_model", "Load and attach a model.", "load_model(${1:world}, ${2:path})"],
  ["place", "Set node position.", "place(${1:node}, ${2:x}, ${3:y}, ${4:z})"],
  ["rotate", "Set node rotation.", "rotate(${1:node}, ${2:h}, ${3:p}, ${4:r})"],
  ["scale", "Set node scale.", "scale(${1:node}, ${2:amount})"],
  ["run", "Run the Panda3D app loop.", "run(${1:world})"]
];

const gameEntries = [
  ["make_player", "Create a small game player dictionary.", "make_player(${1:name})"],
  ["move", "Move a game player within map bounds.", "move(${1:hero}, ${2:direction}, ${3:width}, ${4:height})"],
  ["hurt", "Subtract hit points from a game player.", "hurt(${1:hero}, ${2:amount})"],
  ["heal", "Restore hit points up to the helper's cap.", "heal(${1:hero}, ${2:amount})"],
  ["status", "Format a game player status line.", "status(${1:hero})"]
];

const engineeringEntries = [
  ["vector", "Create an engineering vector.", "vector(${1:values})"],
  ["add", "Add vectors.", "add(${1:a}, ${2:b})"],
  ["subtract", "Subtract vectors.", "subtract(${1:a}, ${2:b})"],
  ["dot", "Vector dot product.", "dot(${1:a}, ${2:b})"],
  ["magnitude", "Vector magnitude.", "magnitude(${1:value})"],
  ["normalize", "Normalize a vector.", "normalize(${1:value})"],
  ["matrix_multiply", "Multiply matrices.", "matrix_multiply(${1:a}, ${2:b})"],
  ["convert", "Convert engineering units.", "convert(${1:value}, ${2:source}, ${3:target})"],
  ["lerp_value", "Interpolate values.", "lerp_value(${1:a}, ${2:b}, ${3:t})"],
  ["energy", "Calculate kinetic energy.", "energy(${1:mass}, ${2:speed})"],
  ["newtons", "Calculate force in newtons.", "newtons(${1:mass}, ${2:acceleration})"],
  ["pascals", "Calculate pressure in pascals.", "pascals(${1:force}, ${2:area})"],
  ["interpolate_points", "Interpolate sampled points.", "interpolate_points(${1:points}, ${2:x})"]
];

const appGameEntries = [
  ["game", "Create game application state.", "game(${1:title})"],
  ["entity", "Create an entity.", "entity(${1:name}, ${2:x}, ${3:y}, ${4:w}, ${5:h})"],
  ["add_entity", "Add an entity.", "add_entity(${1:state}, ${2:entity})"],
  ["add_scene", "Register a scene.", "add_scene(${1:state}, ${2:name}, ${3:scene})"],
  ["change_scene", "Change active scene.", "change_scene(${1:state}, ${2:name})"],
  ["set_input", "Set an input action.", "set_input(${1:state}, ${2:action}, ${3:pressed})"],
  ["pressed", "Check an input action.", "pressed(${1:state}, ${2:action})"],
  ["collides", "Test entity rectangle collision.", "collides(${1:a}, ${2:b})"],
  ["timer", "Create a game timer.", "timer(${1:seconds})"],
  ["tick_timer", "Advance a game timer.", "tick_timer(${1:timer}, ${2:dt})"],
  ["load_text", "Load a text asset.", "load_text(${1:path})"],
  ["load_json", "Load a JSON asset.", "load_json(${1:path})"]
];

const allBuiltinNames = [
  "abs", "acos", "appendfile", "array", "asin", "ask", "atan", "atan2", "avg", "basename", "between", "bundle",
  "ceil", "chant", "chars", "choose", "chunks", "clamp", "clear", "compact", "concat", "contains", "copy", "cos",
  "countby", "cwd", "degrees", "delkey", "dice", "dict", "dirname", "dist", "drop", "endswith", "ensure", "enumerate",
  "exists", "exp", "extname", "fail", "fill", "first", "flatten", "floor", "frompairs", "functions", "get", "grow",
  "harvest", "has", "hypot", "indexof", "insert", "int", "is_array", "is_bool", "is_class", "is_dict", "is_empty",
  "is_even", "is_function", "is_instance", "is_nil", "is_number", "is_odd", "is_string", "isdir", "isfile", "items",
  "join", "joinpath", "json_parse", "json_stringify", "keys", "last", "len", "lerp", "lines", "listdir", "log", "log10",
  "lower", "ltrim", "max", "median", "merge", "methods", "min", "mirror", "mkdir", "now", "num", "omit", "padleft",
  "padright", "pick", "plant", "pow", "prune", "push", "py_available", "py_import", "radians", "rand", "randint", "range", "readfile",
  "readjson", "remove", "repeat", "replace", "rest", "reverse", "round", "rtrim", "sample", "say", "seed", "shout",
  "shuffle", "sign", "sin", "sleep", "slice", "sort", "sparkle", "sprinkle", "sqrt", "startswith", "str", "substr",
  "sum", "take", "tan", "title", "trim", "type", "unique", "upper", "values", "weave", "whisper", "words", "wrap",
  "writefile", "writejson", "zipbud", "expect", "task_spawn", "task_after", "task_wait_all", "queue_open",
  "http_get", "http_post", "http_request", "http_server", "sqlite_open", "sqlite_exec", "sqlite_query",
  "sqlite_begin", "sqlite_commit", "sqlite_rollback", "sqlite_close", "vec_add", "vec_sub", "vec_dot",
  "vec_magnitude", "vec_normalize", "mat_mul", "unit_convert", "interpolate", "kinetic_energy", "force", "pressure"
];

const allEngineNames = [
  "vec3", "vadd", "vsub", "vscale", "dot", "cross", "length", "normalize", "mesh", "cube", "pyramid", "plane", "edge_key", "unique_edges",
  "parse_face_index", "obj_record", "obj_mesh", "load_obj", "translate_mesh", "scale_mesh", "rotate_x", "rotate_y",
  "rotate_z", "rotate_mesh", "transform_mesh", "merge_meshes", "camera", "look_at_camera", "orbit_camera", "world_to_camera", "project", "make_frame",
  "make_zbuffer", "plot", "line", "edge_value", "shade_char", "face_normal", "draw_triangle", "render_solid",
  "render_wireframe", "frame_to_text", "bounds", "object", "scene", "add", "object_mesh", "scene_mesh", "render"
];

const allGeometryNames = [
  "vec2", "rect", "circle", "vadd", "vsub", "vscale", "dot", "length", "normalize", "distance", "angle", "from_angle",
  "lerp_vec", "midpoint", "move_toward", "clamp_vec", "rect_center", "point_in_rect", "rects_overlap", "point_in_circle",
  "circle_overlap", "nearest_point_on_rect", "circle_rect_overlap", "bounds"
];

const allCanvasNames = [
  "make_canvas", "clear", "plot", "line", "stroke_rect", "fill_rect", "circle", "fill_circle", "text", "sprite",
  "sprite_asset", "draw_sprite", "composite", "camera", "world_to_screen", "plot_world", "line_world",
  "sprite_world", "animation", "animation_frame", "frame_to_text"
];

const allPixelGardenNames = [
  "vec2", "rect", "circle_shape", "vadd", "vsub", "vscale", "distance", "move_toward", "rects_overlap",
  "circle_rect_overlap", "bounds", "canvas", "clear", "plot", "line", "stroke_rect", "fill_rect", "circle",
  "fill_circle", "text", "sprite", "sprite_asset", "draw_sprite", "layer", "composite", "camera",
  "world_to_screen", "plot_world", "line_world", "sprite_world", "animation", "animation_frame", "frame_to_text"
];

const allWindow2dNames = [
  "available", "require_pygame", "color", "init", "quit", "window", "clock", "poll", "should_close", "fill",
  "flip", "tick", "rect", "circle", "line"
];

const allPandaNames = [
  "available", "require_core", "require_showbase", "vec3", "point3", "color", "window", "load_model", "place",
  "rotate", "scale", "run"
];

const allGameNames = [
  "make_player", "move", "hurt", "heal", "status"
];

const builtinArities = {
  "abs": 1,
  "acos": 1,
  "appendfile": 2,
  "array": null,
  "asin": 1,
  "ask": 1,
  "atan": 1,
  "atan2": 2,
  "avg": 1,
  "basename": 1,
  "between": 3,
  "bundle": 2,
  "ceil": 1,
  "chant": 2,
  "chars": 1,
  "choose": 1,
  "chunks": 2,
  "clamp": 3,
  "clear": 0,
  "compact": 1,
  "concat": null,
  "contains": 2,
  "copy": 1,
  "cos": 1,
  "countby": 1,
  "cwd": 0,
  "degrees": 1,
  "delkey": 2,
  "dice": 1,
  "dict": null,
  "dirname": 1,
  "dist": 4,
  "drop": 2,
  "endswith": 2,
  "ensure": 2,
  "enumerate": 1,
  "exists": 1,
  "exp": 1,
  "extname": 1,
  "fail": 1,
  "fill": 2,
  "first": 1,
  "flatten": 1,
  "floor": 1,
  "frompairs": 1,
  "functions": 0,
  "get": null,
  "grow": 2,
  "harvest": 1,
  "has": 2,
  "hypot": null,
  "indexof": 2,
  "insert": 3,
  "int": 1,
  "is_array": 1,
  "is_bool": 1,
  "is_class": 1,
  "is_dict": 1,
  "is_empty": 1,
  "is_even": 1,
  "is_function": 1,
  "is_instance": 1,
  "is_nil": 1,
  "is_number": 1,
  "is_odd": 1,
  "is_string": 1,
  "isdir": 1,
  "isfile": 1,
  "items": 1,
  "join": 2,
  "joinpath": null,
  "json_parse": 1,
  "json_stringify": 1,
  "keys": 1,
  "last": 1,
  "len": 1,
  "lerp": 3,
  "lines": 1,
  "listdir": 1,
  "log": 1,
  "log10": 1,
  "lower": 1,
  "ltrim": 1,
  "max": null,
  "median": 1,
  "merge": null,
  "methods": 0,
  "min": null,
  "mirror": 1,
  "mkdir": 1,
  "now": 0,
  "num": 1,
  "omit": 2,
  "padleft": 3,
  "padright": 3,
  "pick": 2,
  "plant": 3,
  "pow": 2,
  "prune": 2,
  "push": 2,
  "py_available": 1,
  "py_import": 1,
  "radians": 1,
  "rand": 0,
  "randint": 2,
  "range": 1,
  "readfile": 1,
  "readjson": 1,
  "remove": 2,
  "repeat": 2,
  "replace": 3,
  "rest": 1,
  "reverse": 1,
  "round": 1,
  "rtrim": 1,
  "sample": 2,
  "say": null,
  "seed": 1,
  "shout": 1,
  "shuffle": 1,
  "sign": 1,
  "sin": 1,
  "sleep": 1,
  "slice": 3,
  "sort": 1,
  "sparkle": 1,
  "sprinkle": 2,
  "sqrt": 1,
  "startswith": 2,
  "str": 1,
  "substr": 3,
  "sum": 1,
  "take": 2,
  "tan": 1,
  "title": 1,
  "trim": 1,
  "type": 1,
  "unique": 1,
  "upper": 1,
  "values": 1,
  "weave": 2,
  "whisper": 1,
  "words": 1,
  "wrap": 3,
  "writefile": 2,
  "writejson": 2,
  "zipbud": 2
};

function callSnippet(name, arity) {
  if (arity === 0) return `${name}()`;
  if (arity === null || arity === undefined) return `${name}(\${1:value})`;
  const args = [];
  for (let i = 1; i <= arity; i += 1) {
    args.push(`\${${i}:value${i}}`);
  }
  return `${name}(${args.join(", ")})`;
}

function completeNamedSet(names, documentedEntries, genericDocs) {
  const documented = new Map(documentedEntries.map((entry) => [entry[0], entry]));
  return names.map((name) => documented.get(name) || [name, `${genericDocs} ${name}.`, callSnippet(name, builtinArities[name])]);
}

function uniqueEntries(entries) {
  const seen = new Set();
  return entries.filter(([name]) => {
    if (seen.has(name)) return false;
    seen.add(name);
    return true;
  });
}

const entryNames = new Set(entries.map((entry) => entry[0]));
const fallbackBuiltinEntries = completeNamedSet(allBuiltinNames, entries, "Sprout built-in").filter((entry) => !entryNames.has(entry[0]));
const completeBuiltinEntries = entries.concat(fallbackBuiltinEntries);
const completeKeywordEntries = keywordEntries.map((entry) => entry.concat(vscode.CompletionItemKind.Keyword));
const completeTopLevelEntries = uniqueEntries(completeKeywordEntries.concat(completeBuiltinEntries));
const completeEngineEntries = completeNamedSet(allEngineNames, engineEntries, "Sprout3D API");
const completeGeometryEntries = completeNamedSet(allGeometryNames, geometryEntries, "Sprout2D geometry API");
const completeCanvasEntries = completeNamedSet(allCanvasNames, canvasEntries, "Sprout2D canvas API");
const completePixelGardenEntries = completeNamedSet(allPixelGardenNames, pixelGardenEntries, "PixelGarden API");
const completeStarBloomEntries = completeNamedSet(allEngineNames, engineEntries, "StarBloom3D API");
const completeWindow2dEntries = completeNamedSet(allWindow2dNames, window2dEntries, "Window2D API");
const completePandaEntries = completeNamedSet(allPandaNames, pandaEntries, "PandaWindow3D API");
const completeGameEntries = completeNamedSet(allGameNames, gameEntries, "Gamekit API");
const completeEngineeringEntries = engineeringEntries;
const completeAppGameEntries = appGameEntries;
function completion(label, docs, insertText, kind = vscode.CompletionItemKind.Function) {
  const item = new vscode.CompletionItem(label, kind);
  item.detail = "Sprout";
  item.documentation = new vscode.MarkdownString(docs || "");
  if (insertText) {
    item.insertText = new vscode.SnippetString(insertText);
  }
  return item;
}

function identifierContext(lineText, character) {
  const text = String(lineText || "");
  const safeCharacter = Math.max(0, Math.min(Number.isFinite(character) ? character : 0, text.length));
  let start = safeCharacter;
  let end = safeCharacter;
  while (start > 0 && /[A-Za-z0-9_]/.test(text[start - 1])) {
    start -= 1;
  }
  while (end < text.length && /[A-Za-z0-9_]/.test(text[end])) {
    end += 1;
  }
  const word = start < end ? text.slice(start, end) : "";
  return {
    word,
    start,
    end,
    insideWord: Boolean(word) && safeCharacter >= start && safeCharacter <= end
  };
}

function finalizeCompletionEntries(entries, lineText, character, options = {}) {
  const deduped = dedupeCompletionEntries(entries);
  if (options.allowExactWord) {
    return deduped;
  }
  const current = identifierContext(lineText, character);
  if (!current.insideWord || !current.word) {
    return deduped;
  }
  const filtered = deduped.filter((entry) => entry?.label !== current.word);
  return filtered.length > 0 ? filtered : deduped;
}

function importCompletionContext(lineText, character) {
  const before = lineText.slice(0, character);
  const rawPrefixMatch = before.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*)?$/);
  if (rawPrefixMatch) {
    const raw = rawPrefixMatch[1];
    const trailing = rawPrefixMatch[2] || "";
    const importLike = new Set([
      "import",
      "importpython",
      "im",
      "imp",
      "impo",
      "impor",
      "importp",
      "importpy",
      "importpyth",
      "importpytho"
    ]);
    if (importLike.has(raw)) {
      const kind = raw.startsWith("importpython") || raw.startsWith("importpy")
        ? "importpython"
        : "import";
      const stripped = String(trailing).trimStart();
      const bare = stripped.match(/^([A-Za-z0-9_./-]*)$/);
      if (bare) {
        return { kind, prefix: bare[1] || "", quoted: false, partialKeyword: raw !== "import" && raw !== "importpython" };
      }
      const quoted = stripped.match(/^"([^"]*)?$/) || stripped.match(/^'([^']*)?$/);
      if (quoted) {
        return { kind, prefix: quoted[1] || "", quoted: true, partialKeyword: raw !== "import" && raw !== "importpython" };
      }
    }
  }
  const bare = before.match(/^\s*(import|importpython)\s+([A-Za-z0-9_./]*)$/);
  if (bare) {
    return { kind: bare[1], prefix: bare[2] || "", quoted: false, partialKeyword: false };
  }
  const quoted = before.match(/^\s*(import|importpython)\s+"([^"]*)?$/);
  if (quoted) {
    return { kind: quoted[1], prefix: quoted[2] || "", quoted: true, partialKeyword: false };
  }
  return null;
}

function findUp(startPath, filename) {
  let current = startPath;
  while (current && current !== path.dirname(current)) {
    const candidate = path.join(current, filename);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    current = path.dirname(current);
  }
  return undefined;
}

function uniquePaths(paths) {
  const seen = new Set();
  return paths.filter((candidate) => {
    if (!candidate) return false;
    const resolved = path.resolve(candidate);
    if (seen.has(resolved) || !fs.existsSync(resolved)) return false;
    seen.add(resolved);
    return true;
  });
}

function diagnosticSeverityToLsp(severity) {
  switch (severity) {
    case vscode.DiagnosticSeverity.Error:
      return 1;
    case vscode.DiagnosticSeverity.Warning:
      return 2;
    case vscode.DiagnosticSeverity.Information:
      return 3;
    case vscode.DiagnosticSeverity.Hint:
      return 4;
    default:
      return 1;
  }
}

async function localCompletionFallback(context, document, lineText, position, importContext, isAfterImportDot, aliasMatch) {
  if (importContext) {
    const contextCompletions = collectImportCompletions(context, document.uri, importContext);
    const aliases = collectImportedAliases(document.getText(), document.uri);
    const aliasCompletions = Array.from(aliases.keys())
      .filter((alias) => alias.startsWith(importContext.prefix))
      .map((alias) => completion(alias, "Imported module alias", alias, vscode.CompletionItemKind.Variable));
    const importItems = dedupeCompletionEntries(contextCompletions.concat(aliasCompletions));
    return finalizeCompletionEntries(importItems, lineText, position.character, { allowExactWord: true });
  }

  if (isAfterImportDot) {
    const imported = aliasMatch ? await importAliasCompletions(context, aliasMatch[1], document.getText(), document.uri) : null;
    if (imported && imported.length > 0) {
      return finalizeCompletionEntries(imported, lineText, position.character, { allowExactWord: true });
    }
    if (aliasMatch) {
      return [];
    }
  }

  return finalizeCompletionEntries(
    completeTopLevelEntries.map(([label, docs, insert, kind]) => completion(label, docs, insert, kind)),
    lineText,
    position.character
  );
}

function installedModuleRunner(pythonPath) {
  const key = String(pythonPath || "");
  const cached = installedRunnerCache.get(key);
  if (cached !== undefined) {
    return cached;
  }
  try {
    const probe = [
      "-c",
      [
        "import importlib.util",
        "import os",
        "spec = importlib.util.find_spec('sprout')",
        "origin = spec.origin if spec and spec.origin else ''",
        "print(origin if origin and os.path.isfile(origin) else '')"
      ].join("; ")
    ];
    const result = childProcess.execFileSync(pythonPath, probe, {
      encoding: "utf8",
      timeout: 5000,
      stdio: ["ignore", "pipe", "ignore"]
    }).trim();
    const resolved = result && fs.existsSync(result) ? result : "";
    installedRunnerCache.set(key, resolved);
    return resolved;
  } catch (_error) {
    installedRunnerCache.set(key, "");
    return "";
  }
}

function runnerCandidates(context, document) {
  const candidates = [];
  const installedRunner = installedModuleRunner(pythonExecutable());
  if (installedRunner) {
    candidates.push({
      path: installedRunner,
      label: "Installed Sprout",
      description: installedRunner
    });
  }
  candidates.push(
    {
      path: path.join(context.extensionPath, "sprout.py"),
      label: "Bundled Sprout",
      description: "Included with the VS Code extension"
    },
    {
      path: path.resolve(context.extensionPath, "..", "..", "sprout.py"),
      label: "Sprout source checkout",
      description: "Development interpreter"
    }
  );

  if (document?.uri.scheme === "file") {
    const runner = findUp(path.dirname(document.uri.fsPath), "sprout.py");
    candidates.push({ path: runner, label: "Current project", description: runner });
  }
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const runner = findUp(folder.uri.fsPath, "sprout.py");
    candidates.push({ path: runner, label: `Workspace: ${folder.name}`, description: runner });
  }

  const paths = uniquePaths(candidates.map((candidate) => candidate.path));
  return paths.map((candidatePath) => candidates.find((candidate) => (
    candidate.path && path.resolve(candidate.path) === candidatePath
  )));
}

function findRunner(context, document) {
  const configured = vscode.workspace.getConfiguration("sprout").get("runnerPath");
  if (configured && fs.existsSync(configured)) {
    return configured;
  }

  return runnerCandidates(context, document)[0]?.path;
}

function pythonExecutable() {
  return vscode.workspace.getConfiguration("sprout").get("pythonPath")
    || (process.platform === "win32" ? "python" : "python3");
}

function validateRunner(runner) {
  return new Promise((resolve) => {
    childProcess.execFile(
      pythonExecutable(),
      [runner, "version"],
      { timeout: 5000 },
      (error, stdout, stderr) => {
        const version = String(stdout || "").trim();
        if (!error && /^Sprout\s+\S+/.test(version)) {
          resolve({ ok: true, version });
          return;
        }
        resolve({
          ok: false,
          message: String(stderr || stdout || error || "Unknown interpreter error").trim()
        });
      }
    );
  });
}

function activeSproutDocument() {
  const document = vscode.window.activeTextEditor?.document;
  return document?.languageId === "sprout" ? document : undefined;
}

function formatAnalysisStatus(status) {
  if (!status || typeof status !== "object") return "Sprout analysis status unavailable.";
  const settings = status.settings || {};
  const effective = status.effectiveSettings || {};
  const operations = status.operations || {};
  const hotOperations = Object.entries(operations)
    .sort((left, right) => (right[1]?.avgMs || 0) - (left[1]?.avgMs || 0))
    .slice(0, 4)
    .map(([name, item]) => `${name}: avg=${item.avgMs ?? 0}ms max=${item.maxMs ?? 0}ms count=${item.count ?? 0}`);
  return [
    `root: ${status.root || "(unknown)"}`,
    `files: ${status.fileCount ?? 0}`,
    `dependency edges: ${status.dependencyEdges ?? 0}`,
    `analysis count: ${status.analysisCount ?? 0}`,
    `cache: hits=${status.cacheHits ?? 0} misses=${status.cacheMisses ?? 0} hit-rate=${((status.cacheHitRate ?? 0) * 100).toFixed(1)}%`,
    `last build: ${(status.lastBuildReason || "unknown")} -> ${(status.lastBuildTarget || "(unknown)")}`,
    `timing: build=${status.lastBuildDurationMs ?? 0}ms reindexed=${status.lastReindexedDurationMs ?? 0}ms refresh=${status.lastRefreshImportsMs ?? 0}ms`,
    `last changed: ${(status.lastChangedPaths || []).join(", ") || "(none)"}`,
    `last reindexed: ${(status.lastReindexedFiles || []).join(", ") || "(none)"}`,
    `settings: mode=${settings.typeCheckingMode || "basic"} diagnostic=${settings.diagnosticMode || "workspace"} indexing=${settings.indexing === false ? "off" : "on"} server=${settings.languageServerMode || "default"}`,
    `effective: diagnostic=${effective.diagnosticMode || "workspace"} indexing=${effective.indexing === false ? "off" : "on"} limit=${effective.userFileIndexingLimit ?? 0} libraryTypes=${effective.useLibraryCodeForTypes === false ? "off" : "on"} server=${effective.languageServerMode || "default"}`,
    `operations: ${hotOperations.join(" | ") || "(none)"}`
  ].join("\n");
}

function usingLanguageServer() {
  return Boolean(languageClient?.ready || languageClient?.starting);
}

function diagnosticsEnabled() {
  return Boolean(vscode.workspace.getConfiguration("sprout").get("diagnostics.enabled"));
}

function diagnosticsVisible() {
  return Boolean(vscode.workspace.getConfiguration("sprout").get("diagnostics.visibleSquiggles", true));
}

function cleanIdentifier(value) {
  return value.replace(/\W+/g, "").replace(/^\d+/, "");
}

function extractWorkspaceFolders() {
  return (vscode.workspace.workspaceFolders || []).map((folder) => folder.uri.fsPath);
}

function parseImportPath(rawPath) {
  return String(rawPath || "").trim().replace(/["']/g, "");
}

function collectImportedAliases(documentText, documentUri) {
  const aliases = new Map();
  if (!documentText) return aliases;
  const documentDir = documentUri?.fsPath ? path.dirname(documentUri.fsPath) : null;
  for (const line of documentText.split(/\r?\n/)) {
    const stripped = line.split(/\s+#/, 2)[0];
    const match = stripped.match(/^\s*(import|importpython)\s+(?:(["'])([^"']+)\2|([^\s]+))(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?/);
    if (!match) continue;
    const importKind = match[1];
    const modulePath = parseImportPath(match[3] || match[4] || "");
    const explicitAlias = match[5];
    const base = modulePath.split(/[\\/]/).pop().replace(/\.sprout$/, "");
    const alias = explicitAlias || cleanIdentifier(base);
    if (!alias || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(alias)) continue;
    aliases.set(alias, {
      path: modulePath,
      alias,
      module: base || alias,
      pathHint: documentDir ? path.resolve(documentDir, modulePath) : modulePath,
      kind: importKind,
      explicit: Boolean(explicitAlias)
    });
  }
  return aliases;
}

function standardLibraryRoots(context) {
  const roots = [];
  const extensionStdlib = path.join(context.extensionPath, "sprout_core", "stdlib");
  roots.push(extensionStdlib);
  const activeDocument = activeSproutDocument();
  const runner = findRunner(context, activeDocument || { uri: undefined, languageId: "sprout" });
  if (runner) {
    roots.push(path.join(path.dirname(runner), "sprout_core", "stdlib"));
  }
  return Array.from(new Set(roots)).filter((candidate) => {
    try {
      return fs.statSync(candidate).isDirectory();
    } catch (_error) {
      return false;
    }
  });
}

function resolveModuleCandidates(context, moduleName, documentUri) {
  const rootPaths = [];
  const trimmed = parseImportPath(moduleName);
  if (!trimmed) return rootPaths;
  const baseDir = documentUri?.fsPath ? path.dirname(documentUri.fsPath) : null;

  const candidates = [];
  const normalized = trimmed.replace(/\\/g, "/");
  if (path.isAbsolute(normalized)) {
    candidates.push(normalized);
  } else {
    if (baseDir) {
      candidates.push(path.join(baseDir, normalized));
    }
    for (const folder of extractWorkspaceFolders()) {
      candidates.push(path.join(folder, normalized));
      candidates.push(path.join(folder, "src", normalized));
      candidates.push(path.join(folder, "modules", normalized));
    }
    for (const folder of extractWorkspaceFolders()) {
      const sproutToml = path.join(folder, "sprout.toml");
      if (fs.existsSync(sproutToml)) {
        candidates.push(path.join(folder, "build", normalized));
      }
    }
    for (const folder of standardLibraryRoots(context)) {
      candidates.push(path.join(folder, normalized));
    }
  }

  for (const candidate of candidates) {
    const direct = candidate.endsWith(".sprout") ? candidate : `${candidate}.sprout`;
    const directNoExt = candidate;
    const addFile = (filePath) => {
      if (!filePath) return;
      try {
        const stat = fs.statSync(filePath);
        if (stat.isFile()) rootPaths.push(filePath);
      } catch (_error) {
        // ignore missing or unreadable files
      }
    };
    addFile(direct);
    if (directNoExt !== direct) {
      addFile(directNoExt);
    }
  }

  return Array.from(new Set(rootPaths)).filter(Boolean);
}

function parseImportedModuleSymbols(moduleText) {
  const names = [];
  const seen = new Set();
  for (const line of moduleText.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    let match = trimmed.match(/^def\s+([A-Za-z_][A-Za-z0-9_]*)/);
    if (match) {
      const name = match[1];
      if (!seen.has(name)) {
        seen.add(name);
        names.push([name, "Imported Sprout function", `${name}($\{1:value\})`]);
      }
      continue;
    }
    match = trimmed.match(/^class\s+([A-Za-z_][A-Za-z0-9_]*)/);
    if (match) {
      const name = match[1];
      if (!seen.has(name)) {
        seen.add(name);
        names.push([name, "Imported Sprout class", `${name}`]);
      }
      continue;
    }
    match = trimmed.match(/^(?:let\s+|sprout\s+|const\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\b)/);
    if (match && !/^(?:if|elif|else|for|while|def|class|import|importpython|return|break|continue)$/.test(match[1])) {
      const name = match[1];
      if (!seen.has(name)) {
        seen.add(name);
        names.push([name, "Imported Sprout symbol", name]);
      }
    }
  }
  return names;
}

function importedSymbolEntry(symbol) {
  const name = String(symbol?.name || "").trim();
  if (!name) return null;
  const kind = String(symbol?.kind || "");
  const docs = symbol?.documentation || `Imported Sprout ${kind || "symbol"}`;
  if (kind === "function" || kind === "method") {
    return [name, docs, `${name}($\{1:value\})`];
  }
  if (kind === "class" || kind === "interface" || kind === "enum") {
    return [name, docs, `${name}`];
  }
  return [name, docs, name];
}

function loadImportedModuleSymbolsFromRunner(context, filePath, documentUri) {
  const runner = findRunner(context, { uri: documentUri, languageId: "sprout" });
  if (!runner) {
    return Promise.resolve([]);
  }
  return new Promise((resolve) => {
    childProcess.execFile(
      pythonExecutable(),
      [runner, "intel", filePath, "--kind", "symbols", "--line", "1", "--col", "1"],
      { timeout: 5000 },
      (_error, stdout) => {
        try {
          const payload = JSON.parse(stdout || "{}");
          const symbols = Array.isArray(payload?.symbols) ? payload.symbols : [];
          resolve(symbols.map(importedSymbolEntry).filter(Boolean));
        } catch (_jsonError) {
          resolve([]);
        }
      }
    );
  });
}

async function resolveImportedModuleSymbols(context, filePaths, documentUri) {
  if (!Array.isArray(filePaths) || filePaths.length === 0) return [];
  const allSymbols = [];
  for (const filePath of filePaths) {
    if (!filePath) continue;
    try {
      const stat = fs.statSync(filePath);
      const cacheEntry = importedModuleSymbolCache.get(filePath);
      if (cacheEntry && cacheEntry.mtimeMs === stat.mtimeMs) {
        allSymbols.push(...cacheEntry.symbols);
        continue;
      }
      let symbols = await loadImportedModuleSymbolsFromRunner(context, filePath, documentUri);
      if (!symbols.length) {
        const text = fs.readFileSync(filePath, "utf8");
        symbols = parseImportedModuleSymbols(text);
      }
      importedModuleSymbolCache.set(filePath, {
        mtimeMs: stat.mtimeMs,
        expiresAt: Date.now() + IMPORT_COMPLETION_CACHE_MS,
        symbols,
        uri: filePath
      });
      allSymbols.push(...symbols);
    } catch (_error) {
      continue;
    }
  }
  return allSymbols;
}

function collectImportPathCandidates(basePaths, prefix) {
  const raw = String(prefix || "").replace(/\\/g, "/");
  const normalizedBasePaths = Array.from(new Set(basePaths.map((item) => path.resolve(item)))).sort();
  const cacheKey = `${raw}|${normalizedBasePaths.join("|")}`;
  const cached = importPathCandidateCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.names;
  }
  const normalized = raw.startsWith("/") ? raw.slice(1) : raw;
  const parts = normalized.split("/").filter(Boolean);
  const baseName = parts.length ? parts[parts.length - 1] : "";
  const parentPath = parts.length > 1 ? parts.slice(0, -1).join("/") : "";
  const candidates = [];

  for (const base of normalizedBasePaths) {
    const cwd = parentPath ? path.join(base, parentPath) : base;
    let stat;
    try {
      stat = fs.statSync(cwd);
    } catch (_error) {
      continue;
    }
    if (!stat.isDirectory()) continue;
    let entries;
    try {
      entries = fs.readdirSync(cwd, { withFileTypes: true });
    } catch (_error) {
      continue;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (entry.name.startsWith(".") || entry.name === "__pycache__") continue;
        if (!baseName || entry.name.startsWith(baseName)) {
          const candidate = parentPath ? `${parentPath}/${entry.name}` : entry.name;
          candidates.push(candidate);
        }
        continue;
      }
      if (!entry.isFile() || !entry.name.endsWith(".sprout")) continue;
      const stem = entry.name.slice(0, -7);
      if (!baseName || stem.startsWith(baseName)) {
        const candidate = parentPath ? `${parentPath}/${stem}` : stem;
        candidates.push(candidate);
      }
    }
  }
  const names = Array.from(new Set(candidates))
    .sort((a, b) => a.localeCompare(b))
    .slice(0, 120);
  importPathCandidateCache.set(cacheKey, {
    names,
    expiresAt: Date.now() + IMPORT_PATH_COMPLETION_CACHE_MS
  });
  return names;
}

function collectImportCompletions(context, documentUri, importContext) {
  const prefix = importContext?.prefix || "";
  const workspaceRoots = extractWorkspaceFolders();
  const docDir = documentUri?.fsPath ? path.dirname(documentUri.fsPath) : null;
  const basePaths = [];
  if (docDir) basePaths.push(docDir, path.join(docDir, "src"), path.join(docDir, "modules"));
  for (const root of workspaceRoots) {
    basePaths.push(root);
    basePaths.push(path.join(root, "src"));
    basePaths.push(path.join(root, "modules"));
  }
  basePaths.push(...standardLibraryRoots(context));

  const uniqueBasePaths = Array.from(new Set(basePaths.map((item) => path.resolve(item)))).filter((item) => {
    try {
      return fs.statSync(item).isDirectory();
    } catch (_error) {
      return false;
    }
  });

  if (!importContext?.quoted) {
    const names = new Set();
    for (const candidate of collectImportPathCandidates(uniqueBasePaths, prefix)) {
      if (resolveModuleCandidates(context, candidate, documentUri).length === 0) continue;
      names.add(candidate.replace(/\//g, "."));
    }
    return Array.from(names)
      .sort((a, b) => a.localeCompare(b))
      .map((candidate) => completion(candidate, "Sprout module", candidate, vscode.CompletionItemKind.Module));
  }

  const names = collectImportPathCandidates(uniqueBasePaths, prefix);
  return names
    .filter((candidate) => !prefix || candidate.startsWith(prefix))
    .map((candidate) => {
      const item = completion(candidate, "Sprout module path", candidate, vscode.CompletionItemKind.Module);
      if (importContext?.quoted) {
        item.insertText = candidate.replace(/^\"|\"$/g, "");
      } else {
        item.insertText = candidate;
      }
      return item;
    });
}

function cleanupImportSymbolCache() {
  const now = Date.now();
  for (const [key, value] of importedModuleSymbolCache.entries()) {
    if (value.expiresAt && value.expiresAt < now) {
      importedModuleSymbolCache.delete(key);
    }
  }
}

async function importAliasCompletions(context, alias, documentText, documentUri) {
  const aliasName = String(alias || "").trim();
  if (!aliasName) return [];
  const aliases = collectImportedAliases(documentText, documentUri);
  const info = aliases.get(aliasName);
  if (!info) return [];

  if (info.kind === "importpython") {
    return [];
  }

  cleanupImportSymbolCache();
  const candidates = resolveModuleCandidates(context, info.path, documentUri);
  if (candidates.length === 0) return [];
  const symbols = await resolveImportedModuleSymbols(context, candidates, documentUri);
  if (symbols.length) {
    const seen = new Set();
    return symbols
      .filter(([name]) => {
        if (seen.has(name)) return false;
        seen.add(name);
        return true;
      })
      .map(([name, docs, insert]) => completion(name, docs || `From ${info.module}.`, insert));
  }

  return [];

}

function dedupeCompletionEntries(entries) {
  const seen = new Set();
  const merged = [];
  for (const entry of entries) {
    if (!entry?.label) continue;
    const key = `${entry.kind || ""}:${entry.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(entry);
  }
  return merged;

}

async function updateInterpreterStatus(context) {
  if (!interpreterStatus) return;
  const document = activeSproutDocument();
  if (!document) {
    interpreterStatus.hide();
    return;
  }
  const configured = vscode.workspace.getConfiguration("sprout", document?.uri).get("runnerPath");
  const runner = findRunner(context, document);
  interpreterStatus.text = configured ? "$(symbol-method) Sprout: Selected" : "$(symbol-method) Sprout: Auto";
  interpreterStatus.tooltip = runner
    ? `Sprout interpreter: ${runner}\nClick to select another interpreter.`
    : "No Sprout interpreter found. Click to select one.";
  interpreterStatus.backgroundColor = runner
    ? undefined
    : new vscode.ThemeColor("statusBarItem.warningBackground");
  interpreterStatus.show();
}

async function selectInterpreter(context) {
  const document = activeSproutDocument();
  const configuration = vscode.workspace.getConfiguration("sprout", document?.uri);
  const current = configuration.get("runnerPath");
  const candidates = runnerCandidates(context, document);
  const selected = await vscode.window.showQuickPick(
    [
      {
        label: "$(wand) Auto Detect",
        description: current ? "Clear the current selection" : "Currently selected",
        detail: "Prefer the selected Python's installed Sprout, then the bundled interpreter, then project sprout.py files.",
        action: "auto"
      },
      ...candidates.map((candidate) => ({
        label: `$(file-code) ${candidate.label}`,
        description: candidate.path === current ? "Currently selected" : "",
        detail: candidate.path,
        runner: candidate.path
      })),
      {
        label: "$(folder-opened) Enter Interpreter Path...",
        detail: "Choose a custom sprout.py file.",
        action: "browse"
      }
    ],
    {
      title: "Select Sprout Interpreter",
      placeHolder: "Choose the interpreter used for running, diagnostics, IntelliSense, tests, and debugging",
      matchOnDescription: true,
      matchOnDetail: true
    }
  );
  if (!selected) return;

  let runner = selected.runner;
  if (selected.action === "browse") {
    const picked = await vscode.window.showOpenDialog({
      title: "Select sprout.py",
      canSelectFiles: true,
      canSelectFolders: false,
      canSelectMany: false,
      filters: { "Sprout interpreter": ["py"], "All files": ["*"] }
    });
    runner = picked?.[0]?.fsPath;
    if (!runner) return;
  }

  const target = vscode.workspace.workspaceFolders?.length
    ? vscode.ConfigurationTarget.Workspace
    : vscode.ConfigurationTarget.Global;
  if (selected.action === "auto") {
    await configuration.update("runnerPath", undefined, target);
  } else {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Validating Sprout interpreter" },
      () => validateRunner(runner)
    );
    if (!result.ok) {
      vscode.window.showErrorMessage(`That file is not a working Sprout interpreter: ${result.message}`);
      return;
    }
    await configuration.update("runnerPath", runner, target);
    vscode.window.showInformationMessage(`Selected ${result.version}.`);
  }
  await updateInterpreterStatus(context);

  const reload = await vscode.window.showInformationMessage(
    "Reload VS Code to restart Sprout IntelliSense, tests, and debugging with this interpreter.",
    "Reload Window"
  );
  if (reload === "Reload Window") {
    vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}

function shellQuote(value) {
  const text = String(value);
  if (process.platform === "win32") {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return `'${text.replace(/'/g, `'\\''`)}'`;
}

async function runCurrentFile(context) {
  const document = activeSproutDocument();
  if (!document || document.uri.scheme !== "file") {
    vscode.window.showErrorMessage("Open a saved .sprout file before running it.");
    return;
  }
  if (document.isDirty) await document.save();
  const runner = findRunner(context, document);
  if (!runner) {
    const choose = await vscode.window.showErrorMessage(
      "No Sprout interpreter was found.",
      "Select Interpreter"
    );
    if (choose === "Select Interpreter") await selectInterpreter(context);
    return;
  }

  const terminal = vscode.window.terminals.find((item) => item.name === "Sprout")
    || vscode.window.createTerminal({ name: "Sprout", cwd: path.dirname(document.uri.fsPath) });
  terminal.show();
  terminal.sendText(
    `${shellQuote(pythonExecutable())} ${shellQuote(runner)} run ${shellQuote(document.uri.fsPath)}`,
    true
  );
}

function normalizeLineColumn(document, line, column) {
  const lineCount = document.lineCount;
  const safeLine = Math.max(0, Math.min(lineCount - 1, Number.isFinite(line) ? Math.floor(line) : 0));
  const lineText = document.lineAt(safeLine).text;
  let safeColumn = Number.isFinite(column) ? Math.floor(column) : 0;
  safeColumn = Math.max(0, Math.min(safeColumn, lineText.length));
  return { line: safeLine, column: safeColumn, lineText };
}

function inferDiagnosticRange(document, line, character) {
  const normalized = normalizeLineColumn(document, line, character);
  const { line: safeLine, column, lineText } = normalized;
  if (lineText.length === 0) {
    return new vscode.Range(safeLine, 0, safeLine, 0);
  }
  const before = lineText.slice(0, Math.max(0, column));
  const after = lineText.slice(Math.max(0, column));
  let start = Math.max(0, Math.min(column, lineText.length - 1));
  const beforeMatch = before.match(/([A-Za-z_][A-Za-z0-9_]*)$/);
  if (beforeMatch) {
    start = before.length - beforeMatch[1].length;
  } else if (/^[A-Za-z_][A-Za-z0-9_]*/.test(after)) {
    start = column;
  }
  const first = lineText[start] || "";
  let length = 1;
  if (/[A-Za-z_]/.test(first)) {
    let end = start + 1;
    while (end < lineText.length && /[A-Za-z0-9_]/.test(lineText[end])) {
      end += 1;
    }
    length = Math.max(1, end - start);
  }
  return new vscode.Range(safeLine, start, safeLine, Math.min(lineText.length, start + length));
}

function dedupeDiagnostics(items) {
  const seen = new Set();
  const deduped = [];
  for (const item of items) {
    if (!item || !item.range) continue;
    const key = [
      item.range.start.line,
      item.range.start.character,
      item.range.end.line,
      item.range.end.character,
      item.severity,
      item.code || "",
      item.message || "",
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

function mergeDiagnostics(items) {
  const bucket = new Map();
  for (const item of items) {
    if (!item || !item.range) continue;
    const key = [
      item.range.start.line,
      item.range.start.character,
      item.range.end.line,
      item.range.end.character,
      item.severity,
      item.code
    ].join("|");
    const existing = bucket.get(key);
    if (!existing) {
      bucket.set(key, item);
      continue;
    }
    if (item.severity === vscode.DiagnosticSeverity.Error && existing.severity !== vscode.DiagnosticSeverity.Error) {
      bucket.set(key, item);
      continue;
    }
    if (item.message && existing.message !== item.message) {
      existing.message = `${existing.message} • ${item.message}`;
    }
    if (Array.isArray(existing.tags) && item.tags) {
      existing.tags = Array.from(new Set(existing.tags.concat(item.tags)));
    }
  }
  return Array.from(bucket.values());
}

function diagnosticFromOutput(text, document) {
  const message = text.replace(/^error:\s*/, "").trim() || "Sprout check failed";
  const match = message.match(/ at (\d+):(\d+)(?:\s|$)/) || message.match(/line (\d+),\s*col (\d+)/i);
  const line = match ? Math.max(0, Number(match[1]) - 1) : 0;
  const character = match ? Math.max(0, Number(match[2]) - 1) : 0;
  const range = inferDiagnosticRange(document, line, character);
  return new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
}

function diagnosticFromJson(item, document) {
  let range = null;
  if (item?.range?.start && item?.range?.end) {
    const start = normalizeLineColumn(
      document,
      Number(item.range.start.line || 0),
      Number(item.range.start.character || 0)
    );
    const end = normalizeLineColumn(
      document,
      Number(item.range.end.line || 0),
      Number(item.range.end.character || 0)
    );
    range = new vscode.Range(start.line, start.column, end.line, end.column);
  } else {
    const line = Math.max(0, Number(item.line || 1) - 1);
    const character = Math.max(0, Number(item.col || 1) - 1);
    range = inferDiagnosticRange(document, line, character);
  }
  if (range.end.line === range.start.line && range.end.character <= range.start.character) {
    let lineText = "";
    try {
      lineText = document.lineAt(range.start.line).text;
    } catch (_error) {
      return null;
    }
    if (lineText.length === 0) {
      return null;
    }
    const startCharacter = Math.max(0, Math.min(range.start.character, lineText.length - 1));
    range = new vscode.Range(
      range.start.line,
      startCharacter,
      range.start.line,
      Math.min(lineText.length, startCharacter + 1)
    );
  }
  let severity = ({
    error: vscode.DiagnosticSeverity.Error,
    warning: vscode.DiagnosticSeverity.Warning,
    information: vscode.DiagnosticSeverity.Information,
    hint: vscode.DiagnosticSeverity.Hint
  })[item.severity] || vscode.DiagnosticSeverity.Warning;
  if (["SPROUT_ERROR", "SPROUT_SYNTAX", "SPROUT_IMPORT"].includes(String(item.code || ""))) {
    severity = vscode.DiagnosticSeverity.Error;
  }
  const diagnostic = new vscode.Diagnostic(range, item.message || "Sprout diagnostic", severity);
  diagnostic.code = item.code;
  diagnostic.source = "sprout";
  diagnostic.data = item.data || {};
  diagnostic.tags = (item.tags || []).map((tag) => {
    if (tag === 1 || tag === "unnecessary") return vscode.DiagnosticTag.Unnecessary;
    if (tag === 2 || tag === "deprecated") return vscode.DiagnosticTag.Deprecated;
    return undefined;
  }).filter(Boolean);
  return diagnostic;
}

function fallbackQuickFixes(document, diagnostics) {
  const actions = [];
  for (const diagnostic of diagnostics) {
    const replacement = diagnostic.data?.replacement || diagnostic.data?.suggestion;
    let title;
    let range = diagnostic.range;
    let newText = replacement;
    if (replacement && ["SPROUT_UNKNOWN_NAME", "SPROUT_UNKNOWN_MEMBER", "SPROUT_IMPORT"].includes(String(diagnostic.code))) {
      title = `Replace with '${replacement}'`;
    } else if (replacement && diagnostic.code === "SPROUT_UNKNOWN_ARGUMENT" && diagnostic.data?.parameter) {
      const line = document.lineAt(diagnostic.range.start.line).text;
      const name = String(diagnostic.data.parameter);
      const match = line.match(new RegExp(`\\b${name.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}(?=\\s*=)`));
      if (match && match.index !== undefined) {
        title = `Rename argument to '${replacement}'`;
        range = new vscode.Range(
          diagnostic.range.start.line,
          match.index,
          diagnostic.range.start.line,
          match.index + name.length
        );
      }
    } else if (diagnostic.code === "SPROUT_UNUSED_IMPORT") {
      title = "Remove unused import";
      const line = diagnostic.range.start.line;
      range = line + 1 < document.lineCount
        ? new vscode.Range(line, 0, line + 1, 0)
        : new vscode.Range(line, 0, line, document.lineAt(line).text.length);
      newText = "";
    } else if (diagnostic.code === "SPROUT_UNUSED_NAME" || diagnostic.code === "SPROUT_UNUSED_PARAMETER") {
      const wordRange = document.getWordRangeAtPosition(diagnostic.range.start);
      const word = wordRange ? document.getText(wordRange) : "";
      if (word && !word.startsWith("_")) {
        title = `Rename unused ${diagnostic.code === "SPROUT_UNUSED_PARAMETER" ? "parameter" : "name"} to _${word}`;
        range = wordRange;
        newText = `_${word}`;
      }
    } else if (diagnostic.code === "SPROUT_DUPLICATE_ARGUMENT" && diagnostic.data?.parameter) {
      const line = document.lineAt(diagnostic.range.start.line).text;
      const parameter = String(diagnostic.data.parameter);
      const duplicate = duplicateArgumentEditRange(line, parameter);
      if (duplicate) {
        title = `Remove duplicate argument '${parameter}'`;
        range = new vscode.Range(
          diagnostic.range.start.line,
          duplicate[0],
          diagnostic.range.start.line,
          duplicate[1]
        );
        newText = "";
      }
    } else if (diagnostic.code === "SPROUT_ARGUMENT_COUNT" && Array.isArray(diagnostic.data?.missing)) {
      const line = document.lineAt(diagnostic.range.start.line).text;
      const functionName = String(diagnostic.data?.function || "");
      const missing = diagnostic.data.missing.filter(Boolean);
      const nameIndex = functionName ? line.lastIndexOf(functionName, diagnostic.range.start.character) : -1;
      const openIndex = nameIndex >= 0 ? line.indexOf("(", nameIndex + functionName.length) : -1;
      const closeIndex = openIndex >= 0 ? line.indexOf(")", openIndex + 1) : -1;
      if (openIndex >= 0 && closeIndex >= openIndex) {
        const inner = line.slice(openIndex + 1, closeIndex);
        title = missing.length === 1 ? `Add missing argument '${missing[0]}'` : "Add missing required arguments";
        range = new vscode.Range(diagnostic.range.start.line, openIndex + 1, diagnostic.range.start.line, closeIndex);
        newText = inner.trim()
          ? `${inner.trimEnd()}, ${missing.map((name) => `${name}=nil`).join(", ")}`
          : missing.map((name) => `${name}=nil`).join(", ");
      }
    } else if (diagnostic.code === "SPROUT_TRAILING_WHITESPACE") {
      const line = document.lineAt(diagnostic.range.start.line).text;
      const stripped = line.replace(/[\t ]+$/, "");
      if (stripped !== line) {
        title = "Remove trailing whitespace";
        range = new vscode.Range(
          diagnostic.range.start.line,
          stripped.length,
          diagnostic.range.start.line,
          line.length
        );
        newText = "";
      }
    }
    if (!title || newText === undefined) continue;
    const action = new vscode.CodeAction(title, vscode.CodeActionKind.QuickFix);
    action.isPreferred = Boolean(replacement);
    action.diagnostics = [diagnostic];
    const edit = new vscode.WorkspaceEdit();
    edit.replace(document.uri, range, String(newText));
    action.edit = edit;
    actions.push(action);
  }
  return actions;
}

function rangeForMatch(document, line, start, length) {
  const lineText = document.lineAt(line).text;
  const safeStart = Math.max(0, Math.min(start, lineText.length));
  const safeEnd = Math.min(lineText.length, safeStart + Math.max(1, length));
  return new vscode.Range(line, safeStart, line, safeEnd);
}

function argumentValueEnd(lineText, start) {
  let depth = 0;
  let quote = "";
  let escaped = false;
  for (let index = start; index < lineText.length; index += 1) {
    const char = lineText[index];
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === quote) {
        quote = "";
      }
      continue;
    }
    if (char === "\"" || char === "'") {
      quote = char;
    } else if ("([{".includes(char)) {
      depth += 1;
    } else if (")]}".includes(char)) {
      if (depth === 0 && char === ")") {
        return index;
      }
      depth = Math.max(0, depth - 1);
    } else if (char === "," && depth === 0) {
      return index;
    }
  }
  return lineText.length;
}

function duplicateArgumentEditRange(lineText, parameter) {
  const escaped = parameter.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = lineText.match(new RegExp(`\\b${escaped}\\s*=`));
  if (!match || match.index === undefined) {
    return null;
  }
  const start = match.index;
  const end = argumentValueEnd(lineText, start + match[0].length);
  let removeStart = start;
  while (removeStart > 0 && /\s/.test(lineText[removeStart - 1])) {
    removeStart -= 1;
  }
  if (removeStart > 0 && lineText[removeStart - 1] === ",") {
    removeStart -= 1;
    while (removeStart > 0 && /\s/.test(lineText[removeStart - 1])) {
      removeStart -= 1;
    }
    return [removeStart, end];
  }
  let removeEnd = end;
  while (removeEnd < lineText.length && /\s/.test(lineText[removeEnd])) {
    removeEnd += 1;
  }
  if (removeEnd < lineText.length && lineText[removeEnd] === ",") {
    removeEnd += 1;
    while (removeEnd < lineText.length && /\s/.test(lineText[removeEnd])) {
      removeEnd += 1;
    }
  }
  return [start, removeEnd];
}

function styleDiagnostics(document) {
  if (!vscode.workspace.getConfiguration("sprout").get("diagnostics.styleWarnings")) {
    return [];
  }

  const warnings = [];
  for (let line = 0; line < document.lineCount; line += 1) {
    const text = document.lineAt(line).text;
    const trimmed = text.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const tabIndex = text.indexOf("\t");
    if (tabIndex !== -1) {
      const tabRun = text.slice(tabIndex).match(/^\t+/);
      const diagnostic = new vscode.Diagnostic(
        rangeForMatch(document, line, tabIndex, tabRun ? tabRun[0].length : 1),
        "Sprout style uses spaces for indentation.",
        vscode.DiagnosticSeverity.Warning
      );
      diagnostic.code = "SPROUT_TAB_INDENT";
      diagnostic.source = "sprout";
      warnings.push(diagnostic);
    }

    const stripped = text.replace(/[\t ]+$/, "");
    if (stripped !== text) {
      const diagnostic = new vscode.Diagnostic(
        new vscode.Range(line, stripped.length, line, text.length),
        "Remove trailing whitespace",
        vscode.DiagnosticSeverity.Warning
      );
      diagnostic.code = "SPROUT_TRAILING_WHITESPACE";
      diagnostic.source = "sprout";
      warnings.push(diagnostic);
    }
  }
  return warnings;
}

  function checkDocument(context, diagnostics, document) {
  if (document.languageId !== "sprout") return;
  if (usingLanguageServer()) return;
  if (!document.getText().trim()) {
    lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback diagnostics cleared for blank document ${document.uri.toString()}`);
    diagnostics.delete(document.uri);
    return;
  }
  if (!diagnosticsEnabled() || !diagnosticsVisible()) {
    diagnostics.delete(document.uri);
    return;
  }
  const requestedVersion = document.version;

  const runner = findRunner(context, document);
  if (!runner) {
    lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback diagnostics: no runner found for ${document.uri.toString()}`);
    diagnostics.set(document.uri, [
      new vscode.Diagnostic(
        new vscode.Range(0, 0, 0, 1),
        "Sprout diagnostics need sprout.py. Set sprout.runnerPath to enable checking.",
        vscode.DiagnosticSeverity.Information
      )
    ]);
    return;
  }

  const pythonPath = pythonExecutable();
  const tempPath = path.join(os.tmpdir(), `sprout-vscode-${process.pid}-${Date.now()}.sprout`);
  fs.writeFile(tempPath, document.getText(), "utf8", (writeError) => {
    if (writeError) {
      diagnostics.set(document.uri, [new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), String(writeError), vscode.DiagnosticSeverity.Error)]);
      return;
    }

    const targetPath = document.uri.scheme === "file" ? document.uri.fsPath : tempPath;
    const args = [
      runner,
      "intel",
      targetPath,
      "--kind",
      "diagnostics",
      "--line",
      "1",
      "--col",
      "1",
      "--source",
      tempPath
    ];

    childProcess.execFile(pythonPath, args, { timeout: 5000 }, (error, stdout, stderr) => {
      fs.unlink(tempPath, () => {});
      if (document.version !== requestedVersion) {
        lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Ignored stale fallback diagnostics for ${document.uri.toString()} requested=${requestedVersion} editor=${document.version}`);
        return;
      }
      if (!document.getText().trim()) {
        lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback diagnostics cleared after document became blank ${document.uri.toString()}`);
        diagnostics.delete(document.uri);
        return;
      }
      let parsed;
      try {
        parsed = JSON.parse(stdout || "{}");
      } catch (_jsonError) {
        parsed = undefined;
      }
      if (parsed && Array.isArray(parsed.diagnostics)) {
        const typoChecking = vscode.workspace.getConfiguration("sprout").get("diagnostics.typoChecking", true);
        const parsedDiagnostics = mergeDiagnostics(dedupeDiagnostics(parsed.diagnostics
          .filter((diag) => typoChecking || !(diag.data || {}).suggestion)
          .map((diag) => diagnosticFromJson(diag, document))
          .filter(Boolean)));
        const warnings = diagnosticsEnabled() && diagnosticsVisible() ? styleDiagnostics(document) : [];
        const allDiagnostics = mergeDiagnostics(dedupeDiagnostics(parsedDiagnostics.concat(warnings)));
        if (allDiagnostics.length > 0) {
          diagnostics.set(document.uri, allDiagnostics);
        } else {
          diagnostics.delete(document.uri);
        }
        lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback diagnostics for ${document.uri.toString()}: ${allDiagnostics.length}`);
        return;
      }
      if (!error) {
        const warningDiagnostics = styleDiagnostics(document);
        if (warningDiagnostics.length > 0) diagnostics.set(document.uri, mergeDiagnostics(warningDiagnostics));
        else diagnostics.delete(document.uri);
        lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback style diagnostics for ${document.uri.toString()}: ${warningDiagnostics.length}`);
        return;
      }
      lspOutputChannel?.appendLine(`[${new Date().toISOString()}] Fallback diagnostic command failed for ${document.uri.toString()}: ${String(stderr || stdout || error).trim()}`);
      diagnostics.set(document.uri, [diagnosticFromOutput(stderr || stdout || String(error), document)]);
    });
  });
}

function runIntelQuery(context, document, position, kind, token) {
  if (document.languageId !== "sprout") {
    return Promise.resolve(undefined);
  }
  if (languageClient?.ready) {
    const methods = {
      completions: "textDocument/completion",
      hover: "textDocument/hover",
      definition: "textDocument/definition",
      references: "textDocument/references",
      signature: "textDocument/signatureHelp"
    };
    const method = methods[kind];
    if (method) {
      const extra = kind === "references" ? { context: { includeDeclaration: true } } : {};
      return languageClient.textRequest(method, document, position, extra, token).then((result) => {
        if (kind === "completions") {
          const items = Array.isArray(result) ? result : (result?.items || []);
          return {
            ok: true,
            items
          };
        }
        if (kind === "hover") return { ok: true, lspHover: result };
        if (kind === "definition") {
          const locations = Array.isArray(result) ? result : (result ? [result] : []);
          return { ok: true, lspDefinition: locations[0] };
        }
        if (kind === "references") return { ok: true, lspReferences: result || [] };
        if (kind === "signature") return { ok: true, lspSignature: result };
        return undefined;
      }).catch(() => undefined);
    }
  }
  if (languageClient?.starting) {
    return Promise.resolve(undefined);
  }
  const runner = findRunner(context, document);
  if (!runner) {
    return Promise.resolve(undefined);
  }
  const pythonPath = pythonExecutable();
  const tempPath = path.join(os.tmpdir(), `sprout-vscode-intel-${process.pid}-${Date.now()}.sprout`);
  const targetPath = document.uri.scheme === "file" ? document.uri.fsPath : tempPath;
  const args = [
    runner,
    "intel",
    targetPath,
    "--kind",
    kind,
    "--line",
    String(position.line + 1),
    "--col",
    String(position.character + 1),
    "--source",
    tempPath
  ];

  return new Promise((resolve) => {
    fs.writeFile(tempPath, document.getText(), "utf8", (writeError) => {
      if (writeError) {
        resolve(undefined);
        return;
      }
      childProcess.execFile(pythonPath, args, { timeout: 5000 }, (_error, stdout) => {
        fs.unlink(tempPath, () => {});
        try {
          const parsed = JSON.parse(stdout || "{}");
          resolve(parsed && parsed.ok ? parsed : undefined);
        } catch (_jsonError) {
          resolve(undefined);
        }
      });
    });
  });
}

function semanticKind(kind) {
  const map = {
    "keyword": vscode.CompletionItemKind.Keyword,
    "function": vscode.CompletionItemKind.Function,
    "builtin": vscode.CompletionItemKind.Function,
    "method": vscode.CompletionItemKind.Method,
    "class": vscode.CompletionItemKind.Class,
    "interface": vscode.CompletionItemKind.Interface,
    "enum": vscode.CompletionItemKind.Enum,
    "enum-member": vscode.CompletionItemKind.EnumMember,
    "type": vscode.CompletionItemKind.TypeParameter,
    "module": vscode.CompletionItemKind.Module,
    "python-module": vscode.CompletionItemKind.Module,
    "variable": vscode.CompletionItemKind.Variable,
    "field": vscode.CompletionItemKind.Field
  };
  return map[kind] || vscode.CompletionItemKind.Variable;
}

function semanticKindNameFromLsp(kind) {
  const map = {
    2: "method",
    3: "function",
    5: "field",
    6: "variable",
    7: "class",
    8: "interface",
    9: "module",
    10: "field",
    13: "enum",
    14: "keyword",
    20: "enum-member",
    25: "type"
  };
  return map[kind] || "variable";
}

function semanticCompletion(symbol) {
  const label = symbol.label || symbol.name;
  const kind = typeof symbol.kind === "number" ? symbol.kind : semanticKind(symbol.kind);
  const item = new vscode.CompletionItem(label, kind);
  item.detail = symbol.signature || symbol.detail || symbol.qualifiedName || `Sprout ${symbol.kind || "symbol"}`;
  const documentation = typeof symbol.documentation === "string"
    ? symbol.documentation
    : symbol.documentation?.value || `Sprout ${symbol.kind || "symbol"}.`;
  item.documentation = new vscode.MarkdownString(documentation);
  item.sortText = symbol.sortText;
  item.filterText = symbol.filterText;
  if (symbol.insertText) {
    item.insertText = symbol.insertTextFormat === 2
      ? new vscode.SnippetString(symbol.insertText)
      : symbol.insertText;
  }
  if (symbol.textEdit?.range && symbol.textEdit.newText !== undefined) {
    item.textEdit = new vscode.TextEdit(
      new vscode.Range(
        symbol.textEdit.range.start.line,
        symbol.textEdit.range.start.character,
        symbol.textEdit.range.end.line,
        symbol.textEdit.range.end.character
      ),
      symbol.textEdit.newText
    );
  }
  if (!symbol.label && (symbol.kind === "function" || symbol.kind === "builtin" || symbol.kind === "method") && symbol.signature) {
    item.insertText = new vscode.SnippetString(`${symbol.name}($1)`);
  }
  return item;
}

function locationFromJson(location) {
  if (!location || !location.path) return undefined;
  const start = new vscode.Position(Math.max(0, Number(location.line || 1) - 1), Math.max(0, Number(location.col || 1) - 1));
  return new vscode.Location(vscode.Uri.file(location.path), new vscode.Range(start, start.translate(0, 1)));
}

function locationFromLsp(location) {
  if (!location || !location.uri || !location.range) return undefined;
  return new vscode.Location(
    vscode.Uri.parse(location.uri),
    new vscode.Range(
      location.range.start.line,
      location.range.start.character,
      location.range.end.line,
      location.range.end.character
    )
  );
}

async function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection("sprout");
  const timers = new Map();
  const runner = findRunner(context);
  let heartbeatTimer = null;
  lspOutputChannel = vscode.window.createOutputChannel("Sprout Language Server");
  lspOutputChannel.appendLine(`[${new Date().toISOString()}] Sprout extension activating`);
  interpreterStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  interpreterStatus.command = "sprout.selectInterpreter";
  interpreterStatus.name = "Sprout Interpreter";
  context.subscriptions.push(
    interpreterStatus,
    lspOutputChannel,
    vscode.commands.registerCommand("sprout.smartEnter", async () => {
      if (await handleSproutSmartEnter()) return;
      await vscode.commands.executeCommand("default:type", { text: "\n" });
    }),
    vscode.commands.registerCommand("sprout.selectInterpreter", () => selectInterpreter(context)),
    vscode.commands.registerCommand("sprout.runCurrentFile", () => runCurrentFile(context)),
    vscode.commands.registerCommand("sprout.showLanguageServerOutput", () => lspOutputChannel.show()),
    vscode.commands.registerCommand("sprout.restartLanguageServer", async () => {
      lspOutputChannel.show(true);
      lspOutputChannel.appendLine(`[${new Date().toISOString()}] Restart requested`);
      if (languageClient) {
        await languageClient.stop();
        languageClient = undefined;
      }
      const currentRunner = findRunner(context, activeSproutDocument());
      const lspEnabledNow = vscode.workspace.getConfiguration("sprout").get("languageServer.enabled");
      if (!currentRunner || lspEnabledNow === false) {
        lspOutputChannel.appendLine(`[${new Date().toISOString()}] Restart skipped: ${currentRunner ? "language server disabled" : "no Sprout interpreter found"}`);
        for (const document of vscode.workspace.textDocuments) scheduleCheck(document, { forceFallback: true });
        return;
      }
      const client = new SproutLanguageClient(
        vscode,
        pythonExecutable(),
        currentRunner,
        context.extensionPath,
        diagnostics,
        lspOutputChannel
      );
      try {
      if (await client.start()) {
          languageClient = client;
          diagnostics.clear();
          for (const document of vscode.workspace.textDocuments) client.open(document);
          if (heartbeatTimer) clearInterval(heartbeatTimer);
          heartbeatTimer = setInterval(() => {
            languageClient?.heartbeat(vscode.workspace.textDocuments);
          }, LSP_HEARTBEAT_MS);
        }
      } catch (error) {
        lspOutputChannel.appendLine(`[${new Date().toISOString()}] Restart failed; using fallback providers: ${error}`);
      }
    }),
    vscode.commands.registerCommand("sprout.showAnalysisStatus", async () => {
      const document = activeSproutDocument();
      if (!languageClient?.ready) {
        vscode.window.showWarningMessage("Sprout language server is not running.");
        return;
      }
      try {
        const status = await languageClient.analysisStatus(document);
        lspOutputChannel.show(true);
        lspOutputChannel.appendLine(`[${new Date().toISOString()}] Analysis status requested`);
        lspOutputChannel.appendLine(formatAnalysisStatus(status));
        vscode.window.showInformationMessage("Sprout analysis status written to the Sprout Language Server output.");
      } catch (error) {
        vscode.window.showErrorMessage(`Sprout analysis status failed: ${error.message || error}`);
      }
    }),
    vscode.commands.registerCommand("sprout.rebuildWorkspaceIndex", async () => {
      const document = activeSproutDocument();
      if (!languageClient?.ready) {
        vscode.window.showWarningMessage("Sprout language server is not running.");
        return;
      }
      try {
        const status = await languageClient.rebuildWorkspaceIndex(document);
        lspOutputChannel.show(true);
        lspOutputChannel.appendLine(`[${new Date().toISOString()}] Workspace index rebuild requested`);
        lspOutputChannel.appendLine(formatAnalysisStatus(status));
        vscode.window.showInformationMessage(`Sprout rebuilt ${status?.lastReindexedFiles?.length || 0} indexed files.`);
      } catch (error) {
        vscode.window.showErrorMessage(`Sprout workspace rebuild failed: ${error.message || error}`);
      }
    }),
    vscode.window.onDidChangeActiveTextEditor(() => {
      updateInterpreterStatus(context);
      ensureVisibleSproutDiagnostics();
    }),
    vscode.window.onDidChangeVisibleTextEditors(() => ensureVisibleSproutDiagnostics()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("sprout.runnerPath") || event.affectsConfiguration("sprout.pythonPath")) {
        if (event.affectsConfiguration("sprout.pythonPath")) {
          installedRunnerCache.clear();
        }
        updateInterpreterStatus(context);
      }
      if (
        event.affectsConfiguration("sprout.diagnostics")
        || event.affectsConfiguration("sprout.analysis")
      ) {
        languageClient?.configure();
        for (const document of vscode.workspace.textDocuments) scheduleCheck(document);
        ensureVisibleSproutDiagnostics();
      }
    })
  );
  await updateInterpreterStatus(context);
  await createSproutTestController(vscode, context, runner, pythonExecutable());
  const lspEnabled = vscode.workspace.getConfiguration("sprout").get("languageServer.enabled");
  if (runner && lspEnabled !== false) {
    const client = new SproutLanguageClient(
      vscode,
      pythonExecutable(),
      runner,
      context.extensionPath,
      diagnostics,
      lspOutputChannel
    );
    try {
      if (await client.start()) {
        languageClient = client;
        diagnostics.clear();
        context.subscriptions.push({ dispose: () => client.stop() });
        for (const document of vscode.workspace.textDocuments) client.open(document);
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        heartbeatTimer = setInterval(() => {
          languageClient?.heartbeat(vscode.workspace.textDocuments);
        }, LSP_HEARTBEAT_MS);
      }
    } catch (error) {
      lspOutputChannel.appendLine(`[${new Date().toISOString()}] Falling back to command-based tooling: ${error}`);
    }
  } else {
    lspOutputChannel.appendLine(`[${new Date().toISOString()}] Language server not started: ${runner ? "disabled by setting" : "no runner found"}`);
  }

  const debugAdapter = findDebugAdapter(context, runner);
  if (debugAdapter) {
    context.subscriptions.push(
      vscode.debug.registerDebugAdapterDescriptorFactory("sprout", {
        createDebugAdapterDescriptor() {
          return new vscode.DebugAdapterExecutable(pythonExecutable(), [debugAdapter]);
        }
      }),
      vscode.debug.registerDebugConfigurationProvider("sprout", {
        resolveDebugConfiguration(_folder, config) {
          const resolved = { ...config };
          resolved.type = "sprout";
          resolved.request = "launch";
          resolved.name = resolved.name || "Debug Sprout file";
          if (!resolved.program && vscode.window.activeTextEditor?.document.languageId === "sprout") {
            resolved.program = vscode.window.activeTextEditor.document.uri.fsPath;
          }
          resolved.args = resolved.args || [];
          resolved.stopOnEntry = Boolean(resolved.stopOnEntry);
          if (!resolved.program) {
            vscode.window.showErrorMessage("Open a Sprout file or set 'program' in launch.json.");
            return undefined;
          }
          return resolved;
        }
      })
    );
  }

  function scheduleCheck(document, options = {}) {
    if (document.languageId !== "sprout") return;
    if (usingLanguageServer() && !options.forceFallback) return;
    const key = document.uri.toString();
    clearTimeout(timers.get(key));
    const delay = options.immediate ? 0 : DIAGNOSTIC_DEBOUNCE_MS;
    timers.set(key, setTimeout(() => {
      checkDocument(
        context,
        diagnostics,
        document
      );
    }, delay));
  }

  function ensureVisibleSproutDiagnostics() {
    const diagEnabled = diagnosticsEnabled();
    const visible = diagnosticsVisible();
    for (const editor of vscode.window.visibleTextEditors) {
      const document = editor.document;
      if (document.languageId !== "sprout") continue;
      languageClient?.open(document);
      if (!diagEnabled || !visible) {
        diagnostics.delete(document.uri);
        clearTimeout(timers.get(document.uri.toString()));
        continue;
      }
      if (!document.getText().trim()) {
        diagnostics.delete(document.uri);
        clearTimeout(timers.get(document.uri.toString()));
      } else if (!usingLanguageServer() && (diagnostics.get(document.uri) || []).length === 0) {
        scheduleCheck(document, { forceFallback: true });
      }
    }
  }

  const provider = vscode.languages.registerCompletionItemProvider(
    "sprout",
    {
      async provideCompletionItems(document, position, token, completionContext) {
        const lineText = document.lineAt(position).text;
        const before = lineText.slice(0, position.character);
        const exactImportKeyword = /^\s*(import|importpython)$/.test(before);
        const trigger = completionContext?.triggerCharacter;
        const importContext = importCompletionContext(lineText, position.character);
        const usingLsp = usingLanguageServer();
        const previousChar = before.slice(-1);
        const isAfterImportDot = before.endsWith(".");
        const aliasMatch = isAfterImportDot ? before.match(/([A-Za-z_][A-Za-z0-9_]*)\.\s*$/) : null;
        const shouldSkipSpace = trigger === " " && !importContext && !isAfterImportDot && previousChar.trim().length === 0;
        if (shouldSkipSpace || exactImportKeyword) {
          return [];
        }

        if (usingLsp) {
          const semantic = await runIntelQuery(context, document, position, "completions", token);
          const lspItems = Array.isArray(semantic?.items) ? semantic.items.map(semanticCompletion) : [];
          const finalized = finalizeCompletionEntries(lspItems, lineText, position.character, {
            allowExactWord: Boolean(importContext || isAfterImportDot)
          });
          if (finalized.length > 0) {
            return finalized;
          }
          return localCompletionFallback(context, document, lineText, position, importContext, isAfterImportDot, aliasMatch);
        }

        const semantic = await runIntelQuery(context, document, position, "completions", token);
        if (Array.isArray(semantic?.items) && semantic.items.length > 0) {
          return finalizeCompletionEntries(
            semantic.items.map(semanticCompletion),
            lineText,
            position.character,
            { allowExactWord: Boolean(importContext || isAfterImportDot) }
          );
        }

        return localCompletionFallback(context, document, lineText, position, importContext, isAfterImportDot, aliasMatch);
      }
    },
    ".",
    " ",
    "\"",
    "/"
  );

  const hover = vscode.languages.registerHoverProvider("sprout", {
    provideHover(document, position, token) {
      return runIntelQuery(context, document, position, "hover", token).then((semantic) => {
        if (semantic?.lspHover?.contents) {
          const contents = semantic.lspHover.contents;
          const value = typeof contents === "string" ? contents : contents.value;
          return value ? new vscode.Hover(new vscode.MarkdownString(value)) : undefined;
        }
        if (usingLanguageServer()) return undefined;
        if (semantic && semantic.symbol) {
          const symbol = semantic.symbol;
          const label = symbol.signature || symbol.qualifiedName || symbol.name;
          const docs = symbol.documentation || `Sprout ${symbol.kind}.`;
          const defined = symbol.location && symbol.location.path && !symbol.location.path.startsWith("<")
            ? `\n\nDefined at \`${symbol.location.path}:${symbol.location.line}:${symbol.location.col}\`.`
            : "";
          return new vscode.Hover(new vscode.MarkdownString(`**${label}**\n\n${docs}${defined}`));
        }
        if (findRunner(context, document)) return undefined;

      const range = document.getWordRangeAtPosition(position);
      if (!range) return undefined;
      const word = document.getText(range);
      const found = completeTopLevelEntries.find(([label]) => label === word);
      if (!found) return undefined;
      return new vscode.Hover(new vscode.MarkdownString(`**${found[0]}**\n\n${found[1]}`), range);
      });
    }
  });

  const definition = vscode.languages.registerDefinitionProvider("sprout", {
    provideDefinition(document, position, token) {
      return runIntelQuery(context, document, position, "definition", token).then((semantic) => (
        locationFromLsp(semantic?.lspDefinition) || locationFromJson(semantic && semantic.definition)
      ));
    }
  });

  const references = vscode.languages.registerReferenceProvider("sprout", {
    provideReferences(document, position, _context, token) {
      return runIntelQuery(context, document, position, "references", token).then((semantic) => {
        if (semantic?.lspReferences) {
          return semantic.lspReferences.map(locationFromLsp).filter(Boolean);
        }
        if (!semantic || !Array.isArray(semantic.references)) return [];
        return semantic.references.map((ref) => locationFromJson(ref.location)).filter(Boolean);
      });
    }
  });

  const rename = vscode.languages.registerRenameProvider("sprout", {
    prepareRename(document, position, token) {
      if (!languageClient?.ready) {
        if (languageClient?.starting) return undefined;
        return document.getWordRangeAtPosition(position);
      }
      return languageClient.textRequest("textDocument/prepareRename", document, position, {}, token).then((result) => {
        if (!result?.range) return undefined;
        return new vscode.Range(
          result.range.start.line,
          result.range.start.character,
          result.range.end.line,
          result.range.end.character
        );
      });
    },
    provideRenameEdits(document, position, newName, token) {
      if (languageClient?.ready) {
        return languageClient.textRequest("textDocument/rename", document, position, { newName }, token).then((result) => {
          const edit = new vscode.WorkspaceEdit();
          for (const [uri, edits] of Object.entries(result?.changes || {})) {
            for (const item of edits) {
              edit.replace(
                vscode.Uri.parse(uri),
                new vscode.Range(
                  item.range.start.line,
                  item.range.start.character,
                  item.range.end.line,
                  item.range.end.character
                ),
                item.newText
              );
            }
          }
          return edit;
        });
      }
      return runIntelQuery(context, document, position, "references", token).then((semantic) => {
        const edit = new vscode.WorkspaceEdit();
        if (semantic?.lspReferences) {
          const wordRange = document.getWordRangeAtPosition(position);
          const word = wordRange ? document.getText(wordRange) : "";
          for (const ref of semantic.lspReferences) {
            const location = locationFromLsp(ref);
            if (!location) continue;
            edit.replace(location.uri, location.range, newName);
          }
          return edit;
        }
        if (!semantic || !Array.isArray(semantic.references) || !semantic.word) return edit;
        for (const ref of semantic.references) {
          const location = ref.location;
          if (!location || !location.path) continue;
          const start = new vscode.Position(Math.max(0, Number(location.line || 1) - 1), Math.max(0, Number(location.col || 1) - 1));
          const range = new vscode.Range(start, start.translate(0, semantic.word.length));
          edit.replace(vscode.Uri.file(location.path), range, newName);
        }
        return edit;
      });
    }
  });

  const signature = vscode.languages.registerSignatureHelpProvider(
    "sprout",
    {
      provideSignatureHelp(document, position, token) {
        return runIntelQuery(context, document, position, "signature", token).then((semantic) => {
          if (semantic?.lspSignature?.signatures?.length) {
            const result = semantic.lspSignature;
            const help = new vscode.SignatureHelp();
            help.signatures = result.signatures.map((signature) => {
              const info = new vscode.SignatureInformation(
                signature.label,
                new vscode.MarkdownString(
                  typeof signature.documentation === "string"
                    ? signature.documentation
                    : signature.documentation?.value || ""
                )
              );
              info.parameters = (signature.parameters || []).map((parameter) => {
                const label = Array.isArray(parameter.label)
                  ? signature.label.slice(parameter.label[0], parameter.label[1])
                  : parameter.label;
                return new vscode.ParameterInformation(
                  label,
                  new vscode.MarkdownString(
                    typeof parameter.documentation === "string"
                      ? parameter.documentation
                      : parameter.documentation?.value || ""
                  )
                );
              });
              return info;
            });
            help.activeSignature = result.activeSignature || 0;
            help.activeParameter = result.activeParameter || 0;
            return help;
          }
          if (!semantic || !semantic.signature) return undefined;
          const help = new vscode.SignatureHelp();
          const info = new vscode.SignatureInformation(
            semantic.signature.signature || semantic.signature.name,
            new vscode.MarkdownString(semantic.signature.documentation || "")
          );
          help.signatures = [info];
          help.activeSignature = 0;
          help.activeParameter = 0;
          return help;
        });
      }
    },
    "(",
    ","
  );

  const codeActions = vscode.languages.registerCodeActionsProvider(
    "sprout",
    {
      provideCodeActions(document, range, context, token) {
        if (!languageClient?.ready) {
          if (languageClient?.starting) return [];
          return fallbackQuickFixes(document, context.diagnostics);
        }
        const diagnosticsPayload = context.diagnostics.map((diagnostic) => ({
          range: {
            start: { line: diagnostic.range.start.line, character: diagnostic.range.start.character },
            end: { line: diagnostic.range.end.line, character: diagnostic.range.end.character }
          },
          severity: diagnosticSeverityToLsp(diagnostic.severity),
          code: diagnostic.code,
          source: diagnostic.source || "sprout",
          message: diagnostic.message,
          data: diagnostic.data || {}
        }));
        return languageClient.request("textDocument/codeAction", {
          textDocument: { uri: document.uri.toString() },
          range: {
            start: { line: range.start.line, character: range.start.character },
            end: { line: range.end.line, character: range.end.character }
          },
          context: { diagnostics: diagnosticsPayload, only: ["quickfix"] }
        }, token).then((items) => (items || []).map((item) => {
          const action = new vscode.CodeAction(item.title, vscode.CodeActionKind.QuickFix);
          action.isPreferred = Boolean(item.isPreferred);
          action.diagnostics = context.diagnostics.filter((diagnostic) => (
            (item.diagnostics || []).some((candidate) => candidate.code === diagnostic.code)
          ));
          const edit = new vscode.WorkspaceEdit();
          for (const [uri, changes] of Object.entries(item.edit?.changes || {})) {
            for (const change of changes) {
              edit.replace(
                vscode.Uri.parse(uri),
                new vscode.Range(
                  change.range.start.line,
                  change.range.start.character,
                  change.range.end.line,
                  change.range.end.character
                ),
                change.newText
              );
            }
          }
          action.edit = edit;
          return action;
        }));
      }
    },
    { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
  );

  const semanticTokens = vscode.languages.registerDocumentSemanticTokensProvider(
    { language: "sprout" },
    {
      async provideDocumentSemanticTokens(document, token) {
        if (languageClient?.ready) {
          const payload = await languageClient.semanticTokens(document, token).catch(() => undefined);
          if (payload && Array.isArray(payload.data)) {
            return new vscode.SemanticTokens(new Uint32Array(payload.data), semanticLegend);
          }
        }
        return new vscode.SemanticTokensBuilder(semanticLegend).build();
      }
    },
    semanticLegend
  );

  const folding = vscode.languages.registerFoldingRangeProvider("sprout", {
    provideFoldingRanges(document) {
      return computeSproutFoldingRanges(document.getText()).map((range) => (
        new vscode.FoldingRange(range.start, range.end, vscode.FoldingRangeKind.Region)
      ));
    }
  });

  context.subscriptions.push(
    { dispose: () => { if (heartbeatTimer) clearInterval(heartbeatTimer); } },
    provider,
    hover,
    definition,
    references,
    rename,
    signature,
    codeActions,
    semanticTokens,
    folding,
    diagnostics,
    vscode.workspace.onDidOpenTextDocument((document) => {
      languageClient?.open(document);
      if (!usingLanguageServer()) {
        scheduleCheck(document);
      }
    }),
    vscode.workspace.onDidSaveTextDocument((document) => {
      languageClient?.save(document);
      if (!usingLanguageServer()) {
        scheduleCheck(document);
      }
    }),
    vscode.workspace.onDidChangeTextDocument((event) => {
      languageClient?.change(event);
      if (event.document.languageId === "sprout") {
        clearTimeout(timers.get(event.document.uri.toString()));
        if (!usingLanguageServer()) {
          const immediate = event.contentChanges.some((change) => (
            String(change.text || "").includes("\n")
            || String(change.text || "").length >= 8
            || Number(change.rangeLength || 0) > 1
          ));
          scheduleCheck(event.document, { immediate });
        }
        return;
      }
    }),
    vscode.workspace.onDidCloseTextDocument((document) => {
      languageClient?.close(document);
      diagnostics.delete(document.uri);
    })
  );

  for (const document of vscode.workspace.textDocuments) {
    if (!usingLanguageServer()) {
      scheduleCheck(document);
    }
  }
}

async function deactivate() {
  if (languageClient) await languageClient.stop();
  languageClient = undefined;
}

module.exports = {
  activate,
  deactivate,
  computeSproutFoldingRanges,
  computeSproutFoldingRangesFromLines,
};
