# Sprout Dogfood Notes

This folder records real-world usability dogfooding for early Sprout.

Projects added under `examples/dogfood`:

- `cli_tool`: argument parsing, command dispatch, formatted output.
- `game2d`: multi-file 2D game loop simulation with movement, collision, score, and rendering.
- `math_utility`: engineering-style beam calculations.
- `python_interop`: Python standard-library calls from Sprout.
- `package_app`: local package dependency with package source under `src`.

Pain points found and fixed:

- `fmt .` tried to open a project directory as a file. It now formats project `.sprout` files.
- Local package imports only searched the dependency root. Package `src` and `modules` folders are now searched too.
- Starter templates were too tiny. They now include useful argument handling, update loops, package tests, and docs.

Release confidence command set:

```sh
python3 tests/vm.py
python3 tests/intellisense.py
python3 tests/package.py
python3 tools/check_editor_coverage.py
tests/smoke.sh
python3 sprout.py doctor
python3 sprout.py release-check
```
