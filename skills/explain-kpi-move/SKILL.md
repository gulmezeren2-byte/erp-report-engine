---
name: explain-kpi-move
description: Explain WHY a weekly ERP KPI moved without inventing a cause — use the findings, driver attribution, and SPC signal the engine already computed, and say when a move is just noise.
---

# Explain a KPI move

Use this when someone asks "why did revenue / on-time / cover change this week?"
The honest answer uses what `erp-report-engine` already derived — not a guess.

## Steps

1. **Get the briefing.** Call `weekly_report`. It returns the KPIs (this week vs
   previous vs 8-week baseline), the `findings`, the `reconciliation`, and the
   SQL `audit_trail`.
2. **Lead with the finding.** The engine's `findings` already name the driver
   (e.g. *"Revenue +26.7% WoW — main driver: region 'Ege' (157% of the move)"*)
   and any SPC signal (*"148,291 is ABOVE the control limits … a real shift
   beyond week-to-week noise"*). Quote that; it is deterministic and audited.
3. **Signal vs noise.** If the finding says a move is within control limits, say
   so plainly — *"this week's dip is inside normal week-to-week variation, not a
   real change."* Don't manufacture a story for noise.
4. **Confirm the driver if asked.** To go deeper, run one aggregate query
   (see `erp-safe-query`): `SELECT region, SUM(net_total) …` for this week vs
   last. Report the split; don't speculate beyond it.
5. **Name the caveats.** If `data_quality_issues` flags unscored on-time orders,
   duplicates, or a reconciliation mismatch, surface it — a KPI built on shaky
   inputs deserves the asterisk.

## Guardrails

- **No invented causes.** "Revenue rose because of a marketing campaign" is not
  in the data. Attribute only to what the driver split and findings support
  (a region, a customer, a status).
- **Correlation ≠ cause.** The engine attributes *where* a move concentrated, not
  *why* it happened in the real world. Frame it as "the move concentrates in X —
  confirm whether that's demand or a one-off," exactly as the finding does.
- **Percentages need a base.** A "+400%" on a tiny customer is smaller than a
  "+5%" on the biggest one; report the absolute change alongside the percent.
