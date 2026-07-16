"""Weekly KPI computation over canonical entities.

Definitions are explicit and travel with the report:
- revenue: sum(net_total) of orders by ISO week of order_date
- on-time %: delivered orders with actual_ship_date <= promised_date
  (an OTIF-lite: completeness requires line-level receipts most ERPs lack;
  the report says so instead of pretending)
- stock cover: stock_qty / average weekly demand of the last 8 weeks
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from . import week_calendar as wc
from .errors import EngineError


def _week(s: pd.Series) -> pd.Series:
    iso = s.dt.isocalendar()
    return iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)


def _concentration(o: pd.DataFrame, weeks: list[str], value_col: str = "net_total") -> dict | None:
    """Revenue concentration over a window: top-customer shares plus the
    Herfindahl-Hirschman Index (sum of squared shares x 10 000). A factual,
    current-state analysis - concentration is risk (one account swings the
    number), not a forecast."""
    if "customer" not in o.columns:
        return None
    wk = o[o.week.isin(weeks)]
    total = float(wk[value_col].sum())
    if total <= 0:
        return None
    by = wk.groupby("customer")[value_col].sum().sort_values(ascending=False)
    shares = by / total
    return {
        "window_weeks": len(weeks),
        "n_customers": int(by.size),
        "top1_pct": round(float(shares.iloc[0] * 100), 1),
        "top3_pct": round(float(shares.iloc[:3].sum() * 100), 1),
        "hhi": int(round(float((shares**2).sum() * 10000))),
        "top": [{"customer": str(k), "revenue": round(float(v)), "pct": round(float(v / total * 100), 1)}
                for k, v in by.head(6).items()],
    }


_AGING_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def _bucket(days: int) -> str:
    if days <= 0:
        return "current"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def _aging(rec: pd.DataFrame | None, as_of: dt.date) -> dict | None:
    """Receivables aging as of the report date: open balances bucketed by days
    past due (current / 1-30 / 31-60 / 61-90 / 90+), the overdue share, and the
    customers who owe the most overdue. Scores only positive, dated balances -
    the extraction gate already flagged the rest."""
    if rec is None or len(rec) == 0:
        return None
    r = rec.copy()
    r["due_date"] = pd.to_datetime(r["due_date"], errors="coerce")
    r["open_amount"] = pd.to_numeric(r["open_amount"], errors="coerce")
    r = r[r["due_date"].notna() & (r["open_amount"] > 0)]
    if r.empty:
        return None

    r["overdue_days"] = (pd.Timestamp(as_of) - r["due_date"]).dt.days
    r["bucket"] = r["overdue_days"].apply(_bucket)
    by_bucket = r.groupby("bucket")["open_amount"].sum()
    total = float(r["open_amount"].sum())
    overdue = float(r.loc[r["overdue_days"] > 0, "open_amount"].sum())
    over90 = float(by_bucket.get("90+", 0.0))
    by_cust = (r.loc[r["overdue_days"] > 0].groupby("customer")["open_amount"].sum()
               .sort_values(ascending=False))
    return {
        "as_of": as_of.isoformat(),
        "n_invoices": int(len(r)),
        "total": round(total, 2),
        "overdue": round(overdue, 2),
        "overdue_pct": round(overdue / total * 100, 1) if total else 0.0,
        "over90": round(over90, 2),
        "over90_pct": round(over90 / total * 100, 1) if total else 0.0,
        "buckets": [{"bucket": b, "amount": round(float(by_bucket.get(b, 0.0)), 2),
                     "pct": round(float(by_bucket.get(b, 0.0)) / total * 100, 1) if total else 0.0}
                    for b in _AGING_BUCKETS],
        "top_overdue": [{"customer": str(k), "amount": round(float(v), 2)}
                        for k, v in by_cust.head(6).items()],
    }


def compute(frames: dict[str, pd.DataFrame], low_cover_weeks: float, as_of: dt.date) -> dict:
    o = frames["orders"].copy()
    o = o[o.order_date.notna()]
    o["net_total"] = pd.to_numeric(o.net_total, errors="coerce").fillna(0.0)
    o["week"] = _week(o.order_date)
    if o.empty:
        raise EngineError("no orders with a valid order_date in the window")

    # "This week" is the last COMPLETED ISO week by the calendar (never the last
    # week that happens to have data). Build a continuous, gap-filled week axis
    # so empty weeks appear as zeros instead of silently disappearing.
    last_full_monday = wc.last_completed_monday(as_of)
    this_w = wc.iso_week(last_full_monday)
    prev_w = wc.iso_week(last_full_monday - dt.timedelta(days=7))
    first_monday = min(wc.monday_of(o.order_date.min().date()), last_full_monday)
    axis = wc.week_axis(first_monday, last_full_monday)
    if len(axis) < 2:
        raise EngineError("need at least 2 completed weeks in the window")

    baseline_weeks = axis[-9:-1]   # the 8 completed weeks before this_w
    demand_weeks = axis[-8:]       # the last 8 completed weeks (incl. this_w)
    trend_weeks = axis[-13:]       # up to 13 completed weeks ending at this_w

    rev = o.groupby("week").net_total.sum().reindex(axis, fill_value=0.0)
    cnt = o.groupby("week").size().reindex(axis, fill_value=0).astype(float)

    all_delivered = o[o.status.astype(str).str.lower().isin(("delivered", "shipped", "closed"))]
    delivered = all_delivered[all_delivered.actual_ship_date.notna() & all_delivered.promised_date.notna()].copy()
    delivered["on_time"] = delivered.actual_ship_date <= delivered.promised_date
    otp = (delivered.groupby("week").on_time.mean() * 100).reindex(axis)  # NaN where no scored deliveries
    # how much of this week's on-time % is actually backed by data (K3 honesty)
    scored_this = int(len(delivered[delivered.week == this_w]))
    delivered_this = int(len(all_delivered[all_delivered.week == this_w]))

    lines = frames["order_lines"].copy()
    lines["qty"] = pd.to_numeric(lines.qty, errors="coerce").fillna(0.0)
    recent_orders = o[o.week.isin(demand_weeks)][["order_id"]]
    recent_lines = lines.merge(recent_orders, on="order_id")
    weekly_demand = recent_lines.groupby("item_code").qty.sum() / 8.0

    inv = frames["inventory"].copy()
    inv["stock_qty"] = pd.to_numeric(inv.stock_qty, errors="coerce").fillna(0.0)
    inv = inv.set_index("item_code")
    cover = (inv.stock_qty / weekly_demand.reindex(inv.index)).rename("cover_weeks")
    # A stocked-out item is always "low cover", even with no recent demand signal -
    # otherwise stock_qty 0 / demand NaN = NaN slips past the threshold (K5).
    cover.loc[inv.stock_qty == 0] = 0.0
    low = cover[cover < low_cover_weeks].sort_values()

    def wow(series: pd.Series) -> dict:
        now = float(series.get(this_w, float("nan")))
        prev = float(series.get(prev_w, float("nan")))
        base_vals = series[series.index.isin(baseline_weeks)]
        base = float(base_vals.mean()) if len(base_vals) else float("nan")
        return {"now": now, "prev": prev, "baseline8": base}

    return {
        "this_week": this_w,
        "prev_week": prev_w,
        "as_of": as_of.isoformat(),
        "revenue": wow(rev),
        "orders": wow(cnt),
        "on_time_pct": {**wow(otp), "scored": scored_this, "delivered": delivered_this},
        "trend": {  # completed weeks only - the current partial week is never plotted
            "weeks": trend_weeks,
            "revenue": [float(rev.get(w, 0.0)) for w in trend_weeks],
            "on_time": [float(otp.get(w, float("nan"))) for w in trend_weeks],
        },
        "low_cover": [
            {"item_code": str(i), "stock_qty": float(inv.loc[i, "stock_qty"]), "cover_weeks": round(float(c), 1)}
            for i, c in low.head(10).items()
        ],
        "n_low_cover": int(len(low)),
        "concentration": _concentration(o, trend_weeks),
        "aging": _aging(frames.get("receivables"), as_of),
        "_dims": {"orders_frame": o, "this_w": this_w, "prev_w": prev_w},
    }
