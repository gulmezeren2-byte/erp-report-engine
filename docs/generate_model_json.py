"""Generate docs/model.json from the canonical model in code.

The published contract is the same object `describe_model` exposes and the
`erp-report-engine schema` CLI prints, so a tool can consume the semantic model
without connecting - and CI regenerates this and fails on drift, so the
published contract can never say more than the code holds.

Usage:  python docs/generate_model_json.py
"""

from __future__ import annotations

import json
import os
import sys

# run from anywhere (docs/ dir, repo root, CI) without an editable install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_report_engine.semantic import canonical_model

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


def build() -> None:
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(canonical_model(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
