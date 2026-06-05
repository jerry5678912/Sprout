#!/usr/bin/env python3
"""Sprout compatibility launcher and public API re-export."""

from __future__ import annotations

import sys

from sprout_core import *  # noqa: F401,F403
from sprout_core.cli import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
