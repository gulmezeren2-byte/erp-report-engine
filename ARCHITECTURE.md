# Architecture

erp-report-engine turns the SQL database behind an ERP into a weekly, self-verifying KPI briefing — as an HTML report, a Power BI project, and a guarded MCP server. This document is the map, and the list of invariants that must survive any change.

## The one-way data flow

```
config ─▶ profile ─▶ [ connect: 3-layer read-only guard + audit ] ─▶ extract
                                                                        │
                                            data-quality gate + COUNT(*) reconciliation
                                                                        │
                                    kpi (calendar-anchored)  ─▶  insights (deterministic)
                                                                        │
                        ┌───────────────────────────┬───────────────────┴───────────────┐
                     render (HTML)          export_powerbi (CSV star)              mcp_server
                                                                                (agent tools)
```

Everything funnels through **one guarded, audited path to the database** (`connect.safe_read`). The CLI, the Power BI export, and the MCP server are all thin consumers of the `runner` facade — none of them re-implements extraction or talks to the database directly.

## Layers and dependency direction

- **Pure core** — `kpi.py`, `insights.py`, `week_calendar.py`: pandas/stdlib only. No I/O, no SQLAlchemy, no rendering. Given the same frames they always produce the same numbers.
- **I/O edge** — `connect.py` (the *only* database path), `config.py`, `state.py`, `extract.py`, `export_powerbi.py`, `render.py`.
- **Orchestration** — `runner.py`: composes the above into `validate` / `build_report` / `guarded_query`, returning data, never printing or exiting.
- **Surfaces** — `cli.py`, `mcp_server.py`: presentation only.
- **Contracts** — `semantic.py` (canonical entities + profile resolver), `errors.py` (exit-code taxonomy).

The core must never import the edge. `kpi`/`insights`/`week_calendar` importing `sqlalchemy`, `connect`, or `render` is a regression.

## Invariants (do not weaken)

1. **`connect.safe_read` is the only way to the database.** Route new queries through it; do not open a second connection path.
2. **The read-only guard holds in three layers**: lexical (single statement, `SELECT`/`WITH` head, no comments, no write keyword, no lock hint) + `sqlglot` AST (no write/DDL node, even inside a CTE) + a read-only session. If you touch the guard, extend the hostile tests first.
3. **The report is honest.** The audit trail, source reconciliation, data-quality gate, and explicit metric definitions ship inside every report. Features that hide information do not merge.
4. **"This week" is the last completed ISO week by the calendar**, anchored on the database server's date — never inferred from which weeks contain data. The current partial week is never plotted.
5. **One definition, two surfaces.** The HTML report and the Power BI model compute the same KPI the same way (dedup once in the gate; DAX thresholds mirror `insights.py`).
6. **Secrets never touch config files or logs.** Credentials come from an environment variable; the loader refuses embedded ones; DSNs are redacted before logging.
7. **Untrusted-in, escaped/framed-out.** ERP strings are HTML-escaped in the report and framed as untrusted data in MCP results.

## Testing

`pytest tests/` covers the guard (hostile cases), profile contracts, the calendar core (unit + hypothesis property tests), render escaping, the honesty fixes, CLI exit codes, the MCP tools, and a full end-to-end run plus PBIP integrity on the bundled demo database. CI additionally runs `ruff` and fails on PBIR generator drift, on Python 3.10–3.13.
