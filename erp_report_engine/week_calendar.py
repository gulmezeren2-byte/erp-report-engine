"""Calendar-anchored ISO-week helpers shared by the KPI engine and the Power BI
export, so the report and the Command Center always agree on what "this week"
means.

Weeks are keyed as ``YYYY-Www`` (zero-padded ISO week). "This week" is always
the last COMPLETED ISO week relative to an anchor date taken from the database
server - never inferred from which weeks happen to contain orders. That
distinction is the whole point: a Monday-07:00 run, or a holiday week with zero
orders, must not silently shift the headline to a different week.
"""

from __future__ import annotations

import datetime as dt


def monday_of(d: dt.date) -> dt.date:
    """The Monday that starts the ISO week containing ``d``."""
    return d - dt.timedelta(days=d.weekday())


def iso_week(d: dt.date) -> str:
    """ISO-week key ``YYYY-Www`` for ``d`` (handles W53 and year boundaries)."""
    c = d.isocalendar()
    return f"{c.year}-W{c.week:02d}"


def monday_of_week(key: str) -> dt.date:
    """The Monday of an ISO-week key (``2026-W28`` -> 2026-07-06).

    The inverse of :func:`iso_week`. Anything comparing two week keys needs this:
    ``2026-W29`` and ``2026-W25`` sort adjacently as strings and are a month
    apart on the calendar, and string order silently lies across a year boundary
    (``2026-W01`` follows ``2025-W53``). Raises ValueError on a malformed key.
    """
    year, _, week = key.partition("-W")
    return dt.date.fromisocalendar(int(year), int(week), 1)


def is_previous_week(earlier: str, later: str) -> bool:
    """True when ``earlier`` is the ISO week immediately before ``later``."""
    try:
        return monday_of_week(later) - monday_of_week(earlier) == dt.timedelta(days=7)
    except (ValueError, TypeError):
        return False


def last_completed_monday(as_of: dt.date) -> dt.date:
    """Monday of the last fully-completed ISO week before the week of ``as_of``."""
    return monday_of(as_of) - dt.timedelta(days=7)


def window_start(as_of: dt.date, lookback_weeks: int) -> dt.date:
    """First day of the extraction window, snapped back to a Monday.

    Snapped so the oldest week in the window is a full ISO week rather than a
    partial one. Stated once here because both the extraction and the ad-hoc
    query path bind it as `:since`, and a window that differed between them would
    mean an agent's query and the report disagreed about which rows exist.
    """
    return monday_of(as_of) - dt.timedelta(weeks=lookback_weeks + 1)


def week_axis(start_monday: dt.date, end_monday: dt.date) -> list[str]:
    """Continuous, gap-free ISO-week keys from ``start_monday`` to ``end_monday``
    inclusive. Empty weeks appear as keys with no data rather than vanishing."""
    weeks: list[str] = []
    m = start_monday
    while m <= end_monday:
        weeks.append(iso_week(m))
        m += dt.timedelta(days=7)
    return weeks
