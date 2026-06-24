"""
seed_history.py  —  run ONCE locally to create seed CSV files.

These CSV files are committed to the repo so GitHub Actions can read
historical data without hitting Yahoo Finance from datacenter IPs.

Four-tier fetch strategy (tried in order until >=200 rows):
  1. yf.download() daily                  (fast, works for ^ tickers)
  2. yf.Ticker().history() weekly         (works for .NS tickers that reject daily)
  3. NiftyIndices Backpage API            (fallback for indices YF doesn't cover)
  4. NiftyIndices weekly snapshots        (definitive fallback — downloads Fri CSVs)

Usage:
    python seed_history.py
"""
import os
import json
import time
import datetime as dt
import pandas as pd
import requests
import yfinance as yf
import config

SEED_DIR = "data/seeds"
os.makedirs(SEED_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

_nifty_session = None
_nifty_src = None   # NiftyIndicesSource instance shared across all indices (shares snapshot cache)


def safe_name(name: str) -> str:
    return name.replace(" ", "_").replace("&", "and").replace("/", "_")


def _clean_yf(raw, name: str) -> pd.Series:
    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return pd.Series(dtype="float64")
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna()
    if len(s) == 0:
        return pd.Series(dtype="float64")
    idx = pd.to_datetime(s.index)
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_convert(None)
    idx = idx.normalize()
    s = pd.Series(s.values, index=idx, name="Close")
    return s[~s.index.duplicated(keep="last")].sort_index()


def fetch_yfinance(ticker: str, name: str) -> pd.Series:
    """Four attempts: daily download, daily Ticker, weekly Ticker (date range), weekly download."""
    s = pd.Series(dtype="float64")
    start_str = (dt.date.today() - dt.timedelta(days=int(5.5 * 365.25))).strftime("%Y-%m-%d")
    end_str   = dt.date.today().strftime("%Y-%m-%d")

    # Attempt 1: yf.download() daily period="5y"
    try:
        raw = yf.download(ticker, period="5y", interval="1d",
                          progress=False, auto_adjust=False)
        s = _clean_yf(raw, name)
        if len(s) >= 200:
            return s
    except Exception:
        pass

    # Attempt 2: Ticker().history() daily period="5y"
    try:
        time.sleep(0.5)
        raw = yf.Ticker(ticker).history(period="5y", interval="1d", auto_adjust=False)
        s2 = _clean_yf(raw, name)
        if len(s2) > len(s):
            s = s2
        if len(s) >= 200:
            return s
    except Exception:
        pass

    # Attempt 3: Ticker().history() WEEKLY with explicit date range
    # Some .NS tickers reject period="5y" with interval="1d" but accept interval="1wk"
    try:
        time.sleep(0.5)
        raw = yf.Ticker(ticker).history(start=start_str, end=end_str,
                                        interval="1wk", auto_adjust=False)
        s3 = _clean_yf(raw, name)
        if len(s3) > len(s):
            s = s3
        if len(s) >= 200:
            return s
    except Exception:
        pass

    # Attempt 4: yf.download() WEEKLY with explicit date range
    try:
        time.sleep(0.5)
        raw = yf.download(ticker, start=start_str, end=end_str,
                          interval="1wk", progress=False, auto_adjust=False)
        s4 = _clean_yf(raw, name)
        if len(s4) > len(s):
            s = s4
    except Exception:
        pass

    return s


def fetch_niftyindices_backpage(label: str, years: float = 5.5) -> pd.Series:
    """Fetch daily history from NiftyIndices Backpage API."""
    global _nifty_session
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365.25))

    if _nifty_session is None:
        _nifty_session = requests.Session()
        _nifty_session.headers.update({
            "User-Agent": UA,
            "Referer": "https://www.niftyindices.com/",
        })
        try:
            _nifty_session.get("https://www.niftyindices.com/", timeout=15)
        except Exception:
            pass

    cinfo = json.dumps({
        "name": label,
        "startDate": start.strftime("%d-%b-%Y"),
        "endDate": end.strftime("%d-%b-%Y"),
        "indexName": label,
    })
    r = _nifty_session.post(
        "https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString",
        data=json.dumps({"cinfo": cinfo}),
        headers={"Content-Type": "application/json; charset=UTF-8"},
        timeout=30,
    )
    recs = json.loads(r.json()["d"])
    rows = []
    for rec in recs:
        d = rec.get("HistoricalDate") or rec.get("Date")
        c = rec.get("CLOSE") or rec.get("Close") or rec.get("close")
        if d and c not in (None, ""):
            rows.append((pd.to_datetime(d), float(c)))
    if not rows:
        return pd.Series(dtype="float64")
    rows.sort()
    s = pd.Series([c for _, c in rows], index=[d for d, _ in rows], name="Close")
    idx = pd.to_datetime(s.index)
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_convert(None)
    idx = idx.normalize()
    s = pd.Series(s.values, index=idx, name="Close")
    return s[~s.index.duplicated(keep="last")].sort_index()


def fetch_niftyindices_weekly_snapshots(label: str, years: float = 5.5) -> pd.Series:
    """
    Definitive fallback: download one Friday snapshot CSV per week from NiftyIndices.
    Slow (many HTTP requests) but works for ALL indices from residential IPs.
    Uses a shared NiftyIndicesSource instance so snapshot CSVs are cached across indices.
    """
    global _nifty_src
    if _nifty_src is None:
        from data_sources import NiftyIndicesSource
        _nifty_src = NiftyIndicesSource()
    s = _nifty_src._weekly_from_snapshots(label, years=years)
    if len(s) == 0:
        return pd.Series(dtype="float64")
    # Normalize index
    idx = pd.to_datetime(s.index)
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_convert(None)
    idx = idx.normalize()
    s = pd.Series(s.values, index=idx, name="Close")
    return s[~s.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# Main seeding loop
# ---------------------------------------------------------------------------
total = len(config.YFINANCE_TICKERS)
ok, failed = [], []

for i, (name, ticker) in enumerate(config.YFINANCE_TICKERS.items(), 1):
    path = os.path.join(SEED_DIR, f"{safe_name(name)}.csv")

    # Skip if seed already exists and is large enough
    if os.path.exists(path):
        try:
            existing = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(existing) >= 200:
                print(f"[{i}/{total}] {name}: already seeded ({len(existing)} rows) — skipping")
                ok.append(name)
                continue
        except Exception:
            pass

    print(f"[{i}/{total}] {name} ({ticker})...", end=" ", flush=True)
    s = pd.Series(dtype="float64")
    source_used = "—"

    # --- Tier 1: Yahoo Finance (4 attempts) ---
    if ticker:
        s = fetch_yfinance(ticker, name)
        if len(s) >= 200:
            source_used = "yfinance"

    # --- Tier 2: NiftyIndices Backpage API ---
    if len(s) < 200:
        nse_label = config.NSE_LABEL_OVERRIDES.get(name, name)
        try:
            s2 = fetch_niftyindices_backpage(nse_label, years=5.5)
            if len(s2) > len(s):
                s = s2
            if len(s) >= 200:
                source_used = "niftyindices_backpage"
        except Exception as e:
            print(f"\n  [backpage] failed: {e}", end=" ", flush=True)

    # --- Tier 3: NiftyIndices weekly snapshots (slowest but most reliable) ---
    if len(s) < 200:
        nse_label = config.NSE_LABEL_OVERRIDES.get(name, name)
        print(f"\n  → trying weekly snapshots for {nse_label}...", end=" ", flush=True)
        try:
            s3 = fetch_niftyindices_weekly_snapshots(nse_label, years=5.5)
            if len(s3) > len(s):
                s = s3
            if len(s) >= 200:
                source_used = "niftyindices_snapshots"
        except Exception as e:
            print(f"\n  [snapshots] failed: {e}", end=" ", flush=True)

    if len(s) >= 200:
        s.to_csv(path, header=True)
        print(f"{len(s)} rows  ✓  [{source_used}]")
        ok.append(name)
    else:
        print(f"FAILED — only {len(s)} rows after all 3 tiers")
        failed.append(f"{name} ({ticker})")

print(f"\n{'='*60}")
print(f"Saved: {len(ok)}/{total}")
if failed:
    print(f"Failed ({len(failed)}):")
    for n in failed:
        print(f"  ✗ {n}")
else:
    print("All indices seeded successfully!")

print("\nNext step: run  bash go13.sh  to commit and push the seed files.")
