"""Declarative profile contracts - expectations a profile author writes in YAML,
checked over the extracted data and reported in the same gate as the built-in
quality checks.

A profile can carry an optional `contract:` block:

    contract:
      orders:
        severity: fail                 # warn (default) | fail  -> fail trips --strict
        unique: order_id
        not_null: [order_id, order_date, net_total]
        accepted_values:
          status: [open, shipped, delivered, closed, cancelled]
        min_rows: 1
      order_lines:
        relationships: {order_id: orders}   # every order_lines.order_id must exist in orders

Same idea as dbt tests or Soda checks - "a check is a query that returns the
failing rows" - but evaluated in-process over the frames the engine already
fetched, so it adds a contract without adding a dependency.
"""

from __future__ import annotations

import pandas as pd


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def evaluate(profile, frames: dict[str, pd.DataFrame]) -> list[tuple[str, str]]:
    """Return (severity, text) for each contract violation. severity is 'warn'
    or 'fail'; 'fail' is what a caller escalates under --strict."""
    out: list[tuple[str, str]] = []
    contract = getattr(profile, "contract", None) or {}

    for entity, checks in contract.items():
        df = frames.get(entity)
        if df is None or not isinstance(checks, dict):
            continue
        sev = str(checks.get("severity", "warn")).lower()
        if sev not in ("warn", "fail"):
            sev = "warn"

        def emit(msg: str, _sev: str = sev, _entity: str = entity) -> None:
            out.append((_sev, f"contract[{_entity}]: {msg}"))

        for col in _as_list(checks.get("not_null")):
            if col in df.columns:
                n = int(df[col].isna().sum())
                if n:
                    emit(f"{n} rows have a null {col}")

        for col in _as_list(checks.get("unique")):
            if col in df.columns:
                n = int(df.duplicated(subset=[col]).sum())
                if n:
                    emit(f"{n} duplicate {col} values (expected unique)")

        for col, allowed in (checks.get("accepted_values") or {}).items():
            if col in df.columns:
                allowed_lc = {str(a).lower() for a in allowed}
                series = df[col]
                bad = int((series.notna() & ~series.astype(str).str.lower().isin(allowed_lc)).sum())
                if bad:
                    emit(f"{bad} rows have {col} outside {sorted(allowed_lc)}")

        if "min_rows" in checks and len(df) < int(checks["min_rows"]):
            emit(f"{len(df)} rows is below min_rows={checks['min_rows']}")
        if "max_rows" in checks and len(df) > int(checks["max_rows"]):
            emit(f"{len(df)} rows exceeds max_rows={checks['max_rows']}")

        for col, ref_entity in (checks.get("relationships") or {}).items():
            ref = frames.get(ref_entity)
            if ref is not None and col in df.columns and col in ref.columns:
                orphan = int((~df[col].isin(ref[col])).sum())
                if orphan:
                    emit(f"{orphan} rows reference a {ref_entity}.{col} that does not exist")

    return out
