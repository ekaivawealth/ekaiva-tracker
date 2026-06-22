"""
Write data/index.html — the landing page that links the SMA and EMA dashboards.
Run after building both:  python build_index.py
"""
import os

import config
import store


def model_info(ma):
    config.MA_TYPE = ma
    try:
        p = store.load_snapshot()
    except Exception:
        p = None
    if not p:
        return {"as_of": "—", "green": "—", "total": "—", "ready": False}
    return {"as_of": p["as_of"], "green": len(p["panels"]["green"]),
            "total": len(p["indices"]), "ready": True}


def card(title, href, info):
    badge = (f'<span class="ok">{info["green"]} at 6/6</span>' if info["ready"]
             else '<span class="no">not built yet</span>')
    return f"""
    <a class="card" href="{href}">
      <div class="t">{title}</div>
      <div class="m">Weekly · strict 6/6 · {info['total']} indices</div>
      <div class="row"><span class="as">Updated {info['as_of']}</span>{badge}</div>
    </a>"""


def main():
    sma = model_info("SMA")
    ema = model_info("EMA")
    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSE Index Trackers</title>
<style>
:root{{--bg:#0b0f14;--surface:#141a21;--line:#232c36;--ink:#e6edf3;--muted:#8b949e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
  min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}}
h1{{font-weight:800;letter-spacing:-.02em;margin:0 0 4px}}
.sub{{color:var(--muted);margin:0 0 28px;font-size:14px}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:18px;width:100%;max-width:720px}}
@media(max-width:620px){{.cards{{grid-template-columns:1fr}}}}
.card{{display:block;text-decoration:none;color:inherit;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;padding:20px;transition:border-color .15s,transform .15s}}
.card:hover{{border-color:#3fb950;transform:translateY(-2px)}}
.card .t{{font-size:22px;font-weight:800;margin-bottom:4px}}
.card .m{{color:var(--muted);font-size:13px;margin-bottom:14px}}
.card .row{{display:flex;justify-content:space-between;align-items:center;font-size:12.5px}}
.as{{color:var(--muted)}}
.ok{{color:#0b0f14;background:#3fb950;border-radius:6px;padding:2px 8px;font-weight:700}}
.no{{color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:2px 8px}}
</style></head><body>
<h1>NSE Index Trackers</h1>
<p class="sub">Six weekly moving averages · strict 6/6 scoring</p>
<div class="cards">{card('SMA model', 'dashboard_sma.html', sma)}{card('EMA model', 'dashboard_ema.html', ema)}</div>
</body></html>"""
    os.makedirs("data", exist_ok=True)
    with open("data/index.html", "w") as f:
        f.write(html)
    print("wrote data/index.html")


if __name__ == "__main__":
    main()
