"""Run Sprout through ``python -m sprout_core``."""

from __future__ import annotations

import sys

from .cli import main


raise SystemExit(main([__file__, *sys.argv[1:]]))
