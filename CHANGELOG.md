# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

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
