# Security Policy

This project connects to production ERP databases, so security is a design pillar, not an afterthought.

## The model

Read-only is enforced in three independent layers, so no single mistake makes the engine capable of writing:

1. **Lexical guard.** Every statement passes `assert_read_only()` before reaching the database: single statement, `SELECT`/`WITH` head, no comments (`--`, `/*`, `#`), no write/DDL/`EXEC`/`INTO` keyword, no write-escalating lock hint (`TABLOCKX`, `UPDLOCK`, `XLOCK`). There is exactly one code path to the database (`safe_read`) and it is guarded and audited.
2. **Parse-tree guard.** The statement is parsed with `sqlglot`; it must resolve to a single read query whose AST contains no `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`DROP`/`ALTER`/`MERGE`/`EXEC`/`INTO` node. This catches writes hidden inside CTEs or subqueries that a keyword scan alone could miss. If a statement cannot be parsed in the target dialect, the lexical guard still governs.
3. **Read-only session — and this is on you too.** The engine puts the session in read-only mode where the driver allows it (PostgreSQL `default_transaction_read_only=on`, SQLite `PRAGMA query_only=ON`). A regex or parser cannot know whether a `SELECT some_function()` writes — so run the engine under a **read-only database login** (`db_datareader` on MSSQL, a `SELECT`-only grant on PostgreSQL). The in-code guards are layers, not a substitute for database-level permissions.
4. **Secrets never live in files.** The config loader refuses to run when the connection URL embeds a credential. Use `connection.url_env` and put the URL in an environment variable.
5. **Everything is visible.** Every executed statement, its parameters, row count and duration ship inside the report's SQL audit trail.
6. **Bounded blast radius.** A row cap (default 500k) and query timeouts (PostgreSQL now; MSSQL via the driver) stop runaway queries.

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
- You should get a response within a few days. Confirmed guard bypasses are fixed with a regression test added to `tests/test_engine.py`.

Please do not open public issues for suspected guard bypasses before a fix exists.

## Scope

In scope: the read-only guard, profile variable validation, config secret handling, anything that could make the engine write to or lock an ERP database.

Out of scope: vulnerabilities in the ERP systems themselves, in your database drivers, or reports generated from data you already control.
