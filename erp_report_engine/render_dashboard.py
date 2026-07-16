"""Premium 'executive command center' report - a dark, modern, bento-grid
dashboard rendered from the same RunResult data as the standard report.

Self-contained (inline CSS + hand-authored SVG, no external assets), rendered
through Jinja2 autoescape so ERP-sourced text is safe. The charts carry the SPC
control band so 'signal vs noise' is visible at a glance. Colors are the
data-viz skill's validated dark palette; the glass/glow is decorative chrome
over those hues.
"""

from __future__ import annotations

import datetime as dt
import html

from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from . import spc

# validated dark palette (data-viz skill) + futuristic accents
PLANE = "#0b0d10"
INK, INK2, MUTED, GRID, AXIS = "#f4f6f8", "#aab3bd", "#7d8590", "#20242b", "#333a44"
BLUE, AQUA, VIOLET, MAGENTA = "#3f8ef5", "#22c197", "#9a8cf0", "#e07bab"
GOOD, WARN, SERIOUS, CRIT = "#28c76f", "#fab219", "#ec835a", "#f0524d"
TONE = {"good": GOOD, "bad": CRIT, "warn": WARN}
ICON = {"good": "▲", "bad": "▼", "warn": "◆"}


def _nums(values: list[float]) -> list[float]:
    return [v for v in values if v == v]


def _area_chart(weeks: list[str], values: list[float], color: str, *,
                width: int = 520, height: int = 150, pct: bool = False, band: dict | None = None) -> str:
    """Hand-authored SVG area chart with a gradient fill, a glowing line, and an
    optional SPC control band (mean ± limits) drawn behind the series."""
    pad_l, pad_r, pad_t, pad_b = 8, 8, 14, 18
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    pts = list(enumerate(values))
    real = _nums(values)
    if not real:
        return f'<svg viewBox="0 0 {width} {height}" width="100%"></svg>'

    lo, hi = min(real), max(real)
    if band:
        lo = min(lo, band["lcl"])
        hi = max(hi, band["ucl"])
    span = (hi - lo) or 1.0
    lo -= span * 0.12
    hi += span * 0.12
    span = hi - lo

    def x(i: int) -> float:
        return pad_l + (iw * i / max(1, len(values) - 1))

    def y(v: float) -> float:
        return pad_t + ih * (1 - (v - lo) / span)

    uid = f"g{abs(hash((tuple(weeks), color))) % 100000}"
    line_pts = [(x(i), y(v)) for i, v in pts if v == v]
    line = " ".join(f"{px:.1f},{py:.1f}" for px, py in line_pts)
    area = (f"M {line_pts[0][0]:.1f},{height - pad_b:.1f} "
            + " ".join(f"L {px:.1f},{py:.1f}" for px, py in line_pts)
            + f" L {line_pts[-1][0]:.1f},{height - pad_b:.1f} Z")

    band_svg = ""
    if band:
        y_ucl, y_lcl, y_cl = y(band["ucl"]), y(band["lcl"]), y(band["cl"])
        band_svg = (
            f'<rect x="{pad_l}" y="{y_ucl:.1f}" width="{iw}" height="{(y_lcl - y_ucl):.1f}" '
            f'fill="{color}" opacity="0.05" rx="4"/>'
            f'<line x1="{pad_l}" y1="{y_ucl:.1f}" x2="{pad_l + iw}" y2="{y_ucl:.1f}" '
            f'stroke="{color}" stroke-opacity="0.35" stroke-width="1" stroke-dasharray="4 4"/>'
            f'<line x1="{pad_l}" y1="{y_lcl:.1f}" x2="{pad_l + iw}" y2="{y_lcl:.1f}" '
            f'stroke="{color}" stroke-opacity="0.35" stroke-width="1" stroke-dasharray="4 4"/>'
            f'<line x1="{pad_l}" y1="{y_cl:.1f}" x2="{pad_l + iw}" y2="{y_cl:.1f}" '
            f'stroke="{MUTED}" stroke-opacity="0.4" stroke-width="1"/>'
        )

    # last point marker; glows red if it breached the band
    lx, ly = line_pts[-1]
    breached = bool(band and (values[-1] > band["ucl"] or values[-1] < band["lcl"]))
    dot_color = CRIT if breached else color
    ticks = ""
    for i in range(0, len(weeks), max(1, len(weeks) // 6)):
        ticks += (f'<text x="{x(i):.1f}" y="{height - 4}" fill="{MUTED}" font-size="9" '
                  f'text-anchor="middle">{html.escape(weeks[i].split("-")[-1])}</text>')

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" preserveAspectRatio="none" '
        f'style="display:block;overflow:visible">'
        f'<defs>'
        f'<linearGradient id="{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{color}" stop-opacity="0.42"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>'
        f'<filter id="{uid}g" x="-20%" y="-40%" width="140%" height="180%">'
        f'<feGaussianBlur stdDeviation="3.2" result="b"/><feMerge>'
        f'<feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        f'</defs>'
        f'{band_svg}'
        f'<path d="{area}" fill="url(#{uid})"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linejoin="round" stroke-linecap="round" filter="url(#{uid}g)"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4.5" fill="{dot_color}" filter="url(#{uid}g)"/>'
        f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.2" fill="{INK}"/>'
        f'{ticks}</svg>'
    )


def _pct(v: float) -> str:
    return f"{v:.1f}%" if v == v else "n/a"


def _delta(d: dict, pct: bool = False) -> tuple[str, str]:
    """(text, tone) for a KPI delta vs the previous week."""
    if d.get("prev") != d.get("prev") or not d.get("prev"):
        return "—", "warn"
    if pct:
        diff = d["now"] - d["prev"]
        return f"{diff:+.1f} pts", ("good" if diff >= 0 else "bad")
    change = (d["now"] / d["prev"] - 1) * 100
    return f"{change:+.1f}%", ("good" if change >= 0 else "bad")


_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ company }} — Command Center {{ week }}</title>
<style>
 *{box-sizing:border-box}
 :root{--blue:#3f8ef5;--aqua:#22c197;--violet:#9a8cf0;--ink:#f4f6f8;--ink2:#aab3bd;--muted:#7d8590}
 body{margin:0;background:#0b0d10;color:var(--ink);position:relative;
   font-family:system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
 /* ambient aurora - drifting orbs behind the glass */
 .bg{position:absolute;inset:0;z-index:0;overflow:hidden;pointer-events:none}
 .orb{position:absolute;border-radius:50%;filter:blur(95px);will-change:transform}
 .orb.a{width:540px;height:540px;background:#1d4ed8;top:-170px;left:-130px;opacity:.5;animation:drift1 22s ease-in-out infinite}
 .orb.b{width:470px;height:470px;background:#0e7490;top:18%;right:-150px;opacity:.42;animation:drift2 26s ease-in-out infinite}
 .orb.c{width:430px;height:430px;background:#6d28d9;bottom:-170px;left:28%;opacity:.36;animation:drift3 30s ease-in-out infinite}
 @keyframes drift1{50%{transform:translate(60px,40px) scale(1.08)}}
 @keyframes drift2{50%{transform:translate(-50px,30px) scale(1.1)}}
 @keyframes drift3{50%{transform:translate(40px,-40px) scale(1.06)}}
 .wrap{position:relative;z-index:1;max-width:1180px;margin:0 auto;padding:34px 26px 54px}
 header{display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:14px;margin-bottom:22px;
   animation:fadeUp .7s cubic-bezier(.2,.7,.2,1) both}
 h1{font-size:23px;margin:0;letter-spacing:.2px;font-weight:650;
   background:linear-gradient(90deg,#ffffff,#c7d6f0 55%,#9a8cf0);-webkit-background-clip:text;background-clip:text;
   -webkit-text-fill-color:transparent;color:#fff}
 .sub{color:var(--ink2);font-size:13px;margin-top:6px}
 .pills{display:flex;gap:8px;flex-wrap:wrap}
 .pill{font-size:11px;color:var(--ink2);border:1px solid rgba(255,255,255,.12);
   background:rgba(255,255,255,.04);border-radius:999px;padding:5px 11px;backdrop-filter:blur(6px)}
 .pill.live::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;
   background:#28c76f;margin-right:6px;box-shadow:0 0 8px #28c76f;vertical-align:middle;animation:pulse 2.4s ease-in-out infinite}
 @keyframes pulse{0%,100%{box-shadow:0 0 6px #28c76f;opacity:1}50%{box-shadow:0 0 14px #28c76f;opacity:.55}}
 .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}
 .card{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);border-radius:18px;
   padding:18px 20px;backdrop-filter:blur(16px);box-shadow:0 8px 40px rgba(0,0,0,.35);
   opacity:0;animation:fadeUp .7s cubic-bezier(.2,.7,.2,1) forwards;transition:transform .25s ease,border-color .25s ease,box-shadow .25s ease}
 .card:hover{transform:translateY(-3px);border-color:rgba(120,150,240,.4);box-shadow:0 14px 50px rgba(40,70,160,.28)}
 @keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
 .kpi{grid-column:span 3;position:relative;overflow:hidden}
 .kpi::after{content:"";position:absolute;top:0;left:0;right:0;height:2px;
   background:linear-gradient(90deg,transparent,var(--accent,var(--blue)),transparent);opacity:.7}
 .kpi .lbl{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}
 .kpi .val{font-size:33px;font-weight:680;margin:8px 0 2px;font-variant-numeric:tabular-nums;line-height:1}
 .kpi .base{font-size:11.5px;color:var(--muted);margin-top:6px}
 .delta{font-size:13px;font-weight:600}
 .verdict{grid-column:span 12;display:flex;gap:16px;align-items:center;
   background:linear-gradient(120deg,rgba(63,142,245,.16),rgba(154,140,240,.12),rgba(34,193,151,.10));
   background-size:200% 200%;border-color:rgba(120,150,240,.28);animation:fadeUp .7s both,sheen 9s ease infinite}
 @keyframes sheen{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
 .verdict .tag{font-size:11px;letter-spacing:.6px;color:var(--violet);text-transform:uppercase}
 .verdict .txt{font-size:16.5px;line-height:1.45;font-weight:520}
 .chart{grid-column:span 6}
 .chart h3,.panel h3{margin:0 0 12px;font-size:13px;color:var(--ink2);font-weight:600;letter-spacing:.3px}
 .panel{grid-column:span 6}
 .sig{display:flex;gap:11px;padding:11px 0;border-top:1px solid rgba(255,255,255,.06);font-size:13.5px;line-height:1.5}
 .sig:first-of-type{border-top:0}
 .sig .ic{font-size:13px;line-height:1.5}
 .rows{width:100%;border-collapse:collapse;font-size:12.5px}
 .rows td,.rows th{padding:8px 6px;text-align:left;border-bottom:1px solid rgba(255,255,255,.06)}
 .rows th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
 .rows td.n{text-align:right;font-variant-numeric:tabular-nums}
 .bar{height:6px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:5px}
 .bar>i{display:block;height:100%;border-radius:3px;animation:grow 1s cubic-bezier(.2,.7,.2,1) both}
 @keyframes grow{from{width:0 !important}}
 .trust{grid-column:span 12;display:flex;gap:26px;flex-wrap:wrap;align-items:center}
 .trust .item{display:flex;flex-direction:column;gap:2px}
 .trust .k{font-size:22px;font-weight:680;font-variant-numeric:tabular-nums}
 .trust .t{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
 .ok{color:#28c76f}.crit{color:#f0524d}.warnc{color:#fab219}
 polyline.draw{stroke-dasharray:2600;stroke-dashoffset:2600;animation:draw 1.6s .3s cubic-bezier(.4,0,.2,1) forwards}
 @keyframes draw{to{stroke-dashoffset:0}}
 footer{margin-top:22px;color:var(--muted);font-size:11.5px;line-height:1.6;text-align:center}
 @media(prefers-reduced-motion:reduce){*{animation:none !important}.card{opacity:1}}
 @media(max-width:820px){.kpi{grid-column:span 6}.chart,.panel{grid-column:span 12}}
</style></head>
<body>
<div class="bg"><div class="orb a"></div><div class="orb b"></div><div class="orb c"></div></div>
<div class="wrap">
<header>
  <div><h1>{{ company }} · Command Center</h1>
  <div class="sub">Week {{ week }} · generated {{ generated }} · profile {{ profile }}</div></div>
  <div class="pills"><span class="pill live">autonomous</span><span class="pill">read-only</span>
  <span class="pill">every query audited</span></div>
</header>
<div class="grid">
  {% for k in kpis %}
  <div class="card kpi" style="animation-delay:{{ loop.index0 * 70 }}ms;--accent:{{ k.color }}">
    <div class="lbl">{{ k.label }}</div>
    <div class="val"{% if k.count is not none %} data-count="{{ k.count }}" data-kind="{{ k.kind }}"{% endif %}>{{ k.value }}</div>
    <div class="delta" style="color:{{ k.color }}">{{ k.delta }}</div>
    <div class="base">{{ k.base }}</div>
  </div>
  {% endfor %}

  <div class="card verdict" style="animation-delay:300ms">
    <div style="font-size:30px">◉</div>
    <div><div class="tag">weekly verdict</div><div class="txt">{{ verdict }}</div></div>
  </div>

  <div class="card chart" style="animation-delay:360ms"><h3>Revenue · with SPC control band</h3>{{ chart_rev }}</div>
  <div class="card chart" style="animation-delay:420ms"><h3>On-time shipping % · with SPC control band</h3>{{ chart_otp }}</div>

  <div class="card panel" style="animation-delay:480ms"><h3>Signals &amp; what to look at</h3>
    {% for f in findings %}
    <div class="sig"><span class="ic" style="color:{{ f.color }}">{{ f.icon }}</span><span>{{ f.text }}</span></div>
    {% endfor %}
  </div>

  <div class="card panel" style="animation-delay:540ms"><h3>Stock attention</h3>
    <table class="rows"><tr><th>Item</th><th class="n">Stock</th><th class="n">Cover (wk)</th></tr>
    {% for s in stock %}
    <tr><td>{{ s.item }}</td><td class="n">{{ s.qty }}</td>
    <td class="n"><span style="color:{{ s.color }}">{{ s.cover }}</span>
    <div class="bar"><i style="width:{{ s.pct }}%;background:{{ s.color }}"></i></div></td></tr>
    {% else %}<tr><td colspan="3">none below threshold</td></tr>{% endfor %}
    </table>
  </div>

  <div class="card trust" style="animation-delay:600ms">
    <div class="item"><span class="k {{ 'ok' if recon_ok else 'crit' }}">{{ '✓' if recon_ok else '✗' }}</span>
      <span class="t">source reconciliation</span></div>
    <div class="item"><span class="k {{ 'warnc' if dq else 'ok' }}">{{ dq }}</span><span class="t">data-quality notes</span></div>
    <div class="item"><span class="k">{{ audited }}</span><span class="t">SQL statements audited</span></div>
    <div class="item"><span class="k">{{ rows_total }}</span><span class="t">rows reconciled</span></div>
    <div class="item" style="margin-left:auto;max-width:340px"><span class="t" style="text-transform:none;font-size:12px;color:var(--ink2)">{{ trust_line }}</span></div>
  </div>
</div>
<footer>erp-report-engine · designed by Eren Gülmez · the report that shows its receipts —
every number traces to an audited, read-only SQL statement.</footer>
</div>
<script>
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('polyline').forEach(function(p){ p.classList.add('draw'); });
  if (reduce) return;
  document.querySelectorAll('.val[data-count]').forEach(function(el){
    var target = parseFloat(el.getAttribute('data-count')), kind = el.getAttribute('data-kind');
    if (isNaN(target)) return;
    var final = el.textContent, t0 = null, dur = 1100;
    function fmt(v){ return kind==='pct' ? v.toFixed(1)+'%' : Math.round(v).toLocaleString('en-US'); }
    function step(ts){ if(!t0)t0=ts; var k=Math.min(1,(ts-t0)/dur), e=1-Math.pow(1-k,3);
      el.textContent = k<1 ? fmt(target*e) : final; if(k<1) requestAnimationFrame(step); }
    el.textContent = fmt(0); requestAnimationFrame(step);
  });
})();
</script>
</body></html>"""

_ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_TPL = _ENV.from_string(_TEMPLATE)


def render(cfg, profile, kpis, findings, extraction, auditor, streak) -> str:
    r, o, s = kpis["revenue"], kpis["orders"], kpis["on_time_pct"]
    rd, rt = _delta(r)
    od, ot = _delta(o)
    sd, st = _delta(s, pct=True)

    kpi_ctx = [
        {"label": "Revenue (last full week)", "value": f"{r['now']:,.0f}", "count": r["now"], "kind": "int",
         "delta": rd, "color": TONE[rt], "base": f"baseline {r['baseline8']:,.0f}"},
        {"label": "Orders", "value": f"{o['now']:,.0f}", "count": o["now"], "kind": "int",
         "delta": od, "color": TONE[ot], "base": f"baseline {o['baseline8']:,.0f}"},
        {"label": "On-time shipping", "value": _pct(s["now"]),
         "count": (s["now"] if s["now"] == s["now"] else None), "kind": "pct",
         "delta": sd, "color": TONE[st],
         "base": (f"{s.get('scored', 0)}/{s.get('delivered', 0)} scored"
                  if s.get("delivered") and s.get("scored", 0) < s["delivered"] else "order-level OTIF-lite")},
        {"label": "Items low on stock", "value": f"{kpis['n_low_cover']}",
         "count": kpis["n_low_cover"], "kind": "int",
         "delta": ("clear" if kpis["n_low_cover"] == 0 else "action"),
         "color": GOOD if kpis["n_low_cover"] == 0 else WARN,
         "base": f"< {cfg.low_cover_weeks:g} weeks cover"},
    ]

    band_rev = spc._limits(_nums(kpis["trend"]["revenue"])[:-1]) if len(_nums(kpis["trend"]["revenue"])) >= 6 else None
    band_otp = spc._limits(_nums(kpis["trend"]["on_time"])[:-1]) if len(_nums(kpis["trend"]["on_time"])) >= 6 else None
    if band_rev and band_rev["mr_bar"] == 0:
        band_rev = None
    if band_otp and band_otp["mr_bar"] == 0:
        band_otp = None

    thr = float(cfg.low_cover_weeks) or 1.0
    stock = []
    for x in kpis["low_cover"][:6]:
        cov = x["cover_weeks"]
        color = CRIT if cov <= thr * 0.5 else WARN
        stock.append({"item": x["item_code"], "qty": f"{x['stock_qty']:,.0f}", "cover": cov,
                      "color": color, "pct": max(4, min(100, (cov / (thr * 2)) * 100))})

    recon_ok = all(v["fetched"] == v["source_count"] for v in extraction.reconciliation.values())
    rows_total = sum(v["fetched"] for v in extraction.reconciliation.values())
    wow = _delta(r)[0]
    verdict = (f"Week {kpis['this_week']}: revenue {wow} week-over-week, on-time "
               f"{_pct(s['now'])}, {kpis['n_low_cover']} item(s) below cover, "
               f"{len(extraction.issues)} data-quality note(s).")

    return _TPL.render(
        company=cfg.company_alias, week=kpis["this_week"], profile=profile.name,
        generated=f"{dt.datetime.now():%Y-%m-%d %H:%M}",
        kpis=kpi_ctx,
        verdict=verdict,
        chart_rev=Markup(_area_chart(kpis["trend"]["weeks"], kpis["trend"]["revenue"], BLUE, band=band_rev)),
        chart_otp=Markup(_area_chart(kpis["trend"]["weeks"], kpis["trend"]["on_time"], AQUA, pct=True, band=band_otp)),
        findings=[{"icon": ICON[f["tone"]], "color": TONE[f["tone"]], "text": f["text"]} for f in findings],
        stock=stock,
        recon_ok=recon_ok, dq=len(extraction.issues), audited=len(auditor.entries),
        rows_total=f"{rows_total:,}",
        trust_line=("All entities reconcile with source counts."
                    if recon_ok else "A reconciliation mismatch — investigate before trusting the KPIs."),
    )
