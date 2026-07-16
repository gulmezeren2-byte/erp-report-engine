"""The premium dashboard renders from RunResult data and, like the standard
report, escapes untrusted ERP text (it is built from the same inputs)."""

from __future__ import annotations

from types import SimpleNamespace

from erp_report_engine.render_dashboard import render

_WOW = {"now": 100.0, "prev": 90.0, "baseline8": 95.0}


def _kpis():
    return {
        "this_week": "2026-W28", "prev_week": "2026-W27",
        "revenue": _WOW, "orders": _WOW,
        "on_time_pct": {"now": 88.0, "prev": 90.0, "baseline8": 89.0, "scored": 8, "delivered": 10},
        "n_low_cover": 1,
        "low_cover": [{"item_code": "<img src=x onerror=alert(1)>", "stock_qty": 5.0, "cover_weeks": 1.2}],
        "trend": {"weeks": [f"2026-W{w}" for w in range(16, 29)],
                  "revenue": [90.0, 92, 88, 95, 91, 97, 93, 99, 90, 101, 94, 100, 148],
                  "on_time": [90.0, 91, 89, 90, 90, 91, 90, 92, 89, 93, 90, 91, 88]},
    }


def test_dashboard_renders_and_escapes_untrusted_text():
    cfg = SimpleNamespace(company_alias="<b>ACME</b>", low_cover_weeks=2.0)
    profile = SimpleNamespace(name="generic")
    findings = [{"tone": "warn", "text": "<script>alert('xss')</script> Ege spike"}]
    extraction = SimpleNamespace(
        issues=["orders: 1 note"],
        reconciliation={"orders": {"fetched": 10, "source_count": 10}},
    )
    auditor = SimpleNamespace(entries=[SimpleNamespace(label="orders", sql="SELECT 1", rows=10, seconds=0.01)])

    html = render(cfg, profile, _kpis(), findings, extraction, auditor, streak=0)

    assert "Command Center" in html and "2026-W28" in html
    assert "88.0%" in html                              # the on-time KPI value renders
    # untrusted content is escaped, not executable
    assert "<script>alert" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<b>ACME</b>" not in html
    assert "&lt;script&gt;alert" in html
