"""erp-report-engine CLI.

    python -m erp_report_engine init-demo          # build the demo database + config
    python -m erp_report_engine validate -c cfg    # connect, check profile & counts, touch nothing
    python -m erp_report_engine run -c cfg         # produce the weekly report
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .config import ConfigError, load_config
from .connect import Auditor, make_engine
from .extract import extract_all
from .insights import build as build_insights
from .kpi import compute
from .render import render
from .semantic import ProfileError, load_profile
from .state import State


def cmd_validate(args) -> None:
    cfg = load_config(args.config)
    profile = load_profile(cfg.profile_path)
    engine = make_engine(cfg.db_url, cfg.query_timeout_s)
    auditor = Auditor()
    ex = extract_all(engine, auditor, profile, cfg)
    print(json.dumps({
        "profile": profile.name,
        "entities": {k: v for k, v in ex.reconciliation.items()},
        "data_quality_issues": ex.issues,
        "verdict": "OK - ready to run" if not any("MISMATCH" in i for i in ex.issues) else "check issues",
    }, indent=2, ensure_ascii=False))


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    profile = load_profile(cfg.profile_path)
    engine = make_engine(cfg.db_url, cfg.query_timeout_s)
    auditor = Auditor()

    ex = extract_all(engine, auditor, profile, cfg)
    kpis = compute(ex.frames, cfg.low_cover_weeks)
    findings = build_insights(kpis, ex.frames, cfg.low_cover_weeks)

    state = State(cfg.state_db)
    streak = state.streak("revenue")
    html = render(cfg, profile, kpis, findings, ex, auditor, streak)

    os.makedirs(cfg.out_dir, exist_ok=True)
    path = os.path.join(cfg.out_dir, f"erp_report_{kpis['this_week']}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    state.record(kpis["this_week"], kpis, path)
    state.close()

    print(json.dumps({
        "report": path,
        "week": kpis["this_week"],
        "findings": [f["text"] for f in findings],
        "data_quality_issues": ex.issues,
        "queries_executed": len(auditor.entries),
    }, indent=2, ensure_ascii=False))


def cmd_init_demo(args) -> None:
    from demo.build_demo_db import main as build_demo

    build_demo()
    print("demo ready: run  python -m erp_report_engine run -c config.demo.yaml")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="erp-report-engine",
        description="Autonomous weekly reporting straight from the SQL database behind your ERP. Read-only, audited, profile-driven.",
    )
    p.add_argument("--version", action="version", version=f"erp-report-engine {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="connect, validate profile and counts - touches nothing")
    s.add_argument("-c", "--config", required=True)
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="produce the weekly report")
    s.add_argument("-c", "--config", required=True)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("init-demo", help="build the bundled demo database and config")
    s.set_defaults(fn=cmd_init_demo)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except (ConfigError, ProfileError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
