#!/usr/bin/env python3
"""Report bundled language-pack catalog coverage for CI."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sprout_core.languages import LANGUAGE_PACK_DIR, validate_language_pack  # noqa: E402


def main() -> int:
    reports = []
    failed = False
    for path in sorted(Path(LANGUAGE_PACK_DIR).glob("*.json")):
        report = validate_language_pack(str(path))
        reports.append(report)
        if report["missing"]:
            failed = True
    print(json.dumps({"packs": reports}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
