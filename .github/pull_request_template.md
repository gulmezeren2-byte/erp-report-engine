## What and why

<!-- one or two sentences -->

## Checklist

- [ ] `pytest tests/` is green
- [ ] `ruff check erp_report_engine demo tests` is clean
- [ ] The read-only guarantee is intact (no new DB path; guard not weakened) — see [ARCHITECTURE.md](../ARCHITECTURE.md)
- [ ] Honesty features (audit trail, reconciliation, DQ gate, definitions) still ship in the report
- [ ] New behavior has a test; guard changes have a hostile test
- [ ] If `powerbi/` or the guard/benchmark changed, the generated pages were regenerated and show no drift (`git diff --exit-code` on the `.Report` tree and `docs/trust.html` / `docs/playground.html`)
- [ ] Synthetic data only — no real ERP data, company names, or connection strings
- [ ] Docs updated if user-facing (README + README.tr.md stay in sync)
