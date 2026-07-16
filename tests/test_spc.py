"""XmR control-chart signals: a genuine shift is flagged with its arithmetic,
noise is not, and short/flat series stay silent."""

from __future__ import annotations

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
