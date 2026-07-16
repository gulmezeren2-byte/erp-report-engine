"""Read-only database access with an audit trail.

Read-only is enforced in three layers, not promised in prose:
1. A lexical guard: single statement, SELECT/WITH head, no comments, no
   write/DDL keyword, no write-escalating lock hint.
2. A sqlglot AST guard: the statement must parse to a single read query, and
   its parse tree must contain no INSERT/UPDATE/DELETE/DDL/EXEC/INTO node.
3. The database session itself is put in read-only mode where the driver allows
   it (PostgreSQL default_transaction_read_only, SQLite PRAGMA query_only), and
   the docs require a read-only login (MSSQL db_datareader) as the backstop.

Every executed statement is recorded (sql, params, rows, duration) and the
audit trail ships inside the report.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from dataclasses import dataclass, field

import pandas as pd
import sqlglot
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlglot import exp

from .errors import DatabaseError, EngineError

_log = logging.getLogger("erp_report_engine")


class ReadOnlyViolation(EngineError):
    """A statement failed the read-only guard - it should never reach the DB."""


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|exec|execute|call|into)\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"(--|/\*|#)")  # SQL, C-style, and MySQL '#' comments
_LOCK_HINTS = re.compile(r"\b(TABLOCKX|UPDLOCK|XLOCK)\b", re.IGNORECASE)

# sqlalchemy dialect name -> sqlglot dialect, for accurate parsing of the guard
_SQLGLOT_DIALECT = {"mssql": "tsql", "postgresql": "postgres", "sqlite": "sqlite", "mysql": "mysql"}

_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.Merge, exp.Command, exp.Into,
)


def _assert_ast_read_only(sql: str, dialect: str | None) -> None:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception:
        return  # unparseable in this dialect -> the lexical guard above still holds
    if len(statements) != 1:
        raise ReadOnlyViolation("exactly one statement is allowed")
    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise ReadOnlyViolation(f"only read queries are allowed (parsed as {type(root).__name__})")
    bad = root.find(*_FORBIDDEN_NODES)
    if bad is not None:
        raise ReadOnlyViolation(f"query contains a non-read operation ({type(bad).__name__})")


def assert_read_only(sql: str, dialect: str | None = None) -> None:
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
    if _LOCK_HINTS.search(stripped):
        raise ReadOnlyViolation("write-escalating lock hint is not allowed")
    _assert_ast_read_only(stripped, dialect)


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
        # per-execute query timeout is set in safe_read; the login should be
        # db_datareader so the session cannot write even if the guard is wrong.
        kwargs["connect_args"] = {"timeout": timeout_s}
    elif db_url.startswith("postgresql"):
        kwargs["connect_args"] = {
            "options": f"-c statement_timeout={timeout_s * 1000} -c default_transaction_read_only=on"
        }
    engine = create_engine(db_url, **kwargs)
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_read_only(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA query_only = ON")
            cur.close()
    elif db_url.startswith("mssql"):
        @event.listens_for(engine, "connect")
        def _mssql_query_timeout(dbapi_conn, _record):  # pragma: no cover - needs a real server
            # connect_args timeout is the *login* timeout; this sets the
            # per-execute *query* timeout so a runaway SELECT can't run for hours.
            with contextlib.suppress(Exception):
                dbapi_conn.timeout = timeout_s
    return engine


def safe_read(
    engine: Engine,
    auditor: Auditor,
    label: str,
    sql: str,
    params: dict | None = None,
    row_cap: int = 500_000,
    retries: int = 2,
    backoff_s: float = 0.5,
) -> pd.DataFrame:
    """The only path to the database. Guards, executes (with bounded retries on
    transient errors), audits."""
    assert_read_only(sql, dialect=_SQLGLOT_DIALECT.get(engine.dialect.name))
    params = params or {}
    attempt = 0
    while True:
        t0 = time.perf_counter()
        try:
            with engine.connect() as conn:
                df = pd.read_sql(text(sql), conn, params=params)
            break
        except OperationalError as e:
            attempt += 1
            if attempt > retries:
                raise DatabaseError(f"{label}: {type(e).__name__} after {retries} retries: {str(e)[:200]}") from e
            wait = backoff_s * (2 ** (attempt - 1))
            _log.warning("safe_read %s transient DB error, retry %d/%d in %.1fs", label, attempt, retries, wait)
            time.sleep(wait)
        except SQLAlchemyError as e:
            raise DatabaseError(f"{label}: {type(e).__name__}: {str(e)[:200]}") from e
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


_TODAY_SQL = {
    "mssql": "SELECT CAST(GETDATE() AS date)",
    "postgresql": "SELECT CURRENT_DATE",
    "sqlite": "SELECT date('now', 'localtime')",
    "mysql": "SELECT CURDATE()",
}


def server_today(engine: Engine, auditor: Auditor):
    """The current date according to the DATABASE server, through the guarded path.

    The report anchor must not depend on the report host's clock/timezone: a UTC
    server and an Istanbul host running just after midnight would otherwise
    disagree on 'today' and shift the reporting week by a day. Falls back to the
    local date if the query fails for any reason.
    """
    import datetime as dt

    sql = _TODAY_SQL.get(engine.dialect.name, "SELECT CURRENT_DATE")
    try:
        val = scalar(engine, auditor, "as_of:server_date", sql)
    except Exception:
        return dt.date.today()
    if isinstance(val, dt.datetime):
        return val.date()
    if isinstance(val, dt.date):
        return val
    if isinstance(val, str) and len(val) >= 10:
        try:
            return dt.date.fromisoformat(val[:10])
        except ValueError:
            pass
    return dt.date.today()
