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
                "meta_reconciliation.csv", "meta_data_quality.csv",
                "meta_audit_trail.csv", "meta_run_info.csv"}
    assert set(payload["files"]) == expected
    for name in expected:
        assert (out / name).exists(), f"{name} missing"

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
