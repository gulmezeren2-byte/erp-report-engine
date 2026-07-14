# Security Policy

This project connects to production ERP databases, so security is a design pillar, not an afterthought.

## The model

1. **Read-only by construction.** Every statement passes `assert_read_only()` before reaching the database: single statement, `SELECT`/`WITH` head, no comments, no write/DDL/`EXEC`/`INTO` keywords. There is exactly one code path to the database (`safe_read`) and it is guarded and audited.
2. **Defense in depth is on you too.** Run the engine under a **read-only database login** (`db_datareader` role on MSSQL, a `SELECT`-only grant on PostgreSQL). The in-code guard is a layer, not a substitute for database-level permissions.
3. **Secrets never live in files.** The config loader refuses to run when `connection.url` embeds a password. Use `connection.url_env` and put the URL in an environment variable.
4. **Everything is visible.** Every executed statement, its parameters, row count and duration ship inside the report's SQL audit trail.
5. **Bounded blast radius.** Row caps and per-dialect statement timeouts stop runaway queries.

## Reporting a vulnerability

If you find a way to sneak a write, a second statement, or an unparameterized value past the guard — that is exactly what I want to hear about.

- Use **GitHub → Security → Report a vulnerability** (private advisory) on this repository.
- Please include a minimal SQL or profile snippet that reproduces the bypass.
- You should get a response within a few days. Confirmed guard bypasses are fixed with a regression test added to `tests/test_engine.py`.

Please do not open public issues for suspected guard bypasses before a fix exists.

## Scope

In scope: the read-only guard, profile variable validation, config secret handling, anything that could make the engine write to or lock an ERP database.

Out of scope: vulnerabilities in the ERP systems themselves, in your database drivers, or reports generated from data you already control.
