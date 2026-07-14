"""Read-only database access with an audit trail.

Two hard guarantees, enforced in code rather than promised in docs:
1. Only single-statement SELECT/WITH queries ever reach the database.
2. Every executed statement is recorded (sql, params, rows, duration) and the
   audit trail ships inside the report.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class ReadOnlyViolation(Exception):
    pass


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|exec|execute|call|into)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"(--|/\*)")


def assert_read_only(sql: str) -> None:
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ReadOnlyViolation("multiple statements are not allowed")
    if _COMMENT.search(stripped):
        raise ReadOnlyViolation("SQL comments are not allowed (injection hygiene)")
    head = stripped.split(None, 1)[0].lower() if stripped else ""
    if head not in ("select", "with"):
        raise ReadOnlyViolation(f"only SELECT/WITH statements are allowed (got: {head!r})")
    if _FORBIDDEN.search(stripped):
        raise ReadOnlyViolation("statement contains a forbidden keyword")


@dataclass
class AuditEntry:
    label: str
    sql: str
    params: dict
    rows: int
    seconds: float


@dataclass
class Auditor:
    entries: list[AuditEntry] = field(default_factory=list)

    def record(self, label: str, sql: str, params: dict, rows: int, seconds: float) -> None:
        self.entries.append(AuditEntry(label, " ".join(sql.split()), dict(params), rows, round(seconds, 3)))


def make_engine(db_url: str, timeout_s: int) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if db_url.startswith("mssql"):
        kwargs["connect_args"] = {"timeout": timeout_s}
    elif db_url.startswith("postgresql"):
        kwargs["connect_args"] = {"options": f"-c statement_timeout={timeout_s * 1000}"}
    return create_engine(db_url, **kwargs)


def safe_read(
    engine: Engine,
    auditor: Auditor,
    label: str,
    sql: str,
    params: dict | None = None,
    row_cap: int = 500_000,
) -> pd.DataFrame:
    """The only path to the database. Guards, executes, audits."""
    assert_read_only(sql)
    params = params or {}
    t0 = time.perf_counter()
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params)
    dt = time.perf_counter() - t0
    if len(df) > row_cap:
        raise ReadOnlyViolation(
            f"{label}: {len(df)} rows exceeds row_cap={row_cap} - narrow the query window"
        )
    auditor.record(label, sql, params, len(df), dt)
    return df


def scalar(engine: Engine, auditor: Auditor, label: str, sql: str, params: dict | None = None):
    df = safe_read(engine, auditor, label, sql, params, row_cap=10)
    return None if df.empty else df.iloc[0, 0]
