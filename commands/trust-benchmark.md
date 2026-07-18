---
description: Run erp-report-engine's read-only SQL guard against its 28-attack trust benchmark and explain the result. No database or config needed.
---

Run the trust benchmark for the erp-report-engine read-only SQL guard and explain what it proves.

Use the Bash tool to run it — it exercises the guard in memory, so no database or config is required:

```
uvx --from erp-report-engine erp-report-engine trust-benchmark
```

If `uvx` is not available, try `pipx run erp-report-engine trust-benchmark`, or `erp-report-engine trust-benchmark` if the package is already installed.

Then summarise for the user, concisely:
- How many of the 28 well-formed-SQL attacks the guard **refused**, and how many legitimate reads it **allowed** (it should be 28/28 and 8/8).
- The **contrast** the benchmark prints against the naive checks real tools ship — a starts-with-`SELECT` head check (refuses only ~6/28) and a write-keyword blocklist (~9/28, and it even blocks a legitimate read whose string contains the word "delete"). The point: a guard that reads only a statement's *shape* lets file reads, shell calls and write-escapes through.
- Invite them to paste their own attack into the live playground: https://gulmezeren2-byte.github.io/erp-report-engine/playground.html
