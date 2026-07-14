"""Weekly KPI computation over canonical entities.

Definitions are explicit and travel with the report:
- revenue: sum(net_total) of orders by ISO week of order_date
- on-time %: delivered orders with actual_ship_date <= promised_date
  (an OTIF-lite: completeness requires line-level receipts most ERPs lack;
  the report says so instead of pretending)
- stock cover: stock_qty / average weekly demand of the last 8 weeks
"""

from __future__ import annotations

import pandas as pd


def _week(s: pd.Series) -> pd.Series:
    iso = s.dt.isocalendar()
    return iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)


def compute(frames: dict[str, pd.DataFrame], low_cover_weeks: float) -> dict:
    o = frames["orders"].copy()
    o = o[o.order_date.notna()]
    o["net_total"] = pd.to_numeric(o.net_total, errors="coerce").fillna(0.0)
    o["week"] = _week(o.order_date)

    weeks = sorted(o.week.unique())
    if len(weeks) < 3:
        raise RuntimeError("need at least 3 weeks of data in the window")
    this_w, prev_w = weeks[-2], weeks[-3]  # last FULL week vs the one before
    baseline_weeks = weeks[max(0, len(weeks) - 10):-2]

    rev = o.groupby("week").net_total.sum()
    cnt = o.groupby("week").size()

    delivered = o[o.status.astype(str).str.lower().isin(("delivered", "shipped", "closed"))].copy()
    delivered = delivered[delivered.actual_ship_date.notna() & delivered.promised_date.notna()]
    delivered["on_time"] = delivered.actual_ship_date <= delivered.promised_date
    otp = delivered.groupby("week").on_time.mean() * 100

    lines = frames["order_lines"].copy()
    lines["qty"] = pd.to_numeric(lines.qty, errors="coerce").fillna(0.0)
    recent_orders = o[o.week.isin(weeks[-9:-1])][["order_id"]]
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
        base = float(series[series.index.isin(baseline_weeks)].mean()) if len(baseline_weeks) else float("nan")
        return {"now": now, "prev": prev, "baseline8": base}

    return {
        "this_week": this_w,
        "prev_week": prev_w,
        "revenue": wow(rev),
        "orders": wow(cnt.astype(float)),
        "on_time_pct": wow(otp),
        "trend": {  # full weeks only - the current partial week would paint a fake crash
            "weeks": weeks[-14:-1],
            "revenue": [float(rev.get(w, 0.0)) for w in weeks[-14:-1]],
            "on_time": [float(otp.get(w, float("nan"))) for w in weeks[-14:-1]],
        },
        "low_cover": [
            {"item_code": str(i), "stock_qty": float(inv.loc[i, "stock_qty"]), "cover_weeks": round(float(c), 1)}
            for i, c in low.head(10).items()
        ],
        "n_low_cover": int(len(low)),
        "_dims": {"orders_frame": o, "this_w": this_w, "prev_w": prev_w},
    }
