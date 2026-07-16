---
name: write-erp-profile
description: Map a new ERP to erp-report-engine's canonical entities by writing a profile YAML — three SELECTs (plus an optional receivables one), identifier-safe placeholders, honest weak-point notes, verified by `validate`.
---

# Write an ERP profile

Use this to onboard a new ERP (Mikro, SAP Business One, Odoo, a custom system).
A profile is a versioned YAML contract that maps that ERP's schema to the
engine's canonical entities. You write **three SELECT statements** (four with
receivables); the engine does the rest.

## The contract

Each entity's query must output exactly these columns (alias to them):

```
orders:       order_id, order_date, region, customer, status,
              promised_date, actual_ship_date, net_total
order_lines:  order_id, item_code, qty
inventory:    item_code, stock_qty
receivables:  invoice_id, customer, due_date, open_amount     # OPTIONAL
```

`receivables` is optional — map it only if the AR ledger is reachable; leave it
out and the aging analysis simply doesn't appear.

## Steps

1. **Start from `generic.yaml`** (the canonical demo shapes) as a template.
2. **Write each SELECT** against the ERP's real tables, aliasing every output to
   the canonical name. Use `{placeholders}` for per-install values (firm/period
   codes); they are validated as `^[A-Za-z0-9_]{1,16}$`, so they can't carry an
   injection. Bind the report window with the `:since` parameter where relevant.
3. **Read-only only.** Every query must be a single `SELECT`/`WITH` — the loader
   runs the read-only guard on each one at load time and refuses the profile
   otherwise.
4. **Flag the weak points inline.** ERP schemas drift by version. In the
   `description`, write "VERIFY AGAINST YOUR VERSION" notes for every field you're
   unsure of — the VAT-inclusiveness of the total, the closed-status code, how
   ship dates are derived, and (for receivables) whether open amount comes from an
   open-item flag or must be FIFO-derived. An honest field mapping beats a
   confident wrong one.
5. **Add a contract** (optional `contract:` block): `not_null`, `unique`,
   `accepted_values`, `relationships`, `min_rows`. `severity: fail` trips
   `validate --strict`.
6. **Verify.** Run `erp-report-engine validate -c config.yaml`. It connects,
   checks every canonical column exists, reconciles each entity's row count
   against an independent `COUNT(*)`, and runs the contract — and tells you
   immediately what's wrong. Don't ship a profile that hasn't passed `validate`.

## Don't

- Don't invent table or column names to fill a gap — research the real schema and
  disclaim what you couldn't confirm. This engine's whole promise is honesty.
- Don't put credentials in the profile or the config; connection secrets come
  from an environment variable (`connection.url_env`).
- Don't widen a query to "just get everything" — the row cap and the canonical
  contract exist to keep the surface small and auditable.
