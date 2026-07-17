"""XmR (individuals + moving range) control charts - "signal vs noise, with
receipts".

Every flagged signal ships the arithmetic that produced it, so a reader can
check it with a pocket calculator. Deterministic: no model, no black box - which
is exactly the measurement-honesty brand, and exactly what NHS England board
reporting and Grafana's production anomaly detection actually use.

For weekly ops KPIs (a two-quarter window) XmR is the defensible choice: seasonal
decomposition and Prophet need two-plus years of data these series don't have.
The 2.66 constant is 3 / d2 with d2 = 1.128 for a moving range of two points
(Shewhart control-chart theory).

Two metrics, two correct tools:
- Revenue is a continuous individual per week -> an XmR (individuals + moving
  range) chart. The 2.66 constant is 3 / d2 with d2 = 1.128 for a two-point
  moving range (Shewhart). Limits come from the `spc` window, which is
  deliberately LONGER than the 13-week chart - baseline size drives limit
  quality, and how many weeks a chart can legibly show is not a statistical
  argument. Every signal carries its baseline n.
- On-time % is a PROPORTION over a varying denominator -> a p-chart. An
  individuals chart would weight a 2-delivery week like a 200-delivery week; a
  p-chart widens its limits when the week is thin (limit = p-bar ± 3 x
  sqrt(p-bar(1-p-bar)/n_week)), which is the statistically correct answer and the
  one this now uses. The current week's n travels with the signal.
"""

from __future__ import annotations

import math
import statistics

_LIMIT_K = 2.66          # individuals-chart control-limit multiplier (3 / 1.128)
_MIN_POINTS = 6          # need enough history for limits to mean anything
_STABLE_N = 15           # below this, limits are labelled provisional
_RUN_LEN = 8             # consecutive points one side of the center line = a shift
_P_MIN_N = 5             # a p-chart point needs a denominator worth trusting


def _limits(baseline: list[float]) -> dict:
    cl = statistics.fmean(baseline)
    ranges = [abs(b - a) for a, b in zip(baseline, baseline[1:], strict=False)]
    mr_bar = statistics.fmean(ranges) if ranges else 0.0
    spread = _LIMIT_K * mr_bar
    return {"method": "XmR", "cl": cl, "ucl": cl + spread, "lcl": cl - spread,
            "mr_bar": mr_bar, "n": len(baseline)}


def _p_limits(nums, dens) -> dict | None:
    """p-chart limits (as fractions 0..1) for the LATEST subgroup, from a baseline
    of the earlier ones.

    Center is the pooled proportion of the baseline; the spread uses the CURRENT
    week's n, so a thin week gets wider limits - the whole reason a proportion
    needs a p-chart and not an individuals chart. Returns None when there is not
    enough history, or when the center is 0/1 (no variation to bound)."""
    series = [(float(x), float(n)) for x, n in zip(nums, dens, strict=False)
              if n == n and x == x]
    if not series:
        return None
    current = series[-1]
    if current[1] < _P_MIN_N:
        return None                       # THIS week is too thin to judge - no signal
    # pool the baseline over earlier weeks, excluding thin ones (they'd distort p-bar)
    baseline = [(x, n) for x, n in series[:-1] if n >= _P_MIN_N]
    if len(baseline) < _MIN_POINTS - 1:
        return None
    base_num = sum(x for x, _ in baseline)
    base_den = sum(n for _, n in baseline)
    if base_den == 0:
        return None
    pbar = base_num / base_den
    if pbar <= 0 or pbar >= 1:
        return None
    p_cur, n_cur = current[0] / current[1], current[1]
    sigma = math.sqrt(pbar * (1 - pbar) / n_cur)
    return {"method": "p", "cl": pbar, "ucl": min(1.0, pbar + 3 * sigma),
            "lcl": max(0.0, pbar - 3 * sigma), "p_cur": p_cur,
            "n_cur": int(n_cur), "n": len(baseline), "sigma": sigma}


def _receipt(metric: str, lim: dict) -> str:
    """The arithmetic a reader can check by hand, in the series' display units.
    One place builds it, so the report finding, the dashboard and Power BI all
    quote the same string for the same limits."""
    if lim["method"] == "p":
        def pc(x): return f"{x * 100:.1f}%"
        # ASCII on purpose: this string travels into CSVs, logs and Windows
        # consoles, where a sqrt glyph would raise an encoding error
        return (f"center {pc(lim['cl'])} +/- 3 x sqrt(p(1-p)/n), n={lim['n_cur']} scored this "
                f"week -> [{pc(lim['lcl'])}, {pc(lim['ucl'])}], baseline n={lim['n']} weeks")
    pct = metric == "on_time"

    def f(x): return f"{x:.1f}%" if pct else f"{x:,.0f}"
    return (f"UCL {f(lim['ucl'])} / LCL {f(lim['lcl'])} = mean {f(lim['cl'])} "
            f"± 2.66 × avg moving range {f(lim['mr_bar'])}, baseline n={lim['n']} weeks")


def _provisional(n: int) -> str:
    return (f" [limits provisional: baseline is only {n} weeks — raise "
            f"report.lookback_weeks to extract more history; limits settle around "
            f"n>={_STABLE_N}]" if n < _STABLE_N else "")


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
    metric = "on_time" if pct else "revenue"
    # The baseline size travels with EVERY signal, not just the weak ones - a
    # reader weighing a control limit needs to know what it was computed from.
    provisional = _provisional(lim["n"])
    receipt = _receipt(metric, lim)

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


def evaluate_proportion(label: str, nums, dens, *, higher_is_better: bool = True) -> list[dict]:
    """Signal for the latest proportion against a p-chart of the earlier weeks.

    The control limits widen when this week's denominator is thin, so a
    2-delivery week can no longer masquerade as a signal the way it could on an
    individuals chart. Same output shape as evaluate_metric.
    """
    lim = _p_limits(nums, dens)
    if lim is None:
        return []
    provisional = _provisional(lim["n"])
    receipt = _receipt("on_time", lim)
    p, ucl, lcl = lim["p_cur"], lim["ucl"], lim["lcl"]

    def pc(x): return f"{x * 100:.1f}%"

    if p > ucl:
        tone = "good" if higher_is_better else "bad"
        return [{"tone": tone, "text": (
            f"{label} signal: {pc(p)} is ABOVE its p-chart control limits ({receipt}) — "
            f"a real shift beyond week-to-week noise, worth a specific cause.{provisional}")}]
    if p < lcl:
        tone = "bad" if higher_is_better else "good"
        return [{"tone": tone, "text": (
            f"{label} signal: {pc(p)} is BELOW its p-chart control limits ({receipt}) — "
            f"a real shift beyond week-to-week noise, worth a specific cause.{provisional}")}]
    return []


def limits_for(kpis: dict, metric: str) -> dict | None:
    """The exact limits and receipt `signals()` will quote for a metric, or None
    when there is not enough history to draw any. In the series' DISPLAY units
    (percent for on_time), with a `method` and a ready `receipt` string.

    Exists so a surface cannot draw one band and cite another. On-time gets its
    p-chart limits here too, so the dashboard band widens with a thin week exactly
    as the finding text says it does.
    """
    series = kpis.get("spc") or kpis.get("trend", {})
    if metric == "on_time" and series.get("on_time_num") and series.get("on_time_den"):
        lim = _p_limits(series["on_time_num"], series["on_time_den"])
        if lim is None:
            return None
        out = {"method": "p", "cl": lim["cl"] * 100, "ucl": lim["ucl"] * 100,
               "lcl": lim["lcl"] * 100, "mr_bar": lim["sigma"] * 100,
               "n": lim["n"], "n_cur": lim["n_cur"]}
        out["receipt"] = _receipt(metric, lim)
        return out
    clean = [float(v) for v in series.get(metric, []) if v == v]
    if len(clean) < _MIN_POINTS:
        return None
    lim = _limits(clean[:-1])
    if not lim["mr_bar"]:
        return None
    lim["receipt"] = _receipt(metric, lim)
    return lim


def signals(kpis: dict) -> list[dict]:
    """SPC findings for revenue (XmR) and on-time % (p-chart).

    Reads the `spc` window (every completed week the extraction holds, capped),
    falling back to the 13-week chart series for callers that predate it.
    """
    series = kpis.get("spc") or kpis.get("trend", {})
    out: list[dict] = []
    out += evaluate_metric("Revenue", series.get("revenue", []))
    nums, dens = series.get("on_time_num"), series.get("on_time_den")
    if nums and dens:
        out += evaluate_proportion("On-time shipping", nums, dens)
    else:                                   # old callers without the p-chart inputs
        out += evaluate_metric("On-time shipping", series.get("on_time", []), pct=True)
    return out
