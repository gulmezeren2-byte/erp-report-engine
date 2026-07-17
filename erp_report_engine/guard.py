"""The read-only guard, standalone.

This module is the crown jewel with its own address, and it depends on nothing
heavier than ``re`` and ``sqlglot`` on purpose: connect.py re-exports everything
here (so every existing ``from .connect import assert_read_only`` still works),
and the in-browser trust playground loads exactly this file — the same code CI
runs, not a re-implementation. "One definition" is the whole brand, so the guard
has exactly one.

Read-only is enforced in layers, and each docstring below is precise about which
layer carries which guarantee. "Read-only by construction" is a claim about the
guard, and a guard that checks a statement's SHAPE while ignoring the FUNCTIONS
it calls does not earn it:

1. A lexical guard, over the statement with string literals blanked out (a
   keyword inside a quoted value is data, not code): single statement, SELECT/
   WITH head, no comments, no write/DDL keyword, no write-escalating lock hint,
   no call to a side-effecting function.
2. A sqlglot AST guard. The statement must PARSE - if it cannot, it is refused,
   not waved through: a guard that cannot read a query cannot vouch for it. It
   must parse to a single read query with no INSERT/UPDATE/DELETE/DDL/EXEC/INTO
   node, and it must call no function on the denylist below - because plenty of
   pure-looking SELECTs write files, open sockets or edit the session.
3. Strict mode (`strict=True`, for agent- and human-supplied ad-hoc SQL)
   additionally refuses EVERY function sqlglot does not recognise. sqlglot's own
   function registry is the allowlist: it knows the portable analytic functions
   and nothing that reads a file or dials out, so default-deny costs nothing.

The database-session layer (PostgreSQL read-only transaction, the login itself
on MSSQL, ...) lives in connect.py with the engine it configures - it is not part
of the pure guard, and cannot be, since it is a property of the connection.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from .errors import ReadOnlyViolation

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
# sqlglot parses them as anonymous calls (see _func_name) - and OPENROWSET does
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
