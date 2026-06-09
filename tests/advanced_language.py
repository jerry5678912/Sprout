#!/usr/bin/env python3
"""Regression tests for Sprout's advanced language and async application model."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run(path: Path, *, vm: bool = False, command: str = "run") -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(ROOT / "sprout.py"), command]
    if vm:
        args.append("--vm")
    args.append(str(path))
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def write(root: Path, name: str, source: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def assert_parity(path: Path, expected: list[str]) -> None:
    stable = run(path)
    vm = run(path, vm=True)
    assert stable.returncode == 0, stable.stderr
    assert vm.returncode == 0, vm.stderr
    assert stable.stdout.splitlines() == expected
    assert vm.stdout == stable.stdout
    assert "fallback" not in vm.stderr.lower()


def test_enums_match_generators_and_comprehensions() -> None:
    assert_parity(
        ROOT / "examples" / "advanced_features.sprout",
        [
            "ok 4",
            "[0, 4, 16]",
            "{0: 1, 1: 2, 2: 3}",
            "seed",
            "leaf",
            "bloom",
        ],
    )


def test_pattern_guards_and_array_destructuring() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "patterns.sprout",
            "enum Event:\n"
            "  Point(x: Int, y: Int)\n"
            "  Stop\n\n"
            "events = [Event.Point(2, 3), Event.Stop]\n"
            "for event in events:\n"
            "  match event:\n"
            "    case Event.Point(x, y) if x < y:\n"
            '      say "point", x + y\n'
            "    case Event.Point(_, _):\n"
            '      say "other point"\n'
            "    case Event.Stop:\n"
            '      say "stop"\n'
            "match [1, 2, 3, 4]:\n"
            "  case [first, second, *rest]:\n"
            "    say first, second, rest\n",
        )
        assert_parity(path, ["point 5", "stop", "1 2 [3, 4]"])


def test_interleaved_resumable_generators() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "generators.sprout",
            "def sequence(start):\n"
            "  try:\n"
            "    yield start\n"
            '    raise "skip"\n'
            "  catch error:\n"
            "    yield start + 1\n"
            "  yield start + 2\n"
            "left = sequence(1)\n"
            "right = sequence(10)\n"
            "say left.next(), right.next()\n"
            "say left.next(), right.next()\n"
            "say left.next(), right.next()\n",
        )
        assert_parity(path, ["1 10", "2 11", "3 12"])


def test_cross_module_types_unions_and_narrowing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(
            root,
            "models.sprout",
            "type Identifier = Int | String\n"
            "class User:\n"
            "  def init(self, id: Identifier):\n"
            "    self.id = id\n"
            "def make(id: Identifier) -> User:\n"
            "  return User(id)\n",
        )
        main = write(
            root,
            "main.sprout",
            'import "models.sprout" as models\n'
            "let user: models.User = models.make(4)\n"
            "let maybe: Int | Nil = 3\n"
            "if maybe is Int:\n"
            "  let exact: Int = maybe\n"
            "say user.id, maybe\n",
        )
        checked = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "typecheck", str(root), "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        payload = json.loads(checked.stdout)
        assert checked.returncode == 0, payload
        assert payload["diagnostics"] == []
        assert_parity(main, ["4 3"])

        main.write_text(main.read_text(encoding="utf-8") + "models.make(True)\n", encoding="utf-8")
        invalid = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "typecheck", str(root), "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        messages = [item["message"] for item in json.loads(invalid.stdout)["diagnostics"]]
        assert invalid.returncode == 1
        assert any("expects Identifier, got Bool" in message for message in messages)


def test_exhaustiveness_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "match.sprout",
            "enum State:\n"
            "  Ready\n"
            "  Failed(message: String)\n"
            "let state: State = State.Ready\n"
            "match state:\n"
            "  case State.Ready:\n"
            '    say "ready"\n',
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "typecheck", str(path), "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        payload = json.loads(result.stdout)
        assert result.returncode == 1
        assert any(item["code"] == "SPROUT_NON_EXHAUSTIVE_MATCH" for item in payload["diagnostics"])


def test_generator_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "invalid_generator.sprout",
            "yield 1\n"
            "def names() -> Generator[Int]:\n"
            '  yield "wrong"\n'
            "async def unsupported():\n"
            "  yield 1\n",
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "typecheck", str(path), "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        codes = {item["code"] for item in json.loads(result.stdout)["diagnostics"]}
        assert result.returncode == 1
        assert "SPROUT_YIELD_OUTSIDE_GENERATOR" in codes
        assert "SPROUT_YIELD_TYPE" in codes
        assert "SPROUT_ASYNC_GENERATOR_UNSUPPORTED" in codes


def test_async_http_file_stream_and_cancellation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = write(
            root,
            "async_io.sprout",
            'response = await http_get_async("data:application/json,%7B%22answer%22%3A42%7D")\n'
            'say response.status, response.json()["answer"]\n'
            'await writefile_async("data.txt", "sprout")\n'
            'say await readfile_async("data.txt")\n'
            "token = cancel_token()\n"
            "waiting = sleep_async(1, token)\n"
            "token.cancel()\n"
            "try:\n"
            "  await waiting\n"
            "catch error:\n"
            '  say error.contains("cancel")\n'
            "",
        )
        assert_parity(path, ["200 42", "sprout", "True"])


def test_string_slice_assignment() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "string_slice.sprout",
            'phrase = "abcdef"\n'
            'phrase[1:4] = "XYZ"\n'
            "say phrase\n",
        )
        assert_parity(path, ["aXYZef"])


def test_dict_method_name_collision_error_is_clear() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write(
            Path(tmp),
            "dict_collision.sprout",
            "state = {}\n"
            "say state.keys.left\n",
        )
        stable = run(path)
        vm = run(path, vm=True)
        assert stable.returncode == 1, stable.stdout + stable.stderr
        assert vm.returncode == 1, vm.stdout + vm.stderr
        assert "Dictionary has no key 'keys'" in stable.stderr
        assert "Dictionary has no key 'keys'" in vm.stderr


def test_vm_compiles_imported_module_bodies() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(
            root,
            "maths.sprout",
            "def square(value):\n"
            "  return value * value\n"
            "class Counter:\n"
            "  def init(self, value):\n"
            "    self.value = value\n"
            "  def next(self):\n"
            "    self.value = self.value + 1\n"
            "    return self.value\n",
        )
        main = write(
            root,
            "main.sprout",
            'import "maths.sprout" as maths\n'
            "counter = maths.Counter(4)\n"
            "say maths.square(counter.next())\n",
        )
        assert_parity(main, ["25"])


def main() -> int:
    test_enums_match_generators_and_comprehensions()
    test_pattern_guards_and_array_destructuring()
    test_interleaved_resumable_generators()
    test_cross_module_types_unions_and_narrowing()
    test_exhaustiveness_diagnostics()
    test_generator_diagnostics()
    test_async_http_file_stream_and_cancellation()
    test_string_slice_assignment()
    test_dict_method_name_collision_error_is_clear()
    test_vm_compiles_imported_module_bodies()
    print("sprout advanced language tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
