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


def test_dashboard_uses_only_validated_palette_steps():
    """The validated palette's whole value is that THOSE steps cleared the
    colour-vision gates. Six of the eight had drifted into brightened
    approximations while the docstring still claimed validation - so pin the
    steps, including the copies hand-written into the CSS, where they drifted.

    Validator run for this exact set against this dashboard's plane (#0b0d10) is
    recorded in render_dashboard's module docstring: ALL CHECKS PASS.
    """
    import re
    from pathlib import Path

    from erp_report_engine import render_dashboard as rd

    # skill-validated dark categorical steps + the fixed status palette
    validated = {"#3987e5", "#008300", "#d55181", "#c98500",     # slots 1-4
                 "#199e70", "#d95926", "#9085e9", "#e66767",     # slots 5-8
                 "#0ca30c", "#fab219", "#ec835a", "#d03b3b"}     # good/warning/serious/critical
    for name in ("BLUE", "MAGENTA", "AQUA", "VIOLET", "GOOD", "WARN", "SERIOUS", "CRIT"):
        assert getattr(rd, name) in validated, f"{name}={getattr(rd, name)} is not a validated step"

    # Chrome the palette does not govern, because none of it encodes a value:
    # the plane, the ink/grid greys, the near-white gradient stop in the title,
    # and the three background orbs - heavily blurred glows at 0.36-0.5 opacity
    # behind everything. The line is data marks, not decoration; if one of these
    # ever carries a number, it belongs in `validated` instead.
    chrome = {rd.PLANE, rd.INK, rd.INK2, rd.MUTED, rd.GRID, rd.AXIS,
              "#ffffff", "#c7d6f0",                      # title gradient stops
              "#1d4ed8", "#0e7490", "#6d28d9"}           # decorative orbs a/b/c
    source = Path(rd.__file__).read_text(encoding="utf-8")
    # ignore the docstring, which quotes the full validated palette by design
    body = source.split('"""', 2)[2]
    stray = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", body)} - validated - chrome
    assert not stray, f"unvalidated colours hard-coded in render_dashboard: {sorted(stray)}"
