"""Generate docs/trust.html from a LIVE run of the guard against its corpus.

The numbers on the page are computed here, from the same attack_corpus the tests
enforce and the `trust-benchmark` CLI runs - so the website cannot claim a result
CI does not hold. CI regenerates this and fails on drift (like the PBIR gate).

Usage:  python docs/generate_trust_page.py
"""

from __future__ import annotations

import html
import os
import sys

# run from anywhere (docs/ dir, repo root, CI) without an editable install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_report_engine import __version__
from erp_report_engine.attack_corpus import CASES, run, summarize
from erp_report_engine.connect import assert_read_only

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trust.html")
REPO = "https://github.com/gulmezeren2-byte/erp-report-engine"

# validated dark palette (matches the Command Center dashboard)
SURFACE, INK, MUTED = "#0b0d10", "#f4f6f8", "#7d8590"
GOOD, BAD = "#0ca30c", "#d03b3b"
SEV = {"critical": "#d03b3b", "high": "#d95926", "medium": "#c98500", "-": MUTED}


def _rows(results: list[dict]) -> str:
    by = {c.name: c for c in CASES}
    order = {"critical": 0, "high": 1, "medium": 2, "-": 3}
    out = []
    for r in sorted(results, key=lambda r: (order.get(r["severity"], 9), r["name"])):
        ok = r["blocked"] == r["expected_block"]
        verdict = "refused" if r["blocked"] else "allowed"
        vcolor = GOOD if ok else BAD
        sev = r["severity"]
        sev_cell = (f'<span class="sev" style="color:{SEV[sev]}">{sev}</span>'
                    if sev != "-" else '<span class="sev muted">read</span>')
        out.append(
            "<tr>"
            f'<td>{sev_cell}</td>'
            f'<td class="mono">{html.escape(r["name"])}</td>'
            f'<td class="mono muted">{html.escape(r["dialect"])}</td>'
            f'<td>{html.escape(by[r["name"]].why)}</td>'
            f'<td class="verdict" style="color:{vcolor}">{verdict}</td>'
            "</tr>"
        )
    return "\n".join(out)


def build() -> None:
    results = run(assert_read_only)
    s = summarize(results)
    attacks = [r for r in results if r["expected_block"]]
    reads = [r for r in results if not r["expected_block"]]
    stat_color = GOOD if s["all_correct"] else BAD

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>erp-report-engine — the read-only guard, measured</title>
<meta name="description" content="A reproducible benchmark: {s['attacks_blocked']} of {s['attacks_total']} well-formed-SQL attacks refused by the read-only guard, {s['reads_allowed']} of {s['reads_total']} legitimate reads allowed.">
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;background:{SURFACE};color:{INK};
   font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
   -webkit-font-smoothing:antialiased}}
 .wrap{{max-width:920px;margin:0 auto;padding:56px 22px 80px}}
 a{{color:#3987e5;text-decoration:none}} a:hover{{text-decoration:underline}}
 h1{{font-size:30px;line-height:1.25;margin:0 0 6px;letter-spacing:-.5px}}
 .sub{{color:{MUTED};font-size:16px;margin:0 0 34px}}
 .lede{{font-size:17px;border-left:3px solid #3987e5;padding:2px 0 2px 18px;margin:0 0 34px;color:#c7d1db}}
 .stat{{display:flex;gap:26px;flex-wrap:wrap;margin:0 0 12px}}
 .stat .n{{font-size:40px;font-weight:700;color:{stat_color};letter-spacing:-1px;line-height:1}}
 .stat .l{{color:{MUTED};font-size:13px;margin-top:4px}}
 .verdictline{{color:{stat_color};font-weight:600;margin:2px 0 36px}}
 h2{{font-size:15px;text-transform:uppercase;letter-spacing:.8px;color:{MUTED};
   margin:40px 0 12px;font-weight:600}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 th{{text-align:left;color:{MUTED};font-weight:600;font-size:12px;text-transform:uppercase;
   letter-spacing:.4px;padding:0 10px 8px;border-bottom:1px solid #20242b}}
 td{{padding:9px 10px;border-bottom:1px solid #16191e;vertical-align:top}}
 tr:hover td{{background:#0f1216}}
 .mono{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}}
 .muted{{color:{MUTED}}}
 .sev{{font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.3px}}
 .verdict{{font-weight:600;white-space:nowrap}}
 .scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
 pre{{background:#111418;border:1px solid #20242b;border-radius:8px;padding:14px 16px;
   overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;color:#c7d1db}}
 .card{{background:#0f1216;border:1px solid #20242b;border-radius:10px;padding:18px 20px;margin:0 0 18px}}
 footer{{margin-top:56px;padding-top:20px;border-top:1px solid #20242b;color:{MUTED};font-size:13px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>The read-only guard, measured against its own attacks</h1>
  <p class="sub">erp-report-engine {html.escape(__version__)} · a reproducible security benchmark</p>

  <p class="lede">"Read-only" is a claim about a guard, and a guard that inspects a statement's
  <em>shape</em> while ignoring the functions it <em>calls</em> has not earned it. Every attack
  below is a perfectly well-formed <span class="mono">SELECT</span> — and every one reads a file,
  opens a socket, runs more SQL, or flips the session. A shape-only guard waves them all through.</p>

  <div class="stat">
    <div><div class="n">{s['attacks_blocked']}/{s['attacks_total']}</div><div class="l">attacks refused</div></div>
    <div><div class="n">{s['reads_allowed']}/{s['reads_total']}</div><div class="l">legitimate reads allowed</div></div>
    <div><div class="n">4</div><div class="l">SQL dialects</div></div>
  </div>
  <p class="verdictline">{'Every case behaves as claimed.' if s['all_correct'] else 'FAILURES — see below.'}</p>

  <div class="card">
    <strong>Run it yourself.</strong> The number above is computed from the guard, not asserted in prose —
    so you can reproduce it in one command:
    <pre>pipx install erp-report-engine
erp-report-engine trust-benchmark</pre>
    The same corpus is enforced by CI on every commit, so this page can never claim a result the tests don't hold.
    Or — no install — <a href="playground.html">paste your own SQL into the guard, in your browser →</a>
  </div>

  <h2>Attacks — {len(attacks)} well-formed SELECTs that are not reads</h2>
  <div class="scroll"><table>
    <thead><tr><th>Severity</th><th>Function</th><th>Dialect</th><th>What it actually does</th><th>Guard</th></tr></thead>
    <tbody>
{_rows(attacks)}
    </tbody>
  </table></div>

  <h2>Legitimate reads — {len(reads)} that must be allowed</h2>
  <p class="muted" style="margin-top:-4px">A guard that blocks real work is useless, so these earn a place in the benchmark too.</p>
  <div class="scroll"><table>
    <thead><tr><th></th><th>Query</th><th>Dialect</th><th>Why it's a read</th><th>Guard</th></tr></thead>
    <tbody>
{_rows(reads)}
    </tbody>
  </table></div>

  <h2>Why this is the benchmark that matters</h2>
  <p>Pointing an autonomous tool — or an AI agent — at a production ERP database is the "lethal trifecta":
  untrusted input, a tool that can act, and a channel to exfiltrate through. Wrapping queries in a read-only
  transaction is not enough on its own: a session flag can be flipped
  (<span class="mono">set_config</span>), a transaction can be escaped, and a function can read a file or dial
  out without writing a single row. The only honest way to claim a guard holds is to measure it against the
  functions that defeat the shape-only version — which is what this page does, on every commit.</p>
  <p>The guard here checks the functions a statement calls, by parse tree <em>and</em> lexically (some of these
  don't even parse), fails closed when it can't read a query, and — on the agent path — default-denies every
  function it doesn't recognise. Full model: <a href="{REPO}/blob/main/SECURITY.md">SECURITY.md</a>.</p>

  <footer>
    <a href="{REPO}">github.com/gulmezeren2-byte/erp-report-engine</a> ·
    <a href="index.html">live sample report</a> ·
    <a href="dashboard.html">command center</a><br>
    Designed by Eren Gülmez · read-only by construction, every query audited · generated from a live guard run.
  </footer>
</div>
</body>
</html>
"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print(f"wrote {OUT}  ({s['attacks_blocked']}/{s['attacks_total']} attacks refused, "
          f"{s['reads_allowed']}/{s['reads_total']} reads allowed)")


if __name__ == "__main__":
    build()
