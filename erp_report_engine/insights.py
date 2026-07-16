"""Rule-based findings: what changed, where it concentrates, what needs a decision.

Deterministic and auditable. The driver search scans region, customer and item
dimensions and names the segment that explains the largest share of the move.
"""

from __future__ import annotations

import pandas as pd

from . import spc


def build(kpis: dict, frames: dict, low_cover_weeks: float,
          rev_threshold_pct: float = 5.0, otp_threshold_pts: float = 1.5) -> list[dict]:
    out: list[dict] = []
    o: pd.DataFrame = kpis["_dims"]["orders_frame"]
    this_w, prev_w = kpis["_dims"]["this_w"], kpis["_dims"]["prev_w"]

    rev_now, rev_prev = kpis["revenue"]["now"], kpis["revenue"]["prev"]
    if rev_prev and rev_prev == rev_prev and rev_prev != 0:
        pct = (rev_now / rev_prev - 1) * 100
        if abs(pct) >= rev_threshold_pct:
            driver = _driver(o, this_w, prev_w, value_col="net_total")
            out.append({
                "tone": "good" if pct > 0 else "bad",
                "text": (
                    f"Revenue {pct:+.1f}% week-over-week — main driver: {driver['dim']} "
                    f"'{driver['segment']}' ({driver['delta_share']:.0f}% of the move). "
                    f"Confirm whether this is demand or a one-off before reacting."
                ),
            })

    otp_now, otp_prev = kpis["on_time_pct"]["now"], kpis["on_time_pct"]["prev"]
    if otp_now == otp_now and otp_prev == otp_prev:
        diff = otp_now - otp_prev
        if abs(diff) >= otp_threshold_pts:
            out.append({
                "tone": "bad" if diff < 0 else "good",
                "text": (
                    f"On-time shipping moved {diff:+.1f} pts to {otp_now:.1f}%. "
                    f"{'Pull the late-order list from the report data and raise it in the ops meeting.' if diff < 0 else 'Acknowledge the improvement in the ops meeting.'}"
                ),
            })

    if kpis["n_low_cover"]:
        top = ", ".join(x["item_code"] for x in kpis["low_cover"][:3])
        out.append({
            "tone": "warn",
            "text": (
                f"{kpis['n_low_cover']} items are below {low_cover_weeks:.0f} weeks of stock cover "
                f"(worst first: {top}). Review replenishment before the weekend."
            ),
        })

    conc = kpis.get("concentration")
    if conc and conc["top3_pct"] >= 50.0:
        risk = conc["top3_pct"] >= 65.0 or conc["hhi"] >= 2500
        out.append({
            "tone": "warn" if risk else "good",
            "text": (
                f"Revenue concentration: the top 3 of {conc['n_customers']} customers are "
                f"{conc['top3_pct']:.0f}% of the last {conc['window_weeks']} weeks' revenue "
                f"(HHI {conc['hhi']}). "
                + ("Concentration risk — one account swings the number; widen the base or protect the key relationships."
                   if risk else "Moderately concentrated; keep an eye on the top accounts.")
            ),
        })

    # SPC: separate genuine signals from week-to-week noise, each with its arithmetic.
    out += spc.signals(kpis)

    if not out:
        out.append({"tone": "good", "text": "No significant week-over-week movements — steady week."})
    return out


def _driver(o: pd.DataFrame, this_w: str, prev_w: str, value_col: str) -> dict:
    """Scan candidate dimensions; return the segment explaining the biggest share of the WoW delta."""
    best = {"dim": "region", "segment": "-", "delta_share": 0.0}
    total_delta = (
        o[o.week == this_w][value_col].sum() - o[o.week == prev_w][value_col].sum()
    )
    if total_delta == 0:
        return best
    for dim in ("region", "customer"):
        if dim not in o.columns:
            continue
        now = o[o.week == this_w].groupby(dim)[value_col].sum()
        prev = o[o.week == prev_w].groupby(dim)[value_col].sum()
        # union the index so a segment that had revenue LAST week and vanished this
        # week (a lost key account - the biggest possible negative driver) is not
        # silently dropped by reindexing onto only this week's segments (K4).
        idx = now.index.union(prev.index)
        delta = (now.reindex(idx, fill_value=0) - prev.reindex(idx, fill_value=0)).fillna(0)
        if delta.abs().max() == 0:
            continue
        seg = delta.abs().idxmax()
        share = abs(delta[seg]) / abs(total_delta) * 100
        if share > best["delta_share"]:
            best = {"dim": dim, "segment": str(seg), "delta_share": min(share, 999.0)}
    return best
