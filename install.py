#!/usr/bin/env python3
"""Install Sprout from a source checkout or release archive."""

from __future__ import annotations

import argparse

from sprout_core.distribution import install_language


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the Sprout language")
    parser.add_argument("--prefix", help="Installation prefix (default: ~/.local)")
    parser.add_argument("--force", action="store_true", help="Replace an existing installation")
    args = parser.parse_args()
    install_language(prefix=args.prefix, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
