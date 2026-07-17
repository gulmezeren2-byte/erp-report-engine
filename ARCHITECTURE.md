# Architecture

erp-report-engine turns the SQL database behind an ERP into a weekly, self-verifying KPI briefing — as an HTML report, a Power BI project, and a guarded MCP server. This document is the map, and the list of invariants that must survive any change.

## The one-way data flow

```
config ─▶ profile ─▶ [ guard.py: 4-layer read-only guard · connect: audit ] ─▶ extract
                                                                        │
                                            data-quality gate + COUNT(*) reconciliation
                                                                        │
                                    kpi (calendar-anchored)  ─▶  insights (XmR + p-chart)
                                                                        │
                        ┌───────────────────────────┬───────────────────┴───────────────┐
                     render (HTML)          export_powerbi (CSV star)              mcp_server
                                                                                (agent tools)
```

Everything funnels through **one guarded, audited path to the database** (`connect.safe_read`, which calls the guard in `guard.py`). The CLI, the Power BI export, and the MCP server are all thin consumers of the `runner` facade — none of them re-implements extraction or talks to the database directly.

## Layers and dependency direction

- **Pure core** — `kpi.py`, `insights.py`, `spc.py`, `week_calendar.py`: pandas/stdlib only. No I/O, no SQLAlchemy, no rendering. Given the same frames they always produce the same numbers.
- **The guard** — `guard.py`: the read-only guard, depending on nothing heavier than `re` and `sqlglot`, so it runs standalone (that is what lets the browser trust playground load the genuine code). `connect.py` re-exports it.
- **I/O edge** — `connect.py` (the *only* database path — the engine + audit + read-only session), `config.py`, `state.py`, `extract.py`, `export_powerbi.py`, `render.py`.
- **Orchestration** — `runner.py`: composes the above into `validate` / `build_report` / `guarded_query`, returning data, never printing or exiting.
- **Surfaces** — `cli.py`, `mcp_server.py`: presentation only.
- **Contracts** — `semantic.py` (`CANONICAL_SCHEMA` — canonical entities with per-column types + meaning — and the profile resolver), `attack_corpus.py` (the guard's shared attack corpus), `errors.py` (exit-code taxonomy).

The core must never import the edge. `kpi`/`insights`/`week_calendar` importing `sqlalchemy`, `connect`, or `render` is a regression.

## Invariants (do not weaken)

1. **`connect.safe_read` is the only way to the database.** Route new queries through it; do not open a second connection path.
2. **The read-only guard holds in four layers, and checks what a statement *calls*, not just its shape**: lexical (single statement, `SELECT`/`WITH` head, no comments, no write keyword, no lock hint — scanned with string literals blanked) + `sqlglot` AST that **must parse or the query is refused** (no write/DDL node, even inside a CTE) + a side-effecting-function denylist (by AST *and* lexically) + a read-only session. Ad-hoc/agent SQL adds strict mode (default-deny every function the parser can't name). The guard lives in `guard.py`; if you touch it, extend the hostile cases in `attack_corpus.py`/`tests/test_guard.py` first, and the published benchmark/playground regenerate from it.
3. **The report is honest.** The audit trail, source reconciliation, data-quality gate, and explicit metric definitions ship inside every report. Features that hide information do not merge.
4. **"This week" is the last completed ISO week by the calendar**, anchored on the database server's date — never inferred from which weeks contain data. The current partial week is never plotted.
5. **One definition, every surface.** The HTML report, the dashboard, the Power BI model, and the docs pages compute the same KPI the same way — a rule (a bucket edge, a window length, the "delivered" set, the SPC limits, the attack corpus) lives in one place and is imported, never restated. The control limits are exported to Power BI as data, not reimplemented in DAX; on-time uses a p-chart (a proportion), revenue an XmR chart, and both quote the same receipt string.
6. **Secrets never touch config files or logs.** Credentials come from an environment variable; the loader refuses embedded ones; DSNs are redacted before logging.
7. **Untrusted-in, escaped/framed-out.** ERP strings are HTML-escaped in the report and framed as untrusted data in MCP results.

## Testing

`pytest tests/` covers the guard (the shared attack corpus, hostile cases, per dialect), profile contracts, the calendar core (unit + hypothesis property tests), render escaping, the honesty fixes, CLI exit codes, the MCP tools (including that the semantic layer's example queries actually run and that `query` can't escape the canonical entities), the SPC methods, and a full end-to-end run plus PBIP integrity on the bundled demo database. CI additionally runs `ruff`, a coverage floor, and fails on drift of the generated PBIR pages and the generated docs pages (`trust.html` / `playground.html`), on Windows and Linux across Python 3.10–3.13.
