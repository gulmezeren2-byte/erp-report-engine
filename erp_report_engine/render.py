"""Self-contained HTML report: KPI cards, findings, trends, stock list,
data-quality gate, source reconciliation and the full SQL audit trail."""

from __future__ import annotations

import datetime as dt
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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


def render(cfg, profile, kpis, findings, extraction, auditor, streak) -> str:
    tw = kpis["this_week"]
    r, c, s = kpis["revenue"], kpis["orders"], kpis["on_time_pct"]

    def card(label, value, delta, good):
        color = GOOD if good else RED
        return (
            f'<div class="card"><div class="lbl">{label}</div><div class="val">{value}</div>'
            f'<div class="delta" style="color:{color}">{delta}</div></div>'
        )

    def fmt_delta(d, unit=""):
        if d["prev"] != d["prev"] or not d["prev"]:
            return "—"
        pct = (d["now"] / d["prev"] - 1) * 100
        return f"{pct:+.1f}% vs prev · baseline {d['baseline8']:,.0f}{unit}"

    cards = "".join([
        card("Revenue", f"{r['now']:,.0f}", fmt_delta(r), r["now"] >= (r["prev"] or 0)),
        card("Orders", f"{c['now']:,.0f}", fmt_delta(c), c["now"] >= (c["prev"] or 0)),
        card("On-time shipping", f"{s['now']:.1f}%" if s["now"] == s["now"] else "n/a",
             f"{(s['now'] - s['prev']):+.1f} pts vs prev" if s["prev"] == s["prev"] else "—",
             (s["now"] or 0) >= (s["prev"] or 0)),
        card("Items low on stock", f"{kpis['n_low_cover']}",
             f"< {cfg.low_cover_weeks:.0f} weeks cover", kpis["n_low_cover"] == 0),
    ])

    streak_html = (
        f'<p class="streak">⚠ Revenue has declined {streak} consecutive weeks (run-state memory).</p>'
        if streak >= 2 else ""
    )

    bullets = "".join(
        f'<li style="border-left:3px solid {TONE[f["tone"]]}">'
        f'<b style="color:{TONE[f["tone"]]}">{ICON[f["tone"]]}</b> {f["text"]}</li>'
        for f in findings
    )

    low_rows = "".join(
        f'<tr><td>{x["item_code"]}</td><td>{x["stock_qty"]:,.0f}</td><td>{x["cover_weeks"]}</td></tr>'
        for x in kpis["low_cover"]
    ) or '<tr><td colspan="3">none</td></tr>'

    dq = "".join(f"<li>{i}</li>" for i in extraction.issues) or "<li>All input checks passed.</li>"
    recon = "".join(
        f'<tr><td>{e}</td><td>{v["fetched"]:,}</td><td>{v["source_count"]:,}</td>'
        f'<td>{"✓" if v["fetched"] == v["source_count"] else "✗ MISMATCH"}</td></tr>'
        for e, v in extraction.reconciliation.items()
    )
    audit = "".join(
        f'<tr><td>{a.label}</td><td class="sql">{a.sql[:180]}</td><td>{a.rows:,}</td><td>{a.seconds}s</td></tr>'
        for a in auditor.entries
    )

    chart_rev = _svg_line(kpis["trend"]["weeks"], kpis["trend"]["revenue"], "Weekly revenue (last 13 weeks)", BLUE)
    chart_otp = _svg_line(kpis["trend"]["weeks"], kpis["trend"]["on_time"], "On-time shipping % (last 13 weeks)", AQUA, pct=True)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{cfg.company_alias} — Weekly ERP Report {tw}</title>
<style>
 body{{margin:0;background:#f9f9f7;color:{INK};font-family:'Segoe UI',system-ui,sans-serif}}
 .wrap{{max-width:920px;margin:0 auto;padding:28px 20px 40px}}
 h1{{font-size:22px;margin:0}} .sub{{color:{INK2};font-size:13px;margin-top:4px}}
 .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:20px 0}}
 .card{{background:{SURFACE};border:1px solid rgba(11,11,11,.08);border-radius:10px;padding:14px 16px}}
 .lbl{{font-size:12px;color:{MUTED}}} .val{{font-size:24px;font-weight:650;margin:2px 0}} .delta{{font-size:12px}}
 .streak{{color:{RED};font-weight:600}}
 h2{{font-size:15px;margin:24px 0 10px}}
 ul.f{{list-style:none;padding:0;margin:0}}
 ul.f li{{background:{SURFACE};border:1px solid rgba(11,11,11,.06);border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:14px;line-height:1.45}}
 .charts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}}
 .chart{{background:{SURFACE};border:1px solid rgba(11,11,11,.06);border-radius:10px;padding:8px;overflow-x:auto}}
 svg{{max-width:100%;height:auto}}
 table{{border-collapse:collapse;font-size:12.5px;background:{SURFACE};border-radius:8px;width:100%}}
 th,td{{padding:6px 12px;border-bottom:1px solid {GRID};text-align:left}} th{{color:{INK2}}}
 td.sql{{font-family:Consolas,monospace;font-size:11px;color:{INK2}}}
 .dim{{color:{MUTED};font-size:12px}}
 details{{margin-top:8px}} summary{{cursor:pointer;color:{INK2};font-size:13px}}
 footer{{margin-top:28px;color:{MUTED};font-size:12px}}
</style></head><body><div class="wrap">
<h1>{cfg.company_alias} — Weekly ERP Report</h1>
<div class="sub">Week {tw} · generated {dt.datetime.now():%Y-%m-%d %H:%M} · profile: {profile.name} · read-only · fully automated</div>
{streak_html}
<div class="cards">{cards}</div>
<h2>What changed, and where to look</h2>
<ul class="f">{bullets}</ul>
<h2>Trends</h2>
<div class="charts"><div class="chart">{chart_rev}</div><div class="chart">{chart_otp}</div></div>
<h2>Stock attention list</h2>
<table><tr><th>Item</th><th>Stock</th><th>Cover (weeks)</th></tr>{low_rows}</table>
<h2 class="dim">Data quality gate</h2>
<ul class="dim">{dq}</ul>
<h2 class="dim">Source reconciliation</h2>
<table><tr><th>Entity</th><th>Fetched</th><th>Source count</th><th></th></tr>{recon}</table>
<details><summary>SQL audit trail ({len(auditor.entries)} statements, all read-only)</summary>
<table><tr><th>Label</th><th>Statement</th><th>Rows</th><th>Time</th></tr>{audit}</table></details>
<footer>erp-report-engine · designed by Eren Gülmez · definitions: revenue = sum(net_total) by ISO week of order date;
on-time = shipped ≤ promised (order level; completeness not asserted — see README); cover = stock / 8-week avg weekly demand.</footer>
</div></body></html>"""
