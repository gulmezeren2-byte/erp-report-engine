"""erp-report-engine CLI.

    erp-report-engine init-demo            # build the demo database + config
    erp-report-engine validate -c cfg      # connect, check profile & counts, touch nothing
    erp-report-engine run -c cfg           # produce the weekly report
    erp-report-engine export-powerbi -c cfg

Machine-readable JSON goes to stdout; logs go to stderr. Exit codes follow the
taxonomy in errors.py (0 ok, 2 config, 3 database, 4 contract, 5 data-quality).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__, logsetup, runner
from .config import load_config
from .errors import DataQualityError, EngineError
from .state import State

_log = logging.getLogger("erp_report_engine")


def cmd_validate(args) -> None:
    cfg = load_config(args.config)
    _log.info("validating against %s", _safe_dsn(cfg.db_url))
    rr = runner.validate(cfg)
    print(json.dumps({
        "profile": rr.profile.name,
        "entities": dict(rr.extraction.reconciliation.items()),
        "data_quality_issues": rr.extraction.issues,
        "verdict": "OK - ready to run" if not rr.mismatches else "check issues",
    }, indent=2, ensure_ascii=False))
    if args.strict and rr.mismatches:
        raise DataQualityError(
            f"--strict: {len(rr.mismatches)} reconciliation mismatch(es) - do not trust the numbers")


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    rr = runner.build_report(cfg, write=True)
    _log.info("wrote %s (week %s, %d queries, %d DQ issue(s))",
              rr.report_path, rr.kpis["this_week"], len(rr.auditor.entries), len(rr.extraction.issues))
    print(json.dumps({
        "report": rr.report_path,
        "week": rr.kpis["this_week"],
        "findings": [f["text"] for f in rr.findings],
        "data_quality_issues": rr.extraction.issues,
        "queries_executed": len(rr.auditor.entries),
    }, indent=2, ensure_ascii=False))
    if args.strict and rr.mismatches:
        raise DataQualityError("--strict: reconciliation mismatch - the report was written but do not trust it")


def cmd_export_powerbi(args) -> None:
    from .export_powerbi import export_all

    cfg = load_config(args.config)
    rr = runner.validate(cfg)  # extract-only, through the guarded path
    state = State(cfg.state_db)
    streak = state.streak("revenue")
    state.close()
    counts = export_all(cfg, rr.profile, rr.extraction, rr.auditor, args.out, streak)
    _log.info("exported %d tables to %s", len(counts), args.out)

    print(json.dumps({
        "out_dir": args.out,
        "files": counts,
        "queries_executed": len(rr.auditor.entries),
        "note": "open powerbi/ERP Command Center.pbip and point the DataFolder parameter here",
    }, indent=2, ensure_ascii=False))


def cmd_init_demo(args) -> None:
    from .demo_builder import build

    build()
    print("demo ready: run  erp-report-engine run -c config.demo.yaml")


def cmd_mcp(args) -> None:
    from .mcp_server import serve

    _log.info("starting MCP server (stdio) with config %s", args.config)
    serve(args.config)


def _safe_dsn(url: str) -> str:
    """A DSN with any credential and host removed, safe to log."""
    scheme = url.split("://", 1)[0] if "://" in url else url
    return f"{scheme}://***"


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        prog="erp-report-engine",
        description="Autonomous weekly reporting straight from the SQL database behind your ERP. Read-only, audited, profile-driven.",
    )
    p.add_argument("--version", action="version", version=f"erp-report-engine {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug-level logs on stderr")
    p.add_argument("--log-file", help="also write JSON-lines logs to this file")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("validate", help="connect, validate profile and counts - touches nothing")
    s.add_argument("-c", "--config", required=True)
    s.add_argument("--strict", action="store_true", help="exit non-zero on a reconciliation mismatch")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="produce the weekly report")
    s.add_argument("-c", "--config", required=True)
    s.add_argument("--strict", action="store_true", help="exit non-zero on a reconciliation mismatch")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("export-powerbi",
                       help="export the star schema + honesty tables for the Power BI Command Center")
    s.add_argument("-c", "--config", required=True)
    # default to a gitignored folder: exporting real ERP data must not land in a
    # git-tracked path where a later `git commit -am` would publish it (S4).
    s.add_argument("-o", "--out", default=os.path.join("powerbi", "data.local"),
                   help="output folder (default: powerbi/data.local, gitignored)")
    s.set_defaults(fn=cmd_export_powerbi)

    s = sub.add_parser("init-demo", help="build the bundled demo database and config")
    s.set_defaults(fn=cmd_init_demo)

    s = sub.add_parser("mcp", help="run the guarded MCP server (stdio) for agent access to the ERP")
    s.add_argument("-c", "--config", required=True)
    s.set_defaults(fn=cmd_mcp)

    args = p.parse_args(argv)
    run_id = logsetup.configure(verbose=args.verbose, log_file=args.log_file)
    _log.info("erp-report-engine %s starting: %s", __version__, args.cmd)
    try:
        args.fn(args)
    except EngineError as e:
        _log.error("%s: %s", type(e).__name__, e)
        print(json.dumps({"error": str(e), "type": type(e).__name__, "run_id": run_id}), file=sys.stderr)
        sys.exit(e.exit_code)
    except Exception as e:  # noqa: BLE001 - last-resort handler for an unattended tool
        _log.exception("unhandled error")
        print(json.dumps({"error": str(e), "type": type(e).__name__, "run_id": run_id}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
