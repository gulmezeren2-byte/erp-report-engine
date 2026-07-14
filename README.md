# erp-report-engine

> The numbers for Monday's meeting are already sitting in your ERP's database. So who's still writing the report?

**Autonomous weekly reports straight from the SQL database behind your ERP — read-only by construction, every query audited.**

[![CI](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/gulmezeren2-byte/erp-report-engine/blob/main/requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇹🇷 Türkçesi: [README.tr.md](README.tr.md)

One scheduled `run` executes **6 audited SELECT statements** and delivers a self-contained HTML report: four KPIs against an 8-week baseline, findings with named drivers, a data-quality gate, and row counts reconciled against the source. No BI license, no agent installed on the ERP server, and **no writes — ever, enforced in code, not promised in docs**.

![Weekly report produced by the engine from the bundled demo database](assets/erp_report_preview.png)

*This exact report was produced by one command against the bundled demo database — including the three data-quality problems deliberately seeded into it, all caught by the gate.*

## 60-second demo (no ERP required)

```bash
git clone https://github.com/gulmezeren2-byte/erp-report-engine.git
cd erp-report-engine
pip install -r requirements.txt

python -m erp_report_engine init-demo            # builds demo.db + config.demo.yaml
python -m erp_report_engine run -c config.demo.yaml
```

Open `reports/erp_report_<week>.html`. You'll see the engine catch a revenue spike and attribute it to one region, flag a two-point on-time decline, list items below two weeks of stock cover — and confess every duplicate and negative row it found on the way. A pre-generated copy ships in [`docs/sample-report.html`](docs/sample-report.html).

## What one run produces

| Section | What it answers |
|---|---|
| KPI cards | Revenue, orders, on-time %, low-stock count — each vs last week **and** vs an 8-week baseline |
| Findings | *"Revenue +25.4% — main driver: region 'Ege' (111% of the move)"* — driver named, action suggested |
| Trends | 13 full weeks of revenue and on-time %, inline SVG (no external assets) |
| Stock attention list | Items below the cover threshold, worst first |
| Data-quality gate | Duplicate IDs, unparseable dates, negative totals, ship-before-order rows |
| Source reconciliation | Rows fetched vs an independent `COUNT(*)` of the same query — ✓ or MISMATCH |
| SQL audit trail | Every statement executed, with parameters, row counts and timings |
| Run-state memory | *"Revenue has declined 3 consecutive weeks"* — context beyond the lookback window |

## How it works

```mermaid
flowchart LR
    DB[("ERP database<br/>MSSQL · PostgreSQL · SQLite")]
    PROF["Semantic profile<br/>(YAML contract)"]
    GUARD["safe_read<br/>read-only guard + audit"]
    GATE["Data-quality gate<br/>+ source reconciliation"]
    KPI["KPI engine<br/>ISO weeks, 8-wk baseline"]
    INS["Insight rules<br/>driver attribution"]
    HTML["Self-contained<br/>HTML report"]
    STATE[("state.db<br/>run memory")]

    PROF --> GUARD
    DB --> GUARD --> GATE --> KPI --> INS --> HTML
    STATE --- HTML
    GATE --> PBI["Power BI Command Center<br/>(TMDL + PBIR, code-authored)"]
```

The layer that makes this portable is the **semantic profile**: a versioned YAML contract that maps one ERP's cryptic schema to three canonical entities — `orders`, `order_lines`, `inventory`. The engine only ever sees canonical columns. Swap the profile, keep the report.

## The security model

Pointing software at a production ERP database is a trust decision. This engine treats it that way — the guarantees are enforced in code and covered by tests:

| Guarantee | Enforced by |
|---|---|
| Single-statement `SELECT`/`WITH` only | `assert_read_only()` — statement-head check, semicolon rejection |
| No write/DDL keywords, no `SELECT INTO`, no `EXEC` | Forbidden-keyword scan (`insert, update, delete, drop, alter, create, truncate, merge, grant, revoke, exec, execute, call, into`) |
| No SQL comments (`--`, `/*`) | Rejected outright — classic injection carrier |
| Profile variables are identifier-safe | `^[A-Za-z0-9_]{1,16}$` — `"001; DROP TABLE x"` raises before any connection |
| Secrets never in config files | Loader **refuses to run** if `connection.url` embeds a password; use `url_env` |
| Every executed statement is visible | `Auditor` — the full trail ships inside each report |
| Runaway queries can't hurt | Row cap (default 500k) + per-dialect statement timeouts |

The test suite throws eight injection attempts at the guard — multi-statement, comment smuggling, `SELECT INTO`, `EXEC`, write verbs — and expects every one to raise. Defense in depth still applies: run it under a **read-only database login** (`db_datareader` on MSSQL) so the guarantee holds even if the code is wrong. See [SECURITY.md](SECURITY.md).

## Connect your own ERP

1. Put the connection URL in an environment variable (never in the file):

```bash
# Windows (System Properties → Environment Variables, or:)
setx ERP_DB_URL "mssql+pyodbc://readonly_user:***@SERVER/LOGODB?driver=ODBC+Driver+17+for+SQL+Server"
```

2. Copy `config.example.yaml` → `config.yaml`:

```yaml
connection:
  url_env: ERP_DB_URL          # the engine reads the URL from this env var
profile: profiles/logo_tiger.yaml
profile_vars:
  firm_no: "001"               # identifier-safe values only, validated
  period_no: "01"
report:
  company_alias: "Company"     # display name — use an alias if you prefer
  lookback_weeks: 13
  low_cover_weeks: 2.0
limits:
  row_cap: 500000
  query_timeout_s: 60
```

3. Dry-run it — `validate` connects, checks the profile contract and reconciles counts, **touches nothing else**:

```bash
python -m erp_report_engine validate -c config.yaml
python -m erp_report_engine run -c config.yaml
```

### Included profiles

- **`profiles/generic.yaml`** — the canonical schema; also the template for writing your own.
- **`profiles/logo_tiger.yaml`** — Logo Tiger / GO on MSSQL: `LG_{firm}_{period}_ORFICHE` order headers joined to `CLCARD` customers, `ORFLINE` lines, `STINVTOT` stock totals, `TRCODE = 2` sales filter. Logo schemas vary by release — the profile carries field notes on exactly what to verify against **your** version before trusting it.

Writing a profile for another ERP (Netsis, SAP B1, Odoo, a custom system) means writing **three SELECT statements** that output the canonical columns. That's the whole contract — and `validate` tells you immediately whether you got it right.

## Make it autonomous

The engine is a single idempotent command, so any scheduler works:

```powershell
# Windows Task Scheduler — every Monday 07:00
schtasks /create /tn "erp-weekly-report" /sc weekly /d MON /st 07:00 ^
  /tr "cmd /c cd /d C:\erp-report-engine && python -m erp_report_engine run -c config.yaml"
```

```bash
# cron — every Monday 07:00
0 7 * * 1  cd /opt/erp-report-engine && python -m erp_report_engine run -c config.yaml
```

Each run appends to `state.db`, which is how the report can say *"third consecutive weekly decline"* — memory across runs, without re-querying history from the ERP.

## The Power BI Command Center

The engine also feeds an interactive Power BI layer — and there is no `.pbix` binary in this repo. The entire artifact is a **PBIP project authored as code**: the semantic model in TMDL (star schema, 20+ documented DAX measures, a *Time Shift* calculation group on a gapless week ordinal, a field parameter), the report in PBIR (4 pages / 24 visuals, generated from compact specs by a script), and a custom theme.

```bash
python -m erp_report_engine export-powerbi -c config.demo.yaml
# then open powerbi/ERP Command Center.pbip in Power BI Desktop
```

The signature is the **Trust page**: source reconciliation, the data-quality gate and the full SQL audit trail rendered as visuals — the dashboard shows its receipts. Alert thresholds are the same ones as `insights.py`, re-derived in DAX: one definition, two surfaces. Field bindings are validated against the TMDL model by `pbir-cli` before the project ever meets Desktop. Full guide: [powerbi/README.md](powerbi/README.md).

## What this does NOT do

Honesty over marketing — you should know the edges before pointing it at production:

- **On-time here is OTIF-lite.** It scores order-level `shipped ≤ promised`. True OTIF needs line-level receipt data most ERP order tables don't carry — so the report says "on-time shipping", not "OTIF", and the footer says why.
- **Findings are pointers, not verdicts.** "Driver: region Ege, 111% of the move" tells you where to look first. It does not tell you *why* — that's the analyst's job (yours).
- **The Logo Tiger profile is a field mapping, not a certified integration.** Logo schemas differ by version and localization; the profile's field notes list what to verify.
- **The current partial week is never plotted.** Trends end at the last completed ISO week, because a Monday-morning "crash" that's really a two-day week is how dashboards lose trust.
- **It's a weekly briefing, not a BI platform.** No drill-down, no real-time, no user management. It does one job: the Monday report writes itself, with receipts.

## Design decisions

**Why rule-based findings instead of an LLM?** Determinism. The same database state always produces the same report, it runs air-gapped next to the ERP, and a number in the report can always be traced to a SQL statement in the audit trail. Nothing is generated that can't be re-derived.

**Why a self-contained HTML file?** Zero infrastructure. Inline SVG charts, inline CSS, no CDN, no tracking — it renders in Outlook's browser preview, on a phone, from a file share, ten years from now.

**Why reconcile row counts?** Because "the DataFrame has 494 rows" and "the source query returns 494 rows" are different claims. An unattended system must audit its own inputs — every entity is re-counted with an independent `COUNT(*)` and any mismatch is flagged in red before anyone trusts a KPI.

## Tests

```bash
pip install pytest && python -m pytest tests/ -v
```

15 tests: 8 injection attempts against the guard, profile contract validation, variable-injection rejection, a full end-to-end run against the demo database asserting that findings fire, the seeded dirt is caught, and the report carries its audit trail — plus the Power BI layer: exporter contract (unique keys, gapless week ordinals) and PBIP project integrity (naming rules, visual overlap detection, theme resolution, every visual field exists in the model).

## Roadmap

- `profiles/netsis.yaml` — second Turkish ERP mapping (`TBLSIPAMAS`-family)
- Optional e-mail dispatch (SMTP via env vars only, following [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline))
- Anomaly layer: control-limit breaches on top of WoW rules
- MCP server wrapper: ask the ERP questions through the same read-only guard

## Part of the measurement-honesty series

Tools that tell you the truth about your operation, by [Eren Gülmez](https://github.com/gulmezeren2-byte):

- [otif-analytics](https://github.com/gulmezeren2-byte/otif-analytics) — the 5-step metric ladder from "98% reported" to "59% OTIF"
- [forecast-accuracy-lab](https://github.com/gulmezeren2-byte/forecast-accuracy-lab) — WMAPE vs MAPE, and why zero-dropping flatters your forecast
- [opsaudit](https://github.com/gulmezeren2-byte/opsaudit) — ops metrics CLI with a non-removable honesty block
- [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline) — this engine's CSV-fed little sibling
- [forecast-autoresearch](https://github.com/gulmezeren2-byte/forecast-autoresearch) — an agent improving a forecast against a sealed holdout

## License

[MIT](LICENSE) © Eren Gülmez
