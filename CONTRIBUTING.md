# Contributing

Thanks for considering it. Two ground rules first, then the easy paths in.

## Ground rules

1. **The read-only guarantee is non-negotiable.** Anything that adds a second path to the database, weakens `assert_read_only`, or string-formats runtime values into SQL will not merge — regardless of how useful the feature is.
2. **Honesty features stay.** The audit trail, source reconciliation, data-quality gate and metric definitions are the product. Changes that hide or soften them don't merge either.

See [AGENTS.md](AGENTS.md) for the full invariant list and repo layout.

## The most valuable contribution: an ERP profile

If you know the schema of Netsis, Mikro, SAP B1, Odoo, Dynamics or any other ERP, a profile is three `SELECT` statements in one YAML file:

1. Copy `profiles/generic.yaml` to `profiles/<erp>.yaml`.
2. Map your ERP's tables to the canonical columns in `erp_report_engine/semantic.py::REQUIRED_COLUMNS`.
3. Use `{vars}` only for schema identifiers (firm/period numbers), `:since` for the date filter, single statement per entity, no comments.
4. Add **field notes** in the description: which ERP versions you verified against, which fields vary, what a user must check before trusting it.
5. `python -m pytest tests/` must pass (load-time validation covers your profile automatically).

## Bug reports and features

- Guard bypasses: **do not open a public issue** — use GitHub's private vulnerability reporting (see [SECURITY.md](SECURITY.md)).
- Everything else: an issue with your Python version, the profile used, and (if report-related) the report's reconciliation/data-quality sections pasted in.

## Pull requests

- Keep the test suite green: `python -m pytest tests/ -v`
- New behavior needs a test; guard changes need a hostile test.
- One topic per PR. Small is fast.
