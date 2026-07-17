"""The 'measurement honesty' fixes, pinned so they can't silently regress:
- duplicates collapse once, both surfaces agree (K2)
- delivered orders without dates are confessed, not hidden (K3)
- a lost segment is still named as a driver (K4)
- a stocked-out item is always flagged, even with no recent demand (K5)
- the decline streak counts the week the reader is looking at (K6)
- a row per warehouse totals instead of crashing the run (K7)
- stock cover divides by the weeks actually measured, not a hopeful 8 (K8)
- no segment ever 'explains' more than 100% of the move (K9)
- a move nobody can support with the sample is reported, not called (K10)
- a late order that never shipped is counted, not silently excused (K11)
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from erp_report_engine.errors import EngineError
from erp_report_engine.extract import Extraction, _inventory_gate, _quality_gate
from erp_report_engine.insights import _driver, build
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


def test_duplicate_items_are_summed_not_first_wins():
    # A profile that returns a row per warehouse (generic.yaml has no GROUP BY;
    # the three real ERP profiles do) must total the stock, not pick one row.
    inv = pd.DataFrame([("ITM-A", 10.0), ("ITM-A", 15.0), ("ITM-B", 3.0)],
                       columns=["item_code", "stock_qty"])
    ex = Extraction(frames={"inventory": inv})
    _inventory_gate(ex)
    got = dict(zip(ex.frames["inventory"].item_code, ex.frames["inventory"].stock_qty, strict=True))
    assert got == {"ITM-A": 25.0, "ITM-B": 3.0}
    assert any("summed into one row per item" in i for i in ex.issues)


def test_compute_refuses_ungated_duplicate_inventory():
    # Handed ungated frames, the KPI core must name the broken contract rather
    # than die on a Series-where-a-number-was-expected deep in a comprehension.
    frames = _frames_for_stockout()
    frames["inventory"] = pd.concat([frames["inventory"], frames["inventory"]])
    with pytest.raises(EngineError, match="duplicate item_code"):
        compute(frames, low_cover_weeks=2.0, as_of=dt.date(2026, 7, 16))


def test_cover_divides_by_the_weeks_actually_measured():
    # Two weeks of history and 16 units of demand is 8/week, so 20 in stock is
    # 2.5 weeks of cover - below the 3-week threshold, and it must alert.
    # Dividing by a hopeful 8 would read 2/week -> 10 weeks of cover -> silence,
    # on exactly the first run, when a new deployment has the least history.
    ts = pd.Timestamp("2026-07-06")            # 2026-W28, the last completed week
    o = _orders([
        ("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0),
        ("SO-2", ts - pd.Timedelta(weeks=1), "Ege", "C", "delivered", ts, ts, 100.0),
    ])
    lines = pd.DataFrame([("SO-1", "ITM-A", 8.0), ("SO-2", "ITM-A", 8.0)],
                         columns=["order_id", "item_code", "qty"])
    inv = pd.DataFrame([("ITM-A", 20.0)], columns=["item_code", "stock_qty"])
    kpis = compute({"orders": o, "order_lines": lines, "inventory": inv},
                   low_cover_weeks=3.0, as_of=dt.date(2026, 7, 16))
    assert kpis["demand_window_weeks"] == 2
    assert [x["cover_weeks"] for x in kpis["low_cover"]] == [2.5]


def test_driver_share_never_exceeds_one_hundred_percent():
    # One account churns (-1000) while another grows (+1200): the NET move is
    # only +200, so a share taken against it reads 600%. Against gross movement
    # it reads 55% - and the offsetting account gets named, which is the half a
    # manager can actually act on.
    o = pd.DataFrame({
        "week": ["2026-W27", "2026-W28", "2026-W27", "2026-W28"],
        "region": ["Ege", "Ege", "Marmara", "Marmara"],
        "customer": ["Churned", "Churned", "Grower", "Grower"],
        "net_total": [1000.0, 0.0, 0.0, 1200.0],
    })
    d = _driver(o, this_w="2026-W28", prev_w="2026-W27", value_col="net_total")
    assert 0.0 <= d["delta_share"] <= 100.0
    assert d["offset"] is not None and d["offset"]["delta"] < 0


def _kpis_with_on_time(now: float, prev: float, scored: int) -> dict:
    empty = pd.DataFrame(columns=["week", "region", "customer", "net_total"])
    return {
        "_dims": {"orders_frame": empty, "this_w": "2026-W28", "prev_w": "2026-W27"},
        "revenue": {"now": 100.0, "prev": 100.0, "baseline8": 100.0},   # flat: no revenue finding
        "on_time_pct": {"now": now, "prev": prev, "baseline8": prev,
                        "scored": scored, "delivered": scored},
        "n_low_cover": 0,
        "trend": {"weeks": [], "revenue": [], "on_time": []},
        "spc": {"weeks": [], "revenue": [], "on_time": []},
    }


def test_a_thin_on_time_sample_is_reported_not_called():
    texts = " ".join(f["text"] for f in
                     build(_kpis_with_on_time(100.0, 50.0, scored=2), frames={}, low_cover_weeks=2.0))
    assert "too few" in texts                          # 1-of-2 to 2-of-2 is arithmetic, not news
    assert "ops meeting" not in texts                  # and it does not ask anyone to act on it


def test_a_supported_on_time_move_is_called_with_its_sample():
    texts = " ".join(f["text"] for f in
                     build(_kpis_with_on_time(80.0, 95.0, scored=40), frames={}, low_cover_weeks=2.0))
    assert "over 40 scored deliveries" in texts        # the denominator travels with the claim
    assert "ops meeting" in texts


def test_on_time_percent_cannot_see_orders_that_never_shipped():
    """The survivorship trap, made visible.

    One order shipped on time; four were promised the same week and never
    shipped. On-time % reads a triumphant 100% - correctly, by its own
    definition, which scores orders that SHIPPED. Left there, the metric
    improves as fulfilment collapses. So the count it cannot see must travel
    beside it.
    """
    ts = pd.Timestamp("2026-07-06")                    # 2026-W28, last completed week
    rows = [("SO-1", ts, "Ege", "C", "delivered", ts, ts, 100.0)]    # shipped, on time
    rows += [(f"SO-L{i}", ts, "Ege", "C", "open", ts, pd.NaT, 100.0)  # promised, never shipped
             for i in range(4)]
    frames = {
        "orders": _orders(rows),
        "order_lines": pd.DataFrame(columns=["order_id", "item_code", "qty"]),
        "inventory": pd.DataFrame(columns=["item_code", "stock_qty"]),
    }
    frames["orders"] = pd.concat([frames["orders"], _orders([
        ("SO-PREV", ts - pd.Timedelta(weeks=1), "Ege", "C", "delivered",
         ts - pd.Timedelta(weeks=1), ts - pd.Timedelta(weeks=1), 100.0)])], ignore_index=True)

    kpis = compute(frames, low_cover_weeks=2.0, as_of=dt.date(2026, 7, 16))
    s = kpis["on_time_pct"]
    assert s["now"] == 100.0            # the percentage is not wrong - it is incomplete
    assert s["promised_unshipped"] == 4  # and this is what it could not see

    texts = " ".join(f["text"] for f in build(kpis, frames, low_cover_weeks=2.0))
    assert "4 order(s) were promised this week and have not shipped" in texts
    assert "never counts as late" in texts


def test_streak_counts_consecutive_revenue_declines(tmp_path):
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2026-W25", 300.0), ("2026-W26", 200.0), ("2026-W27", 100.0)]:
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")
    assert st.streak("revenue") == 2  # W27<W26<W25 -> two consecutive declines
    st.close()


def test_streak_stops_at_a_gap_in_the_record(tmp_path):
    """"Consecutive" means what the calendar means.

    A run in W25 and the next in W29 is a month apart with nothing recorded
    between. That is missing information, not a continuation - the engine has no
    idea what W26-W28 did, and saying "declining consecutively" about weeks it
    never saw is exactly the kind of confident-and-wrong the report exists to
    avoid.
    """
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2026-W25", 300.0), ("2026-W29", 100.0)]:      # a four-week hole
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")
    assert st.streak("revenue") == 0
    st.close()


def test_streak_survives_a_real_w53_year_boundary(tmp_path):
    # 2015 is one of the ISO years that genuinely HAS a week 53, and 2016-W01
    # follows it. Only the calendar knows that: subtracting week numbers says
    # W53 -> W01 is a 52-week jump backwards.
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2015-W52", 300.0), ("2015-W53", 200.0), ("2016-W01", 100.0)]:
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")
    assert st.streak("revenue") == 2
    st.close()


def test_streak_ignores_a_week_that_does_not_exist(tmp_path):
    # 2025 has no W53 - ISO 2025 is a 52-week year. A row claiming one is
    # corrupt, and corrupt is not adjacent to anything.
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2025-W52", 300.0), ("2025-W53", 100.0)]:
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")
    assert st.streak("revenue") == 0
    st.close()


def test_streak_is_the_same_whether_or_not_this_week_is_persisted(tmp_path):
    """A read-only preview must report the streak the written report would, not
    one short of it - the number is about the business, not about whether a file
    got written."""
    st = State(str(tmp_path / "state.db"))
    for wk, rev in [("2026-W26", 300.0), ("2026-W27", 200.0)]:
        st.record(wk, {"revenue": {"now": rev, "prev": 0, "baseline8": 0}}, "r.html")

    this_week = {"revenue": {"now": 100.0, "prev": 200.0, "baseline8": 0}}
    unwritten = st.streak("revenue", current=("2026-W28", this_week))
    st.record("2026-W28", this_week, "r.html")
    assert unwritten == st.streak("revenue") == 2
    st.close()
