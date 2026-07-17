"""The optional LLM narrative is honest by construction: the model is fed ONLY
aggregates (never a raw row), the call never crashes the run, and the report
prints the exact payload the model saw."""

from __future__ import annotations

import json
from types import SimpleNamespace

from erp_report_engine import narrate

_WOW = {"now": 100.0, "prev": 90.0, "baseline8": 95.0}


def _kpis():
    return {
        "this_week": "2026-W28", "prev_week": "2026-W27",
        "revenue": _WOW, "orders": _WOW,
        "on_time_pct": {"now": 88.0, "prev": 90.0, "baseline8": 89.0, "scored": 8, "delivered": 10},
        "n_low_cover": 2,
        "low_cover": [{"item_code": "ITM-1", "stock_qty": 5.0, "cover_weeks": 1.2}],
        "trend": {"weeks": ["2026-W27", "2026-W28"], "revenue": [90.0, 100.0], "on_time": [90.0, 88.0]},
        "concentration": {"top3_pct": 55.0, "hhi": 1800, "n_customers": 12,
                          "top": [{"customer": "C1", "pct": 30.0}]},
        "aging": {"total": 100000.0, "overdue": 60000.0, "overdue_pct": 60.0,
                  "over90": 12000.0, "over90_pct": 12.0, "n_invoices": 42,
                  "buckets": [{"bucket": b, "amount": 20000.0, "pct": 20.0}
                              for b in ("current", "1-30", "31-60", "61-90", "91+")],
                  "top_overdue": [{"customer": "C1", "amount": 5000.0}]},
        "_dims": {"orders_frame": "SENTINEL_DIMS_MUST_NOT_LEAK"},
    }


def test_payload_is_aggregates_only_no_raw_rows():
    import pandas as pd
    cfg = SimpleNamespace(company_alias="ACME")
    frames = {"orders": pd.DataFrame([{"order_id": "SO-SECRET-999", "customer": "RAW_CUSTOMER_LEAK"}])}
    extraction = SimpleNamespace(issues=["orders: 1 note"], frames=frames)

    payload = narrate.build_payload(cfg, _kpis(), [{"tone": "good", "text": "Revenue up in Ege"}], extraction)
    blob = json.dumps(payload)

    # neither the raw extracted frame nor the internal _dims frame can reach the model
    assert "SO-SECRET-999" not in blob and "RAW_CUSTOMER_LEAK" not in blob
    assert "SENTINEL_DIMS_MUST_NOT_LEAK" not in blob and "_dims" not in payload
    # the aggregates ARE present
    assert payload["week"] == "2026-W28" and payload["revenue"]["this_week"] == 100
    assert payload["receivables_aging"]["overdue_pct"] == 60.0
    assert payload["revenue_concentration"]["top3_pct"] == 55.0
    assert payload["findings"] == ["Revenue up in Ege"]


def test_narrate_posts_aggregates_and_returns_summary(monkeypatch):
    captured = {}

    def fake_complete(api_base, model, key, payload, timeout):
        captured.update(api_base=api_base, model=model, key=key, payload=payload)
        return "Revenue rose to 100. Chase overdue receivables."

    monkeypatch.setattr(narrate, "_complete", fake_complete)
    monkeypatch.setenv("TEST_LLM_KEY", "sk-secret")
    cfg = SimpleNamespace(company_alias="ACME", narrative={
        "api_base": "https://api.example/v1", "model": "m1", "api_key_env": "TEST_LLM_KEY"})

    res = narrate.narrate(cfg, _kpis(), [{"tone": "good", "text": "Revenue up"}],
                          SimpleNamespace(issues=[], frames={}))
    assert res["summary"].startswith("Revenue rose")
    assert res["model"] == "m1" and captured["key"] == "sk-secret"
    assert res["payload"]["revenue"]["this_week"] == 100
    assert "SENTINEL" not in json.dumps(captured["payload"])       # only aggregates were sent


def test_narrate_none_when_unconfigured():
    cfg = SimpleNamespace(company_alias="ACME", narrative=None)
    assert narrate.narrate(cfg, _kpis(), [], SimpleNamespace(issues=[], frames={})) is None


def test_narrate_local_keyless_endpoint_needs_no_api_key(monkeypatch):
    monkeypatch.setattr(narrate, "_complete", lambda *a, **k: "ok summary")
    cfg = SimpleNamespace(company_alias="ACME", narrative={
        "api_base": "http://localhost:11434/v1", "model": "llama"})   # local, no key
    res = narrate.narrate(cfg, _kpis(), [], SimpleNamespace(issues=[], frames={}))
    assert res and res["summary"] == "ok summary"


def test_narrate_survives_endpoint_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(narrate, "_complete", boom)
    cfg = SimpleNamespace(company_alias="ACME", narrative={"api_base": "http://localhost:11434/v1", "model": "x"})
    assert narrate.narrate(cfg, _kpis(), [], SimpleNamespace(issues=[], frames={})) is None


def test_render_shows_narrative_and_the_exact_payload():
    from erp_report_engine.render import render
    cfg = SimpleNamespace(company_alias="ACME", low_cover_weeks=2.0)
    profile = SimpleNamespace(name="generic")
    extraction = SimpleNamespace(issues=[], reconciliation={"orders": {"fetched": 1, "source_count": 1}})
    auditor = SimpleNamespace(entries=[SimpleNamespace(label="orders", sql="SELECT 1", rows=1, seconds=0.01)])
    narrative = {"summary": "Revenue rose to 100 this week; watch the 90+ receivables.",
                 "model": "gpt-4o-mini", "payload": {"week": "2026-W28", "revenue": {"this_week": 100}}}

    html = render(cfg, profile, _kpis(), [], extraction, auditor, streak=0, narrative=narrative)

    assert "AI executive summary" in html
    assert "Revenue rose to 100 this week; watch the 90+ receivables." in html
    assert "What the model saw" in html and "gpt-4o-mini" in html
    # the exact payload is shown (autoescaped in the HTML source; the browser un-escapes it)
    assert "this_week" in html and "&#34;week&#34;: &#34;2026-W28&#34;" in html
