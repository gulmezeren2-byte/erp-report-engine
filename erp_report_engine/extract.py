"""Extraction with a data-quality gate and source reconciliation.

An unattended report must audit its own inputs: every extraction returns the
canonical frame PLUS the issues it found, and each entity's row count is
reconciled with an independent COUNT(*) against the same query.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
import sqlglot

from .config import Config
from .connect import _SQLGLOT_DIALECT, Auditor, safe_read, scalar
from .errors import ContractError
from .kpi import _DELIVERED  # one definition of "it shipped", imported, never restated
from .semantic import OPTIONAL_COLUMNS, REQUIRED_COLUMNS, Profile


@dataclass
class Extraction:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    reconciliation: dict[str, dict] = field(default_factory=dict)
    since: dt.date | None = None
    as_of: dt.date | None = None
    contract_failures: list[str] = field(default_factory=list)


def extract_all(engine, auditor: Auditor, profile: Profile, cfg: Config) -> Extraction:
    from . import week_calendar as wc
    from .connect import server_today

    ex = Extraction()
    # anchor on the DATABASE server's date, and snap the window start to a Monday
    # so the oldest week in the window is a full ISO week, not a partial one.
    ex.as_of = server_today(engine, auditor)
    ex.since = wc.window_start(ex.as_of, cfg.lookback_weeks)
    since = ex.since.isoformat()

    all_columns = {**REQUIRED_COLUMNS, **OPTIONAL_COLUMNS}
    # required entities first, then any optional ones the profile actually maps
    for entity in ("orders", "order_lines", "inventory", *sorted(profile.optional_entities)):
        sql = profile.render(entity, cfg.profile_vars)
        params = {"since": since} if ":since" in sql else {}
        df = safe_read(engine, auditor, entity, sql, params, cfg.row_cap)

        missing = [c for c in all_columns[entity] if c not in df.columns]
        if missing:
            raise ContractError(
                f"profile '{profile.name}' entity '{entity}' is missing required columns: {missing}"
            )

        # independent count for reconciliation
        count_sql = _count_wrapper(sql, _SQLGLOT_DIALECT.get(engine.dialect.name))
        n_src = scalar(engine, auditor, f"{entity}:count", count_sql, params)
        ex.reconciliation[entity] = {"fetched": int(len(df)), "source_count": int(n_src or 0)}
        if int(n_src or 0) != len(df):
            ex.issues.append(
                f"{entity}: fetched {len(df)} rows but source counts {n_src} - investigate before trusting"
            )

        ex.frames[entity] = df

    _quality_gate(ex)
    _inventory_gate(ex)
    if "receivables" in ex.frames:
        _receivables_gate(ex)

    # declarative profile contracts (optional `contract:` block), reported in
    # the same gate; `fail`-severity violations trip --strict.
    from . import contracts
    for severity, text in contracts.evaluate(profile, ex.frames):
        ex.issues.append(text)
        if severity == "fail":
            ex.contract_failures.append(text)
    return ex


def _count_wrapper(sql: str, dialect: str | None) -> str:
    """An independent COUNT(*) over the same query, for reconciliation.

    A top-level ORDER BY is stripped first. It means nothing to a COUNT, and MSSQL
    and Oracle both refuse a subquery carrying one without TOP/OFFSET - so on the
    engines two of the three bundled profiles actually target, reconciliation
    would have been the thing that broke the run. The feature that exists to prove
    the numbers is a poor candidate for the feature that stops them arriving.
    """
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
        tree.set("order", None)
        inner = tree.sql(dialect=dialect)
    except Exception:
        inner = sql.strip().rstrip(";")   # the guard already parsed this; belt and braces
    return f"SELECT COUNT(*) FROM ( {inner} ) t"


def _quality_gate(ex: Extraction) -> None:
    o = ex.frames["orders"].copy()
    for col in ("order_date", "promised_date", "actual_ship_date"):
        o[col] = pd.to_datetime(o[col], errors="coerce")

    # Deduplicate ONCE here (keep first) so the HTML report and the Power BI
    # export compute revenue over the same rows - "one definition, two surfaces".
    dupes = int(o.duplicated(subset=["order_id"]).sum())
    if dupes:
        o = o.drop_duplicates(subset=["order_id"], keep="first")
        ex.issues.append(
            f"orders: {dupes} duplicated order_id rows collapsed to one for all KPIs "
            "(check the profile join)"
        )

    bad_dates = int(o.order_date.isna().sum())
    if bad_dates:
        ex.issues.append(f"orders: {bad_dates} rows with unparseable order_date (excluded from KPIs)")

    neg = int((pd.to_numeric(o.net_total, errors="coerce") < 0).sum())
    if neg:
        ex.issues.append(f"orders: {neg} rows with negative net_total (returns/credit notes? counted as-is)")

    ship_before_order = int((o.actual_ship_date.notna() & (o.actual_ship_date < o.order_date)).sum())
    if ship_before_order:
        ex.issues.append(f"orders: {ship_before_order} rows ship BEFORE order date (data entry suspicion)")

    # On-time % only scores delivered orders that HAVE both dates. Surface the
    # unscored share so a high on-time % over a fraction of orders isn't mistaken
    # for the whole picture (survivorship bias is on-brand to confess, not hide).
    delivered = o[o.status.astype(str).str.lower().isin(_DELIVERED)]
    unscored = int((delivered.promised_date.isna() | delivered.actual_ship_date.isna()).sum())
    if unscored:
        ex.issues.append(
            f"orders: {unscored} delivered orders lack a promised or ship date - "
            "excluded from on-time %, which is scored over the rest"
        )

    lines = ex.frames["order_lines"]
    orphan = int((~lines.order_id.isin(o.order_id)).sum()) if len(lines) else 0
    if orphan:
        ex.issues.append(f"order_lines: {orphan} lines reference orders outside the window (ignored)")

    ex.frames["orders"] = o


def _inventory_gate(ex: Extraction) -> None:
    """Collapse duplicate item_code rows by SUMMING the stock.

    Every bundled ERP profile already groups by the item and sums the quantity,
    so the canonical contract is one row per item carrying the total on hand. A
    profile that returns a row per warehouse (or joins a lot/batch table) breaks
    that contract silently: a lookup by item_code then yields a Series instead of
    a number, and the Power BI dim_item key stops being unique. Sum it here so
    the contract holds for every profile - and say so in the gate.
    """
    inv = ex.frames["inventory"].copy()
    inv["stock_qty"] = pd.to_numeric(inv.stock_qty, errors="coerce").fillna(0.0)

    dupes = int(inv.duplicated(subset=["item_code"]).sum())
    if dupes:
        others = {c: "first" for c in inv.columns if c not in ("item_code", "stock_qty")}
        inv = inv.groupby("item_code", as_index=False).agg({"stock_qty": "sum", **others})
        ex.issues.append(
            f"inventory: {dupes} duplicated item_code rows summed into one row per item "
            "(a row per warehouse or lot? add a GROUP BY to the profile)"
        )

    neg = int((inv.stock_qty < 0).sum())
    if neg:
        ex.issues.append(
            f"inventory: {neg} items with negative stock_qty (oversold or a data error? "
            "counted as-is, and they sort to the top of low cover)"
        )

    ex.frames["inventory"] = inv


def _receivables_gate(ex: Extraction) -> None:
    """Clean and audit the optional receivables frame the same way as orders:
    dedupe invoices, flag unparseable due dates and negative (credit) balances.
    The aging analysis then scores only positive, dated open balances."""
    r = ex.frames["receivables"].copy()
    r["due_date"] = pd.to_datetime(r["due_date"], errors="coerce")
    r["open_amount"] = pd.to_numeric(r["open_amount"], errors="coerce")

    dupes = int(r.duplicated(subset=["invoice_id"]).sum())
    if dupes:
        r = r.drop_duplicates(subset=["invoice_id"], keep="first")
        ex.issues.append(f"receivables: {dupes} duplicated invoice_id rows collapsed to one")
    bad_due = int(r.due_date.isna().sum())
    if bad_due:
        ex.issues.append(f"receivables: {bad_due} rows with unparseable due_date (excluded from aging)")
    neg = int((r.open_amount < 0).sum())
    if neg:
        ex.issues.append(
            f"receivables: {neg} rows with negative open_amount (credit balances? excluded from aging)")

    ex.frames["receivables"] = r
