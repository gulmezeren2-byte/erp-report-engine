"""Generate docs/playground.html — the read-only guard, runnable in the browser.

The page embeds the ACTUAL guard.py source (read here, at generate time) and runs
it in the visitor's browser via Pyodide. It is not a re-implementation and not a
description: it is the same code the tests run and the engine ships, parsing the
visitor's SQL client-side. Nothing is sent anywhere - there is no server and no
database; the guard is a pure function from a string to allow/block.

The only transform is mechanical: guard.py's one package-relative import
(`from .errors import ReadOnlyViolation`) is swapped for an inline exception, so
the module loads without the rest of the package. Everything else - every regex,
the whole denylist, the AST walk - is byte-for-byte the shipped guard. CI
regenerates this page and fails on drift, so it can never fall behind guard.py.

Usage:  python docs/generate_playground.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from erp_report_engine.attack_corpus import CASES  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD_PY = os.path.join(HERE, "..", "erp_report_engine", "guard.py")
OUT = os.path.join(HERE, "playground.html")
REPO = "https://github.com/gulmezeren2-byte/erp-report-engine"
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/"

_IMPORT_LINE = "from .errors import ReadOnlyViolation"
_INLINE_EXC = (
    "class ReadOnlyViolation(Exception):\n"
    "    \"\"\"Inlined for the standalone browser playground; in the package this\n"
    "    subclasses EngineError. The guard logic below is verbatim guard.py.\"\"\"\n"
)


def _standalone_guard_source() -> str:
    with open(GUARD_PY, encoding="utf-8") as f:
        src = f.read()
    if _IMPORT_LINE not in src:
        raise SystemExit(
            "guard.py no longer contains the expected errors import - update "
            "generate_playground.py so the browser build stays faithful."
        )
    return src.replace(_IMPORT_LINE, _INLINE_EXC.rstrip("\n"))


def _presets() -> list[dict]:
    # a curated, high-impact subset - the scariest attacks plus the reads that
    # prove the guard is not just saying "no" to everything
    want = ["commit_drop", "trifecta_exfil", "xp_cmdshell", "pg_read_file",
            "lo_export", "dblink", "set_config", "openrowset", "load_extension",
            "aggregate", "literal_keyword", "join"]
    by = {c.name: c for c in CASES}
    out = []
    for name in want:
        c = by[name]
        out.append({"label": c.name, "dialect": c.dialect, "sql": c.sql,
                    "kind": c.kind, "why": c.why})
    return out


def build() -> None:
    guard_src = _standalone_guard_source()
    presets = _presets()

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>erp-report-engine — try to break the read-only guard</title>
<meta name="description" content="Paste SQL and watch the real read-only guard allow or refuse it — running in your browser, client-side, on the exact code the engine ships.">
<script src="{PYODIDE}pyodide.js"></script>
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;background:#0b0d10;color:#f4f6f8;
   font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}}
 .wrap{{max-width:860px;margin:0 auto;padding:52px 22px 80px}}
 a{{color:#3987e5;text-decoration:none}} a:hover{{text-decoration:underline}}
 h1{{font-size:28px;line-height:1.25;margin:0 0 6px;letter-spacing:-.5px}}
 .sub{{color:#7d8590;font-size:15px;margin:0 0 26px}}
 .lede{{font-size:16px;border-left:3px solid #3987e5;padding:2px 0 2px 16px;margin:0 0 26px;color:#c7d1db}}
 label{{display:block;color:#7d8590;font-size:12px;text-transform:uppercase;letter-spacing:.5px;margin:0 0 6px}}
 select,textarea,button{{font-family:inherit;font-size:14px}}
 select{{background:#111418;color:#f4f6f8;border:1px solid #20242b;border-radius:7px;padding:8px 10px}}
 textarea{{width:100%;min-height:96px;background:#111418;color:#e8edf2;border:1px solid #20242b;border-radius:9px;
   padding:13px 15px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;resize:vertical;line-height:1.5}}
 .row{{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin:0 0 14px}}
 .grow{{flex:1;min-width:220px}}
 .chk{{display:flex;align-items:center;gap:7px;color:#c7d1db;font-size:13px;text-transform:none;letter-spacing:0}}
 button.run{{background:#1c4d8f;color:#fff;border:1px solid #2a6bc4;border-radius:8px;padding:10px 22px;font-weight:600;cursor:pointer}}
 button.run:hover{{background:#2560ad}} button.run:disabled{{opacity:.5;cursor:default}}
 .presets{{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 22px}}
 .presets button{{background:#111418;color:#c7d1db;border:1px solid #20242b;border-radius:16px;padding:5px 12px;font-size:12.5px;cursor:pointer;
   font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
 .presets button:hover{{border-color:#3987e5;color:#fff}}
 .presets .atk{{border-color:#3a1c1c;color:#e59a9a}} .presets .atk:hover{{border-color:#d03b3b}}
 #verdict{{border-radius:10px;padding:16px 18px;margin:6px 0 0;font-size:15px;display:none;border:1px solid}}
 #verdict.ok{{display:block;background:#0f2a16;border-color:#14401f;color:#7fe0a0}}
 #verdict.no{{display:block;background:#2a1113;border-color:#4a1c1f;color:#f0a3a3}}
 #verdict .tag{{font-weight:700;text-transform:uppercase;letter-spacing:.5px;font-size:13px;margin-right:8px}}
 #verdict .reason{{color:#e8edf2;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;display:block;margin-top:8px;line-height:1.5}}
 #status{{color:#7d8590;font-size:13px;margin:0 0 22px;min-height:20px}}
 .spin{{display:inline-block;width:12px;height:12px;border:2px solid #2a3038;border-top-color:#3987e5;border-radius:50%;
   animation:sp .7s linear infinite;vertical-align:-1px;margin-right:7px}}
 @keyframes sp{{to{{transform:rotate(360deg)}}}}
 footer{{margin-top:52px;padding-top:20px;border-top:1px solid #20242b;color:#7d8590;font-size:13px}}
 code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:#15181d;padding:1px 5px;border-radius:4px;font-size:.92em}}
</style>
</head>
<body>
<div class="wrap">
  <h1>Try to break the read-only guard</h1>
  <p class="sub">erp-report-engine · the guard runs in your browser, on the exact code the engine ships</p>

  <p class="lede">Paste any SQL and the <strong>real</strong> guard — the same <code>assert_read_only()</code> the
  tests run — decides <em>allow</em> or <em>refuse</em>, right here, client-side. Nothing is sent anywhere; there is
  no server and no database. It's a pure function from a string to a verdict. See if you can sneak a write, a file
  read, or an outbound connection past it.</p>

  <div id="status"><span class="spin"></span>loading the guard (Python + sqlglot, a one-time download)…</div>

  <label>Presets — the red ones are attacks that a shape-only guard waves through</label>
  <div class="presets" id="presets"></div>

  <div class="row">
    <div>
      <label for="dialect">Dialect</label>
      <select id="dialect">
        <option value="postgres">PostgreSQL</option>
        <option value="tsql">SQL Server</option>
        <option value="mysql">MySQL</option>
        <option value="sqlite">SQLite</option>
      </select>
    </div>
    <div style="align-self:center">
      <label class="chk"><input type="checkbox" id="strict"> strict mode (the agent path — default-deny unknown functions)</label>
    </div>
  </div>

  <label for="sql">SQL</label>
  <textarea id="sql" spellcheck="false" placeholder="SELECT customer, SUM(net_total) FROM orders GROUP BY customer">SELECT pg_read_file('/etc/passwd')</textarea>
  <div class="row" style="margin-top:12px">
    <button class="run" id="run" disabled>Check it</button>
  </div>

  <div id="verdict"></div>

  <footer>
    The one transform for the browser: guard.py's package import of its exception class is inlined; every regex,
    the denylist, and the AST walk are verbatim. CI regenerates this page from
    <a href="{REPO}/blob/main/erp_report_engine/guard.py">guard.py</a> and fails on drift.<br>
    <a href="index.html">home</a> · <a href="trust.html">the full benchmark</a> ·
    <a href="{REPO}/blob/main/SECURITY.md">security model</a> · Designed by Eren Gülmez.
  </footer>
</div>

<script>
const GUARD_SRC = {json.dumps(guard_src)};
const PRESETS = {json.dumps(presets)};
let pyodide = null, ready = false;

const $ = (id) => document.getElementById(id);

function renderPresets() {{
  const box = $("presets");
  for (const p of PRESETS) {{
    const b = document.createElement("button");
    b.textContent = p.label;
    if (p.kind !== "read") b.className = "atk";
    b.title = p.why;
    b.onclick = () => {{ $("sql").value = p.sql; $("dialect").value = p.dialect; check(); }};
    box.appendChild(b);
  }}
}}

async function boot() {{
  renderPresets();
  try {{
    pyodide = await loadPyodide({{ indexURL: "{PYODIDE}" }});
    await pyodide.loadPackage("micropip");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("sqlglot");
    pyodide.runPython(GUARD_SRC);            // defines assert_read_only + ReadOnlyViolation
    ready = true;
    $("status").innerHTML = "guard ready — it runs entirely in this tab.";
    $("run").disabled = false;
  }} catch (e) {{
    $("status").innerHTML = "couldn't load the in-browser runtime. The full results are on " +
      "<a href='trust.html'>the benchmark page</a>.";
  }}
}}

function check() {{
  if (!ready) return;
  const v = $("verdict");
  pyodide.globals.set("_sql", $("sql").value);
  pyodide.globals.set("_dialect", $("dialect").value);
  pyodide.globals.set("_strict", $("strict").checked);
  let out;
  try {{
    out = JSON.parse(pyodide.runPython(`
import json as _j
try:
    assert_read_only(_sql, dialect=_dialect, strict=_strict)
    _r = {{"blocked": False, "reason": ""}}
except ReadOnlyViolation as _e:
    _r = {{"blocked": True, "reason": str(_e)}}
except Exception as _e:
    _r = {{"blocked": True, "reason": f"{{type(_e).__name__}}: {{_e}}"}}
_j.dumps(_r)
`));
  }} catch (e) {{
    v.className = "no"; v.innerHTML = "<span class='tag'>error</span> the guard raised unexpectedly.";
    return;
  }}
  if (out.blocked) {{
    v.className = "no";
    v.innerHTML = "<span class='tag'>refused</span> not a read — the guard blocked it." +
      "<span class='reason'>" + escapeHtml(out.reason) + "</span>";
  }} else {{
    v.className = "ok";
    v.innerHTML = "<span class='tag'>allowed</span> a single, side-effect-free read.";
  }}
}}

function escapeHtml(s) {{
  const d = document.createElement("div"); d.textContent = s; return d.innerHTML;
}}

$("run").onclick = check;
$("sql").addEventListener("keydown", (e) => {{ if ((e.metaKey || e.ctrlKey) && e.key === "Enter") check(); }});
boot();
</script>
</body>
</html>
"""
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print(f"wrote {OUT}  (guard {len(guard_src)} chars, {len(presets)} presets)")


if __name__ == "__main__":
    build()
