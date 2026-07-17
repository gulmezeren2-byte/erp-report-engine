"""Power BI layer tests: the star-schema exporter and the integrity of the
hand-authored PBIP project (every JSON parses, pages/visuals stay consistent,
the semantic model references only tables the exporter actually produces)."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBIP = ROOT / "powerbi"
REPORT = PBIP / "ERP Command Center.Report"
MODEL = PBIP / "ERP Command Center.SemanticModel"


def _run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "erp_report_engine", *args],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )


def test_export_powerbi_end_to_end(tmp_path):
    build = subprocess.run([sys.executable, str(ROOT / "demo" / "build_demo_db.py")],
                           capture_output=True, text=True, cwd=ROOT)
    assert build.returncode == 0, build.stderr

    out = tmp_path / "pbi_data"
    proc = _run_cli("export-powerbi", "-c", str(ROOT / "config.demo.yaml"), "-o", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)

    expected = {"fact_orders.csv", "fact_order_lines.csv", "dim_item.csv", "dim_week.csv",
                "fact_receivables.csv", "meta_spc.csv", "meta_reconciliation.csv",
                "meta_data_quality.csv", "meta_audit_trail.csv", "meta_run_info.csv"}
    assert set(payload["files"]) == expected
    for name in expected:
        assert (out / name).exists(), f"{name} missing"

    # the receivables fact carries the aging fields, and every bucket is a known one
    with open(out / "fact_receivables.csv", encoding="utf-8") as f:
        rec = list(csv.DictReader(f))
    assert rec, "demo should export open receivables"
    assert set(rec[0]) == {"invoice_id", "customer", "due_date", "open_amount",
                           "overdue_days", "aging_bucket", "bucket_order"}
    assert {r["aging_bucket"] for r in rec} <= {"current", "1-30", "31-60", "61-90", "91+"}
    assert all(float(r["open_amount"]) > 0 for r in rec)          # only positive open balances

    # fact must have a unique order_id (the model relies on it as a key)
    with open(out / "fact_orders.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["order_id"] for r in rows]
    assert len(ids) == len(set(ids)), "fact_orders order_id must be unique"

    # week_ordinal must be gapless 1..n so DAX week arithmetic holds
    with open(out / "dim_week.csv", encoding="utf-8") as f:
        weeks = list(csv.DictReader(f))
    ordinals = [int(w["week_ordinal"]) for w in weeks]
    assert ordinals == list(range(1, len(weeks) + 1))
    # exactly one partial (current) week, and it is the last one
    assert [w["is_full_week"] for w in weeks][-1] == "0"
    assert sum(1 for w in weeks if w["is_full_week"] == "0") == 1

    # no BOM: Power BI's Csv.Document is configured for utf-8 without BOM
    first_bytes = (out / "fact_orders.csv").read_bytes()[:3]
    assert first_bytes != b"\xef\xbb\xbf"


def test_pbip_project_integrity():
    # every JSON file in the PBIP parses
    for p in PBIP.rglob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
    json.loads((PBIP / "ERP Command Center.pbip").read_text(encoding="utf-8"))

    # page folders match their page.json name and are listed in pages.json
    pages_meta = json.loads((REPORT / "definition" / "pages" / "pages.json").read_text(encoding="utf-8"))
    page_dirs = sorted(d.name for d in (REPORT / "definition" / "pages").iterdir() if d.is_dir())
    assert sorted(pages_meta["pageOrder"]) == page_dirs
    assert pages_meta["activePageName"] in pages_meta["pageOrder"]
    name_rule = re.compile(r"^[\w-]+$")
    for d in page_dirs:
        assert name_rule.match(d), f"page folder {d!r} would be silently ignored by Desktop"
        page = json.loads((REPORT / "definition" / "pages" / d / "page.json").read_text(encoding="utf-8"))
        assert page["name"] == d

    # every visual name matches its folder and visuals never overlap per page
    for d in page_dirs:
        boxes = []
        for vdir in (REPORT / "definition" / "pages" / d / "visuals").iterdir():
            v = json.loads((vdir / "visual.json").read_text(encoding="utf-8"))
            assert v["name"] == vdir.name
            pos = v["position"]
            boxes.append((pos["x"], pos["y"], pos["width"], pos["height"], vdir.name))
        for i, (x1, y1, w1, h1, n1) in enumerate(boxes):
            for x2, y2, w2, h2, n2 in boxes[i + 1:]:
                overlap = x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1
                assert not overlap, f"visuals {n1} and {n2} overlap on page {d}"

    # the theme declared in report.json exists on disk (a missing resource blocks opening)
    report = json.loads((REPORT / "definition" / "report.json").read_text(encoding="utf-8"))
    for pkg in report["resourcePackages"]:
        for item in pkg["items"]:
            assert (REPORT / "StaticResources" / pkg["name"] / item["path"]).exists(), item["path"]

    # model tables referenced by visuals exist as TMDL files
    tmdl_tables = {p.stem for p in (MODEL / "definition" / "tables").glob("*.tmdl")}
    entity_re = re.compile(r'"Entity":\s*"([^"]+)"')
    for p in REPORT.rglob("visual.json"):
        for entity in entity_re.findall(p.read_text(encoding="utf-8")):
            assert entity in tmdl_tables, f"{p.name} references unknown table {entity!r}"


def test_every_week_trend_visual_is_pinned_to_completed_weeks():
    """The report's central promise, enforced on the surface that once broke it.

    README: "The current partial week is never plotted." The base measures carry
    no calendar guard - only the '(This Week)' and sparkline measures do - so a
    line chart over DimWeek[Week] would happily end on the in-progress week and
    draw a cliff that is really a two-day week. Every week-axis trend must pin
    itself to the engine's window, and a viewer must not be able to unpin it.
    """
    checked = []
    for p in (REPORT / "definition" / "pages").glob("*/visuals/*/visual.json"):
        v = json.loads(p.read_text(encoding="utf-8"))
        vis = v.get("visual", {})
        if vis.get("visualType") != "lineChart":
            continue
        cats = vis.get("query", {}).get("queryState", {}).get("Category", {}).get("projections", [])
        if not any(c.get("queryRef", "").startswith("DimWeek.") for c in cats):
            continue

        name = p.parent.name
        checked.append(name)
        pinned = [f for f in v.get("filterConfig", {}).get("filters", [])
                  if f.get("field", {}).get("Column", {}).get("Property") == "Is Trend Week"]
        assert pinned, f"{name}: week trend with no completed-week filter — it can plot a partial week"
        assert pinned[0].get("isLockedInViewMode") is True, \
            f"{name}: the completed-week guarantee must not be switchable off in view mode"

    assert sorted(checked) == ["trend_ontime", "trend_revenue"], checked


def test_is_trend_week_marks_exactly_the_weeks_the_engine_plots(tmp_path):
    """dim_week carries the engine's own trend window as data, so the report's
    filter consumes that definition instead of restating it in DAX."""
    import datetime as dt

    import pandas as pd

    from erp_report_engine.config import Config
    from erp_report_engine.connect import Auditor
    from erp_report_engine.export_powerbi import export_all
    from erp_report_engine.extract import Extraction
    from erp_report_engine.kpi import _TREND_WINDOW, compute
    from erp_report_engine.semantic import load_profile

    as_of = dt.date(2026, 7, 16)
    mondays = [dt.date(2026, 7, 6) - dt.timedelta(weeks=i) for i in range(20)]
    o = pd.DataFrame(
        [(f"SO-{i}", pd.Timestamp(m), "Ege", "C", "delivered",
          pd.Timestamp(m), pd.Timestamp(m), 100.0) for i, m in enumerate(mondays)],
        columns=["order_id", "order_date", "region", "customer", "status",
                 "promised_date", "actual_ship_date", "net_total"])
    frames = {
        "orders": o,
        "order_lines": pd.DataFrame([("SO-0", "ITM-A", 1.0)], columns=["order_id", "item_code", "qty"]),
        "inventory": pd.DataFrame([("ITM-A", 5.0)], columns=["item_code", "stock_qty"]),
    }
    ex = Extraction(frames=frames, as_of=as_of)
    cfg = Config(db_url="sqlite:///x", profile_path="generic")
    export_all(cfg, load_profile("generic"), ex, Auditor(), str(tmp_path), streak=0)

    with open(tmp_path / "dim_week.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    marked = [r["week_key"] for r in rows if r["is_trend_week"] == "1"]
    kpis = compute(frames, low_cover_weeks=2.0, as_of=as_of)

    assert marked == kpis["trend"]["weeks"]          # the same weeks, from the same constant
    assert len(marked) == _TREND_WINDOW
    # and the partial week is never among them, by construction
    assert all(r["is_full_week"] == "1" for r in rows if r["is_trend_week"] == "1")


def test_power_bi_gets_the_same_control_limits_the_report_quotes(tmp_path):
    """SPC did not exist on this surface at all.

    Power BI's Alert Count re-derived a crude |WoW| >= 5% threshold - exactly the
    ordinary common-cause variation the method exists to ignore - so the
    signal-vs-noise verdict that defines the project lived only in the HTML
    report. The limits are now exported rather than reimplemented in DAX, because
    a second implementation is eventually a second answer. This pins that they are
    the same numbers.
    """
    import datetime as dt

    import pandas as pd

    from erp_report_engine import spc
    from erp_report_engine.config import Config
    from erp_report_engine.connect import Auditor
    from erp_report_engine.export_powerbi import export_all
    from erp_report_engine.extract import Extraction
    from erp_report_engine.kpi import compute
    from erp_report_engine.semantic import load_profile

    as_of = dt.date(2026, 7, 16)
    mondays = [dt.date(2026, 7, 6) - dt.timedelta(weeks=i) for i in range(20)]
    o = pd.DataFrame(
        [(f"SO-{i}", pd.Timestamp(m), "Ege", "C", "delivered", pd.Timestamp(m),
          pd.Timestamp(m), 100.0 + i * 7) for i, m in enumerate(mondays)],
        columns=["order_id", "order_date", "region", "customer", "status",
                 "promised_date", "actual_ship_date", "net_total"])
    frames = {
        "orders": o,
        "order_lines": pd.DataFrame([("SO-0", "ITM-A", 1.0)], columns=["order_id", "item_code", "qty"]),
        "inventory": pd.DataFrame([("ITM-A", 5.0)], columns=["item_code", "stock_qty"]),
    }
    ex = Extraction(frames=frames, as_of=as_of)
    cfg = Config(db_url="sqlite:///x", profile_path="generic")
    export_all(cfg, load_profile("generic"), ex, Auditor(), str(tmp_path), streak=0)

    with open(tmp_path / "meta_spc.csv", encoding="utf-8") as f:
        rows = {r["metric"]: r for r in csv.DictReader(f)}
    assert "revenue" in rows, "the control limits must reach Power BI"

    kpis = compute(frames, low_cover_weeks=2.0, as_of=as_of)
    lim = spc.limits_for(kpis, "revenue")
    exported = rows["revenue"]
    assert round(lim["ucl"], 2) == float(exported["ucl"])
    assert round(lim["lcl"], 2) == float(exported["lcl"])
    assert round(lim["cl"], 2) == float(exported["cl"])
    assert int(lim["n"]) == int(exported["baseline_n"])   # the sample size travels too


def test_promised_week_reaches_the_fact_so_power_bi_can_count_unshipped(tmp_path):
    """On-time % scores orders that SHIPPED, so the surface needs the week an
    order was PROMISED in to count the ones it cannot see."""
    import datetime as dt

    import pandas as pd

    from erp_report_engine.config import Config
    from erp_report_engine.connect import Auditor
    from erp_report_engine.export_powerbi import export_all
    from erp_report_engine.extract import Extraction
    from erp_report_engine.semantic import load_profile

    ts = pd.Timestamp("2026-07-06")     # 2026-W28
    o = pd.DataFrame([
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),
        ("SO-2", ts, "Ege", "C", "open", ts, pd.NaT, 100.0),      # promised W28, never shipped
    ], columns=["order_id", "order_date", "region", "customer", "status",
                "promised_date", "actual_ship_date", "net_total"])
    ex = Extraction(frames={
        "orders": o,
        "order_lines": pd.DataFrame(columns=["order_id", "item_code", "qty"]),
        "inventory": pd.DataFrame(columns=["item_code", "stock_qty"]),
    }, as_of=dt.date(2026, 7, 16))
    cfg = Config(db_url="sqlite:///x", profile_path="generic")
    export_all(cfg, load_profile("generic"), ex, Auditor(), str(tmp_path), streak=0)

    with open(tmp_path / "fact_orders.csv", encoding="utf-8") as f:
        rows = {r["order_id"]: r for r in csv.DictReader(f)}
    assert rows["SO-2"]["promised_week"] == "2026-W28"
    assert rows["SO-2"]["actual_ship_date"] == ""      # the order the percentage cannot count
