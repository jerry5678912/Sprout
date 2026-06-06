#!/usr/bin/env python3
"""Regression tests for standalone Sprout application distribution."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.model import SproutError  # noqa: E402
from sprout_core.standalone import build_standalone, package_standalone, verify_standalone  # noqa: E402


def write_projects(base: Path) -> Path:
    library = base / "greetings"
    app = base / "hello_app"
    (library / "src").mkdir(parents=True)
    (library / "src/main.sprout").write_text('say "library"\n', encoding="utf-8")
    (library / "src/greetings.sprout").write_text(
        'def hello(name):\n  return "hello " + name\n',
        encoding="utf-8",
    )
    (library / "sprout.toml").write_text(
        '[project]\nname = "greetings"\nversion = "1.0.0"\nmain = "src/main.sprout"\n'
        'description = "Greeting library"\nlicense = "MIT"\n\n'
        '[paths]\nsource = ["src"]\nmodules = []\n',
        encoding="utf-8",
    )

    (app / "src").mkdir(parents=True)
    (app / "assets").mkdir()
    (app / "assets/message.txt").write_text("from asset", encoding="utf-8")
    (app / "src/main.sprout").write_text(
        'import "greetings.sprout" as greetings\n'
        'say greetings.hello(argv[0])\n'
        'say readfile("../assets/message.txt")\n',
        encoding="utf-8",
    )
    (app / "sprout.toml").write_text(
        '[project]\nname = "hello_app"\nversion = "1.2.0"\nmain = "src/main.sprout"\n'
        'description = "Standalone test app"\nlicense = "MIT"\n\n'
        '[paths]\nsource = ["src"]\nmodules = []\nassets = ["assets"]\n\n'
        '[dependencies]\ngreetings = { path = "../greetings", version = "1.0.0" }\n',
        encoding="utf-8",
    )
    return app


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_run_package_and_verify() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        app = write_projects(Path(tmp))
        bundle = Path(build_standalone(str(app)))
        assert (bundle / "runtime/sprout_core/runtime.py").exists()
        assert (bundle / "app/dependencies/greetings/src/greetings.sprout").exists()
        assert (bundle / "app/assets/message.txt").read_text(encoding="utf-8") == "from asset"
        assert (bundle / "hello_app").stat().st_mode & 0o111
        verify_standalone(str(bundle))
        verified = subprocess.run(
            [sys.executable, str(ROOT / "sprout.py"), "app", "verify", str(bundle)],
            text=True,
            capture_output=True,
            check=True,
        )
        assert "standalone app ok hello_app 1.2.0" in verified.stdout

        result = subprocess.run(
            [sys.executable, str(bundle / "launcher.py"), "Mina"],
            cwd=Path(tmp),
            text=True,
            capture_output=True,
            check=True,
        )
        assert result.stdout.splitlines() == ["hello Mina", "from asset"]

        first = Path(package_standalone(str(app)))
        first_hash = digest(first)
        second = Path(package_standalone(str(app)))
        assert digest(second) == first_hash
        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            assert "standalone-manifest.json" in names
            assert "runtime/sprout_core/runtime.py" in names
            assert "app/src/main.sprout" in names

        target = bundle / "app/src/main.sprout"
        target.write_text('say "tampered"\n', encoding="utf-8")
        try:
            verify_standalone(str(bundle))
            raise AssertionError("tampered app passed verification")
        except SproutError as exc:
            assert "integrity check failed" in str(exc)


def main() -> int:
    test_build_run_package_and_verify()
    print("sprout standalone tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
