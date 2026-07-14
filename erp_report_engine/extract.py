"""Extraction with a data-quality gate and source reconciliation.

An unattended report must audit its own inputs: every extraction returns the
canonical frame PLUS the issues it found, and each entity's row count is
reconciled with an independent COUNT(*) against the same query.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .connect import Auditor, safe_read, scalar
from .semantic import REQUIRED_COLUMNS, Profile


@dataclass
class Extraction:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    reconciliation: dict[str, dict] = field(default_factory=dict)
    since: dt.date | None = None


def extract_all(engine, auditor: Auditor, profile: Profile, cfg: Config) -> Extraction:
    ex = Extraction()
    ex.since = dt.date.today() - dt.timedelta(weeks=cfg.lookback_weeks + 1)
    since = ex.since.isoformat()

    for entity in ("orders", "order_lines", "inventory"):
        sql = profile.render(entity, cfg.profile_vars)
        params = {"since": since} if ":since" in sql else {}
        df = safe_read(engine, auditor, entity, sql, params, cfg.row_cap)

        missing = [c for c in REQUIRED_COLUMNS[entity] if c not in df.columns]
        if missing:
            raise RuntimeError(
                f"profile '{profile.name}' entity '{entity}' is missing required columns: {missing}"
            )

        # independent count for reconciliation
        count_sql = f"SELECT COUNT(*) FROM ( {sql.strip().rstrip(';')} ) t"
        n_src = scalar(engine, auditor, f"{entity}:count", count_sql, params)
        ex.reconciliation[entity] = {"fetched": int(len(df)), "source_count": int(n_src or 0)}
        if int(n_src or 0) != len(df):
            ex.issues.append(
                f"{entity}: fetched {len(df)} rows but source counts {n_src} - investigate before trusting"
            )

        ex.frames[entity] = df

    _quality_gate(ex)
    return ex


def _quality_gate(ex: Extraction) -> None:
    o = ex.frames["orders"].copy()
    for col in ("order_date", "promised_date", "actual_ship_date"):
        o[col] = pd.to_datetime(o[col], errors="coerce")

    dupes = int(o.duplicated(subset=["order_id"]).sum())
    if dupes:
        ex.issues.append(f"orders: {dupes} duplicated order_id rows (kept - check the profile join)")

    bad_dates = int(o.order_date.isna().sum())
    if bad_dates:
        ex.issues.append(f"orders: {bad_dates} rows with unparseable order_date (excluded from KPIs)")

    neg = int((pd.to_numeric(o.net_total, errors="coerce") < 0).sum())
    if neg:
        ex.issues.append(f"orders: {neg} rows with negative net_total (returns/credit notes? counted as-is)")

    ship_before_order = int((o.actual_ship_date.notna() & (o.actual_ship_date < o.order_date)).sum())
    if ship_before_order:
        ex.issues.append(f"orders: {ship_before_order} rows ship BEFORE order date (data entry suspicion)")

    lines = ex.frames["order_lines"]
    orphan = int(~lines.order_id.isin(o.order_id).sum() if len(lines) else 0)
    orphan = int((~lines.order_id.isin(o.order_id)).sum()) if len(lines) else 0
    if orphan:
        ex.issues.append(f"order_lines: {orphan} lines reference orders outside the window (ignored)")

    ex.frames["orders"] = o
