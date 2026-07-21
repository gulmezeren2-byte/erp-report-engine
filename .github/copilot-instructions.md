# Copilot instructions — erp-report-engine

A read-only, self-verifying data layer over the SQL database behind an ERP: a weekly HTML KPI report, a Power BI project, and a guarded MCP server for AI agents. Python 3.10–3.14, `hatchling` build. Runtime deps: `pandas`, `sqlalchemy`, `sqlglot`, `jinja2`, `pyyaml` (+ optional `mcp` extra). Dev: `pytest`, `ruff`, `hypothesis`.

## Build, test, lint

```bash
pip install -e ".[dev,mcp]"                 # install with dev + MCP extras
python -m pytest tests/ -q                  # full suite (guard, calendar, MCP, end-to-end on the demo DB)
python -m ruff check erp_report_engine demo tests
erp-report-engine init-demo                 # build the bundled demo DB + config
erp-report-engine trust-benchmark           # run the read-only guard against its attack corpus (no DB)
```

CLI verbs: `init-demo`, `validate`, `run`, `export-powerbi`, `mcp`, `trust-benchmark`, `schema`.

## Architecture (one-way data flow)

`config → profile → guard.py (4-layer read-only) + connect (audit) → extract → data-quality gate + COUNT(*) reconciliation → kpi (calendar-anchored) → insights (XmR + p-chart) → render / export_powerbi / mcp_server`

- **Pure core** (`kpi.py`, `insights.py`, `spc.py`, `week_calendar.py`): pandas/stdlib only, no I/O. **Never import the I/O edge** (`connect`, `sqlalchemy`, `render`) from here.
- **The guard** (`guard.py`): the read-only guard, `re` + `sqlglot` only, so it runs standalone (the browser playground loads it verbatim). `connect.py` re-exports it.
- **I/O edge**: `connect.py` is the *only* path to the database. **Route every query through `connect.safe_read`** — do not open a second connection path.
- **Surfaces** (`cli.py`, `mcp_server.py`) are thin consumers of the `runner.py` facade (`validate` / `build_report` / `guarded_query`).
- **Contracts**: `semantic.py` (`CANONICAL_SCHEMA` — canonical entities + per-column meaning), `attack_corpus.py` (the shared guard benchmark), `errors.py` (exit-code taxonomy).

## Invariants — do not weaken

1. **`connect.safe_read` is the only way to the database.**
2. **The read-only guard holds in four layers** (lexical + fail-closed `sqlglot` AST + side-effecting-function denylist + read-only session) and checks what a statement *calls*, not just its shape. If you touch the guard, add the hostile case to `attack_corpus.py` / `tests/test_guard.py` **first**.
3. **The report is honest**: the audit trail, source reconciliation, data-quality gate, and metric definitions ship inside every report. Do not add features that hide information.
4. **"This week" is the last completed ISO week**, anchored on the DB server's date; the current partial week is never plotted.
5. **One definition, every surface**: a KPI, bucket edge, SPC limit, or the attack corpus lives in one place and is imported — never restated in the report, dashboard, Power BI (DAX), or docs.
6. **Secrets come from an environment variable only** — the config loader refuses embedded credentials; DSNs are redacted in logs.

## Conventions

- **Generated files are CI-drift-gated — never hand-edit them.** `docs/trust.html`, `docs/playground.html`, `docs/model.json`, and the PBIR pages under `powerbi/ERP Command Center.Report/` are produced by scripts (`docs/generate_*.py`, `powerbi/tools/generate_report_pages.py`). Change the generator, then regenerate; CI fails on drift.
- **Public repo hygiene**: synthetic data only — no real ERP data, company names, or connection strings. Keep `README.md` and `README.tr.md` in sync.
- Bundled ERP profiles are YAML under `erp_report_engine/profiles/` (`generic`, `logo_tiger`, `netsis`, `mikro`); the wheel job asserts all four ship.
- The read-only guard is also published standalone as [`readonly-sql-guard`](https://github.com/gulmezeren2-byte/readonly-sql-guard).

See [ARCHITECTURE.md](../ARCHITECTURE.md), [AGENTS.md](../AGENTS.md), and [SECURITY.md](../SECURITY.md) for the full picture.
