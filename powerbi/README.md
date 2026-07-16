# ERP Command Center — the Power BI layer

> The same engine, the same honesty — now as an interactive Power BI semantic model and report, **authored entirely as code**.

🇹🇷 Türkçesi: [README.tr.md](README.tr.md)

No `.pbix` binary lives in this repo. The whole Power BI artifact is a **PBIP project** in source-control-friendly text formats — [TMDL](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview) for the semantic model, [PBIR](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report#pbir-format) for the report — which means every measure, every relationship and every visual is reviewable in a git diff, exactly like the rest of the engine.

## Quickstart

```bash
# 1. produce the data (demo shown; use your own config for a real ERP)
python -m erp_report_engine init-demo
python -m erp_report_engine export-powerbi -c config.demo.yaml

# 2. open the project (Power BI Desktop, any recent version)
#    double-click:  powerbi/ERP Command Center.pbip
```

On first open: **Transform data → Edit parameters → set `DataFolder`** to this repo's `powerbi\data` folder (absolute path), then **Refresh**. That's the whole setup — the parameter exists precisely so no absolute path is baked into the model.

A committed demo export ships in [`data/`](data/), so the report renders meaningful numbers on the very first refresh. **A real ERP export goes somewhere safe by default:** `export-powerbi` writes to `powerbi/data.local/` (gitignored) unless you pass `-o`, so a later `git commit` can never publish your order values, customer names, or SQL. Point `DataFolder` at `powerbi\data.local` when you work with real data; the committed `data/` folder stays the demo snapshot.

## What's inside

| Piece | Technology | What it does |
|---|---|---|
| `ERP Command Center.SemanticModel/` | **TMDL** | Star schema (2 facts, 2 dimensions), 4 meta tables, 23 DAX measures with descriptions and display folders, `discourageImplicitMeasures` |
| `Time Shift` table | **Calculation group** | Apply *Previous Week / WoW Change / WoW % / 8-Week Baseline / vs Baseline %* to ANY measure — week arithmetic runs on a gapless ordinal, so it never breaks at year boundaries |
| `Selected KPI` table | **Field parameter** | One chart, four KPIs — the viewer switches instead of four near-duplicate visuals |
| `Revenue/On-Time Sparkline`, `Cover Bar` | **DAX SVG micro-charts** | Measures that return `data:image/svg+xml` and are tagged `dataCategory: ImageUrl`, so a table draws a **per-row sparkline** (one 13-week trend per customer) or a **cover bar** (red below the threshold, amber tick at it) — a real chart in every cell, no custom visual |
| `measurement-honesty-theme.json` | **Dark theme** | A futuristic dark theme (validated against Microsoft's official theme schema): rounded glass containers, soft shadows, and a colour-blind-safe categorical palette stepped for the dark surface |
| `ERP Command Center.Report/` | **PBIR** | 4 pages, 24 visuals, the dark theme — every visual an individual reviewable JSON |
| `tools/generate_report_pages.py` | **Report-as-code** | The report pages are *generated* from compact specs; layout changes are one edit + one rerun |
| `data/` | CSV star schema | Written by `export-powerbi` through the engine's guarded, audited, read-only path |

## The four pages

1. **Overview** — headline cards anchored to the **last completed ISO week** (a two-day week can never masquerade as a crash), weekly revenue and on-time trends, and a plain-language *Weekly Verdict* card computed live by DAX.
2. **Drivers** — a decomposition tree over revenue (region → customer → status) plus a WoW driver table where **each customer carries its own 13-week revenue sparkline** (an SVG micro-chart, drawn by DAX): where the move concentrates *and* how each account got there.
3. **Stock** — cover-weeks table with a **per-item cover bar** (SVG, red below the threshold) and an ordered-quantity ranking; the low-cover threshold comes from the engine's config via `MetaRunInfo`, not hardcoded in DAX.
4. **Trust** — the signature page: **source reconciliation counts, every data-quality finding, and the full SQL audit trail** rendered as visuals. The dashboard shows its receipts.

## Proactive by design

The model re-derives the engine's insight rules in DAX — same thresholds as `insights.py` (revenue alert at |5%| WoW, on-time alert at 1.5 pts), one definition on two surfaces:

- **`Alert Count`** — how many rules fire right now (including the revenue decline streak from run-state memory)
- **`Weekly Verdict`** — the one-line story: *"Week 2026-W28: revenue +25.4% WoW · on-time −2.0 pts · 4 items below 2.0 weeks of cover · 4 data-quality issues"*
- **`Trust Statement`** — reads OK **only** when every entity's row count reconciles with its source `COUNT(*)`

Schedule `export-powerbi` right after the weekly `run` (same Task Scheduler / cron job) and the numbers refresh themselves; publish to the Power BI Service if you want data alerts pushed to your phone.

## Validation — how a hand-authored PBIP stays correct

The project is checked on three levels before it ever meets Power BI Desktop:

1. `pytest tests/test_powerbi.py` — exporter contract (unique keys, gapless week ordinals, no BOM) + project integrity (page/visual naming rules, **visual overlap detection**, theme resolution, every visual entity exists in TMDL).
2. [`pbir-cli`](https://pypi.org/project/pbir-cli/): `pbir validate "ERP Command Center.Report" --fields --qa` — official JSON schemas plus **field binding validation against the loaded TMDL model** (42 field references checked, including the SVG micro-chart measures).
3. Power BI Desktop itself validates all PBIR files on open.

## Honest limits

- **Desktop required.** PBIP opens in Power BI Desktop (free) on Windows; the repo ships no `.pbix` binary by design — text formats are the point.
- **On-time here is OTIF-lite**, same definition and same disclaimer as the engine's HTML report.
- The demo data is synthetic. The seeded story (a regional revenue spike, a late-shipping cluster, four dirty rows) exists so every page has something honest to show.
