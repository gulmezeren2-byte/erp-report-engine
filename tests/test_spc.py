"""XmR control-chart signals: a genuine shift is flagged with its arithmetic,
noise is not, and short/flat series stay silent."""

from __future__ import annotations

from erp_report_engine import spc
from erp_report_engine.spc import evaluate_metric, signals


def test_spike_above_limits_is_flagged_with_its_math():
    vals = [100, 102, 98, 101, 99, 103, 100, 200]  # a clean spike after stable weeks
    out = evaluate_metric("Revenue", vals)
    assert len(out) == 1
    text = out[0]["text"]
    assert "ABOVE the control limits" in text
    # the receipt: mean, the multiplier, and the moving range are all shown
    assert "mean" in text and "2.66" in text and "moving range" in text


def test_steady_series_produces_no_signal():
    vals = [100, 102, 98, 101, 99, 103, 100]  # ordinary week-to-week wobble
    assert evaluate_metric("Revenue", vals) == []


def test_short_series_is_silent():
    assert evaluate_metric("Revenue", [100, 110, 90]) == []


def test_flat_series_is_silent():
    assert evaluate_metric("Revenue", [100, 100, 100, 100, 100, 100, 100]) == []


def test_sustained_downward_run_is_flagged():
    vals = [120, 80, 120, 80, 95, 95, 95, 95, 95, 95, 95, 95]  # 8 straight below the mean
    out = evaluate_metric("On-time shipping", vals, pct=True, higher_is_better=True)
    assert out and "straight weeks below" in out[0]["text"]


def test_signals_reads_the_trend_series():
    kpis = {"trend": {"revenue": [100, 102, 98, 101, 99, 103, 100, 200], "on_time": [90, 91, 89, 90, 90, 91, 90, 90]}}
    out = signals(kpis)
    assert any("Revenue signal" in s["text"] for s in out)


def test_on_time_uses_a_p_chart_not_xmr():
    """On-time % is a proportion: its control limits must widen with a thin
    denominator, so a 2-delivery week can't masquerade as a signal, while a real
    drop on a large sample still does. XmR (individuals) gets this wrong."""
    base_num, base_den = [90] * 20, [100] * 20   # ~90% on-time, healthy weekly n

    def sig(nums, dens):
        kpis = {"spc": {"on_time": [n / d * 100 for n, d in zip(nums, dens, strict=True)],
                        "on_time_num": nums, "on_time_den": dens, "revenue": [1000] * len(nums)}}
        return [s for s in spc.signals(kpis) if "time" in s["text"]]

    # a thin, extreme week (2 of 2 = 100%) is NOT a signal - the limits widened
    assert sig(base_num + [2], base_den + [2]) == []
    # a real collapse (60% over n=200) IS a signal, and quotes the p-chart
    hit = sig(base_num + [120], base_den + [200])
    assert hit and "p-chart" in hit[0]["text"] and "BELOW" in hit[0]["text"]


def test_p_chart_limits_and_receipt_reach_the_export_shape():
    """limits_for exposes the p-chart method + a ready receipt in percent units,
    so Power BI and the dashboard quote what the report quotes - and the UCL is
    capped at 100%, unlike an individuals chart on a proportion."""
    nums, dens = [90] * 20 + [95], [100] * 20 + [100]
    kpis = {"spc": {"on_time": [n / d * 100 for n, d in zip(nums, dens, strict=True)],
                    "on_time_num": nums, "on_time_den": dens}}
    lim = spc.limits_for(kpis, "on_time")
    assert lim["method"] == "p"
    assert lim["ucl"] <= 100.0 and lim["lcl"] >= 0.0      # a proportion stays in [0,100]
    assert "sqrt(p(1-p)/n)" in lim["receipt"] and "scored this week" in lim["receipt"]
