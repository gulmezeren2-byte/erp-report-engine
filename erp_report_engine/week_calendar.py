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


def last_completed_monday(as_of: dt.date) -> dt.date:
    """Monday of the last fully-completed ISO week before the week of ``as_of``."""
    return monday_of(as_of) - dt.timedelta(days=7)


def week_axis(start_monday: dt.date, end_monday: dt.date) -> list[str]:
    """Continuous, gap-free ISO-week keys from ``start_monday`` to ``end_monday``
    inclusive. Empty weeks appear as keys with no data rather than vanishing."""
    weeks: list[str] = []
    m = start_monday
    while m <= end_monday:
        weeks.append(iso_week(m))
        m += dt.timedelta(days=7)
    return weeks
