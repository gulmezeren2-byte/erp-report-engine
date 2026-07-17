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
    _strict_gate(args, rr)


def cmd_run(args) -> None:
    cfg = load_config(args.config)
    rr = runner.build_report(cfg, write=True, narrate=args.narrate)
    _log.info("wrote %s (week %s, %d queries, %d DQ issue(s))",
              rr.report_path, rr.kpis["this_week"], len(rr.auditor.entries), len(rr.extraction.issues))
    out = {
        "report": rr.report_path,
        "week": rr.kpis["this_week"],
        "findings": [f["text"] for f in rr.findings],
        "data_quality_issues": rr.extraction.issues,
        "queries_executed": len(rr.auditor.entries),
    }
    if rr.narrative:
        out["narrative"] = rr.narrative["summary"]
    elif args.narrate:
        out["narrative"] = "skipped: no narrative endpoint/key configured"
    if args.dashboard:
        from . import render_dashboard
        dash = render_dashboard.render(cfg, rr.profile, rr.kpis, rr.findings,
                                       rr.extraction, rr.auditor, rr.streak)
        dpath = os.path.join(cfg.out_dir, f"dashboard_{rr.kpis['this_week']}.html")
        tmp = dpath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(dash)
        os.replace(tmp, dpath)
        out["dashboard"] = dpath
    if args.send:
        from . import delivery
        out["delivery"] = delivery.send_report(
            cfg, week=rr.kpis["this_week"], findings=out["findings"], html=rr.html)
        _log.info("delivery: %s", out["delivery"])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    _strict_gate(args, rr, wrote=True)


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


def cmd_trust_benchmark(args) -> None:
    """Run the read-only guard against its own attack corpus and report.

    No database, no config - it exercises the guard in memory, so anyone who
    installed the package can reproduce the number on the results page:
    `erp-report-engine trust-benchmark`. Exits non-zero if any case is wrong,
    so it doubles as a self-check.
    """
    from .attack_corpus import CASES, run, summarize
    from .connect import assert_read_only

    results = run(assert_read_only)
    s = summarize(results)

    if args.json:
        print(json.dumps({"summary": s, "cases": results}, indent=2, ensure_ascii=False))
    else:
        by = {c.name: c for c in CASES}
        order = {"critical": 0, "high": 1, "medium": 2, "-": 3}
        print("READ-ONLY GUARD — TRUST BENCHMARK\n")
        print("Attacks (well-formed SQL that is not a read; every one must be REFUSED):")
        for r in sorted([r for r in results if r["expected_block"]],
                        key=lambda r: (order.get(r["severity"], 9), r["name"])):
            mark = "BLOCKED " if r["blocked"] else "PASSED!!"
            print(f"  {mark} [{r['severity']:8}] {r['name']:16} {r['dialect']:8} — {by[r['name']].why}")
        print("\nLegitimate reads (must be ALLOWED, or the guard is useless):")
        for r in [r for r in results if not r["expected_block"]]:
            mark = "allowed " if not r["blocked"] else "BLOCKED!"
            print(f"  {mark}            {r['name']:16} {r['dialect']:8} — {by[r['name']].why}")
        print(
            f"\n{s['attacks_blocked']}/{s['attacks_total']} attacks refused · "
            f"{s['reads_allowed']}/{s['reads_total']} reads allowed · "
            f"{'ALL CORRECT' if s['all_correct'] else 'FAILURES ABOVE'}"
        )
        print("\nThe guard checks the functions a statement CALLS, not just its shape. "
              "Run in strict mode (the agent path) it also default-denies every "
              "function it does not recognise. See SECURITY.md.")

    if not s["all_correct"]:
        raise EngineError(
            f"trust benchmark FAILED: "
            f"{s['attacks_blocked']}/{s['attacks_total']} attacks blocked, "
            f"{s['reads_allowed']}/{s['reads_total']} reads allowed"
        )


def _strict_gate(args, rr, *, wrote: bool = False) -> None:
    """Under --strict, a reconciliation mismatch or a fail-severity contract
    violation is a hard failure (exit 5)."""
    if not args.strict:
        return
    reasons = list(rr.mismatches) + list(rr.extraction.contract_failures)
    if reasons:
        tail = " (the report was written but do not trust it)" if wrote else ""
        raise DataQualityError(f"--strict: {len(reasons)} blocking issue(s){tail}: {reasons[0]}")


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
    s.add_argument("--send", action="store_true", help="deliver the report via the config's delivery: channels")
    s.add_argument("--dashboard", action="store_true",
                   help="also write the premium dark 'command center' dashboard HTML")
    s.add_argument("--narrate", action="store_true",
                   help="add an LLM executive summary from aggregates only (needs a narrative: config block)")
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

    s = sub.add_parser("trust-benchmark",
                       help="run the read-only guard against its attack corpus (no DB needed)")
    s.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    s.set_defaults(fn=cmd_trust_benchmark)

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
