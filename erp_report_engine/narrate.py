"""Optional LLM narrative — an executive summary generated from AGGREGATES ONLY.

Honesty by construction: the model never sees a raw row. The payload is built
from the already-computed KPIs, findings and honesty artifacts (never from the
extracted frames), and the report prints that exact payload as a "what the model
saw" appendix, so a reader can verify the model was fed only audited aggregates.
If no endpoint/key is configured the whole feature no-ops and the report is
unchanged — the engine works with or without an LLM.

"Aggregates only" is necessary but it is not the same as "nothing identifiable".
An aggregate can still name a party: the top overdue balances are customer names
and amounts, and a driver finding names the account behind the move. For a firm
that treats its debtor list as confidential, "we only send aggregates" would be a
technically true sentence doing dishonest work — the endpoint is very often a
third party. So names are PSEUDONYMISED by default (`<name-1>`, stable within a
run, so the model can still tell two accounts apart and say something useful),
and `narrative.include_names: true` is an explicit, opt-in decision. The payload
appendix makes either choice auditable rather than assumed.

Transport is an OpenAI-compatible Chat Completions POST over stdlib urllib, so it
works with OpenAI, OpenRouter, or a local, keyless server (Ollama / LM Studio /
llama.cpp) by setting `narrative.api_base`. No new dependency.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
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


def _pseudonymiser():
    """Stable `<name-N>` labels, assigned in order of first appearance.

    Numbered rather than blanked so the summary can still distinguish two
    accounts - "<name-1> grew while <name-2> churned" is a useful sentence that
    identifies nobody.
    """
    seen: dict[str, str] = {}

    def sub(value: str) -> str:
        value = str(value)
        if value not in seen:
            seen[value] = f"<name-{len(seen) + 1}>"
        return seen[value]

    return sub


def build_payload(cfg, kpis: dict, findings: list[dict], extraction,
                  *, include_names: bool = False) -> dict:
    """The exact object sent to the model. By construction it is built from
    KPIs/findings/DQ - NOT from extraction.frames - so no raw ERP row can leak
    into the prompt; and unless `include_names`, every customer and item it does
    carry is pseudonymised first."""
    r, o, s = kpis["revenue"], kpis["orders"], kpis["on_time_pct"]
    sub = _pseudonymiser()

    def clean(text: str, names: list) -> str:
        if include_names:
            return text
        # longest first, so a name that contains another is replaced whole
        for n in sorted({str(x) for x in names}, key=len, reverse=True):
            text = text.replace(n, sub(n))
        return text

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
                        "scored": s.get("scored"), "delivered": s.get("delivered"),
                        "promised_unshipped": s.get("promised_unshipped")},
        "items_below_cover": kpis["n_low_cover"],
        "findings": [clean(f["text"], f.get("names", [])) for f in findings],
        "data_quality_issues": list(extraction.issues),
        "names_included": bool(include_names),
    }
    c = kpis.get("concentration")
    if c:
        payload["revenue_concentration"] = {
            "top3_pct": c["top3_pct"], "hhi": c["hhi"], "n_customers": c["n_customers"]}
    a = kpis.get("aging")
    if a:
        payload["receivables_aging"] = {
            "total": a["total"], "overdue_pct": a["overdue_pct"], "over90_pct": a["over90_pct"],
            "top_overdue": [{"customer": t["customer"] if include_names else sub(t["customer"]),
                             "amount": t["amount"]}
                            for t in a["top_overdue"][:3]],
        }
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects.

    The request carries an Authorization header and a week of company figures.
    urllib follows redirects by default, so a compromised or merely careless
    endpoint could bounce both to a host the operator never configured - and the
    operator would see a working report and never know. The endpoint they wrote
    in the config is the endpoint that gets the data, or nothing does.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code,
            f"narrative endpoint tried to redirect to {newurl!r}; refusing to "
            f"forward the payload or the API key to a host that is not the one "
            f"configured", headers, fp)


def _complete(api_base: str, model: str, key: str | None, payload: dict, timeout: int) -> str:
    url = api_base.rstrip("/") + "/chat/completions"
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"narrative.api_base must be http(s), got {scheme!r}")
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
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked above
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

    payload = build_payload(cfg, kpis, findings, extraction,
                            include_names=bool(n.get("include_names", False)))
    try:
        summary = _complete(api_base, model, key, payload, int(n.get("timeout_s", 30)))
    except Exception as e:  # noqa: BLE001 - the narrative is a nice-to-have, never fatal
        _log.warning("narrative generation failed (%s) - report written without it",
                     type(e).__name__)
        return None
    return {"summary": summary, "model": model, "api_base": api_base, "payload": payload}
