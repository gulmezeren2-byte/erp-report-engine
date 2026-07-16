# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [0.4.0] — 2026-07-16 · "Installable, correct, and agent-ready"

### Added
- **Guarded ERP MCP server** (`erp-report-engine mcp`, optional `[mcp]` extra): an agent talks to canonical entities through the same three-layer read-only guard and audit trail as the report. Five tools (`describe_model`, `weekly_report`, `reconcile`, `check_query`, `query`); every data result is framed as untrusted input. The first SQL-level-guarded ERP MCP server, and the first for Logo Tiger.
- **Proper packaging**: `pyproject.toml` (hatchling), the `erp-report-engine` console script, `pipx`/`uv` installability, and profiles shipped as package data (referenced by name). Extras: `[mssql]`, `[postgres]`, `[mcp]`, `[dev]`.
- **Exit-code taxonomy** (`errors.py`): 2 config · 3 database · 4 contract · 5 data-quality, so a scheduler can branch on *why* a run failed. `--strict` fails on a reconciliation mismatch. Structured logging (stderr + `--log-file` JSON-lines, a run id); result JSON stays on stdout.
- **Runner facade** (`runner.py`): one orchestration path shared by the CLI and the MCP server; `guarded_query` is the safe seam for ad-hoc reads.
- Property-based calendar tests (hypothesis) and a CI gate that fails on PBIR generator drift; CI now installs the package and runs ruff on 3.10–3.13.

### Fixed (correctness & security)
- **Calendar anchor**: "this week" is now the last completed ISO week by the calendar (from the database server's date), not the last week that happens to hold orders — a Monday-07:00 run no longer reports a stale week. Continuous, gap-filled week axis (empty weeks read as zero; W53 handled). The Power BI `DimWeek` shares the same axis.
- **Stored XSS**: the report renders through Jinja2 autoescape; ERP-sourced strings (and SQL in the audit trail) can no longer execute or break the layout.
- **Read-only guard hardened**: a `sqlglot` AST layer over the lexical checks (rejects writes hidden in CTEs, lock hints, `#` comments), plus read-only sessions (PostgreSQL `default_transaction_read_only`, SQLite `PRAGMA query_only`).
- **Duplicate handling unified** so the HTML report and Power BI agree on revenue; on-time survivorship, vanished-segment drivers, stocked-out items, and the decline-streak off-by-one all fixed and disclosed.
- **Data-leak & credential footguns**: `export-powerbi` defaults to a gitignored folder; embedded credentials are rejected in every URL shape (`?password=`, `?pwd=`, pyodbc `odbc_connect`).
- MSSQL per-execute query timeout (was a login timeout); atomic report writes; bounded retries on transient DB errors.

## [0.2.0] — 2026-07-14 · "The command center"

### Added
- **`export-powerbi` CLI command**: star-schema CSV export (2 facts, 2 dimensions, 4 meta tables) through the same guarded read-only extraction path; duplicate order keys collapsed with the collapse itself reported in `meta_data_quality.csv`; gapless `week_ordinal` for year-boundary-safe DAX.
- **Power BI Command Center** (`powerbi/`): a full PBIP project authored as code — no `.pbix` binary.
  - Semantic model in **TMDL**: star schema, 20+ documented DAX measures (thresholds mirror `insights.py`), `Time Shift` **calculation group** (Previous Week / WoW / WoW % / 8-Week Baseline / vs Baseline %), `Selected KPI` **field parameter**, `DataFolder` parameter so no absolute path is baked in, `discourageImplicitMeasures`.
  - Report in **PBIR**: 4 pages / 24 visuals — Overview (last-full-week anchored cards + live `Weekly Verdict`), Drivers (decomposition tree), Stock, and the signature **Trust page** rendering reconciliation, data-quality findings and the full SQL audit trail as visuals.
  - Custom *Measurement Honesty* theme; report pages generated from compact specs by `powerbi/tools/generate_report_pages.py`.
- **Tests (2 new, 15 total)**: exporter contract (unique fact keys, gapless ordinals, no BOM) and PBIP integrity (page/visual naming rules, visual overlap detection, theme resolution on disk, every visual entity exists in TMDL).
- Committed demo export in `powerbi/data/` so the report renders on first refresh.

## [0.1.0] — 2026-07-14 · "Read-only by construction"

First public release.

### Added
- **Read-only guard** (`connect.assert_read_only`): single-statement `SELECT`/`WITH` only; rejects comments, semicolons, and 14 write/DDL/`EXEC`/`INTO` keywords. One guarded code path to the database (`safe_read`), with row caps and per-dialect timeouts.
- **SQL audit trail**: every executed statement (SQL, parameters, row count, duration) recorded and shipped inside the report.
- **Semantic profile layer**: versioned YAML contracts mapping ERP schemas to canonical entities (`orders`, `order_lines`, `inventory`); identifier-safe `{placeholder}` substitution; profiles validated read-only at load time.
- **Profiles**: `generic.yaml` (canonical/demo schema) and `logo_tiger.yaml` (Logo Tiger / GO on MSSQL, with field notes on version differences).
- **Extraction with self-audit**: data-quality gate (duplicate IDs, unparseable dates, negative totals, ship-before-order, orphan lines) and independent `COUNT(*)` source reconciliation per entity.
- **Weekly KPI engine**: revenue, order count, on-time shipping %, stock-cover — each vs previous week and an 8-week baseline; trends plot completed ISO weeks only (the current partial week is never drawn).
- **Rule-based insight engine** with driver attribution across region/customer dimensions.
- **Run-state memory** (`state.db`): consecutive-decline streak detection across runs.
- **Self-contained HTML report**: inline SVG trends, data-quality section, reconciliation table, collapsible SQL audit trail, explicit metric definitions in the footer.
- **CLI**: `init-demo` (demo database + config), `validate` (dry-run: connect, check contract, reconcile counts), `run` (produce the report).
- **Config hardening**: loader refuses connection URLs with embedded passwords; secrets via environment variables only.
- **Demo database builder**: 26 weeks of seeded synthetic orders with an injected regional spike, a late-shipping cluster, and deliberate dirt for the quality gate.
- **Tests (13)**: 8 injection attempts against the guard, profile contract checks, variable-injection rejection, end-to-end run on the demo database.
