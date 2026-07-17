# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.6.0] — 2026-07-17 · "Receivables, a narrative that can't lie, and a guard that keeps its word"

The headline is not the new features — it is that a five-way audit of this repository found the honesty discipline holding in the Python core and **not** travelling to the newer surfaces. Everything under *Fixed* below is a place where this project said more than it knew. For a project whose entire claim is measurement honesty, those are not ordinary bugs.

### Added
- **Receivables aging (cari yaşlandırma)** as an *optional* canonical entity: open balances bucketed `current / 1-30 / 31-60 / 61-90 / 91+`, the overdue share, and the customers who owe the most overdue. One bucket definition, imported by every surface. A profile that cannot reach an AR ledger simply omits it and everything downstream degrades gracefully — the report still runs.
- **Real-ERP AR mappings** for all three Turkish profiles, with their weak points flagged inline rather than smoothed over: Logo Tiger (`PAYTRANS`, TOTAL−PAID), Netsis (`TBLCAHAR`, with the open-item caveat), Mikro (`CARI_HESAP_HAREKETLERI`, where `open_amount` is gross because Mikro has no per-invoice open flag).
- **Mikro profile** — the third Turkish ERP. With Logo Tiger and Netsis, the bundled profiles now cover most of the Turkish SME ERP market.
- **Optional LLM narrative** (`run --narrate`): an executive summary built **only** from audited aggregates — never from `extraction.frames`, by construction — with the exact payload printed in the report as a "what the model saw" appendix. Any OpenAI-compatible endpoint, including a local keyless one (Ollama / LM Studio). No key configured → the flag no-ops and the report is unchanged.
- **Revenue concentration**: top-3 share + the Herfindahl-Hirschman Index, across all three surfaces. Concentration is risk, not a forecast, and the report says so.
- **Agent skill pack** (`skills/`) — `erp-safe-query`, `explain-kpi-move`, `write-erp-profile` — plus an `aging` MCP tool (the sixth), and `describe_model` now flags which entities are optional.
- **Power BI**: a receivables Aging page, a dark theme validated against the official `reportThemeSchema-2.155.json` (0 errors), DAX SVG micro-charts, and rendered previews of every page.
- **Packaging**: PyPI Trusted Publishing (OIDC, no stored token) and a lean non-root Docker image. CI builds the wheel on every leg and asserts all four profiles ship inside it.

### Fixed
- **Power BI plotted the current partial week.** The README's central promise is that it never does — *"a Monday-morning 'crash' that's really a two-day week is how dashboards lose trust"* — and the Overview's trend visuals had no calendar guard at any level, while the sparklines of the same metrics did. `dim_week` now carries `is_trend_week`, written from the engine's own window constant, and the trend visuals filter on it: **locked**, so a viewer cannot switch the guarantee off, and visible, so the filter card states the scope.
- **"Read-only by construction" did not hold at the guard level.** The guard checked a statement's shape and never asked what it *called*, so `pg_read_file`, `lo_export` (which writes a file), `dblink` (which dials out), `OPENROWSET`, `LOAD_FILE`, `load_extension`, `query_to_xml`, `SLEEP` and — worst — `set_config('default_transaction_read_only','off')` all passed. It was read-only *by configuration*: it held because the docs tell you to use a least-privilege login. Functions are now checked by AST **and** lexically (`OPENROWSET` is precisely what sqlglot cannot parse), the parser **fails closed** instead of waving through what it cannot read, and ad-hoc/agent SQL runs in strict mode that default-denies every function the guard cannot name. Pinned by name and per dialect in `tests/test_guard.py`.
- **A duplicated `item_code` crashed the entire run.** Orders and receivables were deduplicated; inventory was not. The three real profiles `GROUP BY` and hid it; `generic.yaml` does not — the "swap the profile, keep the report" path. Summed in the gate now, and said out loud.
- **Stock cover was overstated on short history**, hiding stockout risk. Weekly demand always divided by 8 even when the window held fewer weeks — suppressing the low-stock alert on exactly the first run, when a new deployment has the least history.
- **The 8-week baseline was two different numbers under one name.** `AVERAGEX` skips `BLANK`, so an empty week quietly left the DAX divisor while Python counted it as zero. Same window, same name, higher in Power BI.
- **On-time % can rise as fulfilment collapses** — a late, unshipped order is in neither the numerator nor the denominator, so it never costs the metric a point. Unfixable with what an order table carries, so the engine now counts what the percentage cannot see: *promised this week, not shipped*.
- **Attribution could claim 999% of a move.** Share was taken against the *net* delta, which goes to zero when segments move in opposite directions — so the absurd number appeared exactly when attribution mattered most. Measured against gross movement now, bounded 0–100% by construction, and the offsetting segment is named.
- **On-time findings ignored their own denominator** — two deliveries going 1-of-2 to 2-of-2 fired a confident "+50.0 pts". Below five scored deliveries a move is reported and explicitly not called.
- **Every SPC signal was labelled provisional, forever.** Limits promised to stabilise at n≥15 while the trend was hard-capped at 13 weeks, so the non-provisional branch was dead code — and `lookback_weeks` above 13 pulled rows and used none of them. Control limits now get their own, longer window; the default lookback is two quarters, so the threshold is reachable out of the box.
- **The `90+` aging bucket actually held 91+**; `61-90` is inclusive of day 90. The arithmetic was right and consistent everywhere — only the label claimed a boundary it did not have.
- **The dashboard claimed the data-viz skill's validated palette while using brightened approximations of it**, on a surface it was never validated against. Two of its colours were below the normal-vision ΔE floor — hard to tell apart even with full colour vision. Re-validated against the actual plane and corrected to the validated steps, in the validated order.
- **The LLM narrative's "aggregates only" understated what left the building.** No raw row ever reached the model, but an aggregate can still name a party — `top_overdue` *is* customer names, and driver findings name accounts. Names are pseudonymised by default now; `narrative.include_names: true` is an explicit opt-in that the payload appendix records either way. The narrative call also no longer follows redirects while holding an API key.
- MySQL had neither a read-only session nor a statement timeout, so `SELECT SLEEP(100000)` was a guard-legal denial of service. The credential check missed `?passwd=` (MySQLdb) and `?sslpassword=` (libpq). `SELECT 'please delete this note'` was refused, because the keyword scan read string literals as code.

### Changed
- **`report.lookback_weeks` now defaults to 26** (was 13). The chart still shows 13; the extra history is what the control limits are computed from, and they only settle around n≥15. The demo already generated 26 weeks — half of it was being discarded.
- The delivered-status set and both window constants are defined once and imported, rather than restated per surface.

## [0.5.0] — 2026-07-16 · "Signals, contracts, delivery, a plural profile library"

### Added
- **SPC/XmR anomaly layer**: an individuals control chart over the weekly trend separates a genuine shift from week-to-week noise. Every signal ships its arithmetic (UCL/LCL = mean ± 2.66 × avg moving range) plus a Western Electric run rule; provisional limits are labelled while the baseline is short. Deterministic, no black box — flows into the report and the MCP `weekly_report`.
- **Native delivery** (`run --send`): SMTP e-mail (the HTML report inline), Slack and Microsoft Teams (Power Automate Workflows) webhooks, and a healthchecks.io dead-man's-switch that fires on success *or* failure. Secrets via environment variables only; a failed channel is logged, never fatal. Optional `[notify]` extra (apprise) for 143 services.
- **Declarative profile contracts** (`contract:` block): `not_null`, `unique`, `accepted_values`, `relationships`, `min_rows`/`max_rows`, checked over the extracted data and reported in the quality gate; `severity: fail` trips `run --strict`.
- **Netsis profile** — Logo Netsis 3 on MSSQL (database-per-company), field-mapped from real production integrations (`TBLSIPAMAS`/`TBLSIPATRA` sales orders, `TBLCASABIT`, `TBLSTOKPH`), with the uncertain fields flagged inline. With Logo Tiger, the bundled profiles now cover most of the Turkish SME ERP market.
- **Live sample report** via GitHub Pages, linked from the README.

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
