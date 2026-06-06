#!/usr/bin/env python3
"""Build the deterministic Sprout VS Code extension package."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.distribution import package_vscode_extension


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "dist"))
    args = parser.parse_args()
    package_vscode_extension(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
