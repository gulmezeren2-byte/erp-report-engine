"""Self-contained HTML report: KPI cards, findings, trends, stock list,
data-quality gate, source reconciliation and the full SQL audit trail.

Rendered through Jinja2 with autoescape on, so every value that originates in
the ERP (customer and region names, item codes, the profile's SQL, data-quality
text) is HTML-escaped by default. A customer literally named ``<script>...``
cannot execute in the manager's browser, and a query containing ``a < b`` no
longer breaks the audit table. Only our own matplotlib SVG charts - which carry
no ERP-sourced text - are marked safe.
"""

from __future__ import annotations

import datetime as dt
import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from jinja2 import Environment, select_autoescape  # noqa: E402
from markupsafe import Markup  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, AQUA, GOOD, RED = "#2a78d6", "#1baf7a", "#006300", "#d03b3b"
TONE = {"good": GOOD, "bad": RED, "warn": "#9a6a00"}
ICON = {"good": "▲", "bad": "▼", "warn": "⚠"}


def _svg_line(weeks, values, title, color, pct=False) -> str:
    fig, ax = plt.subplots(figsize=(6.4, 2.5))
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    xs = range(len(weeks))
    ax.plot(xs, values, color=color, linewidth=2, marker="o", markersize=4)
    ax.set_xticks(list(xs)[::2], [w.split("-")[1] for w in weeks][::2], fontsize=8)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_title(title, fontsize=11, loc="left", color=INK)
    if pct:
        vals = [v for v in values if v == v]
        if vals:
            ax.set_ylim(min(min(vals) - 2, 90), 101)
    buf = io.StringIO()
    fig.tight_layout()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    return buf.getvalue()


_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ company_alias }} — Weekly ERP Report {{ this_week }}</title>
<style>
 body{margin:0;background:#f9f9f7;color:#0b0b0b;font-family:'Segoe UI',system-ui,sans-serif}
 .wrap{max-width:920px;margin:0 auto;padding:28px 20px 40px}
 h1{font-size:22px;margin:0} .sub{color:#52514e;font-size:13px;margin-top:4px}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:20px 0}
 .card{background:#fcfcfb;border:1px solid rgba(11,11,11,.08);border-radius:10px;padding:14px 16px}
 .lbl{font-size:12px;color:#898781} .val{font-size:24px;font-weight:650;margin:2px 0} .delta{font-size:12px}
 .streak{color:#d03b3b;font-weight:600}
 h2{font-size:15px;margin:24px 0 10px}
 ul.f{list-style:none;padding:0;margin:0}
 ul.f li{background:#fcfcfb;border:1px solid rgba(11,11,11,.06);border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:14px;line-height:1.45}
 .charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
 .chart{background:#fcfcfb;border:1px solid rgba(11,11,11,.06);border-radius:10px;padding:8px;overflow-x:auto}
 svg{max-width:100%;height:auto}
 table{border-collapse:collapse;font-size:12.5px;background:#fcfcfb;border-radius:8px;width:100%}
 th,td{padding:6px 12px;border-bottom:1px solid #e1e0d9;text-align:left} th{color:#52514e}
 td.sql{font-family:Consolas,monospace;font-size:11px;color:#52514e;white-space:pre-wrap}
 .dim{color:#898781;font-size:12px}
 details{margin-top:8px} summary{cursor:pointer;color:#52514e;font-size:13px}
 .narrative{background:#f3f7ff;border:1px solid #d6e0f5;border-left:4px solid #2a78d6;border-radius:10px;padding:15px 18px;margin:20px 0}
 .narrative .ntag{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#2a78d6;font-weight:700}
 .narrative .ntext{font-size:15px;line-height:1.55;margin:8px 0 0}
 .narrative .ndisc{font-size:12px;color:#898781;margin-top:10px}
 .narrative pre{font-family:Consolas,monospace;font-size:11px;background:#fcfcfb;border:1px solid #e1e0d9;border-radius:6px;padding:10px;white-space:pre-wrap;color:#52514e;max-height:300px;overflow:auto;margin-top:8px}
 footer{margin-top:28px;color:#898781;font-size:12px}
</style></head><body><div class="wrap">
<h1>{{ company_alias }} — Weekly ERP Report</h1>
<div class="sub">Week {{ this_week }} · generated {{ generated }} · profile: {{ profile_name }} · read-only · fully automated</div>
{% if streak >= 2 %}<p class="streak">⚠ Revenue has declined {{ streak }} consecutive weeks (run-state memory).</p>{% endif %}
{% if narr %}<div class="narrative"><div class="ntag">AI executive summary</div>
<div class="ntext">{{ narr.summary }}</div>
<div class="ndisc">Written by <b>{{ narr.model }}</b> from the aggregates below — <b>never raw data</b>. This is unverified model text; check it against the figures in the report.</div>
<details><summary>What the model saw — the exact payload (aggregates only)</summary><pre>{{ narr.payload_json }}</pre></details></div>{% endif %}
<div class="cards">{% for c in cards %}<div class="card"><div class="lbl">{{ c.label }}</div><div class="val">{{ c.value }}</div><div class="delta" style="color:{{ c.color }}">{{ c.delta }}</div></div>{% endfor %}</div>
<h2>What changed, and where to look</h2>
<ul class="f">{% for f in findings %}<li style="border-left:3px solid {{ f.color }}"><b style="color:{{ f.color }}">{{ f.icon }}</b> {{ f.text }}</li>{% endfor %}</ul>
<h2>Trends</h2>
<div class="charts"><div class="chart">{{ chart_rev }}</div><div class="chart">{{ chart_otp }}</div></div>
<h2>Stock attention list</h2>
<table><tr><th>Item</th><th>Stock</th><th>Cover (weeks)</th></tr>{% for x in low_cover %}<tr><td>{{ x.item_code }}</td><td>{{ x.stock_qty }}</td><td>{{ x.cover_weeks }}</td></tr>{% else %}<tr><td colspan="3">none</td></tr>{% endfor %}</table>
{% if aging %}<h2>Receivables aging</h2>
<div class="sub">{{ aging.total }} open across {{ aging.n_invoices }} invoices · <b style="color:{{ aging.color }}">{{ aging.overdue_pct }}% overdue</b> ({{ aging.overdue }}) · {{ aging.over90_pct }}% is 90+ days</div>
<table style="margin-top:8px"><tr><th>Days past due</th><th>Amount</th><th>Share</th></tr>{% for b in aging.buckets %}<tr><td>{{ b.label }}</td><td>{{ b.amount }}</td><td>{{ b.pct }}%</td></tr>{% endfor %}</table>
{% if aging.top_overdue %}<details><summary>Top overdue customers</summary>
<table><tr><th>Customer</th><th>Overdue balance</th></tr>{% for t in aging.top_overdue %}<tr><td>{{ t.customer }}</td><td>{{ t.amount }}</td></tr>{% endfor %}</table></details>{% endif %}{% endif %}
<h2 class="dim">Data quality gate</h2>
<ul class="dim">{% for i in dq %}<li>{{ i }}</li>{% else %}<li>All input checks passed.</li>{% endfor %}</ul>
<h2 class="dim">Source reconciliation</h2>
<table><tr><th>Entity</th><th>Fetched</th><th>Source count</th><th></th></tr>{% for e in recon %}<tr><td>{{ e.entity }}</td><td>{{ e.fetched }}</td><td>{{ e.source_count }}</td><td>{{ "✓" if e.ok else "✗ MISMATCH" }}</td></tr>{% endfor %}</table>
<details><summary>SQL audit trail ({{ audit|length }} statements, all read-only)</summary>
<table><tr><th>Label</th><th>Statement</th><th>Rows</th><th>Time</th></tr>{% for a in audit %}<tr><td>{{ a.label }}</td><td class="sql">{{ a.sql }}</td><td>{{ a.rows }}</td><td>{{ a.seconds }}s</td></tr>{% endfor %}</table></details>
<footer>erp-report-engine · designed by Eren Gülmez · definitions: revenue = sum(net_total) by ISO week of order date;
on-time = shipped ≤ promised (order level; completeness not asserted — see README); cover = stock / 8-week avg weekly demand.</footer>
</div></body></html>"""

_ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_REPORT = _ENV.from_string(_TEMPLATE)


def render(cfg, profile, kpis, findings, extraction, auditor, streak, narrative=None) -> str:
    r, c, s = kpis["revenue"], kpis["orders"], kpis["on_time_pct"]

    narr = None
    if narrative:
        narr = {"summary": narrative["summary"], "model": narrative["model"],
                "payload_json": json.dumps(narrative["payload"], ensure_ascii=False, indent=2)}

    def fmt_delta(d, unit=""):
        if d["prev"] != d["prev"] or not d["prev"]:
            return "—"
        pct = (d["now"] / d["prev"] - 1) * 100
        return f"{pct:+.1f}% vs prev · baseline {d['baseline8']:,.0f}{unit}"

    def _otp_delta(d):
        base = f"{(d['now'] - d['prev']):+.1f} pts vs prev" if d["prev"] == d["prev"] else "—"
        delivered, scored = d.get("delivered", 0), d.get("scored", 0)
        if delivered and scored < delivered:
            base += f" · {scored}/{delivered} scored"
        return base

    cards = [
        {"label": "Revenue", "value": f"{r['now']:,.0f}", "delta": fmt_delta(r),
         "color": GOOD if r["now"] >= (r["prev"] or 0) else RED},
        {"label": "Orders", "value": f"{c['now']:,.0f}", "delta": fmt_delta(c),
         "color": GOOD if c["now"] >= (c["prev"] or 0) else RED},
        {"label": "On-time shipping",
         "value": f"{s['now']:.1f}%" if s["now"] == s["now"] else "n/a",
         "delta": _otp_delta(s),
         "color": GOOD if (s["now"] or 0) >= (s["prev"] or 0) else RED},
        {"label": "Items low on stock", "value": f"{kpis['n_low_cover']}",
         "delta": f"< {cfg.low_cover_weeks:g} weeks cover",
         "color": GOOD if kpis["n_low_cover"] == 0 else RED},
    ]

    find_ctx = [
        {"tone": f["tone"], "icon": ICON[f["tone"]], "color": TONE[f["tone"]], "text": f["text"]}
        for f in findings
    ]

    low_cover = [
        {"item_code": x["item_code"], "stock_qty": f"{x['stock_qty']:,.0f}", "cover_weeks": x["cover_weeks"]}
        for x in kpis["low_cover"]
    ]

    recon = [
        {"entity": e, "fetched": f"{v['fetched']:,}", "source_count": f"{v['source_count']:,}",
         "ok": v["fetched"] == v["source_count"]}
        for e, v in extraction.reconciliation.items()
    ]

    audit = [
        {"label": a.label, "sql": a.sql[:180], "rows": f"{a.rows:,}", "seconds": a.seconds}
        for a in auditor.entries
    ]

    aging = kpis.get("aging")
    aging_ctx = None
    if aging:
        _label = {"current": "Current (not due)", "1-30": "1–30 days", "31-60": "31–60 days",
                  "61-90": "61–90 days", "90+": "90+ days"}
        aging_ctx = {
            "total": f"{aging['total']:,.0f}", "overdue": f"{aging['overdue']:,.0f}",
            "overdue_pct": aging["overdue_pct"], "over90_pct": aging["over90_pct"],
            "n_invoices": f"{aging['n_invoices']:,}",
            "color": RED if aging["overdue_pct"] >= 40 else (TONE["warn"] if aging["overdue_pct"] >= 20 else GOOD),
            "buckets": [{"label": _label.get(b["bucket"], b["bucket"]),
                         "amount": f"{b['amount']:,.0f}", "pct": b["pct"]} for b in aging["buckets"]],
            "top_overdue": [{"customer": t["customer"], "amount": f"{t['amount']:,.0f}"}
                            for t in aging["top_overdue"]],
        }

    n_weeks = len(kpis["trend"]["weeks"])
    chart_rev = _svg_line(kpis["trend"]["weeks"], kpis["trend"]["revenue"],
                          f"Weekly revenue (last {n_weeks} weeks)", BLUE)
    chart_otp = _svg_line(kpis["trend"]["weeks"], kpis["trend"]["on_time"],
                          f"On-time shipping % (last {n_weeks} weeks)", AQUA, pct=True)

    return _REPORT.render(
        company_alias=cfg.company_alias,
        this_week=kpis["this_week"],
        generated=f"{dt.datetime.now():%Y-%m-%d %H:%M}",
        profile_name=profile.name,
        streak=streak,
        cards=cards,
        narr=narr,
        findings=find_ctx,
        chart_rev=Markup(chart_rev),
        chart_otp=Markup(chart_otp),
        low_cover=low_cover,
        aging=aging_ctx,
        dq=list(extraction.issues),
        recon=recon,
        audit=audit,
    )
