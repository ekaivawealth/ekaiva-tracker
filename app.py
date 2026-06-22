"""
Streamlit dashboard (the VPS / Streamlit-Cloud deployment path).

    streamlit run app.py

Reads the stored snapshot (written by jobs.run_daily). It never fetches in the page
render path; the "Refresh now" button explicitly triggers a fetch.
"""
from __future__ import annotations

import streamlit as st

import config
import store

st.set_page_config(page_title="Index SMA Tracker", layout="wide")

CSS = """
<style>
.block-container{padding-top:1.2rem}
.row{display:grid;grid-template-columns:1fr auto 150px;align-items:center;gap:10px;
  padding:7px 4px;border-bottom:1px solid #232c36;font-size:14px}
.nm{font-weight:600} .rt{color:#8b949e;text-align:right}
.pips{display:inline-flex;gap:3px;justify-content:flex-end}
.pips i{width:13px;height:8px;border-radius:2px;background:#2a333d;display:inline-block}
.lbl{font-weight:700;font-size:12px;margin-left:8px}
.phead{padding:8px 12px;color:#fff;font-weight:700;border-radius:8px 8px 0 0}
.g{background:#1a7f37} .r{background:#b3261e}
.vixflag{font-size:9px;color:#c084fc;border:1px solid #6d4a8f;border-radius:4px;padding:0 4px;margin-left:6px}
.new{font-size:9px;color:#0b0f14;background:#3fb950;border-radius:4px;padding:1px 5px;margin-left:6px;font-weight:800}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def pips_html(crossed, full, color, label):
    if crossed is None:
        cells = "".join('<i></i>' for _ in range(full))
        return f'<span class="pips">{cells}</span><span class="lbl" style="color:#6b7280">{label}</span>'
    cells = "".join(
        f'<i style="background:{color}"></i>' if k < crossed else '<i></i>'
        for k in range(full))
    return f'<span class="pips">{cells}</span><span class="lbl" style="color:{color}">{label}</span>'


def row_html(name, info, full):
    flag = '<span class="vixflag">VIX</span>' if info.get("is_volatility") else ""
    new = '<span class="new">NEW</span>' if info.get("entered_full_today") else ""
    close = "—" if info["close"] is None else f'{info["close"]:,.2f}'
    return (f'<div class="row"><div class="nm">{name}{flag}{new}</div>'
            f'<div class="rt">{close}</div>'
            f'<div style="text-align:right">{pips_html(info["crossed"], full, info["color"], info["score_label"])}</div></div>')


def panel(title, css, names, idx, full):
    st.markdown(f'<div class="phead {css}">{title} · {len(names)}</div>', unsafe_allow_html=True)
    if not names:
        st.caption("Nothing here right now.")
    for n in names:
        st.markdown(row_html(n, idx[n], full), unsafe_allow_html=True)


payload = store.load_snapshot()

c1, c2 = st.columns([4, 1])
c1.title("Index SMA Tracker")
if c2.button("↻ Refresh now", use_container_width=True):
    with st.spinner("Fetching latest closes and recomputing…"):
        from jobs.run_daily import run
        run(force=True)
    st.rerun()

if not payload:
    st.warning("No snapshot yet. Run:  python -m jobs.run_daily --force  (add --synthetic for demo data).")
    st.stop()

full = payload["full"]
idx = payload["indices"]
st.caption(f"Latest data updated on: **{payload['as_of']}**  ·  generated {payload['generated_at']}")

st.subheader("Entered 6/6 today")
if payload["panels"]["entered_today"]:
    for n in payload["panels"]["entered_today"]:
        st.markdown(row_html(n, idx[n], full), unsafe_allow_html=True)
else:
    st.caption("Nothing crossed into 6/6 today yet. (Resets each trading day.)")

st.divider()
left, right = st.columns(2)
with left:
    panel("Green Alert · 6/6", "g", payload["panels"]["green"], idx, full)
with right:
    panel("Everything else", "r", payload["panels"]["rest"], idx, full)

st.divider()
st.subheader("Weekly history")
pick = st.selectbox("Index", config.index_names())
info = idx.get(pick)
if info:
    st.caption(f'Live: {("—" if info["close"] is None else f"{info["close"]:,.2f}")} · {info["score_label"]}'
               + (" · VIX (high = fear, not strength)" if info.get("is_volatility") else ""))
    rows = [{"Date": f"{payload['as_of']} (live)",
             "Close": info["close"], "Score": info["score_label"]}]
    for r in info.get("archive", []):
        rows.append({"Date": r["week_ending"], "Close": r["close"], "Score": r["score_label"]})
    st.dataframe(rows, use_container_width=True, hide_index=True)
