"""Rule-based findings: what changed, where it concentrates, what needs a decision.

Deterministic and auditable. The driver search scans the region and customer
dimensions and names the segment behind the largest share of the week's movement.
A finding is only raised when the underlying sample can carry it - a metric that
moves 50 points on two deliveries is arithmetic, not news.
"""

from __future__ import annotations

import pandas as pd

from . import spc


def build(kpis: dict, frames: dict, low_cover_weeks: float,
          rev_threshold_pct: float = 5.0, otp_threshold_pts: float = 1.5,
          min_scored_deliveries: int = 5) -> list[dict]:
    out: list[dict] = []
    o: pd.DataFrame = kpis["_dims"]["orders_frame"]
    this_w, prev_w = kpis["_dims"]["this_w"], kpis["_dims"]["prev_w"]

    rev_now, rev_prev = kpis["revenue"]["now"], kpis["revenue"]["prev"]
    if rev_prev and rev_prev == rev_prev and rev_prev != 0:
        pct = (rev_now / rev_prev - 1) * 100
        if abs(pct) >= rev_threshold_pct:
            driver = _driver(o, this_w, prev_w, value_col="net_total")
            off = driver["offset"]
            offset_txt = (f", partly offset by {off['segment']} ({off['delta']:+,.0f})"
                          if off else "")
            out.append({
                "tone": "good" if pct > 0 else "bad",
                "text": (
                    f"Revenue {pct:+.1f}% week-over-week — main driver: {driver['dim']} "
                    f"'{driver['segment']}' ({driver['delta_share']:.0f}% of the week's "
                    f"movement{offset_txt}). "
                    f"Confirm whether this is demand or a one-off before reacting."
                ),
                # the identifiable strings in `text`, declared so a consumer that
                # must not see them (the LLM narrative) can redact rather than guess
                "names": [driver["segment"]] + ([off["segment"]] if off else []),
            })

    otp = kpis["on_time_pct"]
    otp_now, otp_prev = otp["now"], otp["prev"]
    if otp_now == otp_now and otp_prev == otp_prev:
        diff = otp_now - otp_prev
        if abs(diff) >= otp_threshold_pts:
            # A percentage carries no information about the sample under it. Two
            # deliveries moving 1-of-2 to 2-of-2 IS "+50 pts", and reporting that
            # with a straight face is how a report loses the room.
            if int(otp.get("scored", 0)) < min_scored_deliveries:
                out.append({
                    "tone": "warn",
                    "text": (
                        f"On-time shipping reads {otp_now:.1f}% ({diff:+.1f} pts), but only "
                        f"{otp.get('scored', 0)} deliveries were scored this week — too few to "
                        f"tell a move from arithmetic. Reported, not called."
                    ),
                })
            else:
                out.append({
                    "tone": "bad" if diff < 0 else "good",
                    "text": (
                        f"On-time shipping moved {diff:+.1f} pts to {otp_now:.1f}% "
                        f"over {otp['scored']} scored deliveries. "
                        f"{'Pull the late-order list from the report data and raise it in the ops meeting.' if diff < 0 else 'Acknowledge the improvement in the ops meeting.'}"
                    ),
                })

    # On-time % is scored over orders that SHIPPED, so an order that is late and
    # still sitting there never costs it a point - the metric can improve while
    # fulfilment falls over. Say the number the percentage cannot see.
    unshipped = int(otp.get("promised_unshipped", 0))
    if unshipped:
        out.append({
            "tone": "warn",
            "text": (
                f"{unshipped} order(s) were promised this week and have not shipped. "
                f"They are not in the on-time % — it scores orders that shipped, so an "
                f"order that never ships never counts as late. Check them before reading "
                f"the percentage as good news."
            ),
        })

    if kpis["n_low_cover"]:
        top = ", ".join(x["item_code"] for x in kpis["low_cover"][:3])
        dw = int(kpis.get("demand_window_weeks", 8))
        thin = (f" Demand is averaged over {dw} week(s) of history, so cover is a coarse read."
                if dw < 8 else "")
        out.append({
            "tone": "warn",
            "text": (
                f"{kpis['n_low_cover']} items are below {low_cover_weeks:.0f} weeks of stock cover "
                f"(worst first: {top}). Review replenishment before the weekend.{thin}"
            ),
            "names": [x["item_code"] for x in kpis["low_cover"][:3]],
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

    aging = kpis.get("aging")
    if aging and (aging["overdue_pct"] >= 25.0 or aging["over90_pct"] >= 10.0):
        worst = aging["top_overdue"][0] if aging["top_overdue"] else None
        worst_txt = f" Largest overdue: {worst['customer']} ({worst['amount']:,.0f})." if worst else ""
        out.append({
            "tone": "warn",
            "text": (
                f"Receivables: {aging['overdue_pct']:.0f}% of open AR is overdue "
                f"({aging['overdue']:,.0f} of {aging['total']:,.0f}), "
                f"{aging['over90_pct']:.0f}% is over 90 days.{worst_txt} "
                f"Chase the oldest balances before they age further."
            ),
            "names": [worst["customer"]] if worst else [],
        })

    # SPC: separate genuine signals from week-to-week noise, each with its arithmetic.
    out += spc.signals(kpis)

    if not out:
        out.append({"tone": "good", "text": "No significant week-over-week movements — steady week."})
    return out


def _driver(o: pd.DataFrame, this_w: str, prev_w: str, value_col: str) -> dict:
    """Scan candidate dimensions; return the segment that moved most, its share of
    the week's GROSS movement, and the largest segment moving the other way.

    Share is measured against gross movement (the sum of every segment's absolute
    delta), never against the net delta. Segments routinely move in opposite
    directions - one account churns while another grows - which drives the net
    toward zero and makes a share of it explode: "999% of the move" is not a
    statement a manager can act on, and it surfaces exactly when attribution
    matters most. Gross share is bounded 0-100% by construction and answers the
    question actually being asked: of everything that moved, how much was this?
    """
    best = {"dim": "region", "segment": "-", "delta_share": 0.0, "delta": 0.0, "offset": None}
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
        gross = float(delta.abs().sum())
        if gross == 0:
            continue
        seg = delta.abs().idxmax()
        share = abs(float(delta[seg])) / gross * 100
        if share > best["delta_share"]:
            # Name the biggest segment pulling the other way when it is material.
            # "+200 here, -150 there" is the honest shape of a small net move, and
            # the offsetting name is usually the more actionable half.
            offset = None
            counter = delta[delta * float(delta[seg]) < 0]
            if len(counter):
                off_seg = counter.abs().idxmax()
                if abs(float(counter[off_seg])) >= abs(float(delta[seg])) * 0.25:
                    offset = {"segment": str(off_seg), "delta": float(counter[off_seg])}
            best = {"dim": dim, "segment": str(seg), "delta_share": share,
                    "delta": float(delta[seg]), "offset": offset}
    return best
