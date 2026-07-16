"""Optional LLM narrative — an executive summary generated from AGGREGATES ONLY.

Honesty by construction: the model never sees a raw row. The payload is built
from the already-computed KPIs, findings and honesty artifacts (never from the
extracted frames), and the report prints that exact payload as a "what the model
saw" appendix, so a reader can verify the model was fed only audited aggregates.
If no endpoint/key is configured the whole feature no-ops and the report is
unchanged — the engine works with or without an LLM.

Transport is an OpenAI-compatible Chat Completions POST over stdlib urllib, so it
works with OpenAI, OpenRouter, or a local, keyless server (Ollama / LM Studio /
llama.cpp) by setting `narrative.api_base`. No new dependency.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

_log = logging.getLogger("erp_report_engine")

SYSTEM_PROMPT = (
    "You are an operations analyst writing for a busy manager. You are given "
    "ONLY pre-aggregated, already-audited weekly figures for one company - never "
    "raw records. Write a short executive summary (4-6 sentences): what changed "
    "this week, what needs a decision, and what to watch. Use ONLY the numbers "
    "provided; never invent, estimate, or extrapolate a figure that is not in the "
    "data. Plain, direct language - no preamble, no bullet lists."
)


def _num(v) -> float | int | None:
    """Round a KPI value; NaN (missing week) becomes null in the payload."""
    return round(float(v)) if v == v and v is not None else None


def build_payload(cfg, kpis: dict, findings: list[dict], extraction) -> dict:
    """The exact, aggregates-only object sent to the model. By construction it is
    built from KPIs/findings/DQ - NOT from extraction.frames - so no raw ERP row
    can leak into the prompt."""
    r, o, s = kpis["revenue"], kpis["orders"], kpis["on_time_pct"]
    payload: dict = {
        "company": cfg.company_alias,
        "week": kpis["this_week"],
        "prev_week": kpis["prev_week"],
        "revenue": {"this_week": _num(r["now"]), "prev_week": _num(r["prev"]),
                    "baseline_8wk": _num(r["baseline8"])},
        "orders": {"this_week": _num(o["now"]), "prev_week": _num(o["prev"]),
                   "baseline_8wk": _num(o["baseline8"])},
        "on_time_pct": {"this_week": round(s["now"], 1) if s["now"] == s["now"] else None,
                        "prev_week": round(s["prev"], 1) if s["prev"] == s["prev"] else None,
                        "scored": s.get("scored"), "delivered": s.get("delivered")},
        "items_below_cover": kpis["n_low_cover"],
        "findings": [f["text"] for f in findings],
        "data_quality_issues": list(extraction.issues),
    }
    c = kpis.get("concentration")
    if c:
        payload["revenue_concentration"] = {
            "top3_pct": c["top3_pct"], "hhi": c["hhi"], "n_customers": c["n_customers"]}
    a = kpis.get("aging")
    if a:
        payload["receivables_aging"] = {
            "total": a["total"], "overdue_pct": a["overdue_pct"],
            "over90_pct": a["over90_pct"], "top_overdue": a["top_overdue"][:3]}
    return payload


def _complete(api_base: str, model: str, key: str | None, payload: dict, timeout: int) -> str:
    body = {
        "model": model, "temperature": 0.2, "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Weekly figures (JSON):\n"
             + json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(api_base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configured endpoint
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def narrate(cfg, kpis: dict, findings: list[dict], extraction) -> dict | None:
    """Return {summary, model, api_base, payload} or None. Never raises: a
    failed or unconfigured LLM call logs and returns None so the report still
    writes (an unattended run must not die because an API was down)."""
    n = getattr(cfg, "narrative", None) or {}
    api_base = n.get("api_base") or "https://api.openai.com/v1"
    model = n.get("model") or "gpt-4o-mini"
    key = os.environ.get(n["api_key_env"]) if n.get("api_key_env") else None
    if not key and not n.get("api_base"):
        _log.warning("narrative requested but no api_key_env is set and no local "
                     "api_base configured - skipping (report unaffected)")
        return None

    payload = build_payload(cfg, kpis, findings, extraction)
    try:
        summary = _complete(api_base, model, key, payload, int(n.get("timeout_s", 30)))
    except Exception as e:  # noqa: BLE001 - the narrative is a nice-to-have, never fatal
        _log.warning("narrative generation failed (%s) - report written without it",
                     type(e).__name__)
        return None
    return {"summary": summary, "model": model, "api_base": api_base, "payload": payload}
