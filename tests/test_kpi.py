"""Calendar-anchor unit tests for kpi.compute.

These pin the behavior the whole 'measurement honesty' pitch rests on: the
headline week is the last COMPLETED ISO week by the calendar, never the last
week that happens to contain orders. A Monday-morning run, or a holiday week
with zero orders, must not silently report a stale week.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from erp_report_engine import insights
from erp_report_engine.kpi import _aging, compute


def _frames(week_revenue: dict[int, float], year: int = 2026):
    """Build minimal canonical frames with one order per (ISO week -> revenue)."""
    orders = []
    lines = []
    for oid, (week, rev) in enumerate(week_revenue.items(), start=1):
        monday = dt.date.fromisocalendar(year, week, 3)  # Wednesday of that ISO week
        oidk = f"SO-{oid:04d}"
        orders.append((
            oidk, pd.Timestamp(monday), "Ege", "Musteri-01", "delivered",
            pd.Timestamp(monday + dt.timedelta(days=2)),
            pd.Timestamp(monday + dt.timedelta(days=1)),  # shipped before promised = on time
            float(rev),
        ))
        lines.append((oidk, "ITM-001", 10.0))
    o = pd.DataFrame(orders, columns=[
        "order_id", "order_date", "region", "customer", "status",
        "promised_date", "actual_ship_date", "net_total"])
    ol = pd.DataFrame(lines, columns=["order_id", "item_code", "qty"])
    inv = pd.DataFrame([("ITM-001", 5.0)], columns=["item_code", "stock_qty"])
    return {"orders": o, "order_lines": ol, "inventory": inv}


def test_this_week_is_last_completed_week_not_last_with_data():
    # Anchor: Thu 2026-07-16 is in ISO week 29 (Mon 2026-07-13).
    # Orders exist only through week 27 - weeks 28 (last completed) and 29
    # (current, partial) have NO orders.
    as_of = dt.date(2026, 7, 16)
    frames = _frames({25: 1000.0, 26: 1100.0, 27: 1200.0})
    kpis = compute(frames, low_cover_weeks=2.0, as_of=as_of)

    # last COMPLETED week is 28, even though the freshest data is week 27
    assert kpis["this_week"] == "2026-W28"
    assert kpis["prev_week"] == "2026-W27"
    # week 28 genuinely had no orders -> zero, not a stale carry-over of week 27
    assert kpis["revenue"]["now"] == 0.0
    assert kpis["revenue"]["prev"] == 1200.0
    # the current partial week (29) is never the headline
    assert "2026-W29" not in kpis["trend"]["weeks"]
    assert kpis["trend"]["weeks"][-1] == "2026-W28"


def test_empty_middle_week_reads_as_zero_and_keeps_calendar_adjacency():
    # Orders in weeks 26 and 28 but a hole at 27. Anchor in week 30 so 29 is the
    # last completed week (also empty).
    as_of = dt.date(2026, 7, 23)  # ISO week 30
    frames = _frames({26: 900.0, 28: 1500.0})
    kpis = compute(frames, low_cover_weeks=2.0, as_of=as_of)

    assert kpis["this_week"] == "2026-W29"
    weeks = kpis["trend"]["weeks"]
    rev = dict(zip(weeks, kpis["trend"]["revenue"], strict=True))
    # the gap week 27 is present and zero (not skipped, not merged away)
    assert "2026-W27" in rev
    assert rev["2026-W27"] == 0.0
    assert rev["2026-W28"] == 1500.0
    assert rev["2026-W29"] == 0.0


def test_year_boundary_week_keys_are_ordered_and_padded():
    # Late-December / early-January anchor exercises ISO week 52/53 -> 01.
    as_of = dt.date(2027, 1, 14)
    frames = _frames({51: 500.0, 52: 600.0}, year=2026)
    kpis = compute(frames, low_cover_weeks=2.0, as_of=as_of)
    # keys are zero-padded YYYY-Www and sort chronologically as strings
    assert all(len(w) == 8 and w[4:6] == "-W" for w in kpis["trend"]["weeks"])
    assert kpis["trend"]["weeks"] == sorted(kpis["trend"]["weeks"])


def _multi_customer_frames(year: int = 2026):
    """Orders across weeks 24-28 with one dominant customer and three small ones."""
    rows, lines, oid = [], [], 0
    for week in range(24, 29):
        wed = dt.date.fromisocalendar(year, week, 3)
        for cust, rev in [("Big", 800.0), ("Small-1", 60.0), ("Small-2", 50.0), ("Small-3", 40.0)]:
            oid += 1
            oidk = f"SO-{oid:04d}"
            rows.append((oidk, pd.Timestamp(wed), "Ege", cust, "delivered",
                         pd.Timestamp(wed + dt.timedelta(days=2)),
                         pd.Timestamp(wed + dt.timedelta(days=1)), rev))
            lines.append((oidk, "ITM-001", 10.0))
    o = pd.DataFrame(rows, columns=[
        "order_id", "order_date", "region", "customer", "status",
        "promised_date", "actual_ship_date", "net_total"])
    ol = pd.DataFrame(lines, columns=["order_id", "item_code", "qty"])
    inv = pd.DataFrame([("ITM-001", 5.0)], columns=["item_code", "stock_qty"])
    return {"orders": o, "order_lines": ol, "inventory": inv}


def test_revenue_concentration_analysis():
    kpis = compute(_multi_customer_frames(), low_cover_weeks=2.0, as_of=dt.date(2026, 7, 16))
    c = kpis["concentration"]
    assert c["n_customers"] == 4
    assert c["top"][0]["customer"] == "Big"                 # ranked, dominant first
    assert c["top1_pct"] > 80 and c["top3_pct"] > 90        # heavily concentrated
    assert c["hhi"] > 2500                                  # HHI in the "concentrated" band
    # shares are a descending ranking
    pcts = [t["pct"] for t in c["top"]]
    assert pcts == sorted(pcts, reverse=True)


def test_concentration_finding_fires_on_risk_and_is_silent_when_diversified():
    base = {
        "revenue": {"now": 100.0, "prev": 100.0}, "on_time_pct": {"now": 90.0, "prev": 90.0},
        "n_low_cover": 0, "low_cover": [], "trend": {"weeks": [], "revenue": [], "on_time": []},
        "_dims": {"orders_frame": pd.DataFrame({"week": [], "customer": [], "net_total": []}),
                  "this_w": "2026-W28", "prev_w": "2026-W27"},
    }
    risky = {**base, "concentration": {"window_weeks": 13, "n_customers": 5,
                                       "top1_pct": 72.0, "top3_pct": 88.0, "hhi": 5400, "top": []}}
    findings = insights.build(risky, {}, low_cover_weeks=2.0)
    conc = [f for f in findings if "concentration" in f["text"].lower()]
    assert len(conc) == 1 and conc[0]["tone"] == "warn"
    assert "88%" in conc[0]["text"] and "HHI 5400" in conc[0]["text"]

    diversified = {**base, "concentration": {"window_weeks": 13, "n_customers": 20,
                                             "top1_pct": 9.0, "top3_pct": 24.0, "hhi": 620, "top": []}}
    assert not any("concentration" in f["text"].lower()
                   for f in insights.build(diversified, {}, low_cover_weeks=2.0))


def test_receivables_aging_buckets_are_inclusive_at_the_edges():
    as_of = dt.date(2026, 7, 16)

    def due(days_overdue: int) -> str:            # due_date giving exactly this overdue
        return (as_of - dt.timedelta(days=days_overdue)).isoformat()

    rec = pd.DataFrame([
        ("A", "C1", due(-5), 100.0), ("B", "C1", due(0), 100.0),    # current (<= 0)
        ("C", "C2", due(1), 100.0), ("D", "C2", due(30), 100.0),    # 1-30
        ("E", "C3", due(31), 100.0), ("F", "C3", due(60), 100.0),   # 31-60
        ("G", "C4", due(61), 100.0), ("H", "C4", due(90), 100.0),   # 61-90
        ("I", "C5", due(91), 100.0), ("J", "C5", due(200), 300.0),  # 91+
    ], columns=["invoice_id", "customer", "due_date", "open_amount"])

    a = _aging(rec, as_of)
    b = {x["bucket"]: x["amount"] for x in a["buckets"]}
    # 61-90 is inclusive of day 90, so the last bucket starts at 91 and is named
    # for it. "90+" would have claimed a boundary the arithmetic does not have.
    assert b == {"current": 200.0, "1-30": 200.0, "31-60": 200.0, "61-90": 200.0, "91+": 400.0}
    assert a["total"] == 1200.0 and a["overdue"] == 1000.0 and a["over90"] == 400.0
    assert a["top_overdue"][0] == {"customer": "C5", "amount": 400.0}   # worst overdue first


def test_aging_is_none_without_usable_receivables():
    assert _aging(None, dt.date(2026, 7, 16)) is None
    empty = pd.DataFrame(columns=["invoice_id", "customer", "due_date", "open_amount"])
    assert _aging(empty, dt.date(2026, 7, 16)) is None
    # a frame with only unusable rows (no due date / non-positive) also yields None
    junk = pd.DataFrame([("X", "C", None, 100.0), ("Y", "C", "2026-01-01", -5.0)],
                        columns=["invoice_id", "customer", "due_date", "open_amount"])
    assert _aging(junk, dt.date(2026, 7, 16)) is None
