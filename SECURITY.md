# Security Policy

This project connects to production ERP databases, so security is a design pillar, not an afterthought.

## The model

Read-only is enforced in four independent layers, so no single mistake makes the engine capable of writing:

1. **Lexical guard.** Every statement passes `assert_read_only()` before reaching the database: single statement, `SELECT`/`WITH` head, no comments (`--`, `/*`, `#`), no write/DDL/`EXEC`/`INTO` keyword, no write-escalating lock hint (`TABLOCKX`, `UPDLOCK`, `XLOCK`). Scanning happens with string literals blanked out, because a keyword inside a quoted value is data: `SELECT 'please delete this note'` is a read. There is exactly one code path to the database (`safe_read`) and it is guarded and audited.
2. **Parse-tree guard.** The statement is parsed with `sqlglot`; it must resolve to a single read query whose AST contains no `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`DROP`/`ALTER`/`MERGE`/`EXEC`/`INTO` node. This catches writes hidden inside CTEs or subqueries that a keyword scan alone could miss. **If a statement cannot be parsed in the target dialect it is refused**, not waved through — a guard that cannot read a query has nothing to say about it.
3. **Function guard.** A statement's shape does not tell you whether it writes. `pg_read_file` reads a server file, `lo_export` *writes* one, `dblink` opens an outbound connection, `query_to_xml` runs more SQL, `set_config` switches off layer 4, `OPENROWSET`/`LOAD_FILE` reach the filesystem, `load_extension` is arbitrary code, and `SLEEP`/`BENCHMARK` are a denial of service — every one of them is a perfectly well-formed `SELECT`. They are refused by name, on the AST **and** lexically (`OPENROWSET` is exactly what `sqlglot` cannot parse). Ad-hoc SQL from the MCP/agent path runs in **strict mode**, which additionally default-denies every function the guard cannot recognise.
4. **Read-only session — and this layer is on you.** The engine puts the session in read-only mode where the driver allows it (PostgreSQL `default_transaction_read_only=on`, SQLite `PRAGMA query_only=ON`, MySQL `SET SESSION TRANSACTION READ ONLY`), with a per-statement timeout everywhere. **MSSQL has no session-level read-only switch at all**, so there this layer *is* the login. A denylist of dangerous functions is never provably complete, and the next vendor built-in is not in ours yet — so run the engine under a **least-privilege, read-only database login** (`db_datareader` on MSSQL, a `SELECT`-only grant on PostgreSQL, ideally a physical read replica). The in-code guards are defence in depth, not a substitute for database-level permissions.
5. **Secrets never live in files.** The config loader refuses to run when the connection URL embeds a credential, in any spelling — `password`, `passwd`, `pwd`, `sslpassword`, or an ODBC `PWD=` inside `odbc_connect`. Use `connection.url_env` and put the URL in an environment variable.
6. **Everything is visible.** Every executed statement, its parameters, row count and duration ship inside the report's SQL audit trail.
7. **Bounded blast radius.** A row cap (default 500k) and per-statement query timeouts (PostgreSQL, MySQL, and MSSQL via the driver) stop runaway queries.

### Known limits, stated rather than implied

- **The function denylist is a denylist.** It covers the PostgreSQL, MSSQL, MySQL and SQLite surface we know about. Layer 4 is what holds when it misses one.
- **`query` reads whatever the login can read.** The guard constrains *how* a statement reads, not *what* it may reach; the semantic profile shapes the report, but ad-hoc SQL is bounded by the grant. This is another reason the read-only login should also be a *narrow* one.
- **The guard has been wrong before.** The function bypasses above were found by auditing this repository, not reported from outside. They are pinned by name and per dialect in `tests/test_guard.py`.

## The MCP server (agent access)

The optional MCP server (`erp-report-engine mcp`) exposes the ERP to an AI agent, so it is held to the model above **plus** the lessons of the 2025 MCP data-exfiltration incidents:

- Every tool runs through the same guarded, audited, read-only path (`runner.guarded_query` / the report facade). The agent gets no code path to write.
- The agent sees only **canonical entities** (`orders`, `order_lines`, `inventory`) via the semantic profile — never raw ERP table names, and never a way to run arbitrary DDL.
- Every result that carries ERP data is wrapped with an explicit note that the rows are **data, not instructions** — a defense against prompt-injection through record contents (the "lethal trifecta": untrusted input + a tool + an exfiltration channel).
- Run the server under the same **read-only database login** as the report. The guard is a layer; the login is the backstop.
- Do not expose the server beyond the local machine (stdio transport only, by design).

## Reporting a vulnerability

If you find a way to sneak a write, a second statement, or an unparameterized value past the guard — that is exactly what I want to hear about.

- Use **GitHub → Security → Report a vulnerability** (private advisory) on this repository.
- Please include a minimal SQL or profile snippet that reproduces the bypass.
- You should get a response within a few days. Confirmed guard bypasses are fixed with a regression test added to `tests/test_guard.py`, named for the bypass and parametrized over the dialect it applies to.

Please do not open public issues for suspected guard bypasses before a fix exists.

## Scope

In scope: the read-only guard, profile variable validation, config secret handling, anything that could make the engine write to or lock an ERP database.

Out of scope: vulnerabilities in the ERP systems themselves, in your database drivers, or reports generated from data you already control.
