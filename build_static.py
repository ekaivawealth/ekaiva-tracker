"""
Render the snapshot into a single self-contained HTML file (no external assets).

Used for the free GitHub Pages deployment path, and as an offline preview.
    python build_static.py            # reads the stored snapshot -> data/dashboard.html
"""
from __future__ import annotations

import html
import json
import sys

import config
import store


def _fmt(x, dp=2):
    if x is None:
        return "—"
    return f"{float(x):,.{dp}f}"


def _bar(crossed, full, color, label):
    """Six-pip breadth bar tinted by the score colour."""
    if crossed is None:
        return (f'<div class="bar insuff"><span class="pips">'
                + "".join('<i></i>' for _ in range(full))
                + f'</span><span class="lbl">{html.escape(label)}</span></div>')
    pips = "".join(
        f'<i class="{"on" if k < crossed else ""}" style="--c:{color}"></i>'
        for k in range(full)
    )
    return (f'<div class="bar"><span class="pips">{pips}</span>'
            f'<span class="lbl" style="color:{color}">{html.escape(label)}</span></div>')


def _row(name, info, full):
    cls = "row vix" if info.get("is_volatility") else "row"
    flag = ' <span class="vixflag" title="High = expected volatility (fear), not strength">VIX</span>' \
        if info.get("is_volatility") else ""
    new = ' <span class="new">NEW</span>' if info.get("entered_full_today") else ""
    bar = _bar(info["crossed"], full, info["color"], info["score_label"])
    return (f'<button class="{cls}" data-idx="{html.escape(name)}">'
            f'<span class="nm">{html.escape(name)}{flag}{new}</span>'
            f'<span class="rt">{_fmt(info["close"])}</span>{bar}</button>')


def render(payload: dict) -> str:
    full = payload["full"]
    idx = payload["indices"]
    panels = payload["panels"]
    unit = "day" if payload.get("basis") == "daily" else "week"
    ma = payload.get("ma_type", "SMA")

    green = "".join(_row(n, idx[n], full) for n in panels["green"]) \
        or '<div class="empty">No index is at 6/6 today.</div>'
    rest = "".join(_row(n, idx[n], full) for n in panels["rest"])
    if panels["entered_today"]:
        entered = "".join(_row(n, idx[n], full) for n in panels["entered_today"])
    else:
        entered = '<div class="empty">Nothing crossed into 6/6 today yet.</div>'

    # Inside a <script> block the content is raw text (NOT entity-decoded), so we must
    # NOT html-escape it; we only neutralise any "</" that could close the tag early.
    data_json = json.dumps(payload).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Index SMA Tracker</title>
<style>
:root{{
  --bg:#0b0f14; --surface:#141a21; --surface2:#1b232c; --line:#232c36;
  --ink:#e6edf3; --muted:#8b949e; --green:#1a7f37; --red:#b3261e;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Inter",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-variant-numeric:tabular-nums;}}
.wrap{{max-width:1180px;margin:0 auto;padding:18px 16px 60px}}
header.top{{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  padding-bottom:14px;border-bottom:1px solid var(--line);margin-bottom:18px;flex-wrap:wrap}}
.brand{{font-weight:800;letter-spacing:-.02em;font-size:20px}}
.brand small{{color:var(--muted);font-weight:600;letter-spacing:0}}
.asof{{color:var(--muted);font-size:13px}}
.asof b{{color:var(--ink)}}
.strip{{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;margin-bottom:18px}}
.strip h2{{margin:0 0 8px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:780px){{.cols{{grid-template-columns:1fr}}}}
.panel{{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
.phead{{padding:10px 14px;font-weight:700;color:#fff;display:flex;justify-content:space-between}}
.phead .cnt{{opacity:.85;font-weight:600}}
.phead.g{{background:var(--green)}} .phead.r{{background:var(--red)}}
.list{{max-height:560px;overflow:auto}}
.row{{width:100%;text-align:left;background:none;border:0;border-bottom:1px solid var(--line);
  color:var(--ink);cursor:pointer;display:grid;
  grid-template-columns:1fr auto 132px;align-items:center;gap:12px;padding:9px 14px;font-size:13.5px}}
.row:hover{{background:var(--surface2)}}
.row .nm{{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.row .rt{{color:var(--muted);font-feature-settings:"tnum"}}
.vixflag{{font-size:9px;color:#c084fc;border:1px solid #6d4a8f;border-radius:4px;padding:0 4px;margin-left:6px;vertical-align:middle}}
.new{{font-size:9px;color:#0b0f14;background:#3fb950;border-radius:4px;padding:1px 5px;margin-left:6px;font-weight:800}}
.bar{{display:flex;align-items:center;gap:8px;justify-content:flex-end}}
.pips{{display:inline-flex;gap:3px}}
.pips i{{width:13px;height:8px;border-radius:2px;background:#2a333d;display:inline-block}}
.pips i.on{{background:var(--c)}}
.bar.insuff .pips i{{background:#2a333d}}
.lbl{{font-size:12px;font-weight:700;min-width:34px;text-align:right;color:var(--muted)}}
.empty{{padding:14px;color:var(--muted);font-size:13px}}
/* modal */
.scrim{{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;align-items:flex-start;
  justify-content:center;padding:40px 16px;z-index:20}}
.scrim.open{{display:flex}}
.modal{{background:var(--surface);border:1px solid var(--line);border-radius:14px;width:680px;
  max-width:100%;max-height:84vh;display:flex;flex-direction:column;overflow:hidden}}
.mhead{{padding:14px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}}
.mhead h3{{margin:0;font-size:16px}} .mhead .sub{{color:var(--muted);font-size:12px}}
.x{{background:none;border:0;color:var(--muted);font-size:22px;cursor:pointer;line-height:1}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead th{{position:sticky;top:0;background:var(--surface2);color:var(--muted);text-align:left;
  font-weight:600;font-size:11px;letter-spacing:.08em;text-transform:uppercase;padding:8px 14px}}
tbody td{{padding:8px 14px;border-bottom:1px solid var(--line)}}
tbody tr.live{{background:rgba(63,185,80,.08)}}
.tbar{{display:inline-flex;gap:3px;vertical-align:middle;margin-right:8px}}
.tbar i{{width:12px;height:7px;border-radius:2px;background:#2a333d;display:inline-block}}
.mbody{{overflow:auto}}
.foot{{color:var(--muted);font-size:11px;margin-top:18px;line-height:1.5}}
</style></head><body>
<div class="wrap">
  <header class="top">
    <div class="brand">Index {ma} Tracker <small>· {unit}ly {ma} · strict 6/6</small></div>
    <div class="asof">Latest data updated on: <b>{html.escape(payload['as_of'])}</b></div>
  </header>

  <section class="strip">
    <h2>Entered 6/6 today</h2>
    <div class="cols" style="grid-template-columns:1fr">{entered}</div>
  </section>

  <div class="cols">
    <div class="panel">
      <div class="phead g"><span>Green Alert · 6/6</span><span class="cnt">{len(panels['green'])}</span></div>
      <div class="list">{green}</div>
    </div>
    <div class="panel">
      <div class="phead r"><span>Everything else</span><span class="cnt">{len(panels['rest'])}</span></div>
      <div class="list">{rest}</div>
    </div>
  </div>

  <p class="foot">
    Score = number of the six {unit}ly {ma}s (5/10/20/50/100/200 {unit}s) the close is above.
    A SMA that doesn't exist yet (not enough weekly history) counts as not-crossed, so newer
    indices stay below 6/6 until they mature. For India VIX a high reading means expected
    volatility, not strength. Click any index for its weekly history.
  </p>
</div>

<div class="scrim" id="scrim">
  <div class="modal">
    <div class="mhead"><div><h3 id="mtitle"></h3><div class="sub" id="msub"></div></div>
      <button class="x" id="mx">&times;</button></div>
    <div id="msmas" style="padding:10px 16px;border-bottom:1px solid var(--line)"></div>
    <div class="mbody"><table>
      <thead><tr><th>Date</th><th>Close</th><th>Score</th></tr></thead>
      <tbody id="mbody"></tbody></table></div>
  </div>
</div>

<script id="data" type="application/json">{data_json}</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const FULL = DATA.full;
function pips(crossed, color){{
  let h='<span class="tbar">'; for(let k=0;k<FULL;k++){{
    h+= '<i style="'+((crossed!=null&&k<crossed)?('background:'+color):'')+'"></i>'; }}
  return h+'</span>';
}}
function openIdx(name){{
  const info = DATA.indices[name]; if(!info) return;
  document.getElementById('mtitle').textContent = name;
  document.getElementById('msub').textContent =
    'Live: ' + (info.close!=null? Number(info.close).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}):'—')
    + '  ·  ' + info.score_label + (info.is_volatility?'  · VIX (high = fear)':'');
  const sm = info.smas||{{}}, close = info.close;
  let sh = '<div style="color:#8b949e;font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px">'+(DATA.basis==='daily'?'Daily':'Weekly')+' '+(DATA.ma_type||'SMA')+' vs close ('+(close==null?'—':Number(close).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}))+')</div>';
  sh += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:5px 20px;font-size:12.5px">';
  [5,10,20,50,100,200].forEach(p=>{{
    const v = sm[p];
    let ind='—', col='#6b7280';
    if(v!=null){{ if(close>v){{ind='Above';col='#3fb950';}} else {{ind='Below';col='#e5484d';}} }}
    sh += '<div style="display:flex;justify-content:space-between;gap:10px"><span>SMA '+p+'</span><span><span style="color:#8b949e">'+(v==null?'—':Number(v).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}))+'</span> &nbsp;<b style="color:'+col+'">'+ind+'</b></span></div>';
  }});
  sh += '</div>';
  document.getElementById('msmas').innerHTML = sh;
  const tb = document.getElementById('mbody'); tb.innerHTML='';
  // live row first
  const live = document.createElement('tr'); live.className='live';
  live.innerHTML = '<td>'+DATA.as_of+' (live)</td><td>'+
    (info.close!=null?Number(info.close).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}}):'—')+
    '</td><td>'+pips(info.crossed,info.color)+'<b style="color:'+info.color+'">'+info.score_label+'</b></td>';
  tb.appendChild(live);
  (info.archive||[]).forEach(r=>{{
    const tr=document.createElement('tr');
    tr.innerHTML='<td>'+r.week_ending+'</td><td>'+
      Number(r.close).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}})+
      '</td><td>'+pips(r.crossed,r.color)+'<b style="color:'+r.color+'">'+r.score_label+'</b></td>';
    tb.appendChild(tr);
  }});
  document.getElementById('scrim').classList.add('open');
}}
document.querySelectorAll('.row').forEach(b=>b.addEventListener('click',()=>openIdx(b.dataset.idx)));
const scrim=document.getElementById('scrim');
document.getElementById('mx').addEventListener('click',()=>scrim.classList.remove('open'));
scrim.addEventListener('click',e=>{{if(e.target===scrim)scrim.classList.remove('open');}});
</script>
</body></html>"""


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--ma", choices=["sma", "ema"], default="sma")
    config.MA_TYPE = ap.parse_args().ma.upper()
    payload = store.load_snapshot()
    if not payload:
        print("No snapshot for", config.MA_TYPE, "- run: python -m jobs.run_daily --ma",
              config.MA_TYPE.lower(), "--force first.")
        sys.exit(1)
    out = render(payload)
    with open(config.static_html(), "w") as f:
        f.write(out)
    print("wrote", config.static_html(), f"({len(out)} bytes)")


if __name__ == "__main__":
    main()
