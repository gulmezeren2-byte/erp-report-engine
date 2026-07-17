---
name: ERP profile request / contribution
about: Add or fix a semantic profile for an ERP
labels: profile
---

**Which ERP** (and version/localization)

**Database**: MSSQL / PostgreSQL / other

**Do you have the schema?** Link docs or paste the relevant table/column names for orders, order lines, and inventory. A profile is a few `SELECT`s mapping your ERP to the canonical entities in `erp_report_engine/semantic.py::CANONICAL_SCHEMA` (which documents each column's type and meaning) — see [CONTRIBUTING.md](../../CONTRIBUTING.md).

**Can you test against a real instance?** Even a restored backup lets `erp-report-engine validate -c ...` confirm the mapping.
