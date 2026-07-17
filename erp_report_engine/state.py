"""Run-state store: a small SQLite file that gives the engine memory.

Keeps every run's KPI snapshot so the report can say "third consecutive
decline" instead of only "down vs last week" - trend memory beyond the
lookback window, without re-querying the ERP.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3

from . import week_calendar as wc


class State:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS runs ("
            " run_at TEXT, week TEXT, kpis_json TEXT, report_path TEXT)"
        )
        self.conn.commit()

    def record(self, week: str, kpis: dict, report_path: str) -> None:
        slim = {k: v for k, v in kpis.items() if not k.startswith("_") and k != "trend"}
        self.conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?)",
            (dt.datetime.now().isoformat(timespec="seconds"), week, json.dumps(slim), report_path),
        )
        self.conn.commit()

    def streak(self, metric: str = "revenue", *, current: tuple[str, dict] | None = None) -> int:
        """Consecutive weekly declines of a metric, newest week first.

        "Consecutive" means what the calendar means. This used to compare the
        stored weeks in order without asking whether they were ADJACENT, so a run
        in W25 followed by the next run in W29 - a month later, nothing recorded
        between - reported "1 consecutive decline". A gap is missing information,
        not a continuation, and the streak stops there.

        Ordered by the ISO WEEK key, not by run timestamp: two runs recorded in
        the same second (a re-run, or a test) must not scramble the sequence. The
        latest run per week wins via MAX(run_at).

        `current` is this week's (week_key, kpis), for a caller that has not
        persisted it - a read-only preview must report the same streak as the
        written report, not one short of it.
        """
        rows = self.conn.execute(
            "SELECT week, kpis_json, MAX(run_at) FROM runs GROUP BY week ORDER BY week DESC LIMIT 26"
        ).fetchall()
        series: list[tuple[str, float]] = []
        for week, blob, _run_at in rows:
            try:
                series.append((week, float(json.loads(blob)[metric]["now"])))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                break   # this week can't be compared, so nothing older can be either

        if current is not None:
            week, kpis = current
            series = [(w, v) for w, v in series if w != week]
            with contextlib.suppress(ValueError, TypeError, KeyError):
                series.insert(0, (week, float(kpis[metric]["now"])))
            series.sort(key=lambda wv: wv[0], reverse=True)

        streak = 0
        for (w_new, v_new), (w_old, v_old) in zip(series, series[1:], strict=False):
            if not wc.is_previous_week(w_old, w_new):
                break   # a gap in the record: we do not know what happened between
            if v_new != v_new or v_old != v_old or not v_new < v_old:
                break
            streak += 1
        return streak

    def close(self) -> None:
        self.conn.close()
