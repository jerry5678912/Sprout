#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

python3 sprout.py examples/fibonacci.sprout >/tmp/sprout_fib.out
python3 sprout.py examples/lists.sprout >/tmp/sprout_lists.out
python3 sprout.py examples/guess.sprout >/tmp/sprout_guess.out
python3 sprout.py examples/garden.sprout >/tmp/sprout_garden.out
python3 sprout.py examples/pythonish.sprout >/tmp/sprout_pythonish.out
python3 sprout.py examples/special.sprout >/tmp/sprout_special.out
python3 sprout.py examples/pythonlibs.sprout >/tmp/sprout_pythonlibs.out
python3 sprout.py examples/minigame.sprout >/tmp/sprout_minigame.out
python3 sprout.py examples/adventure.sprout Jerry >/tmp/sprout_adventure.out
python3 sprout.py examples/fileio.sprout >/tmp/sprout_fileio.out
python3 sprout.py examples/oopgame.sprout >/tmp/sprout_oopgame.out
python3 sprout.py examples/errors.sprout >/tmp/sprout_errors.out
if python3 sprout.py examples/stacktrace.sprout >/tmp/sprout_stacktrace.out 2>&1; then
  echo "stacktrace example should fail" >&2
  exit 1
fi
python3 sprout.py examples/scopes.sprout >/tmp/sprout_scopes.out
python3 sprout.py examples/variadic.sprout >/tmp/sprout_variadic.out
python3 sprout.py examples/variadic_errors.sprout >/tmp/sprout_variadic_errors.out
python3 sprout.py examples/python_blocks.sprout >/tmp/sprout_python_blocks.out
python3 sprout.py examples/garden_blocks.sprout >/tmp/sprout_garden_blocks.out
python3 sprout.py examples/seedfn.sprout >/tmp/sprout_seedfn.out
python3 sprout.py examples/vm_supported.sprout >/tmp/sprout_vm_supported_tree.out
python3 sprout.py run --vm examples/vm_supported.sprout >/tmp/sprout_vm_supported_vm.out
python3 sprout.py examples/vm_expanded.sprout >/tmp/sprout_vm_expanded_tree.out
python3 sprout.py run --vm examples/vm_expanded.sprout >/tmp/sprout_vm_expanded_vm.out
python3 sprout.py compile examples/vm_supported.sprout >/tmp/sprout_vm_compile.out
python3 sprout.py dis examples/vm_supported.sprout >/tmp/sprout_vm_dis.out
python3 sprout.py bench examples/vm_expanded.sprout >/tmp/sprout_vm_bench.out
printf 'c\n' | python3 sprout.py debug examples/vm_expanded.sprout --break 21 >/tmp/sprout_vm_debug.out
python3 sprout.py profile examples/vm_expanded.sprout >/tmp/sprout_vm_profile.out
printf 'def bad(**opts, other) {}\n' >/tmp/sprout_bad_kwrest.sprout
if python3 sprout.py check /tmp/sprout_bad_kwrest.sprout >/tmp/sprout_bad_kwrest.out 2>&1; then
  echo "bad kw-rest placement should fail" >&2
  exit 1
fi
printf 'def bad(**opts={}) {}\n' >/tmp/sprout_bad_kwrest_default.sprout
if python3 sprout.py check /tmp/sprout_bad_kwrest_default.sprout >/tmp/sprout_bad_kwrest_default.out 2>&1; then
  echo "bad kw-rest default should fail" >&2
  exit 1
fi
python3 sprout.py examples/slices_defaults.sprout >/tmp/sprout_slices_defaults.out
python3 sprout.py examples/keywordargs.sprout >/tmp/sprout_keywordargs.out
python3 sprout.py examples/inheritance.sprout >/tmp/sprout_inheritance.out
python3 sprout.py examples/super.sprout >/tmp/sprout_super.out
python3 sprout.py examples/super_errors.sprout >/tmp/sprout_super_errors.out
printf '1\n4\n2\n5\n3\n' | python3 sprout.py examples/tictactoe.sprout >/tmp/sprout_tictactoe.out
python3 sprout.py examples/stdlib100.sprout >/tmp/sprout_stdlib100.out
python3 sprout.py examples/geom2d_demo.sprout >/tmp/sprout_geom2d.out
python3 sprout.py examples/canvas2d_demo.sprout >/tmp/sprout_canvas2d.out
python3 sprout.py examples/pixelgarden_demo.sprout >/tmp/sprout_pixelgarden.out
python3 sprout.py examples/starbloom3d_demo.sprout >/tmp/sprout_starbloom3d.out
python3 sprout.py examples/named_imports.sprout >/tmp/sprout_named_imports.out
python3 sprout.py examples/engine3d_demo.sprout >/tmp/sprout_engine3d.out
python3 sprout.py examples/engine3d_solid_demo.sprout >/tmp/sprout_engine3d_solid.out
python3 sprout.py examples/engine3d_obj_demo.sprout >/tmp/sprout_engine3d_obj.out
python3 sprout.py examples/engine3d_camera_demo.sprout >/tmp/sprout_engine3d_camera.out
python3 sprout.py run examples/fibonacci.sprout >/tmp/sprout_run_cmd.out
python3 sprout.py check examples/tictactoe.sprout >/tmp/sprout_check.out
python3 sprout.py check examples/fibonacci.sprout --json >/tmp/sprout_check_json.out
python3 sprout.py lint examples/seedfn.sprout --json >/tmp/sprout_lint_json.out
python3 sprout.py fmt examples/seedfn.sprout >/tmp/sprout_fmt.out
python3 sprout.py run examples/project >/tmp/sprout_project.out
python3 sprout.py check examples/project --json >/tmp/sprout_project_check_json.out
python3 sprout.py check examples/window2d_demo.sprout >/tmp/sprout_window2d_check.out
python3 sprout.py check examples/panda3d_window_demo.sprout >/tmp/sprout_panda3d_check.out
python3 sprout.py check examples/modules/window2d.sprout >/tmp/sprout_window2d_module_check.out
python3 sprout.py check examples/modules/panda3d_window.sprout >/tmp/sprout_panda3d_module_check.out
python3 sprout.py stdlib >/tmp/sprout_stdlib_cmd.out
python3 sprout.py examples >/tmp/sprout_examples_cmd.out
python3 sprout.py version >/tmp/sprout_version.out
python3 sprout.py doctor >/tmp/sprout_doctor.out
python3 sprout.py < tests/repl_multiline.in >/tmp/sprout_repl.out
python3 -m json.tool editor/vscode-sprout/package.json >/tmp/sprout_vscode_package.out
python3 -m json.tool editor/vscode-sprout/snippets/sprout.code-snippets >/tmp/sprout_vscode_snippets.out
python3 -m json.tool editor/vscode-sprout/syntaxes/sprout.tmLanguage.json >/tmp/sprout_vscode_syntax.out
python3 tools/check_editor_coverage.py >/tmp/sprout_editor_coverage.out
python3 tools/check_vscode_editor_behavior.py >/tmp/sprout_vscode_editor_behavior.out
node --check editor/vscode-sprout/extension.js >/tmp/sprout_vscode_extension.out
node --check editor/vscode-sprout/lsp-client.js >/tmp/sprout_vscode_lsp_client.out
PYTHONPYCACHEPREFIX=/tmp/sprout-pycache python3 -m py_compile sprout.py sprout_core/*.py tools/*.py tests/*.py >/tmp/sprout_compile.out
python3 tests/tooling.py >/tmp/sprout_tooling_tests.out
python3 tests/intellisense.py >/tmp/sprout_intellisense_tests.out
python3 tests/vm.py >/tmp/sprout_vm_tests.out
python3 tests/package.py >/tmp/sprout_package_tests.out
python3 tests/dogfood.py >/tmp/sprout_dogfood_tests.out
python3 tests/application.py >/tmp/sprout_application_tests.out
python3 tests/ecosystem.py >/tmp/sprout_ecosystem_tests.out
python3 tests/standalone.py >/tmp/sprout_standalone_tests.out
python3 tests/async_language.py >/tmp/sprout_async_language_tests.out
python3 tests/advanced_language.py >/tmp/sprout_advanced_language_tests.out
python3 tests/quality.py >/tmp/sprout_quality_tests.out
python3 tests/security.py >/tmp/sprout_security_tests.out
python3 tests/typesystem.py >/tmp/sprout_typesystem_tests.out
python3 tests/distribution.py >/tmp/sprout_distribution_tests.out
python3 tests/lsp.py >/tmp/sprout_lsp_tests.out
python3 tests/errors.py >/tmp/sprout_error_tests.out
python3 tests/debug_adapter.py >/tmp/sprout_debug_adapter_tests.out
python3 sprout.py test tests/application_test.sprout >/tmp/sprout_language_tests.out
python3 sprout.py test tests/graphics_test.sprout >/tmp/sprout_graphics_tests.out
python3 sprout.py run examples/application/async_demo.sprout >/tmp/sprout_async_demo.out
python3 sprout.py run examples/application/sqlite_demo.sprout >/tmp/sprout_sqlite_demo.out
python3 sprout.py run examples/application/engineering_demo.sprout >/tmp/sprout_engineering_demo.out
python3 sprout.py run examples/application/game_app_demo.sprout >/tmp/sprout_game_app_demo.out
python3 sprout.py stdlib --groups >/tmp/sprout_stdlib_groups.out

test "$(wc -l </tmp/sprout_fib.out | tr -d ' ')" = "10"
grep -q "34" /tmp/sprout_fib.out
grep -q "item 1 = 42" /tmp/sprout_lists.out
grep -q "Ada is excellent" /tmp/sprout_guess.out
grep -q "Mina feels bright" /tmp/sprout_garden.out
grep -q "squares: \\[0, 1, 9, 16, 25\\]" /tmp/sprout_garden.out
grep -q "Ada A" /tmp/sprout_pythonish.out
grep -q "Sam C" /tmp/sprout_pythonish.out
grep -q "average 84" /tmp/sprout_pythonish.out
grep -q "true true" /tmp/sprout_pythonish.out
grep -q "\\* welcome to Sprout \\*" /tmp/sprout_special.out
grep -q "last: Kai" /tmp/sprout_special.out
grep -q "unique: \\[Ada, Lin, Mina, Kai\\]" /tmp/sprout_special.out
grep -q "woven: Ada + Lin + Mina + Kai" /tmp/sprout_special.out
grep -q "sprinkled: sun -> rain -> soil" /tmp/sprout_special.out
grep -q "scores: {Ada: 98, Lin: 84, Mina: 91, Kai: 77}" /tmp/sprout_special.out
grep -q "bundled: \\[\\[x, 4\\], \\[y, 9\\]\\]" /tmp/sprout_special.out
grep -q "harvest: stone" /tmp/sprout_special.out
grep -q "pruned: \\[leaf\\]" /tmp/sprout_special.out
grep -q "dice is alive:" /tmp/sprout_special.out
grep -q "sqrt: 9.0" /tmp/sprout_pythonlibs.out
grep -q "wave: 1.0" /tmp/sprout_pythonlibs.out
grep -q "lucky: 6" /tmp/sprout_pythonlibs.out
grep -q "module type: python-module" /tmp/sprout_pythonlibs.out
grep -q "dynamic import: true 4.0" /tmp/sprout_pythonlibs.out
grep -q "date: 2026-06-04 2026" /tmp/sprout_pythonlibs.out
grep -q "date type: python-object" /tmp/sprout_pythonlibs.out
grep -q "turn 5" /tmp/sprout_minigame.out
grep -q "\\* Tiny Adventure \\*" /tmp/sprout_adventure.out
grep -q "module: sprout-module Jerry @(1,1) hp=10" /tmp/sprout_adventure.out
grep -q "map rows: 5" /tmp/sprout_adventure.out
grep -q "first map line: ########" /tmp/sprout_adventure.out
grep -q "file exists: true" /tmp/sprout_fileio.out
grep -q "is file: true" /tmp/sprout_fileio.out
grep -q "file lines: \\[seed, leaf\\]" /tmp/sprout_fileio.out
grep -q "dir exists: true" /tmp/sprout_fileio.out
grep -q "dir listing: \\[save.json\\]" /tmp/sprout_fileio.out
grep -q "json save: Mina 10 seed/leaf" /tmp/sprout_fileio.out
grep -q "class Hero" /tmp/sprout_oopgame.out
grep -q "Mina @(6,1) hp=7 bag=key" /tmp/sprout_oopgame.out
grep -q "caught: hp cannot be negative" /tmp/sprout_errors.out
grep -q "raised: manual boom" /tmp/sprout_errors.out
grep -q "file error caught" /tmp/sprout_errors.out
grep -q "still running" /tmp/sprout_errors.out
grep -q "error: .*missing_config.txt" /tmp/sprout_stacktrace.out
grep -q "stack:" /tmp/sprout_stacktrace.out
grep -q "  called at examples/stacktrace.sprout:2:18" /tmp/sprout_stacktrace.out
grep -q "  at load_config (examples/stacktrace.sprout:1:5)" /tmp/sprout_stacktrace.out
grep -q "  called at examples/stacktrace.sprout:8:21" /tmp/sprout_stacktrace.out
grep -q "  at boot_game (examples/stacktrace.sprout:6:5)" /tmp/sprout_stacktrace.out
grep -q "  called at examples/stacktrace.sprout:12:19" /tmp/sprout_stacktrace.out
grep -q "  at main (examples/stacktrace.sprout:11:5)" /tmp/sprout_stacktrace.out
grep -q "  called at examples/stacktrace.sprout:15:5" /tmp/sprout_stacktrace.out
grep -q "function scope: local global" /tmp/sprout_scopes.out
grep -q "caller local: \\[safe, 7\\]" /tmp/sprout_scopes.out
grep -q "loop update: 3" /tmp/sprout_scopes.out
grep -q "block assignment: visible" /tmp/sprout_scopes.out
grep -q "player: Mina | hp | 13 | zone | lab" /tmp/sprout_variadic.out
grep -q "total: 20" /tmp/sprout_variadic.out
grep -q "crate -> gear,cell,key" /tmp/sprout_variadic.out
grep -q "chest -> " /tmp/sprout_variadic.out
grep -q "drone hp=6 speed=3" /tmp/sprout_variadic.out
grep -q "move args=north/fast mode=debug" /tmp/sprout_variadic.out
grep -q "bot @(4,9) hp=12 team=blue" /tmp/sprout_variadic.out
grep -q "scout @(1,2) hp=5 team=green" /tmp/sprout_variadic.out
grep -q "\\[quest\\] open gate 3" /tmp/sprout_variadic.out
grep -q "too many: fixed expected 2 args, got 3" /tmp/sprout_variadic_errors.out
grep -q "rest keyword: gather got unknown keyword 'values'" /tmp/sprout_variadic_errors.out
grep -q "kw duplicate: flexible got multiple values for 'name'" /tmp/sprout_variadic_errors.out
grep -q "bad spread: Call positional spread expects an array" /tmp/sprout_variadic_errors.out
grep -q "bad kw spread: Call keyword spread expects a dictionary" /tmp/sprout_variadic_errors.out
grep -q "bad kw key: Call keyword spread expects string keys" /tmp/sprout_variadic_errors.out
grep -q "dup kw spread: Call got duplicate keyword 'hp'" /tmp/sprout_variadic_errors.out
grep -q "python blocks: \\[0, 1, 1, 2, 3, 5, 8\\] 5" /tmp/sprout_python_blocks.out
grep -q "garden blocks: \\* keep growing \\* 3" /tmp/sprout_garden_blocks.out
grep -q "seedfn: \\[0, 2, 4, 6, 8\\] 7 seed:leaf sun:bloom 15" /tmp/sprout_seedfn.out
cmp /tmp/sprout_vm_supported_tree.out /tmp/sprout_vm_supported_vm.out
cmp /tmp/sprout_vm_expanded_tree.out /tmp/sprout_vm_expanded_vm.out
grep -q "compiled examples/vm_supported.sprout" /tmp/sprout_vm_compile.out
grep -q "CALL_BUILTIN say" /tmp/sprout_vm_dis.out
grep -q "tree-walk:" /tmp/sprout_vm_bench.out
grep -q "vm:" /tmp/sprout_vm_bench.out
grep -q "ratio tree/vm:" /tmp/sprout_vm_bench.out
grep -q "\\[debug\\]" /tmp/sprout_vm_debug.out
grep -q "hero.hurt(2)" /tmp/sprout_vm_debug.out
grep -q "instructions:" /tmp/sprout_vm_profile.out
grep -q "describe: calls=1" /tmp/sprout_vm_profile.out
grep -q "Keyword variadic parameter 'opts' must be last" /tmp/sprout_bad_kwrest.out
grep -q "Variadic parameter 'opts' cannot have a default" /tmp/sprout_bad_kwrest_default.out
grep -q "hero: {name: Mina, hp: 10, x: 0, y: 0}" /tmp/sprout_slices_defaults.out
grep -q "word pieces: spr out sp" /tmp/sprout_slices_defaults.out
grep -q "patched: \\[a, X, Y, e\\]" /tmp/sprout_slices_defaults.out
grep -q "draw two: \\[leaf, bloom\\]" /tmp/sprout_slices_defaults.out
grep -q "hero: {name: Mina, hp: 10, x: 0, y: 3}" /tmp/sprout_keywordargs.out
grep -q "loot:sun/4" /tmp/sprout_keywordargs.out
grep -q "python kw: 2026-06-04" /tmp/sprout_keywordargs.out
grep -q "keyword error: spawn got multiple values for 'name'" /tmp/sprout_keywordargs.out
grep -q "class" /tmp/sprout_inheritance.out
grep -q "Mina @(3,3)" /tmp/sprout_inheritance.out
grep -q "Mina collected key" /tmp/sprout_inheritance.out
grep -q "spikes danger 4" /tmp/sprout_inheritance.out
grep -q "super class: class" /tmp/sprout_super.out
grep -q "super status: Mina @(3,2) hp=13" /tmp/sprout_super.out
grep -q "super error: Superclass Base has no method 'nope'" /tmp/sprout_super_errors.out
grep -q "Tic-Tac-Toe" /tmp/sprout_tictactoe.out
grep -q "Player X wins!" /tmp/sprout_tictactoe.out
grep -q "function count: 183" /tmp/sprout_stdlib100.out
grep -q "stdlib ok" /tmp/sprout_stdlib100.out
grep -q "step: 3 3" /tmp/sprout_geom2d.out
grep -q "distance: 7" /tmp/sprout_geom2d.out
grep -q "inside: true" /tmp/sprout_geom2d.out
grep -q "wall hit: false" /tmp/sprout_geom2d.out
grep -q "circle hit: true" /tmp/sprout_geom2d.out
grep -q "bounds: 1 2 6 3" /tmp/sprout_geom2d.out
grep -q "forward: 0 3" /tmp/sprout_geom2d.out
grep -q "########################" /tmp/sprout_canvas2d.out
grep -q "oo@....#" /tmp/sprout_canvas2d.out
grep -q "========..Sprout2D" /tmp/sprout_canvas2d.out
grep -q "PixelGarden" /tmp/sprout_pixelgarden.out
grep -q "garden step:" /tmp/sprout_pixelgarden.out
grep -q "sprite size: 3 3" /tmp/sprout_pixelgarden.out
grep -q "StarBloom3D" /tmp/sprout_starbloom3d.out
grep -q "\\*" /tmp/sprout_starbloom3d.out
grep -q "scene objects: 2" /tmp/sprout_starbloom3d.out
grep -q "named imports: Mina 3 5" /tmp/sprout_named_imports.out
grep -q "4 passed" /tmp/sprout_graphics_tests.out
grep -q "vertices: 8 edges: 12" /tmp/sprout_engine3d.out
grep -q "\\*" /tmp/sprout_engine3d.out
grep -q "solid faces: 12 zbuffered: true" /tmp/sprout_engine3d_solid.out
grep -q "%" /tmp/sprout_engine3d_solid.out
grep -q "obj vertices: 5 faces: 6 edges: 9" /tmp/sprout_engine3d_obj.out
grep -q "camera forward z: 9" /tmp/sprout_engine3d_camera.out
grep -q "orbit forward z: 8" /tmp/sprout_engine3d_camera.out
grep -q "camera oriented: true true" /tmp/sprout_engine3d_camera.out
grep -q "34" /tmp/sprout_run_cmd.out
grep -q "ok .*examples/tictactoe.sprout" /tmp/sprout_check.out
grep -q '"ok": true' /tmp/sprout_check_json.out
grep -q '"name": "fib"' /tmp/sprout_check_json.out
grep -Fq '"diagnostics": []' /tmp/sprout_lint_json.out
grep -q "double = seedfn x: x \\* 2" /tmp/sprout_fmt.out
grep -q "project: Mina 2 3" /tmp/sprout_project.out
grep -q '"path": ".*examples/project/src/main.sprout"' /tmp/sprout_project_check_json.out
grep -q "ok .*examples/window2d_demo.sprout" /tmp/sprout_window2d_check.out
grep -q "ok .*examples/panda3d_window_demo.sprout" /tmp/sprout_panda3d_check.out
grep -q "ok .*examples/modules/window2d.sprout" /tmp/sprout_window2d_module_check.out
grep -q "ok .*examples/modules/panda3d_window.sprout" /tmp/sprout_panda3d_module_check.out
grep -q "183 functions" /tmp/sprout_stdlib_cmd.out
grep -q "^json_parse$" /tmp/sprout_stdlib_cmd.out
grep -q "^readjson$" /tmp/sprout_stdlib_cmd.out
grep -q "^grow$" /tmp/sprout_stdlib_cmd.out
grep -q "^py_available$" /tmp/sprout_stdlib_cmd.out
grep -q "examples/tictactoe.sprout" /tmp/sprout_examples_cmd.out
grep -q "Sprout 0.3.8" /tmp/sprout_version.out
grep -q "ok python >= 3.9" /tmp/sprout_doctor.out
grep -q "\\[0, 1, 1, 2, 3, 5, 8, 13\\]" /tmp/sprout_repl.out
grep -q '"snippets"' /tmp/sprout_vscode_package.out
grep -q '"sprout.diagnostics.enabled"' /tmp/sprout_vscode_package.out
grep -q "editor coverage ok" /tmp/sprout_editor_coverage.out
grep -q "sprout vscode editor behavior check passed" /tmp/sprout_vscode_editor_behavior.out
grep -q "sprout tooling tests passed" /tmp/sprout_tooling_tests.out
grep -q "sprout intellisense tests passed" /tmp/sprout_intellisense_tests.out
grep -q "sprout vm tests passed" /tmp/sprout_vm_tests.out
grep -q "sprout package tests passed" /tmp/sprout_package_tests.out
grep -q "sprout dogfood tests passed" /tmp/sprout_dogfood_tests.out
grep -q "sprout application tests passed" /tmp/sprout_application_tests.out
grep -q "sprout ecosystem tests passed" /tmp/sprout_ecosystem_tests.out
grep -q "sprout standalone tests passed" /tmp/sprout_standalone_tests.out
grep -q "sprout async language tests passed" /tmp/sprout_async_language_tests.out
grep -q "sprout quality tests passed" /tmp/sprout_quality_tests.out
grep -q "sprout security tests passed" /tmp/sprout_security_tests.out
grep -q "sprout type system tests passed" /tmp/sprout_typesystem_tests.out
grep -q "sprout distribution tests passed" /tmp/sprout_distribution_tests.out
grep -q "sprout lsp tests passed" /tmp/sprout_lsp_tests.out
grep -q "sprout error reporting tests passed" /tmp/sprout_error_tests.out
grep -q "sprout debug adapter tests passed" /tmp/sprout_debug_adapter_tests.out
grep -q "6 tests: 6 passed, 0 failed" /tmp/sprout_language_tests.out
grep -q "task results: \\[16, 25\\]" /tmp/sprout_async_demo.out
grep -q "2 ship app" /tmp/sprout_sqlite_demo.out
grep -q "magnitude: 5.0" /tmp/sprout_engineering_demo.out
grep -q "finished: 3" /tmp/sprout_game_app_demo.out
grep -q "sqlite:" /tmp/sprout_stdlib_groups.out

echo "sprout smoke tests passed"
