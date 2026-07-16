"""Run-state store: a small SQLite file that gives the engine memory.

Keeps every run's KPI snapshot so the report can say "third consecutive
decline" instead of only "down vs last week" - trend memory beyond the
lookback window, without re-querying the ERP.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3


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

    def streak(self, metric: str = "revenue") -> int:
        """Consecutive weekly declines of a metric, newest week first.

        Ordered by the ISO WEEK key, not by run timestamp: two runs recorded in
        the same second (a re-run, or a test) must not scramble the sequence.
        The latest run per week wins via MAX(run_at).
        """
        rows = self.conn.execute(
            "SELECT week, kpis_json, MAX(run_at) FROM runs GROUP BY week ORDER BY week DESC LIMIT 13"
        ).fetchall()
        values = []
        for _week, blob, _run_at in rows:
            try:
                values.append(json.loads(blob)[metric]["now"])
            except Exception:
                break
        streak = 0
        for newer, older in zip(values, values[1:], strict=False):
            if newer < older:
                streak += 1
            else:
                break
        return streak

    def close(self) -> None:
        self.conn.close()
