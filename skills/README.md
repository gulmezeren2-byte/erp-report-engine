# Agent skill pack

Three first-party skills for an AI agent working with `erp-report-engine`. They
pair with the guarded [MCP server](../ARCHITECTURE.md) (`erp-report-engine mcp`)
and encode the engine's non-negotiables so an agent stays inside them:

| Skill | Use it when |
|-------|-------------|
| [`erp-safe-query`](erp-safe-query/SKILL.md) | You need data from an ERP exposed through the MCP server — canonical entities only, read-only, rows treated as untrusted data. |
| [`explain-kpi-move`](explain-kpi-move/SKILL.md) | A KPI moved and you must explain *why* without inventing a cause — use the findings and driver attribution the engine already computed. |
| [`write-erp-profile`](write-erp-profile/SKILL.md) | You're mapping a new ERP (Mikro, SAP B1, Odoo, a custom system) to the canonical entities — three SELECTs + an optional receivables one, verified by `validate`. |

The skills are plain Markdown with `name`/`description` frontmatter, so they drop
into Claude Code (`.claude/skills/`), an [agentskills.io](https://agentskills.io)
pack, or any agent runtime that reads instruction files. They assume the MCP
tools `describe_model`, `weekly_report`, `reconcile`, `check_query`, `query`, and
`aging`.

Why a skill pack at all: the engine already enforces read-only + audit *in code*.
These skills teach an agent to work *with* that grain — dry-run before querying,
aggregate instead of dumping rows, cite audited numbers, and never treat ERP text
as a command — so the human-in-the-loop story matches the technical one.
