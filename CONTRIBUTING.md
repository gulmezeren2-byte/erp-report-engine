# Contributing

Thanks for considering it. Two ground rules first, then the easy paths in.

## Ground rules

1. **The read-only guarantee is non-negotiable.** Anything that adds a second path to the database, weakens `assert_read_only`, or string-formats runtime values into SQL will not merge — regardless of how useful the feature is.
2. **Honesty features stay.** The audit trail, source reconciliation, data-quality gate and metric definitions are the product. Changes that hide or soften them don't merge either.

See [AGENTS.md](AGENTS.md) for the full invariant list and repo layout.

## The single most valuable contribution: a guard bypass

If you can get a write, a second statement, a file read, an outbound connection, or any side effect past the read-only guard, that's the best thing you can send — it is treated as a contribution, not an attack. **Report it privately first** ([SECURITY.md](SECURITY.md)) with a minimal SQL snippet. Confirmed bypasses are fixed with a regression test in `tests/test_guard.py`, named for the bypass and parametrized per dialect, and added to the public [trust benchmark](https://gulmezeren2-byte.github.io/erp-report-engine/trust.html). Try to break it first: [in your browser](https://gulmezeren2-byte.github.io/erp-report-engine/playground.html), or `erp-report-engine trust-benchmark`.

## Also very valuable: an ERP profile

If you know the schema of any ERP — the bundled ones are Logo Tiger, Netsis and Mikro — a profile is a few `SELECT` statements in one YAML file:

1. Copy `erp_report_engine/profiles/generic.yaml` to `erp_report_engine/profiles/<erp>.yaml` (it ships bundled, referenced as `profile: <erp>`; add the filename to the wheel force-include in `pyproject.toml` and the CI profile-bundled check).
2. Map your ERP's tables to the canonical entities in `erp_report_engine/semantic.py::CANONICAL_SCHEMA` (which documents each column's type and meaning).
3. Use `{vars}` only for schema identifiers (firm/period numbers), `:since` for the date filter, single statement per entity, no comments.
4. Add **field notes** in the description: which ERP versions you verified against, which fields vary, what a user must check before trusting it.
5. *(optional)* Add a `contract:` block — declarative expectations (`not_null`, `unique`, `accepted_values`, `relationships`, `min_rows`) checked over the extracted data and reported in the quality gate; `severity: fail` trips `run --strict`. See `erp_report_engine/profiles/generic.yaml`.
6. `python -m pytest tests/` must pass (load-time validation covers your profile automatically).

## Bug reports and features

- Guard bypasses: **do not open a public issue** — use GitHub's private vulnerability reporting (see [SECURITY.md](SECURITY.md)).
- Everything else: an issue with your Python version, the profile used, and (if report-related) the report's reconciliation/data-quality sections pasted in.

## The gates your change has to clear (this is what CI runs)

```bash
ruff check .                                     # lint
python -m pytest -q                              # the whole suite
```

If you touched `powerbi/`, the pages are generated — regenerate and confirm no drift:

```bash
python powerbi/tools/generate_report_pages.py
git diff --exit-code -- "powerbi/ERP Command Center.Report"
```

If you touched the guard, the benchmark corpus, or `guard.py`, the docs pages are generated from them too:

```bash
python docs/generate_trust_page.py && python docs/generate_playground.py
git diff --exit-code -- docs/trust.html docs/playground.html
```

CI also runs on Windows and Linux across Python 3.10–3.13 with a coverage floor, so a green local run is a good predictor — but not a guarantee on Windows path/encoding edges.

## House rules

- **Synthetic data only.** Never commit real ERP data, company names, credentials, or a connection string. The demo is generated; `export-powerbi` writes to a gitignored folder by default.
- **One definition, every surface.** If a rule lives in one place (a bucket edge, a window length, the "delivered" status set), import it — don't restate it. Drift between surfaces is the bug this project is most allergic to.
- **Keep claims true.** If a doc says the guard blocks something, there's a test that proves it. Add the test with the claim.

## Pull requests

- Keep the test suite green: `python -m pytest tests/ -q`
- New behavior needs a test; guard changes need a hostile test.
- One topic per PR. Small is fast. Fill in the PR template checklist.
