const vscode = require("vscode");
const childProcess = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

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
  ["if", "Run a block when a condition is truthy.", "if ${1:condition}:\n  ${2}"],
  ["else", "Fallback branch for if.", "else:\n  ${1}"],
  ["while", "Loop while a condition is truthy.", "while ${1:condition}:\n  ${2}"],
  ["for", "Loop over arrays, strings, ranges, or dictionary keys.", "for ${1:item} in ${2:items}:\n  ${3}"],
  ["try", "Catch Sprout errors and raised values.", "try:\n  ${1}\ncatch ${2:err}:\n  ${3:say err}"],
  ["import", "Import another .sprout file.", "import \"${1:modules/gamekit.sprout}\" as ${2:game}"],
  ["importpython", "Import a Python standard-library module.", "importpython ${1:math}"],
  ["super", "Call a parent class method from a subclass.", "super.${1:method}(${2})"],
  ["return", "Return a value from a function.", "return ${1:value}"],
  ["pluck", "Sprout-flavored return.", "pluck ${1:value}"],
  ["end", "End a garden-style bloom block."],
  ["true", "Boolean true."],
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
];

const keywordEntries = [
  ["def", "Define a Python-style Sprout function.", "def ${1:name}(${2:args}):\n  ${3}"],
  ["fn", "Define a Sprout function.", "fn ${1:name}(${2:args}):\n  ${3}"],
  ["bloom", "Define a garden-flavored function or open a garden block.", "bloom ${1:name}(${2:args}):\n  ${3}"],
  ["seedfn", "Create a tiny inline Sprout function.", "seedfn ${1:x}: ${2:x}"],
  ["defbloom", "Define a garden-style Sprout function.", "def ${1:name}(${2:args}) bloom\n  ${3}\nend"],
  ["defbraces", "Define an old-compatible brace-style function.", "def ${1:name}(${2:args}) {\n  ${3}\n}"],
  ["class", "Define a Sprout class.", "class ${1:Name}:\n  def init(self${2:, value}):\n    ${3}"],
  ["extends", "Define a class that inherits from another class.", "class ${1:Child} extends ${2:Parent}:\n  def init(self${3:, value}):\n    super.init(${4:value})\n    ${5}"],
  ["if", "Run a block when a condition is truthy.", "if ${1:condition}:\n  ${2}"],
  ["elif", "Add another conditional branch.", "elif ${1:condition}:\n  ${2}"],
  ["else", "Fallback branch for if.", "else:\n  ${1}"],
  ["while", "Loop while a condition is truthy.", "while ${1:condition}:\n  ${2}"],
  ["whirl", "Garden-flavored while loop.", "whirl ${1:condition}:\n  ${2}"],
  ["for", "Loop over arrays, strings, ranges, or dictionary keys.", "for ${1:item} in ${2:items}:\n  ${3}"],
  ["each", "Garden-flavored for loop.", "each ${1:item} in ${2:items} bloom\n  ${3}\nend"],
  ["try", "Catch Sprout errors and raised values.", "try:\n  ${1}\ncatch ${2:err}:\n  ${3:say err}"],
  ["catch", "Handle a Sprout try block error.", "catch ${1:err}:\n  ${2}"],
  ["raise", "Raise a value as a recoverable Sprout error.", "raise ${1:value}"],
  ["return", "Return a value from a function.", "return ${1:value}"],
  ["pluck", "Garden-flavored return.", "pluck ${1:value}"],
  ["break", "Exit the nearest loop.", "break"],
  ["continue", "Skip to the next loop iteration.", "continue"],
  ["import", "Import another .sprout file.", "import \"${1:modules/gamekit.sprout}\" as ${2:game}"],
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
  ["true", "Boolean true.", "true"],
  ["false", "Boolean false.", "false"],
  ["nil", "No value.", "nil"],
  ["none", "No value alias.", "none"],
  ["True", "Python-style true alias.", "True"],
  ["False", "Python-style false alias.", "False"],
  ["None", "Python-style nil alias.", "None"]
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
  ["camera", "Create a simple 2D camera.", "camera(${1:position}, zoom=${2:1})"],
  ["world_to_screen", "Convert a world point through a 2D camera.", "world_to_screen(${1:point}, ${2:camera}, ${3:canvas})"],
  ["plot_world", "Draw a world-space point through a 2D camera.", "plot_world(${1:canvas}, ${2:point}, ${3:camera}, char=${4:\"#\"})"],
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

const allBuiltinNames = [
  "abs", "acos", "appendfile", "array", "asin", "ask", "atan", "atan2", "avg", "basename", "between", "bundle",
  "ceil", "chant", "chars", "choose", "chunks", "clamp", "clear", "compact", "concat", "contains", "copy", "cos",
  "countby", "cwd", "degrees", "delkey", "dice", "dict", "dirname", "dist", "drop", "endswith", "ensure", "enumerate",
  "exists", "exp", "extname", "fail", "fill", "first", "flatten", "floor", "frompairs", "functions", "get", "grow",
  "harvest", "has", "hypot", "indexof", "insert", "int", "is_array", "is_bool", "is_class", "is_dict", "is_empty",
  "is_even", "is_function", "is_instance", "is_nil", "is_number", "is_odd", "is_string", "isdir", "isfile", "items",
  "join", "joinpath", "json_parse", "json_stringify", "keys", "last", "len", "lerp", "lines", "listdir", "log", "log10",
  "lower", "ltrim", "max", "median", "merge", "methods", "min", "mirror", "mkdir", "now", "num", "omit", "padleft",
  "padright", "pick", "plant", "pow", "print", "prune", "push", "py_available", "py_import", "radians", "rand", "randint", "range", "readfile",
  "readjson", "remove", "repeat", "replace", "rest", "reverse", "round", "rtrim", "sample", "say", "seed", "shout",
  "shuffle", "sign", "sin", "sleep", "slice", "sort", "sparkle", "sprinkle", "sqrt", "startswith", "str", "substr",
  "sum", "take", "tan", "title", "trim", "type", "unique", "upper", "values", "weave", "whisper", "words", "wrap",
  "writefile", "writejson", "zipbud"
];

const allEngineNames = [
  "vec3", "vadd", "vsub", "vscale", "dot", "cross", "length", "normalize", "mesh", "cube", "edge_key", "unique_edges",
  "parse_face_index", "obj_record", "obj_mesh", "load_obj", "translate_mesh", "scale_mesh", "rotate_x", "rotate_y",
  "rotate_z", "rotate_mesh", "camera", "look_at_camera", "orbit_camera", "world_to_camera", "project", "make_frame",
  "make_zbuffer", "plot", "line", "edge_value", "shade_char", "face_normal", "draw_triangle", "render_solid",
  "render_wireframe", "frame_to_text", "bounds"
];

const allGeometryNames = [
  "vec2", "rect", "circle", "vadd", "vsub", "vscale", "dot", "length", "normalize", "distance", "angle", "from_angle",
  "lerp_vec", "midpoint", "move_toward", "clamp_vec", "rect_center", "point_in_rect", "rects_overlap", "point_in_circle",
  "circle_overlap", "nearest_point_on_rect", "circle_rect_overlap", "bounds"
];

const allCanvasNames = [
  "make_canvas", "clear", "plot", "line", "stroke_rect", "fill_rect", "circle", "fill_circle", "text", "sprite",
  "camera", "world_to_screen", "plot_world", "frame_to_text"
];

const allPixelGardenNames = [
  "vec2", "rect", "circle_shape", "vadd", "vsub", "vscale", "distance", "move_toward", "rects_overlap",
  "circle_rect_overlap", "bounds", "canvas", "clear", "plot", "line", "stroke_rect", "fill_rect", "circle",
  "fill_circle", "text", "sprite", "camera", "plot_world", "frame_to_text"
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
  "print": null,
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

function completion(label, docs, insertText, kind = vscode.CompletionItemKind.Function) {
  const item = new vscode.CompletionItem(label, kind);
  item.detail = "Sprout";
  item.documentation = new vscode.MarkdownString(docs || "");
  if (insertText) {
    item.insertText = new vscode.SnippetString(insertText);
  }
  return item;
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

function findRunner(context, document) {
  const configured = vscode.workspace.getConfiguration("sprout").get("runnerPath");
  if (configured && fs.existsSync(configured)) {
    return configured;
  }

  const extensionRunner = path.join(context.extensionPath, "sprout.py");
  if (fs.existsSync(extensionRunner)) {
    return extensionRunner;
  }

  const developmentRunner = path.resolve(context.extensionPath, "..", "..", "sprout.py");
  if (fs.existsSync(developmentRunner)) {
    return developmentRunner;
  }

  if (document && document.uri.scheme === "file") {
    const documentRunner = findUp(path.dirname(document.uri.fsPath), "sprout.py");
    if (documentRunner) {
      return documentRunner;
    }
  }

  for (const folder of vscode.workspace.workspaceFolders || []) {
    const workspaceRunner = findUp(folder.uri.fsPath, "sprout.py");
    if (fs.existsSync(workspaceRunner)) {
      return workspaceRunner;
    }
  }

  return undefined;
}

function diagnosticFromOutput(text, document) {
  const message = text.replace(/^error:\s*/, "").trim() || "Sprout check failed";
  const match = message.match(/ at (\d+):(\d+)$/);
  let line = 0;
  let character = 0;
  if (match) {
    line = Math.max(0, Number(match[1]) - 1);
    character = Math.max(0, Number(match[2]) - 1);
  }
  const lineText = document.lineAt(Math.min(line, document.lineCount - 1)).text;
  const end = Math.min(lineText.length, character + 1);
  const range = new vscode.Range(line, character, line, end);
  return new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
}

function diagnosticFromJson(item, document) {
  const line = Math.max(0, Number(item.line || 1) - 1);
  const character = Math.max(0, Number(item.col || 1) - 1);
  const lineText = document.lineAt(Math.min(line, document.lineCount - 1)).text;
  const end = Math.min(lineText.length, character + 1);
  const severity = item.severity === "warning" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error;
  const diagnostic = new vscode.Diagnostic(new vscode.Range(line, character, line, end), item.message || "Sprout diagnostic", severity);
  diagnostic.code = item.code;
  diagnostic.source = "sprout";
  return diagnostic;
}

function rangeForMatch(document, line, start, length) {
  const lineText = document.lineAt(line).text;
  const safeStart = Math.min(start, lineText.length);
  const safeEnd = Math.min(lineText.length, safeStart + Math.max(1, length));
  return new vscode.Range(line, safeStart, line, safeEnd);
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
      warnings.push(
        new vscode.Diagnostic(
          rangeForMatch(document, line, tabIndex, 1),
          "Sprout style uses spaces for indentation.",
          vscode.DiagnosticSeverity.Warning
        )
      );
    }

    const pythonAlias = text.match(/\b(True|False|None)\b/);
    if (pythonAlias) {
      warnings.push(
        new vscode.Diagnostic(
          rangeForMatch(document, line, pythonAlias.index, pythonAlias[0].length),
          "Sprout style usually uses true, false, or nil here.",
          vscode.DiagnosticSeverity.Warning
        )
      );
    }
  }
  return warnings;
}

function checkDocument(context, diagnostics, document) {
  if (document.languageId !== "sprout") return;
  if (!vscode.workspace.getConfiguration("sprout").get("diagnostics.enabled")) {
    diagnostics.delete(document.uri);
    return;
  }

  const runner = findRunner(context, document);
  if (!runner) {
    diagnostics.set(document.uri, [
      new vscode.Diagnostic(
        new vscode.Range(0, 0, 0, 1),
        "Sprout diagnostics need sprout.py. Set sprout.runnerPath to enable checking.",
        vscode.DiagnosticSeverity.Information
      )
    ]);
    return;
  }

  const pythonPath = vscode.workspace.getConfiguration("sprout").get("pythonPath") || "python3";
  const tempPath = path.join(os.tmpdir(), `sprout-vscode-${process.pid}-${Date.now()}.sprout`);
  fs.writeFile(tempPath, document.getText(), "utf8", (writeError) => {
    if (writeError) {
      diagnostics.set(document.uri, [new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), String(writeError), vscode.DiagnosticSeverity.Error)]);
      return;
    }

    childProcess.execFile(pythonPath, [runner, "check", tempPath, "--json"], { timeout: 5000 }, (error, stdout, stderr) => {
      fs.unlink(tempPath, () => {});
      let parsed;
      try {
        parsed = JSON.parse(stdout || "{}");
      } catch (_jsonError) {
        parsed = undefined;
      }
      if (parsed && Array.isArray(parsed.diagnostics)) {
        const parsedDiagnostics = parsed.diagnostics.map((diag) => diagnosticFromJson(diag, document));
        const warnings = styleDiagnostics(document);
        const allDiagnostics = parsedDiagnostics.concat(error ? [] : warnings);
        if (allDiagnostics.length > 0) {
          diagnostics.set(document.uri, allDiagnostics);
        } else {
          diagnostics.delete(document.uri);
        }
        return;
      }
      if (!error) {
        const warnings = styleDiagnostics(document);
        if (warnings.length > 0) diagnostics.set(document.uri, warnings);
        else diagnostics.delete(document.uri);
        return;
      }
      diagnostics.set(document.uri, [diagnosticFromOutput(stderr || stdout || String(error), document)]);
    });
  });
}

function runIntelQuery(context, document, position, kind) {
  if (document.languageId !== "sprout") {
    return Promise.resolve(undefined);
  }
  const runner = findRunner(context, document);
  if (!runner) {
    return Promise.resolve(undefined);
  }
  const pythonPath = vscode.workspace.getConfiguration("sprout").get("pythonPath") || "python3";
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
    "function": vscode.CompletionItemKind.Function,
    "builtin": vscode.CompletionItemKind.Function,
    "method": vscode.CompletionItemKind.Method,
    "class": vscode.CompletionItemKind.Class,
    "module": vscode.CompletionItemKind.Module,
    "python-module": vscode.CompletionItemKind.Module,
    "variable": vscode.CompletionItemKind.Variable,
    "field": vscode.CompletionItemKind.Field
  };
  return map[kind] || vscode.CompletionItemKind.Variable;
}

function semanticCompletion(symbol) {
  const item = new vscode.CompletionItem(symbol.name, semanticKind(symbol.kind));
  item.detail = symbol.signature || symbol.qualifiedName || `Sprout ${symbol.kind}`;
  item.documentation = new vscode.MarkdownString(symbol.documentation || `Sprout ${symbol.kind}.`);
  if ((symbol.kind === "function" || symbol.kind === "builtin" || symbol.kind === "method") && symbol.signature) {
    item.insertText = new vscode.SnippetString(`${symbol.name}($1)`);
  }
  return item;
}

function locationFromJson(location) {
  if (!location || !location.path) return undefined;
  const start = new vscode.Position(Math.max(0, Number(location.line || 1) - 1), Math.max(0, Number(location.col || 1) - 1));
  return new vscode.Location(vscode.Uri.file(location.path), new vscode.Range(start, start.translate(0, 1)));
}

function ignoredRanges(text) {
  const ranges = [];
  let inString = false;
  let start = -1;
  let escape = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escape) {
        escape = false;
      } else if (ch === "\\") {
        escape = true;
      } else if (ch === "\"") {
        ranges.push([start, i + 1]);
        inString = false;
      }
      continue;
    }
    if (ch === "#") {
      ranges.push([i, text.length]);
      break;
    }
    if (ch === "\"") {
      inString = true;
      start = i;
    }
  }
  if (inString) {
    ranges.push([start, text.length]);
  }
  return ranges;
}

function rangeContains(ranges, start, end) {
  return ranges.some(([a, b]) => start < b && end > a);
}

function collectSemanticNames(document) {
  const names = {
    classes: new Set(),
    functions: new Set(),
    variables: new Set(),
    parameters: new Set()
  };
  for (let line = 0; line < document.lineCount; line += 1) {
    const text = document.lineAt(line).text;
    const declaration = text.match(/\b(class|def|fn|bloom)\s+([A-Za-z_][A-Za-z0-9_]*)/);
    if (declaration) {
      if (declaration[1] === "class") names.classes.add(declaration[2]);
      else names.functions.add(declaration[2]);
      const open = text.indexOf("(", declaration.index + declaration[0].length);
      const close = open === -1 ? -1 : text.indexOf(")", open + 1);
      if (open !== -1 && close !== -1) {
        const params = text.slice(open + 1, close);
        for (const match of params.matchAll(/\*{0,2}([A-Za-z_][A-Za-z0-9_]*)/g)) {
          names.parameters.add(match[1]);
        }
      }
    }
    const assignment = text.match(/^\s*(?:let\s+|sprout\s+)?([A-Za-z_][A-Za-z0-9_]*)(?=\s*=)/);
    if (assignment) {
      names.variables.add(assignment[1]);
    }
    const loop = text.match(/^\s*(?:for|each)\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b/);
    if (loop) {
      names.variables.add(loop[1]);
    }
  }
  return names;
}

function collectSemanticTokens(document) {
  const tokenType = Object.fromEntries(semanticTokenTypes.map((name, index) => [name, index]));
  const tokens = [];
  const seen = new Set();
  const known = collectSemanticNames(document);

  function add(line, start, length, type) {
    if (length <= 0 || !Number.isInteger(start)) return;
    const key = `${line}:${start}:${length}:${type}`;
    if (seen.has(key)) return;
    seen.add(key);
    tokens.push({ line, start, length, type: tokenType[type] });
  }

  for (let line = 0; line < document.lineCount; line += 1) {
    const text = document.lineAt(line).text;
    const ignored = ignoredRanges(text);
    const declaration = text.match(/\b(class|def|fn|bloom)\s+([A-Za-z_][A-Za-z0-9_]*)/);
    if (declaration) {
      const kind = declaration[1];
      const name = declaration[2];
      const nameStart = text.indexOf(name, declaration.index + declaration[0].indexOf(name));
      add(line, nameStart, name.length, kind === "class" ? "class" : "function");

      const open = text.indexOf("(", nameStart + name.length);
      const close = open === -1 ? -1 : text.indexOf(")", open + 1);
      if (open !== -1 && close !== -1) {
        const params = text.slice(open + 1, close);
        const paramRegex = /\*{0,2}([A-Za-z_][A-Za-z0-9_]*)/g;
        let match;
        while ((match = paramRegex.exec(params))) {
          const paramStart = open + 1 + match.index + match[0].lastIndexOf(match[1]);
          add(line, paramStart, match[1].length, "parameter");
        }
      }
    }

    const assignment = text.match(/^\s*(?:let\s+|sprout\s+)?([A-Za-z_][A-Za-z0-9_]*)(?=\s*=)/);
    if (assignment) {
      const start = text.indexOf(assignment[1], assignment.index);
      add(line, start, assignment[1].length, /^[A-Z]/.test(assignment[1]) ? "class" : "variable");
    }

    for (const match of text.matchAll(/\b([A-Z][A-Za-z0-9_]*)\b/g)) {
      if (!rangeContains(ignored, match.index, match.index + match[1].length)) {
        add(line, match.index, match[1].length, "class");
      }
    }

    for (const match of text.matchAll(/\b([A-Za-z_][A-Za-z0-9_]*)\s*(?=\()/g)) {
      const name = match[1];
      if (["if", "elif", "while", "for", "catch", "class", "def", "fn", "bloom"].includes(name)) continue;
      if (!rangeContains(ignored, match.index, match.index + name.length)) {
        add(line, match.index, name.length, /^[A-Z]/.test(name) ? "class" : "function");
      }
    }

    for (const match of text.matchAll(/\bself\b/g)) {
      if (!rangeContains(ignored, match.index, match.index + 4)) {
        add(line, match.index, 4, "parameter");
      }
    }

    for (const match of text.matchAll(/\.([A-Za-z_][A-Za-z0-9_]*)/g)) {
      const start = match.index + 1;
      if (!rangeContains(ignored, start, start + match[1].length)) {
        add(line, start, match[1].length, "property");
      }
    }

    for (const match of text.matchAll(/\b[A-Za-z_][A-Za-z0-9_]*\b/g)) {
      const name = match[0];
      const start = match.index;
      const end = start + name.length;
      if (rangeContains(ignored, start, end)) continue;
      if (start > 0 && text[start - 1] === ".") continue;
      if (known.parameters.has(name)) {
        add(line, start, name.length, "parameter");
      } else if (known.variables.has(name)) {
        add(line, start, name.length, "variable");
      } else if (known.functions.has(name)) {
        add(line, start, name.length, "function");
      } else if (known.classes.has(name)) {
        add(line, start, name.length, "class");
      }
    }
  }

  tokens.sort((a, b) => (a.line - b.line) || (a.start - b.start) || (a.length - b.length));
  const builder = new vscode.SemanticTokensBuilder(semanticLegend);
  for (const token of tokens) {
    builder.push(token.line, token.start, token.length, token.type, 0);
  }
  return builder.build();
}

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection("sprout");
  const timers = new Map();

  function scheduleCheck(document) {
    if (document.languageId !== "sprout") return;
    const key = document.uri.toString();
    clearTimeout(timers.get(key));
    timers.set(key, setTimeout(() => checkDocument(context, diagnostics, document), 350));
  }

  const provider = vscode.languages.registerCompletionItemProvider(
    "sprout",
    {
      provideCompletionItems(document, position) {
        return runIntelQuery(context, document, position, "completions").then((semantic) => {
          if (semantic && Array.isArray(semantic.items) && semantic.items.length > 0) {
            return semantic.items.map(semanticCompletion);
          }

        const before = document.lineAt(position).text.slice(0, position.character);
        if (before.endsWith("s3d.")) {
          return completeEngineEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("star.")) {
          return completeStarBloomEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("g2d.")) {
          return completeGeometryEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("c2d.")) {
          return completeCanvasEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("pix.")) {
          return completePixelGardenEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("w2d.")) {
          return completeWindow2dEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("p3d.")) {
          return completePandaEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith("game.")) {
          return completeGameEntries.map(([label, docs, insert]) => completion(label, docs, insert));
        }
        if (before.endsWith(".")) {
          return methodEntries.map(([label, docs, insert]) => completion(label, docs, insert, vscode.CompletionItemKind.Method));
        }
        return completeTopLevelEntries.map(([label, docs, insert, kind]) => completion(label, docs, insert, kind));
        });
      }
    },
    "."
  );

  const hover = vscode.languages.registerHoverProvider("sprout", {
    provideHover(document, position) {
      return runIntelQuery(context, document, position, "hover").then((semantic) => {
        if (semantic && semantic.symbol) {
          const symbol = semantic.symbol;
          const label = symbol.signature || symbol.qualifiedName || symbol.name;
          const docs = symbol.documentation || `Sprout ${symbol.kind}.`;
          const defined = symbol.location && symbol.location.path && !symbol.location.path.startsWith("<")
            ? `\n\nDefined at \`${symbol.location.path}:${symbol.location.line}:${symbol.location.col}\`.`
            : "";
          return new vscode.Hover(new vscode.MarkdownString(`**${label}**\n\n${docs}${defined}`));
        }

      const range = document.getWordRangeAtPosition(position);
      if (!range) return undefined;
      const word = document.getText(range);
      const found = completeTopLevelEntries
        .concat(methodEntries, completeEngineEntries, completeGeometryEntries, completeCanvasEntries)
        .concat(completePixelGardenEntries, completeStarBloomEntries, completeWindow2dEntries, completePandaEntries, completeGameEntries)
        .find(([label]) => label === word);
      if (!found) return undefined;
      return new vscode.Hover(new vscode.MarkdownString(`**${found[0]}**\n\n${found[1]}`), range);
      });
    }
  });

  const definition = vscode.languages.registerDefinitionProvider("sprout", {
    provideDefinition(document, position) {
      return runIntelQuery(context, document, position, "definition").then((semantic) => locationFromJson(semantic && semantic.definition));
    }
  });

  const references = vscode.languages.registerReferenceProvider("sprout", {
    provideReferences(document, position) {
      return runIntelQuery(context, document, position, "references").then((semantic) => {
        if (!semantic || !Array.isArray(semantic.references)) return [];
        return semantic.references.map((ref) => locationFromJson(ref.location)).filter(Boolean);
      });
    }
  });

  const rename = vscode.languages.registerRenameProvider("sprout", {
    provideRenameEdits(document, position, newName) {
      return runIntelQuery(context, document, position, "references").then((semantic) => {
        const edit = new vscode.WorkspaceEdit();
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
      provideSignatureHelp(document, position) {
        return runIntelQuery(context, document, position, "signature").then((semantic) => {
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

  const semanticTokens = vscode.languages.registerDocumentSemanticTokensProvider(
    { language: "sprout" },
    {
      provideDocumentSemanticTokens(document) {
        return collectSemanticTokens(document);
      }
    },
    semanticLegend
  );

  context.subscriptions.push(
    provider,
    hover,
    definition,
    references,
    rename,
    signature,
    semanticTokens,
    diagnostics,
    vscode.workspace.onDidOpenTextDocument(scheduleCheck),
    vscode.workspace.onDidSaveTextDocument(scheduleCheck),
    vscode.workspace.onDidChangeTextDocument((event) => scheduleCheck(event.document)),
    vscode.workspace.onDidCloseTextDocument((document) => diagnostics.delete(document.uri))
  );

  for (const document of vscode.workspace.textDocuments) {
    scheduleCheck(document);
  }
}

function deactivate() {}

module.exports = { activate, deactivate };
