"""The report is rendered from untrusted ERP content, so it must escape it.

A customer, region, or item literally named ``<script>...`` reaches the report
via findings, the stock list, the data-quality gate, and the SQL audit trail.
None of it may execute in the browser of whoever opens Monday's report.
"""

from __future__ import annotations

from types import SimpleNamespace

from erp_report_engine.render import render

_WOW = {"now": 100.0, "prev": 90.0, "baseline8": 95.0}


def _kpis():
    return {
        "this_week": "2026-W28",
        "revenue": _WOW, "orders": _WOW,
        "on_time_pct": {"now": 88.0, "prev": 90.0, "baseline8": 89.0},
        "n_low_cover": 1,
        "low_cover": [{"item_code": "<img src=x onerror=alert(1)>", "stock_qty": 5.0, "cover_weeks": 1.2}],
        "trend": {"weeks": ["2026-W27", "2026-W28"], "revenue": [90.0, 100.0], "on_time": [90.0, 88.0]},
    }


def test_report_escapes_untrusted_erp_content():
    cfg = SimpleNamespace(company_alias="<b>ACME</b>", low_cover_weeks=2.0)
    profile = SimpleNamespace(name="generic")
    findings = [{"tone": "good", "text": "<script>alert('xss')</script> revenue up in region 'Ege'"}]
    extraction = SimpleNamespace(
        issues=["orders: <script>bad</script> flagged"],
        reconciliation={"orders": {"fetched": 10, "source_count": 10}},
    )
    auditor = SimpleNamespace(entries=[
        SimpleNamespace(label="orders", sql="SELECT * FROM t WHERE a < 5 AND name = '<x>'", rows=10, seconds=0.01),
    ])

    html = render(cfg, profile, _kpis(), findings, extraction, auditor, streak=0)

    # no raw, executable markup survives anywhere in the document
    assert "<script>alert" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<b>ACME</b>" not in html
    # the escaped forms are what actually render
    assert "&lt;script&gt;alert" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "&lt;b&gt;ACME&lt;/b&gt;" in html
    # a '<' inside audited SQL is escaped rather than breaking the table cell
    assert "a &lt; 5" in html
