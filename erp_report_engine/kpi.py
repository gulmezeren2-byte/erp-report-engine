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

    delivered = o[o.status.astype(str).str.lower().isin(("delivered", "shipped", "closed"))].copy()
    delivered = delivered[delivered.actual_ship_date.notna() & delivered.promised_date.notna()]
    delivered["on_time"] = delivered.actual_ship_date <= delivered.promised_date
    otp = (delivered.groupby("week").on_time.mean() * 100).reindex(axis)  # NaN where no scored deliveries

    lines = frames["order_lines"].copy()
    lines["qty"] = pd.to_numeric(lines.qty, errors="coerce").fillna(0.0)
    recent_orders = o[o.week.isin(demand_weeks)][["order_id"]]
    recent_lines = lines.merge(recent_orders, on="order_id")
    weekly_demand = recent_lines.groupby("item_code").qty.sum() / 8.0

    inv = frames["inventory"].copy()
    inv["stock_qty"] = pd.to_numeric(inv.stock_qty, errors="coerce").fillna(0.0)
    inv = inv.set_index("item_code")
    cover = (inv.stock_qty / weekly_demand.reindex(inv.index)).rename("cover_weeks")
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
        "on_time_pct": wow(otp),
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
        "_dims": {"orders_frame": o, "this_w": this_w, "prev_w": prev_w},
    }
