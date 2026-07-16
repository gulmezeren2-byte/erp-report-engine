# erp-report-engine

> The numbers for Monday's meeting are already sitting in your ERP's database. So who's still writing the report?

**Autonomous weekly reports straight from the SQL database behind your ERP — read-only by construction, every query audited.**

[![CI](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/gulmezeren2-byte/erp-report-engine/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/gulmezeren2-byte/erp-report-engine/blob/main/requirements.txt)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

🇹🇷 Türkçesi: [README.tr.md](README.tr.md)

One scheduled `run` executes **6 audited SELECT statements** and delivers a self-contained HTML report: four KPIs against an 8-week baseline, findings with named drivers, a data-quality gate, and row counts reconciled against the source. No BI license, no agent installed on the ERP server, and **no writes — enforced in three layers (a lexical + parse-tree guard and a read-only session), not promised in prose**.

![Weekly report produced by the engine from the bundled demo database](assets/erp_report_preview.png)

*This exact report was produced by one command against the bundled demo database — including the three data-quality problems deliberately seeded into it, all caught by the gate.*

## 60-second demo (no ERP required)

```bash
# install (pipx or uv keep it isolated; plain pip works too)
pipx install erp-report-engine          # or: uv tool install erp-report-engine
# from source instead:  pip install .

erp-report-engine init-demo             # builds demo.db + config.demo.yaml here
erp-report-engine run -c config.demo.yaml
```

Every command is also available as `python -m erp_report_engine …`. Add a database driver with the extras: `pipx install "erp-report-engine[mssql]"` (Logo Tiger / SQL Server) or `[postgres]`.

Open `reports/erp_report_<week>.html`. You'll see the engine catch a revenue spike and attribute it to one region, flag a two-point on-time decline, list items below two weeks of stock cover — and confess every duplicate and negative row it found on the way.

**▶ See a live sample report: [gulmezeren2-byte.github.io/erp-report-engine](https://gulmezeren2-byte.github.io/erp-report-engine/)** (also committed at [`docs/sample-report.html`](docs/sample-report.html)).

Or run `run --dashboard` for the premium **Command Center** — a dark, modern, self-contained dashboard with animated KPIs and glowing SPC control-band charts (**[live](https://gulmezeren2-byte.github.io/erp-report-engine/dashboard.html)**):

![The Command Center dashboard — dark glassmorphic bento grid with SPC control-band charts](assets/dashboard_preview.png)

## What one run produces

| Section | What it answers |
|---|---|
| KPI cards | Revenue, orders, on-time %, low-stock count — each vs last week **and** vs an 8-week baseline |
| Findings | *"Revenue +25.4% — main driver: region 'Ege' (111% of the move)"* — driver named, action suggested |
| Signals (SPC) | *"Revenue signal: 148,291 is ABOVE the control limits (UCL 143,078 = mean 93,168 ± 2.66 × avg moving range 18,763)"* — a genuine shift, separated from week-to-week noise, with the arithmetic shown |
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

The layer that makes this portable is the **semantic profile**: a versioned YAML contract that maps one ERP's cryptic schema to three canonical entities — `orders`, `order_lines`, `inventory` — plus an **optional `receivables`** entity (open AR, for aging) that a profile maps when the ledger is reachable and everything downstream skips gracefully when it isn't. The engine only ever sees canonical columns. Swap the profile, keep the report.

## The security model

Pointing software at a production ERP database is a trust decision. This engine treats it that way — the guarantees are enforced in code and covered by tests:

Read-only is enforced in **three layers**, so no single mistake makes the engine capable of writing:

| Layer | Enforced by |
|---|---|
| Lexical guard | Single statement, `SELECT`/`WITH` head, no comments (`--`, `/*`, `#`), no write/DDL keyword, no write-escalating lock hint (`TABLOCKX`, `UPDLOCK`, `XLOCK`) |
| Parse-tree guard | `sqlglot` parses the statement; it must be a single read query whose AST contains no `INSERT`/`UPDATE`/`DELETE`/`CREATE`/`DROP`/`ALTER`/`MERGE`/`EXEC`/`INTO` node (catches writes hidden inside CTEs) |
| Read-only session | PostgreSQL `default_transaction_read_only=on`, SQLite `PRAGMA query_only`, and a documented **read-only login** (`db_datareader` on MSSQL) as the backstop — so even a function that tries to write is refused by the database |

Plus: profile variables are identifier-safe (`^[A-Za-z0-9_]{1,16}$`, so `"001; DROP TABLE x"` raises before any connection), secrets never live in config files (the loader refuses embedded credentials — use `url_env`), every executed statement ships in the report's audit trail, and a row cap (default 500k) bounds any single query.

The test suite throws a battery of injection attempts at the guard — multi-statement, comment smuggling in three syntaxes, transaction-control splices (`ROLLBACK`/`COMMIT`), `SELECT INTO`, lock hints, and a `DELETE` hidden inside a CTE — and expects every one to raise. See [SECURITY.md](SECURITY.md).

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
profile: logo_tiger            # a bundled profile name, or a path to your own YAML
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

Profiles ship inside the package and are referenced by name (`generic`, `logo_tiger`) — no `profiles/` folder needs to exist next to your config.

- **`generic`** — the canonical schema; also the template for writing your own.
- **`logo_tiger`** — Logo Tiger / GO on MSSQL: `LG_{firm}_{period}_ORFICHE` order headers joined to `CLCARD` customers, `ORFLINE` lines, `STINVTOT` stock totals, `TRCODE = 2` sales filter, and **optional receivables aging** from `PAYTRANS` (installment `TOTAL − PAID`, `MODULENR = 4`). Logo schemas vary by release — the profile carries field notes on exactly what to verify against **your** version before trusting it.
- **`netsis`** — Logo Netsis 3 on MSSQL (database-per-company): `TBLSIPAMAS`/`TBLSIPATRA` sales orders (`FTIRSIP = '6'`), `TBLCASABIT` customers, `TBLSTOKPH` stock totals, and **optional receivables aging** from `TBLCAHAR` (with the open-item vs. running-balance caveat called out inline — the honest weak point). Field-mapped from real production integrations, with the weak points (order status, delivery dates, AR closing method) flagged inline to verify against your install.

Together, Logo Tiger and Netsis cover most of the Turkish SME ERP market (both MSSQL). Writing a profile for another ERP (Mikro, SAP B1, Odoo, a custom system) means writing **three SELECT statements** that output the canonical columns — either a standalone YAML you point `profile:` at, or a file dropped into `erp_report_engine/profiles/` to ship it bundled. That's the whole contract — and `validate` tells you immediately whether you got it right.

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

**Exit codes** let the scheduler branch on *why* a run failed: `0` success · `2` config error · `3` database/connection error · `4` contract error (profile schema wrong or source counts don't reconcile) · `5` data-quality failure under `--strict` · `1` anything unexpected. The machine-readable result goes to stdout (`… run -c config.yaml | jq`); logs go to stderr, optionally also to a JSON-lines file with `--log-file run.jsonl`. Run `validate --strict` in CI to fail the pipeline when the numbers don't reconcile.

**Delivery is built in.** `run --send` emails the report (SMTP), posts a summary to Slack or Teams (Power Automate Workflows), and pings a [healthchecks.io](https://healthchecks.io) dead-man's-switch on success *or* failure — so a silent cron is detectable. Every secret comes from an environment variable; a channel that fails is logged, never fatal. Configure it in a `delivery:` block (see `config.example.yaml`). For a full hands-off pipeline, the `power_automate` channel posts an Adaptive Card to Teams **and** archives the HTML report to SharePoint/OneDrive — an importable flow and step-by-step guide live in **[automation/POWER-AUTOMATE.md](automation/POWER-AUTOMATE.md)**. The report writes itself *and* delivers itself — the feature most BI tools charge for.

## The Power BI Command Center

The engine also feeds an interactive Power BI layer — and there is no `.pbix` binary in this repo. The entire artifact is a **PBIP project authored as code**: the semantic model in TMDL (star schema, 28 documented DAX measures — including **SVG micro-chart measures** that draw a per-customer sparkline and a per-item cover bar straight from DAX, and a **receivables-aging** fact + measures — a *Time Shift* calculation group on a gapless week ordinal, and a field parameter), the report in PBIR (5 pages / 30 visuals, generated from compact specs by a script), and a **dark futuristic theme validated against Microsoft's official theme schema**.

```bash
# a demo export already ships in powerbi/data — just open the project:
#   powerbi/ERP Command Center.pbip   (Power BI Desktop)
# to feed it your own ERP (writes to gitignored powerbi/data.local by default):
erp-report-engine export-powerbi -c config.yaml
```

The signature is the **Trust page**: source reconciliation, the data-quality gate and the full SQL audit trail rendered as visuals — the dashboard shows its receipts. Alert thresholds are the same ones as `insights.py`, re-derived in DAX: one definition, two surfaces. Field bindings are validated against the TMDL model by `pbir-cli` before the project ever meets Desktop. Full guide: [powerbi/README.md](powerbi/README.md).

## Ask your ERP through an agent — the guarded MCP server

An AI agent connecting to an ERP is a trust problem nobody has solved well: every existing "ERP MCP" is a REST wrapper that leans on the ERP's own permissions, and every database MCP hands the agent raw tables. This engine ships the combination that doesn't exist elsewhere — a [Model Context Protocol](https://modelcontextprotocol.io) server where the agent talks to **canonical entities** (`orders`, never `LG_001_01_ORFICHE`), through the **same three-layer read-only guard and audit trail** as the report, with every data result framed as untrusted input.

```bash
pipx install "erp-report-engine[mcp]"
erp-report-engine mcp -c config.yaml          # stdio server
```

Five tools, all funneled through the guarded path:

| Tool | What the agent gets |
|---|---|
| `describe_model` | the canonical entities/columns it may query (no raw ERP table names) |
| `weekly_report` | the full KPI briefing — findings, data-quality gate, reconciliation, SQL audit trail |
| `reconcile` | fetched rows vs an independent `COUNT(*)` per entity, with a trust verdict |
| `check_query` | whether a SQL statement would pass the guard — *without running it* |
| `query` | run a read-only `SELECT`/`WITH`, capped and audited; rows returned as **untrusted data** |

Point Claude Desktop (or any MCP client) at it:

```json
{ "mcpServers": { "erp": { "command": "erp-report-engine", "args": ["mcp", "-c", "C:\\path\\config.yaml"] } } }
```

The agent **cannot write**: the lexical + AST guard rejects anything but a single read query, the session is read-only, and — per the 2025 MCP data-exfiltration incidents — every returned value carries a note that rows are data, not instructions. It is, as far as we can find, the first SQL-level-guarded ERP MCP server, and the first for Logo Tiger.

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

The suite covers the read-only guard (a battery of injection attempts), profile contracts, the calendar core (unit + property-based), render escaping, the honesty fixes, CLI exit codes, the MCP tools, SPC signals, delivery routing, and a full end-to-end run plus Power BI PBIP integrity (exporter keys, gapless week ordinals, visual-overlap detection, every visual field exists in the model). CI additionally runs `ruff` and fails on PBIR generator drift, on Python 3.10–3.13.

## Roadmap

Shipped: the guarded MCP server, the SPC/XmR anomaly layer, native delivery (SMTP/Slack/Teams/healthchecks), declarative profile contracts, the Netsis profile, revenue-concentration analysis (top-3 share + HHI), **receivables aging (cari yaşlandırma)** as an optional canonical entity, DAX SVG micro-charts, and a schema-validated dark Power BI theme. Next:

- `profiles/mikro.yaml` — a third Turkish ERP mapping
- Real-ERP receivables mappings (Logo/Netsis cari ledgers) behind the same optional `receivables` entity the generic profile already demos
- LLM-optional narrative layer: an executive summary generated from aggregates only (never raw rows), with a "what the model saw" appendix
- A first-party agent skill pack (`erp-safe-query`, `explain-kpi-move`, `write-erp-profile`)

## Part of the measurement-honesty series

Tools that tell you the truth about your operation, by [Eren Gülmez](https://github.com/gulmezeren2-byte):

- [otif-analytics](https://github.com/gulmezeren2-byte/otif-analytics) — the 5-step metric ladder from "98% reported" to "59% OTIF"
- [forecast-accuracy-lab](https://github.com/gulmezeren2-byte/forecast-accuracy-lab) — WMAPE vs MAPE, and why zero-dropping flatters your forecast
- [opsaudit](https://github.com/gulmezeren2-byte/opsaudit) — ops metrics CLI with a non-removable honesty block
- [auto-report-pipeline](https://github.com/gulmezeren2-byte/auto-report-pipeline) — this engine's CSV-fed little sibling
- [forecast-autoresearch](https://github.com/gulmezeren2-byte/forecast-autoresearch) — an agent improving a forecast against a sealed holdout

## License

[MIT](LICENSE) © Eren Gülmez
