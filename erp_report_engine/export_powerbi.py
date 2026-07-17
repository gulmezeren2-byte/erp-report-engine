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

from . import __version__, spc
from . import week_calendar as wc
from .config import Config
from .connect import Auditor
from .extract import Extraction

# one definition per rule, imported - never restated here
from .kpi import _AGING_BUCKETS, _DELIVERED, _TREND_WINDOW, _bucket, compute
from .semantic import Profile

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


def _export_receivables(ex: Extraction, out_dir: str, as_of: dt.date) -> int:
    """Write fact_receivables.csv (open balances with aging fields) when the
    profile maps receivables; an empty file otherwise so the model still loads.
    Buckets come from kpi._bucket, so Power BI and the HTML report agree."""
    header = ["invoice_id", "customer", "due_date", "open_amount",
              "overdue_days", "aging_bucket", "bucket_order"]
    rows: list[list] = []
    rec = ex.frames.get("receivables")
    if rec is not None and len(rec):
        r = rec.copy()
        r["due_date"] = pd.to_datetime(r["due_date"], errors="coerce")
        r["open_amount"] = pd.to_numeric(r["open_amount"], errors="coerce")
        r = r[r["due_date"].notna() & (r["open_amount"] > 0)]
        for t in r.itertuples(index=False):
            od = int((pd.Timestamp(as_of) - t.due_date).days)
            bucket = _bucket(od)
            rows.append([t.invoice_id, t.customer, t.due_date.date().isoformat(),
                         round(float(t.open_amount), 2), od, bucket, _AGING_BUCKETS.index(bucket)])
    return _write(os.path.join(out_dir, "fact_receivables.csv"), header, rows)


def _export_spc(cfg: Config, ex: Extraction, out_dir: str, as_of: dt.date) -> int:
    """Write meta_spc.csv: the control limits, computed by the engine's own SPC
    module from the engine's own series.

    Without this, Power BI had no SPC at all. Its `Alert Count` re-derived a crude
    |WoW| >= 5% threshold, which is precisely the "ordinary variation reported as
    an alert" that the whole method exists to stop - so the surface a manager
    actually sits in front of carried the naive layer, and the signal-vs-noise
    verdict that defines this project lived only in the HTML report.

    Exported rather than reimplemented in DAX: the limits are arithmetic the
    report already publishes, and a second implementation is a second answer.
    """
    header = ["metric", "label", "cl", "ucl", "lcl", "mr_bar", "baseline_n",
              "current", "provisional", "verdict"]
    rows: list[list] = []
    try:
        kpis = compute(ex.frames, cfg.low_cover_weeks, as_of)
    except Exception:
        return _write(os.path.join(out_dir, "meta_spc.csv"), header, rows)

    for metric, label, pct in (("revenue", "Revenue", False), ("on_time", "On-time shipping", True)):
        lim = spc.limits_for(kpis, metric)
        series = [v for v in kpis.get("spc", {}).get(metric, []) if v == v]
        if not lim or not series:
            continue
        current = float(series[-1])
        if current > lim["ucl"]:
            verdict = "ABOVE the control limits - a real shift, worth a specific cause"
        elif current < lim["lcl"]:
            verdict = "BELOW the control limits - a real shift, worth a specific cause"
        else:
            verdict = "within the control limits - ordinary week-to-week variation"
        rows.append([
            metric, label,
            round(lim["cl"], 4 if pct else 2), round(lim["ucl"], 4 if pct else 2),
            round(lim["lcl"], 4 if pct else 2), round(lim["mr_bar"], 4 if pct else 2),
            int(lim["n"]), round(current, 4 if pct else 2),
            int(lim["n"] < spc._STABLE_N), verdict,
        ])
    return _write(os.path.join(out_dir, "meta_spc.csv"), header, rows)


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

    delivered = o.status.astype(str).str.lower().isin(_DELIVERED)
    on_time = (delivered & o.actual_ship_date.notna() & o.promised_date.notna()
               & (o.actual_ship_date <= o.promised_date))
    scored = delivered & o.actual_ship_date.notna() & o.promised_date.notna()
    lead = (o.actual_ship_date - o.order_date).dt.days

    fact_rows = []
    for i, r in enumerate(o.itertuples(index=False)):
        wk, wk_idx = _iso_week(r.order_date.date())
        # the week the order was PROMISED in, which is a different question from
        # the week it was ordered in: it is what "promised this week and still
        # not shipped" counts over, and on-time % cannot see those orders at all
        promised_wk = _iso_week(r.promised_date.date())[0] if pd.notna(r.promised_date) else ""
        fact_rows.append([
            r.order_id, r.order_date.date().isoformat(), wk, wk_idx,
            r.region, r.customer, str(r.status).lower(),
            r.promised_date.date().isoformat() if pd.notna(r.promised_date) else "",
            promised_wk,
            r.actual_ship_date.date().isoformat() if pd.notna(r.actual_ship_date) else "",
            round(float(r.net_total), 2),
            int(bool(delivered.iloc[i])),
            (int(bool(on_time.iloc[i])) if bool(scored.iloc[i]) else ""),
            (int(lead.iloc[i]) if pd.notna(lead.iloc[i]) else ""),
        ])
    counts["fact_orders.csv"] = _write(
        os.path.join(out_dir, "fact_orders.csv"),
        ["order_id", "order_date", "week_key", "week_index", "region", "customer",
         "status", "promised_date", "promised_week", "actual_ship_date", "net_total",
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

    # Calendar anchor (server date), shared with the HTML report so both surfaces
    # agree on 'this week'. The week axis is continuous by the calendar - empty
    # weeks appear as rows (with zero orders) instead of vanishing.
    as_of = ex.as_of or dt.date.today()
    current_monday = wc.monday_of(as_of)
    last_full_monday = wc.last_completed_monday(as_of)
    current_wk = wc.iso_week(current_monday)
    o["week_key"] = [w for w, _ in (_iso_week(d.date()) for d in o.order_date)]
    if len(o):
        first_monday = min(wc.monday_of(o.order_date.min().date()), last_full_monday)
    else:
        first_monday = last_full_monday
    dim_axis = wc.week_axis(first_monday, current_monday)          # includes the current partial week
    completed_axis = wc.week_axis(first_monday, last_full_monday)  # excludes it
    demand_weeks = completed_axis[-8:]                             # last 8 completed weeks, same as kpi.py

    # item dimension with demand context (8 completed weeks, same rule as kpi.py -
    # including the divisor: the weeks actually measured, never a hoped-for 8)
    recent = o[o.week_key.isin(demand_weeks)][["order_id"]]
    weekly_demand = (lines.merge(recent, on="order_id")
                     .groupby("item_code").qty.sum() / len(demand_weeks))
    inv = ex.frames["inventory"].copy()
    inv["stock_qty"] = pd.to_numeric(inv.stock_qty, errors="coerce").fillna(0.0)
    item_rows = []
    for r in inv.itertuples(index=False):
        wd = float(weekly_demand.get(r.item_code, float("nan")))
        if float(r.stock_qty) == 0:
            cover = 0.0                                   # stocked out is always low cover (K5)
        elif wd and wd == wd and wd > 0:
            cover = float(r.stock_qty) / wd
        else:
            cover = ""                                   # has stock but no demand signal -> not urgent
        item_rows.append([r.item_code, float(r.stock_qty),
                          round(wd, 2) if wd == wd else "",
                          round(cover, 1) if cover != "" else ""])
    counts["dim_item.csv"] = _write(
        os.path.join(out_dir, "dim_item.csv"),
        ["item_code", "stock_qty", "avg_weekly_demand", "cover_weeks"],
        item_rows,
    )

    # week dimension over the continuous calendar axis. week_ordinal is a gapless
    # 1..n counter (safe for year boundaries AND empty weeks); is_full_week is 0
    # only for the current, still-open week; is_trend_week marks the exact weeks
    # the engine plots, so the report's trend filter consumes the engine's window
    # instead of restating it in DAX and drifting from it.
    trend_weeks = set(completed_axis[-_TREND_WINDOW:])
    week_rows = []
    for i, w in enumerate(dim_axis, start=1):
        year, num = int(w[:4]), int(w[-2:])
        monday = dt.date.fromisocalendar(year, num, 1)
        week_rows.append([w, year * 100 + num, i, monday.isoformat(),
                          (monday + dt.timedelta(days=6)).isoformat(),
                          int(w != current_wk), int(w in trend_weeks)])
    counts["dim_week.csv"] = _write(
        os.path.join(out_dir, "dim_week.csv"),
        ["week_key", "week_index", "week_ordinal", "week_start", "week_end",
         "is_full_week", "is_trend_week"],
        week_rows,
    )

    # optional receivables fact with aging fields, computed as of the same anchor
    # date the HTML report used (so both surfaces bucket identically). Always
    # written - empty when the profile maps no receivables - so the model loads.
    counts["fact_receivables.csv"] = _export_receivables(ex, out_dir, as_of)

    # the SPC control limits, so Power BI can draw the band and quote the same
    # arithmetic the HTML report does instead of a naive threshold
    counts["meta_spc.csv"] = _export_spc(cfg, ex, out_dir, as_of)

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
