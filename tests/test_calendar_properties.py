"""Property-based tests over the calendar core - the piece the whole 'this week'
guarantee rests on. Twenty years of random dates, including W53 years and the
December/January ISO-year boundaries where naive week math breaks."""

from __future__ import annotations

import datetime as dt

from hypothesis import given
from hypothesis import strategies as st

from erp_report_engine import week_calendar as wc

_dates = st.dates(min_value=dt.date(2015, 1, 1), max_value=dt.date(2035, 12, 31))


@given(_dates)
def test_monday_of_is_always_a_monday(d):
    assert wc.monday_of(d).weekday() == 0


@given(_dates)
def test_last_completed_monday_is_exactly_one_week_before_this_week(d):
    lcm = wc.last_completed_monday(d)
    assert lcm.weekday() == 0
    assert (wc.monday_of(d) - lcm).days == 7  # strictly the previous ISO week


@given(_dates)
def test_iso_week_key_is_well_formed(d):
    k = wc.iso_week(d)
    assert len(k) == 8 and k[4:6] == "-W"
    assert 1 <= int(k[6:]) <= 53


@given(_dates, st.integers(min_value=0, max_value=80))
def test_week_axis_is_contiguous_sorted_and_unique(d, n):
    end = wc.monday_of(d)
    start = end - dt.timedelta(weeks=n)
    axis = wc.week_axis(start, end)
    assert len(axis) == n + 1                 # one key per week, no gaps
    assert len(set(axis)) == len(axis)        # no duplicates across year boundaries
    assert axis == sorted(axis)               # zero-padded keys sort chronologically
    assert axis[-1] == wc.iso_week(end)
