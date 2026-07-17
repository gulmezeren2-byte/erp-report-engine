"""Read-only database access with an audit trail.

Read-only is enforced in layers, and this docstring is deliberately precise
about which layer carries which guarantee - "read-only by construction" is a
claim about the guard, and a guard that checks a statement's SHAPE while
ignoring the FUNCTIONS it calls does not earn it.

1. A lexical guard, over the statement with string literals blanked out (a
   keyword inside a quoted value is data, not code): single statement, SELECT/
   WITH head, no comments, no write/DDL keyword, no write-escalating lock hint,
   no call to a side-effecting function.
2. A sqlglot AST guard. The statement must PARSE - if it cannot, it is refused,
   not waved through: a guard that cannot read a query cannot vouch for it. It
   must parse to a single read query with no INSERT/UPDATE/DELETE/DDL/EXEC/INTO
   node, and it must call no function on the denylist below - because plenty of
   pure-looking SELECTs write files, open sockets or edit the session.
3. Strict mode (`strict=True`, used for agent- and human-supplied ad-hoc SQL)
   additionally refuses EVERY function sqlglot does not recognise. sqlglot's own
   function registry is the allowlist: it knows the portable analytic functions
   and nothing that reads a file or dials out, so default-deny costs nothing.
   All four bundled profiles pass it - they use no anonymous functions at all.
4. The database session itself is put in read-only mode where the driver allows
   it (PostgreSQL default_transaction_read_only, SQLite PRAGMA query_only, MySQL
   SET SESSION TRANSACTION READ ONLY), with a per-statement timeout everywhere.

What this does NOT do, stated plainly: MSSQL has no session-level read-only
switch, so there layer 4 is the login itself. A least-privilege, read-only login
(MSSQL db_datareader, or a PostgreSQL role with no write grants - ideally a
physical read replica) remains the outermost layer on every engine, and it is
the only one that holds if the guard has a hole. The guard is defence in depth,
not a substitute for the grant.

Every executed statement is recorded (sql, params, rows, duration) and the
audit trail ships inside the report.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from .errors import DatabaseError

# The read-only guard lives in guard.py - dependency-light (only re + sqlglot) so
# it can run standalone, including in the browser trust playground. Re-exported
# here so every `from .connect import assert_read_only / ReadOnlyViolation /
# _SQLGLOT_DIALECT` across the codebase keeps working, one definition behind it.
from .guard import _SQLGLOT_DIALECT, ReadOnlyViolation, assert_read_only

__all__ = [
    "assert_read_only", "ReadOnlyViolation", "_SQLGLOT_DIALECT",
    "Auditor", "AuditEntry", "make_engine", "safe_read", "scalar", "server_today",
]

_log = logging.getLogger("erp_report_engine")


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
    elif db_url.startswith("mysql"):
        @event.listens_for(engine, "connect")
        def _mysql_read_only(dbapi_conn, _record):  # pragma: no cover - needs a real server
            # MySQL had neither of the other engines' backstops: no read-only
            # session and no statement timeout, so it leaned entirely on the
            # guard - and SELECT SLEEP(100000) is a guard-legal denial of service.
            cur = dbapi_conn.cursor()
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            with contextlib.suppress(Exception):      # MySQL 5.7.8+, milliseconds
                cur.execute(f"SET SESSION max_execution_time = {int(timeout_s * 1000)}")
            with contextlib.suppress(Exception):      # MariaDB's spelling, seconds
                cur.execute(f"SET SESSION max_statement_time = {int(timeout_s)}")
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
    strict: bool = False,
) -> pd.DataFrame:
    """The only path to the database. Guards, executes (with bounded retries on
    transient errors), audits.

    `strict` default-denies unrecognised functions; pass it for any SQL the
    operator did not write themselves (the MCP query tool does).
    """
    assert_read_only(sql, dialect=_SQLGLOT_DIALECT.get(engine.dialect.name), strict=strict)
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
