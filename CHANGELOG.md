# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

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
