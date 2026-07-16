"""Thin shim kept for `python demo/build_demo_db.py` and existing docs.

The real builder lives in the package (`erp_report_engine.demo_builder`) so
`erp-report-engine init-demo` works from an installed wheel. This shim writes
the demo database and config into the repository root, matching prior behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))  # allow running as a loose script from a checkout

from erp_report_engine.demo_builder import build  # noqa: E402


def main() -> None:
    build(target_dir=_ROOT)


if __name__ == "__main__":
    main()
