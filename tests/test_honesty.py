"""The 'measurement honesty' fixes, pinned so they can't silently regress:
- duplicates collapse once, both surfaces agree (K2)
- delivered orders without dates are confessed, not hidden (K3)
- a lost segment is still named as a driver (K4)
- a stocked-out item is always flagged, even with no recent demand (K5)
- the decline streak counts the week the reader is looking at (K6)
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from erp_report_engine.extract import Extraction, _quality_gate
from erp_report_engine.insights import _driver
from erp_report_engine.kpi import compute
from erp_report_engine.state import State


def _orders(rows):
    return pd.DataFrame(rows, columns=[
        "order_id", "order_date", "region", "customer", "status",
        "promised_date", "actual_ship_date", "net_total"])


def test_quality_gate_collapses_duplicates_once():
    ts = pd.Timestamp("2026-07-06")
    o = _orders([
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),  # exact duplicate
        ("SO-2", ts, "Ege", "C", "delivered", ts, ts, 50.0),
    ])
    ex = Extraction(frames={"orders": o, "order_lines": pd.DataFrame(columns=["order_id", "item_code", "qty"])})
    _quality_gate(ex)
    assert len(ex.frames["orders"]) == 2  # collapsed to one SO-1
    assert any("collapsed to one" in i for i in ex.issues)


def test_quality_gate_confesses_unscored_deliveries():
    ts = pd.Timestamp("2026-07-06")
    o = _orders([
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),          # scored
        ("SO-2", ts, "Ege", "C", "delivered", pd.NaT, pd.NaT, 50.0),   # delivered, no dates
    ])
    ex = Extraction(frames={"orders": o, "order_lines": pd.DataFrame(columns=["order_id", "item_code", "qty"])})
    _quality_gate(ex)
    assert any("lack a promised or ship date" in i for i in ex.issues)


def test_driver_catches_a_vanished_segment():
    # Whale had all the revenue last week and none this week - the biggest move.
    o = pd.DataFrame({
        "week": ["2026-W27", "2026-W28"],
        "region": ["Whale", "Minnow"],
        "customer": ["A", "B"],
        "net_total": [1000.0, 10.0],
    })
    d = _driver(o, this_w="2026-W28", prev_w="2026-W27", value_col="net_total")
    assert d["segment"] == "Whale"        # not dropped just because it's absent this week


def _frames_for_stockout():
    ts = pd.Timestamp("2026-07-06")
    o = _orders([
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),
        ("SO-2", ts - pd.Timedelta(days=7), "Ege", "C", "delivered", ts, ts, 100.0),
    ])
    lines = pd.DataFrame([("SO-1", "ITM-A", 5.0)], columns=["order_id", "item_code", "qty"])
    inv = pd.DataFrame([("ITM-A", 20.0), ("ITM-OUT", 0.0)], columns=["item_code", "stock_qty"])
    return {"orders": o, "order_lines": lines, "inventory": inv}


def test_stocked_out_item_is_flagged_even_without_demand():
    kpis = compute(_frames_for_stockout(), low_cover_weeks=2.0, as_of=dt.date(2026, 7, 16))
    flagged = {x["item_code"] for x in kpis["low_cover"]}
    assert "ITM-OUT" in flagged  # zero stock, no recent demand -> still surfaced


def test_streak_counts_consecutive_revenue_declines(tmp_path):
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2026-W25", 300.0), ("2026-W26", 200.0), ("2026-W27", 100.0)]:
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")
    assert st.streak("revenue") == 2  # W27<W26<W25 -> two consecutive declines
    st.close()
