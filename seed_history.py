"""
seed_history.py  —  run ONCE locally to create seed CSV files.

These CSV files are committed to the repo so GitHub Actions can read
historical data without hitting Yahoo Finance from datacenter IPs.

Usage:
    python seed_history.py
"""
import os
import pandas as pd
import yfinance as yf
import config

SEED_DIR = "data/seeds"
os.makedirs(SEED_DIR, exist_ok=True)

def safe_name(name: str) -> str:
    return name.replace(" ", "_").replace("&", "and").replace("/", "_")

total = len(config.YFINANCE_TICKERS)
ok, empty = [], []

for i, (name, ticker) in enumerate(config.YFINANCE_TICKERS.items(), 1):
    print(f"[{i}/{total}] {name} ({ticker})...", end=" ", flush=True)
    try:
        df = yf.download(ticker, period="5y", interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            raise ValueError("empty")

        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        s = close.dropna()

        if len(s) < 10:
            raise ValueError(f"only {len(s)} rows")

        idx = pd.to_datetime(s.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        idx = idx.normalize()
        s = pd.Series(s.values, index=idx, name="Close")
        s = s[~s.index.duplicated(keep="last")].sort_index()

        path = os.path.join(SEED_DIR, f"{safe_name(name)}.csv")
        s.to_csv(path, header=True)
        print(f"{len(s)} rows  ✓")
        ok.append(name)

    except Exception as e:
        print(f"FAILED: {e}")
        empty.append(f"{name} ({ticker})")

print(f"\n{'='*50}")
print(f"Saved: {len(ok)}/{total}")
if empty:
    print(f"Failed ({len(empty)}):")
    for n in empty:
        print(f"  ✗ {n}")

print("\nNext step: run  bash go12.sh  to commit and push these seed files.")
