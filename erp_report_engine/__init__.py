"""erp-report-engine - autonomous weekly reporting straight from the SQL
database behind your ERP.

Design pillars:
- READ-ONLY by construction: every statement passes a SELECT-only guard,
  every executed query lands in an audit log shipped with the report.
- A semantic profile layer maps cryptic ERP schemas (Logo Tiger, Netsis, ...)
  to canonical entities (orders, order_lines, inventory) via versioned YAML
  contracts.
- Measurement honesty: the report carries a data-quality gate, source
  reconciliation counts and explicit metric definitions.
"""

__version__ = "0.4.0"
