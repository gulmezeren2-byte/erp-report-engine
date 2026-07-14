"""Star-schema export for the Power BI Command Center.

Feeds the PBIP semantic model in powerbi/ with tidy CSVs. Uses the exact
same guarded extraction path as the HTML report - no new SQL, no writes -
and ships the engine's honesty artifacts (reconciliation, data-quality
issues, the full audit trail) as first-class tables so the dashboard can
show its receipts.
"""

from __future__ import annotations

import csv
import datetime as dt
import os

import pandas as pd

from .config import Config
from .connect import Auditor
from .extract import Extraction
from .semantic import Profile
from . import __version__

_ENC = "utf-8"  # no BOM: Power BI's Csv.Document reads 65001 cleanly


def _write(path: str, header: list[str], rows: list[list]) -> int:
    with open(path, "w", encoding=_ENC, newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return len(rows)


def _iso_week(d: dt.date) -> tuple[str, int]:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", iso.year * 100 + iso.week


def export_all(cfg: Config, profile: Profile, ex: Extraction, auditor: Auditor,
               out_dir: str, streak: int) -> dict[str, int]:
    """Write the star schema + meta tables. Returns row counts per file."""
    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}

    o = ex.frames["orders"].copy()
    for col in ("order_date", "promised_date", "actual_ship_date"):
        o[col] = pd.to_datetime(o[col], errors="coerce")
    o = o[o.order_date.notna()]
    o["net_total"] = pd.to_numeric(o.net_total, errors="coerce").fillna(0.0)

    # the fact keeps ONE row per order_id; duplicates stay visible in meta_data_quality
    dupes_dropped = int(o.duplicated(subset=["order_id"]).sum())
    o = o.drop_duplicates(subset=["order_id"], keep="first")

    delivered = o.status.astype(str).str.lower().isin(("delivered", "shipped", "closed"))
    on_time = (delivered & o.actual_ship_date.notna() & o.promised_date.notna()
               & (o.actual_ship_date <= o.promised_date))
    scored = delivered & o.actual_ship_date.notna() & o.promised_date.notna()
    lead = (o.actual_ship_date - o.order_date).dt.days

    fact_rows = []
    for i, r in enumerate(o.itertuples(index=False)):
        wk, wk_idx = _iso_week(r.order_date.date())
        fact_rows.append([
            r.order_id, r.order_date.date().isoformat(), wk, wk_idx,
            r.region, r.customer, str(r.status).lower(),
            r.promised_date.date().isoformat() if pd.notna(r.promised_date) else "",
            r.actual_ship_date.date().isoformat() if pd.notna(r.actual_ship_date) else "",
            round(float(r.net_total), 2),
            int(bool(delivered.iloc[i])),
            (int(bool(on_time.iloc[i])) if bool(scored.iloc[i]) else ""),
            (int(lead.iloc[i]) if pd.notna(lead.iloc[i]) else ""),
        ])
    counts["fact_orders.csv"] = _write(
        os.path.join(out_dir, "fact_orders.csv"),
        ["order_id", "order_date", "week_key", "week_index", "region", "customer",
         "status", "promised_date", "actual_ship_date", "net_total",
         "is_delivered", "is_on_time", "lead_days"],
        fact_rows,
    )

    lines = ex.frames["order_lines"].copy()
    lines["qty"] = pd.to_numeric(lines.qty, errors="coerce").fillna(0.0)
    lines = lines[lines.order_id.isin(o.order_id)]
    counts["fact_order_lines.csv"] = _write(
        os.path.join(out_dir, "fact_order_lines.csv"),
        ["order_id", "item_code", "qty"],
        [[r.order_id, r.item_code, float(r.qty)] for r in lines.itertuples(index=False)],
    )

    # item dimension with demand context (8 completed weeks, same rule as kpi.py)
    o["week_key"] = [w for w, _ in (_iso_week(d.date()) for d in o.order_date)]
    weeks = sorted(o.week_key.unique())
    recent = o[o.week_key.isin(weeks[-9:-1])][["order_id"]]
    weekly_demand = (lines.merge(recent, on="order_id")
                     .groupby("item_code").qty.sum() / 8.0)
    inv = ex.frames["inventory"].copy()
    inv["stock_qty"] = pd.to_numeric(inv.stock_qty, errors="coerce").fillna(0.0)
    item_rows = []
    for r in inv.itertuples(index=False):
        wd = float(weekly_demand.get(r.item_code, float("nan")))
        cover = (float(r.stock_qty) / wd) if wd and wd == wd and wd > 0 else ""
        item_rows.append([r.item_code, float(r.stock_qty),
                          round(wd, 2) if wd == wd else "",
                          round(cover, 1) if cover != "" else ""])
    counts["dim_item.csv"] = _write(
        os.path.join(out_dir, "dim_item.csv"),
        ["item_code", "stock_qty", "avg_weekly_demand", "cover_weeks"],
        item_rows,
    )

    # week dimension; the current partial week is FLAGGED, never hidden.
    # week_ordinal is a gapless 1..n counter so DAX week arithmetic never
    # breaks at year boundaries.
    today = dt.date.today()
    current_wk, _ = _iso_week(today)
    week_rows = []
    for i, w in enumerate(weeks, start=1):
        year, num = int(w[:4]), int(w[-2:])
        monday = dt.date.fromisocalendar(year, num, 1)
        week_rows.append([w, year * 100 + num, i, monday.isoformat(),
                          (monday + dt.timedelta(days=6)).isoformat(),
                          int(w != current_wk)])
    counts["dim_week.csv"] = _write(
        os.path.join(out_dir, "dim_week.csv"),
        ["week_key", "week_index", "week_ordinal", "week_start", "week_end", "is_full_week"],
        week_rows,
    )

    counts["meta_reconciliation.csv"] = _write(
        os.path.join(out_dir, "meta_reconciliation.csv"),
        ["entity", "fetched", "source_count", "match"],
        [[e, v["fetched"], v["source_count"],
          "OK" if v["fetched"] == v["source_count"] else "MISMATCH"]
         for e, v in ex.reconciliation.items()],
    )

    issues = list(ex.issues)
    if dupes_dropped:
        issues.append(
            f"orders: {dupes_dropped} duplicate order_id rows collapsed to one in fact_orders "
            "(kept in the HTML report's gate; Power BI fact needs a unique key)"
        )
    counts["meta_data_quality.csv"] = _write(
        os.path.join(out_dir, "meta_data_quality.csv"),
        ["issue"], [[i] for i in issues],
    )

    counts["meta_audit_trail.csv"] = _write(
        os.path.join(out_dir, "meta_audit_trail.csv"),
        ["label", "sql", "params", "rows", "seconds"],
        [[a.label, a.sql, repr(a.params), a.rows, a.seconds] for a in auditor.entries],
    )

    counts["meta_run_info.csv"] = _write(
        os.path.join(out_dir, "meta_run_info.csv"),
        ["generated_at", "profile", "company_alias", "engine_version",
         "lookback_weeks", "low_cover_weeks", "revenue_decline_streak"],
        [[dt.datetime.now().isoformat(timespec="seconds"), profile.name,
          cfg.company_alias, __version__, cfg.lookback_weeks,
          cfg.low_cover_weeks, streak]],
    )
    return counts
