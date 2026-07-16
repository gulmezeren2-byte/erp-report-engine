# AGENTS.md — working on this repo with an AI coding agent

Context for coding agents (and fast-moving humans) contributing here.

## What this is

A read-only autonomous reporting engine that runs SQL against the database behind an ERP and renders a weekly HTML report. The two things that must survive any change: **the read-only guarantee** and **the report's honesty features** (audit trail, reconciliation, data-quality gate, explicit definitions).

## Hard invariants — never weaken these

1. `connect.safe_read` is the **only** path to the database. Do not add a second one; route new queries through it.
2. `assert_read_only` must keep rejecting: multiple statements, comments (`--`, `/*`), non-`SELECT`/`WITH` heads, and the forbidden keyword list (including `INTO`, `EXEC`, `CALL`). If you touch it, extend `tests/test_engine.py::test_guard_blocks_writes_and_tricks` first.
3. Profile `{placeholders}` accept identifier-safe values only (`^[A-Za-z0-9_]{1,16}$`). All runtime values (dates, thresholds) travel as bound parameters (`:since`), never string-formatted into SQL.
4. Secrets never land in files or code. The config loader's embedded-password refusal stays.
5. The report keeps its audit trail, source reconciliation, data-quality section and definitions footer. Features that hide information don't merge.
6. Trends plot completed ISO weeks only — never the current partial week.

## Layout

```
erp_report_engine/
  config.py          # YAML config; refuses embedded passwords
  connect.py         # THE security layer: guard, engine, safe_read, Auditor
  semantic.py        # profile contracts (canonical entities, REQUIRED_COLUMNS)
  extract.py         # extraction + quality gate + COUNT(*) reconciliation
  kpi.py             # ISO-week KPIs vs 8-week baseline
  insights.py        # deterministic findings + driver attribution
  state.py           # SQLite run memory (decline streaks)
  render.py          # self-contained HTML (inline SVG via matplotlib)
  export_powerbi.py  # star-schema CSV export for the PBIP layer
  cli.py             # validate / run / export-powerbi / init-demo
  demo_builder.py    # bundled synthetic demo DB builder (seeded, deliberately dirty)
  profiles/          # bundled package-data profiles: generic (canonical), logo_tiger (MSSQL)
powerbi/             # PBIP project authored as code (TMDL model + PBIR report)
  tools/generate_report_pages.py  # PBIR pages are GENERATED - edit specs, rerun, never hand-edit visual.json
demo/                # thin shim -> erp_report_engine.demo_builder (kept for docs)
tests/               # guard, contracts, e2e on demo DB, PBIP integrity
pyproject.toml       # packaging (hatchling), console script, extras, ruff config
```

Power BI layer rules: keep DAX alert thresholds identical to `insights.py` (5% revenue, 1.5 pts on-time) — one definition, two surfaces. After changing the generator or TMDL, run `pytest tests/test_powerbi.py` and, if available, `pbir validate "powerbi/ERP Command Center.Report" --allow-download-schemas --fields --qa`.

## Commands

```bash
pip install -e ".[dev]"                         # editable install with dev tools
python -m pytest tests/ -q                       # must stay green (17 tests)
python -m ruff check erp_report_engine demo tests
erp-report-engine init-demo                      # rebuild demo.db + config.demo.yaml
erp-report-engine run -c config.demo.yaml
```

The e2e test rebuilds the demo DB itself; running pytest from a clean clone works with no setup.

## Adding an ERP profile (most valuable contribution)

Write three `SELECT`s in a new `erp_report_engine/profiles/<erp>.yaml` producing the canonical columns listed in `semantic.REQUIRED_COLUMNS`; it ships bundled and becomes referenceable as `profile: <erp>`. Rules: `{vars}` for schema identifiers only, `:since` for the date filter, no comments, single statement each. Load-time validation and `validate -c` will tell you immediately if the contract is broken. Include field notes about version differences — profiles here are honest field mappings, not certified integrations.

## Style

- Python ≥ 3.10, type hints on public signatures, docstrings state *why* (the code shows *what*).
- Findings text follows the pattern: metric move → named driver → suggested next look. No verdicts the data can't support.
- Synthetic demo data only: neutral fictional names, fixed seeds, no real company/person data — ever.
