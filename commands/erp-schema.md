---
description: Print erp-report-engine's canonical semantic model — entities, column types and meanings, and example queries the agent should use. No database needed.
---

Show the canonical semantic model that erp-report-engine exposes to an agent: the entities, each column's type and *meaning*, and runnable example queries.

Use the Bash tool (no database or config required):

```
uvx --from erp-report-engine erp-report-engine schema
```

(or `pipx run erp-report-engine schema`, or `erp-report-engine schema` if the package is already installed.)

Then explain to the user:
- The canonical entities available (`orders`, `order_lines`, `inventory`, and optionally `receivables`), and each one's grain.
- That a **semantic profile** maps these canonical names to a specific ERP's real, cryptic tables (e.g. `LG_001_01_ORFICHE` for Logo Tiger) — the agent only ever sees the canonical names, never the raw schema.
- That every query runs read-only and audited through the guard; a write, a file-reading function, or a second statement is refused before it reaches the database.
