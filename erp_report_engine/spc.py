"""XmR (individuals + moving range) control charts - "signal vs noise, with
receipts".

Every flagged signal ships the arithmetic that produced it, so a reader can
check it with a pocket calculator. Deterministic: no model, no black box - which
is exactly the measurement-honesty brand, and exactly what NHS England board
reporting and Grafana's production anomaly detection actually use.

For weekly ops KPIs (a ~13-week window) XmR is the defensible choice: seasonal
decomposition and Prophet need two-plus years of data these series don't have.
The 2.66 constant is 3 / d2 with d2 = 1.128 for a moving range of two points
(Shewhart control-chart theory).
"""

from __future__ import annotations

import statistics

_LIMIT_K = 2.66          # individuals-chart control-limit multiplier (3 / 1.128)
_MIN_POINTS = 6          # need enough history for limits to mean anything
_STABLE_N = 15           # below this, limits are labelled provisional
_RUN_LEN = 8             # consecutive points one side of the center line = a shift


def _limits(baseline: list[float]) -> dict:
    cl = statistics.fmean(baseline)
    ranges = [abs(b - a) for a, b in zip(baseline, baseline[1:], strict=False)]
    mr_bar = statistics.fmean(ranges) if ranges else 0.0
    spread = _LIMIT_K * mr_bar
    return {"cl": cl, "ucl": cl + spread, "lcl": cl - spread, "mr_bar": mr_bar, "n": len(baseline)}


def evaluate_metric(label: str, values, *, pct: bool = False, higher_is_better: bool = True) -> list[dict]:
    """Signals for the latest point against an XmR baseline of the earlier points.

    The current point is excluded from its own limits. Returns finding dicts
    ({tone, text}) whose text carries the full arithmetic.
    """
    clean = [float(v) for v in values if v == v]  # drop NaN weeks
    if len(clean) < _MIN_POINTS:
        return []
    lim = _limits(clean[:-1])
    if lim["mr_bar"] == 0:
        return []                                   # a flat series has no meaningful spread

    def f(x: float) -> str:
        return f"{x:.1f}%" if pct else f"{x:,.0f}"

    current = clean[-1]
    provisional = (f" [limits provisional: baseline n={lim['n']}, stabilize at n>={_STABLE_N}]"
                   if lim["n"] < _STABLE_N else "")
    receipt = (f"UCL {f(lim['ucl'])} / LCL {f(lim['lcl'])} = mean {f(lim['cl'])} "
               f"± 2.66 × avg moving range {f(lim['mr_bar'])}")

    if current > lim["ucl"]:
        tone = "good" if higher_is_better else "bad"
        return [{"tone": tone, "text": (
            f"{label} signal: {f(current)} is ABOVE the control limits ({receipt}) — "
            f"a real shift beyond week-to-week noise, worth a specific cause.{provisional}")}]
    if current < lim["lcl"]:
        tone = "bad" if higher_is_better else "good"
        return [{"tone": tone, "text": (
            f"{label} signal: {f(current)} is BELOW the control limits ({receipt}) — "
            f"a real shift beyond week-to-week noise, worth a specific cause.{provisional}")}]

    tail = clean[-_RUN_LEN:]
    if len(tail) == _RUN_LEN and all(v > lim["cl"] for v in tail):
        return [{"tone": "good" if higher_is_better else "warn", "text": (
            f"{label}: {_RUN_LEN} straight weeks above the average ({f(lim['cl'])}) — "
            f"a sustained upward shift, not noise.{provisional}")}]
    if len(tail) == _RUN_LEN and all(v < lim["cl"] for v in tail):
        return [{"tone": "bad" if higher_is_better else "warn", "text": (
            f"{label}: {_RUN_LEN} straight weeks below the average ({f(lim['cl'])}) — "
            f"a sustained downward shift, not noise.{provisional}")}]
    return []


def signals(kpis: dict) -> list[dict]:
    """SPC findings for the report's trend series (revenue and on-time %)."""
    trend = kpis.get("trend", {})
    out: list[dict] = []
    out += evaluate_metric("Revenue", trend.get("revenue", []))
    out += evaluate_metric("On-time shipping", trend.get("on_time", []), pct=True)
    return out
