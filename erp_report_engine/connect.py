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

# A single-quoted literal, standard-SQL rules: '' doubles, backslash is NOT an
# escape. Deliberately not dialect-aware. On MySQL, where \' does escape, this
# splits a literal early and scans text that was really inside it - a false
# positive, which is the safe direction for a guard to be wrong in.
_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'", re.DOTALL)

# Functions that make a SELECT stop being a read. Every one of these was verified
# to sail straight through the old shape-only guard. They are vendor-specific, so
# sqlglot parses them as anonymous calls (see _FUNC_NAMES) - and OPENROWSET does
# not parse at all, which is exactly why the lexical net below exists too.
_DANGEROUS_FUNCS = frozenset({
    # PostgreSQL - server-side file I/O and large objects (lo_export WRITES)
    "pg_read_file", "pg_read_binary_file", "pg_stat_file", "pg_ls_dir",
    "pg_ls_logdir", "pg_ls_waldir", "pg_ls_tmpdir", "pg_ls_archive_statusdir",
    "lo_import", "lo_export", "lo_get", "lo_put", "lo_from_bytea", "lo_unlink",
    # PostgreSQL - outbound connections (SSRF / exfiltration)
    "dblink", "dblink_exec", "dblink_connect", "dblink_connect_u",
    "dblink_send_query", "dblink_open", "dblink_fetch",
    # PostgreSQL - re-enters the executor with arbitrary SQL, or edits the session
    "query_to_xml", "query_to_xmlschema", "query_to_xml_and_xmlschema",
    "set_config", "pg_reload_conf", "pg_rotate_logfile", "pg_logical_emit_message",
    "pg_terminate_backend", "pg_cancel_backend",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    # MSSQL - ad-hoc remote/bulk sources, shell, registry, trace files
    "openrowset", "opendatasource", "openquery", "openxml",
    "xp_cmdshell", "xp_dirtree", "xp_fileexist", "xp_subdirs", "xp_regread",
    "xp_regwrite", "xp_regdeletekey", "xp_regdeletevalue", "xp_regenumvalues",
    "sp_executesql", "sp_oacreate", "sp_oamethod", "sp_configure",
    "fn_trace_gettable", "fn_get_audit_file", "fn_xe_file_target_read_file",
    # MySQL / MariaDB - file reads, UDF shells, and unbounded time sinks
    "load_file", "sys_exec", "sys_eval", "benchmark", "sleep",
    # SQLite - loading an extension is arbitrary code execution
    "load_extension", "readfile", "writefile", "edit", "fts3_tokenizer",
})

# Lexical net for the same names, requiring a '(' so a COLUMN called "sleep" is
# untouched. This is what catches OPENROWSET, which sqlglot cannot parse at all.
_DANGEROUS_LEXICAL = re.compile(
    r"\b(" + "|".join(sorted(_DANGEROUS_FUNCS)) + r")\s*\(", re.IGNORECASE
)

# sqlalchemy dialect name -> sqlglot dialect, for accurate parsing of the guard
_SQLGLOT_DIALECT = {"mssql": "tsql", "postgresql": "postgres", "sqlite": "sqlite", "mysql": "mysql"}

_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.Merge, exp.Command, exp.Into,
)


def _func_name(node: exp.Func) -> str:
    """The called name, for a node sqlglot recognised and for one it didn't.

    An unknown call (`pg_read_file(...)`) becomes exp.Anonymous with the name in
    `this`; a known one (`SUM(...)`) is a typed node whose name comes from the
    class. A schema qualifier is dropped by the parser, so `sys.fn_trace_gettable`
    arrives here as `fn_trace_gettable` - which is what the denylist stores.
    """
    if isinstance(node, exp.Anonymous):
        return str(node.this or "").lower()
    try:
        return str(node.sql_name() or "").lower()
    except Exception:
        return type(node).__name__.lower()


def _assert_ast_read_only(sql: str, dialect: str | None, strict: bool) -> None:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except Exception as e:
        # Fail CLOSED. This used to return, on the theory that the lexical guard
        # still held - but the lexical guard has never heard of OPENROWSET, and
        # OPENROWSET is precisely what fails to parse. A guard that cannot read a
        # query has nothing to say about it, and silence is not a pass.
        raise ReadOnlyViolation(
            f"the read-only guard could not parse this statement as "
            f"{dialect or 'generic'} SQL, so it cannot vouch for it: {str(e)[:120]}"
        ) from e
    if len(statements) != 1:
        raise ReadOnlyViolation("exactly one statement is allowed")
    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise ReadOnlyViolation(f"only read queries are allowed (parsed as {type(root).__name__})")
    bad = root.find(*_FORBIDDEN_NODES)
    if bad is not None:
        raise ReadOnlyViolation(f"query contains a non-read operation ({type(bad).__name__})")

    for fn in root.find_all(exp.Func):
        name = _func_name(fn)
        if name in _DANGEROUS_FUNCS:
            raise ReadOnlyViolation(
                f"function {name}() is not a read: it can touch the filesystem, open a "
                f"connection, run more SQL or change the session"
            )
        if strict and isinstance(fn, exp.Anonymous):
            raise ReadOnlyViolation(
                f"strict mode allows only functions the guard can recognise, and "
                f"{name}() is not one of them"
            )


def assert_read_only(sql: str, dialect: str | None = None, *, strict: bool = False) -> None:
    """Refuse anything that is not a single, side-effect-free read.

    `strict` is for SQL the operator did not write - the agent/MCP path - and
    additionally default-denies every function sqlglot cannot name.
    """
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        raise ReadOnlyViolation("multiple statements are not allowed")
    if _COMMENT.search(stripped):
        raise ReadOnlyViolation("SQL comments are not allowed (injection hygiene)")
    head = stripped.split(None, 1)[0].lower() if stripped else ""
    if head not in ("select", "with"):
        raise ReadOnlyViolation(f"only SELECT/WITH statements are allowed (got: {head!r})")

    # Keyword scanning happens with string literals blanked: SELECT 'please delete
    # this note' is a perfectly good read, and blocking it taught users that the
    # guard is superstitious rather than principled.
    scannable = _STRING_LITERAL.sub("''", stripped)
    if _FORBIDDEN.search(scannable):
        raise ReadOnlyViolation("statement contains a forbidden keyword")
    if _LOCK_HINTS.search(scannable):
        raise ReadOnlyViolation("write-escalating lock hint is not allowed")
    hit = _DANGEROUS_LEXICAL.search(scannable)
    if hit:
        raise ReadOnlyViolation(
            f"function {hit.group(1).lower()}() is not a read: it can touch the filesystem, "
            f"open a connection, run more SQL or change the session"
        )

    _assert_ast_read_only(stripped, dialect, strict)


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
