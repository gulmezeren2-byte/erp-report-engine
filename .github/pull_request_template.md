## What and why

<!-- one or two sentences -->

## Checklist

- [ ] `pytest tests/` is green
- [ ] `ruff check erp_report_engine demo tests` is clean
- [ ] The read-only guarantee is intact (no new DB path; guard not weakened) — see [ARCHITECTURE.md](../ARCHITECTURE.md)
- [ ] Honesty features (audit trail, reconciliation, DQ gate, definitions) still ship in the report
- [ ] New behavior has a test; guard changes have a hostile test
- [ ] Docs updated if user-facing (README + README.tr.md stay in sync)
