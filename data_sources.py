"""
Data sources.

Live sources (used on the user's deployment):
  * SmartApiSource     - Angel One SmartAPI, free, datacenter-friendly auth API.
  * NiftyIndicesSource - niftyindices.com PUBLIC daily snapshot files (no account).
                         Builds history by reading the dated all-index CSVs, and reads
                         today's close from the latest one.
  * VixSource          - dedicated India VIX feed (SmartAPI / NSE all-indices / yfinance).

Offline source (tests + bundled demo, no network):
  * SyntheticSource

Heavy third-party imports are lazy so this module loads (and SyntheticSource works)
without smartapi-python / yfinance / requests installed.

The live HTTP paths could not be exercised from the build environment (no outbound
access to the exchanges); they self-report problems and are best-effort. See README.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

import numpy as np
import pandas as pd

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SCRIP_MASTER_URL = ("https://margincalculator.angelbroking.com/OpenAPI_File/files/"
                    "OpenAPIScripMaster.json")


def _norm(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\bindex\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ===========================================================================
# SmartAPI
# ===========================================================================
class SmartApiSource:
    name = "smartapi"

    def __init__(self):
        self._api = None
        self._token_by_norm = {}

    def _connect(self):
        if self._api is not None:
            return self._api
        from SmartApi import SmartConnect
        import pyotp
        api = SmartConnect(api_key=os.environ["SMARTAPI_KEY"])
        api.generateSession(os.environ["SMARTAPI_CLIENT_CODE"],
                            os.environ["SMARTAPI_MPIN"],
                            pyotp.TOTP(os.environ["SMARTAPI_TOTP_SECRET"]).now())
        self._api = api
        return api

    def _load_scrip_master(self):
        if self._token_by_norm:
            return
        import requests
        data = requests.get(SCRIP_MASTER_URL, headers={"User-Agent": UA}, timeout=60).json()
        for row in data:
            if row.get("exch_seg") == "NSE":
                nm = row.get("name") or row.get("symbol") or ""
                self._token_by_norm[_norm(nm)] = row.get("token")

    def resolve_token(self, name, nse_label):
        if name in config.SMARTAPI_TOKEN_OVERRIDES:
            return config.SMARTAPI_TOKEN_OVERRIDES[name]
        self._load_scrip_master()
        for cand in (nse_label, name):
            if cand and _norm(cand) in self._token_by_norm:
                return self._token_by_norm[_norm(cand)]
        return None

    def daily_history(self, name, nse_label, token, years) -> pd.Series:
        api = self._connect()
        if not token:
            return pd.Series(dtype="float64")
        end = dt.datetime.now()
        start = end - dt.timedelta(days=int(years * 365.25) + 10)
        frames, cur = [], start
        while cur < end:
            chunk_end = min(cur + dt.timedelta(days=1800), end)
            resp = api.getCandleData({
                "exchange": "NSE", "symboltoken": str(token), "interval": "ONE_DAY",
                "fromdate": cur.strftime("%Y-%m-%d %H:%M"),
                "todate": chunk_end.strftime("%Y-%m-%d %H:%M")})
            rows = (resp or {}).get("data") or []
            if rows:
                frames.append(pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"])[["ts", "c"]])
            cur = chunk_end + dt.timedelta(days=1)
        if not frames:
            return pd.Series(dtype="float64")
        allrows = pd.concat(frames, ignore_index=True).drop_duplicates("ts")
        idx = pd.to_datetime(allrows["ts"]).dt.tz_localize(None).dt.normalize()
        s = pd.Series(allrows["c"].astype(float).values, index=idx).sort_index()
        s.name = name
        return s

    def latest_close(self, name, nse_label, token):
        s = self.daily_history(name, nse_label, token, years=0.1)
        return (s.index.max().strftime("%Y-%m-%d"), float(s.iloc[-1])) if len(s) else None


# ===========================================================================
# niftyindices.com PUBLIC daily snapshots  (no account needed)
# ===========================================================================
class NiftyIndicesSource:
    name = "niftyindices"

    def __init__(self):
        self._session = None
        self._snap_cache = {}      # "DDMMYYYY" -> {norm_label: (date_str, close)}
        self._blocked = False      # set once NSE stops responding -> fail fast
        self._fail_streak = 0

    def _sess(self):
        if self._session is not None:
            return self._session
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Referer": "https://www.niftyindices.com/"})
        try:                       # prime cookies / pass the bot check
            s.get("https://www.niftyindices.com/", timeout=15)
        except Exception:
            pass
        self._session = s
        return s

    def _load_snapshot(self, date: dt.date):
        key = date.strftime("%d%m%Y")
        if key in self._snap_cache:
            return self._snap_cache[key]
        if self._blocked:
            raise RuntimeError("source unavailable")
        import io
        url = f"https://niftyindices.com/Daily_Snapshot/ind_close_all_{key}.csv"
        try:
            content = self._sess().get(url, timeout=12).content
            df = pd.read_csv(io.BytesIO(content))
            df.columns = [c.strip() for c in df.columns]
            name_col = next(c for c in df.columns if "Index Name" in c)
            close_col = next(c for c in df.columns if "Closing" in c)
            date_col = next((c for c in df.columns if "Date" in c), None)
            out = {}
            for _, r in df.iterrows():
                dd = str(r[date_col]) if date_col else date.strftime("%d-%m-%Y")
                out[_norm(str(r[name_col]))] = (dd, float(r[close_col]))
            self._snap_cache[key] = out
            self._fail_streak = 0
            return out
        except Exception:
            self._fail_streak += 1
            if self._fail_streak >= 8:        # NSE clearly not serving us -> stop trying
                self._blocked = True
            raise

    @staticmethod
    def _match(snap, label):
        key = _norm(label)
        # Exact match only, with a single trailing-"s" tolerance (market/markets).
        # Deliberately NO prefix/substring matching: that would let "nifty 50"
        # silently grab "nifty 500", producing wrong-but-plausible data.
        for cand in (key, key + "s", key[:-1] if key.endswith("s") else ""):
            if cand and cand in snap:
                return snap[cand]
        return None

    def latest_close(self, name, nse_label, token):
        for back in range(0, 6):           # skip weekends/holidays
            try:
                snap = self._load_snapshot(dt.date.today() - dt.timedelta(days=back))
            except Exception:
                continue
            hit = self._match(snap, nse_label or name)
            if hit:
                return hit
        return None

    def _weekly_from_snapshots(self, label, years) -> pd.Series:
        end = dt.date.today()
        years = min(years, 6.5)            # ~338 weeks: plenty for a 200-week SMA, fewer requests
        start = end - dt.timedelta(days=int(years * 365.25))
        fridays = pd.date_range(start, end, freq="W-FRI")
        rows = []
        for i, fri in enumerate(fridays):
            if self._blocked:
                break
            val = None
            for back in range(0, 5):       # Fri, then Thu..Mon if Fri was a holiday
                day = (fri - pd.Timedelta(days=back)).date()
                if day > end:
                    continue
                try:
                    snap = self._load_snapshot(day)
                except Exception:
                    continue
                hit = self._match(snap, label)
                if hit:
                    val = (pd.Timestamp(fri.date()), float(hit[1]))
                    break
            if val:
                rows.append(val)
            if (i + 1) % 25 == 0:
                print(f"        ...{len(rows)}/{i + 1} weeks fetched", flush=True)
            time.sleep(0.2)
        if not rows:
            return pd.Series(dtype="float64")
        s = pd.Series([c for _, c in rows], index=[d for d, _ in rows]).sort_index()
        s.name = label
        return s

    def _backpage_history(self, label, years) -> pd.Series:
        end = dt.date.today()
        start = end - dt.timedelta(days=int(years * 365.25))
        cinfo = json.dumps({"name": label, "startDate": start.strftime("%d-%b-%Y"),
                            "endDate": end.strftime("%d-%b-%Y"), "indexName": label})
        r = self._sess().post(
            "https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString",
            data=json.dumps({"cinfo": cinfo}),
            headers={"Content-Type": "application/json; charset=UTF-8"}, timeout=25)
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
        s = pd.Series([c for _, c in rows], index=[d for d, _ in rows])
        s.name = label
        return s

    def _daily_from_snapshots(self, label, years) -> pd.Series:
        """Assemble a DAILY series from the public dated CSVs (one per trading day).
        Slow (many requests); used only if the per-index endpoint is unavailable."""
        end = dt.date.today()
        years = min(years, 1.5)
        start = end - dt.timedelta(days=int(years * 365.25))
        rows, day, seen = [], start, 0
        while day <= end:
            if self._blocked:
                break
            if day.weekday() < 5:               # weekdays only (holidays just 404)
                try:
                    hit = self._match(self._load_snapshot(day), label)
                    if hit:
                        rows.append((pd.Timestamp(day), float(hit[1])))
                except Exception:
                    pass
                seen += 1
                if seen % 25 == 0:
                    print(f"        ...{len(rows)}/{seen} days fetched", flush=True)
                time.sleep(0.2)
            day += dt.timedelta(days=1)
        if not rows:
            return pd.Series(dtype="float64")
        s = pd.Series([c for _, c in rows], index=[d for d, _ in rows]).sort_index()
        s.name = label
        return s

    def daily_history(self, name, nse_label, token, years) -> pd.Series:
        label = nse_label or name
        if config.SMA_BASIS == "daily":
            # daily SMAs need a full daily series. Per-index endpoint first (few requests),
            # then daily-snapshot accumulation (slow) as a fallback.
            try:
                s = self._backpage_history(label, years)
                if len(s) >= 20:
                    return s
            except Exception:
                pass
            return self._daily_from_snapshots(label, min(years, 1.5))
        # weekly basis: Friday snapshots are enough
        s = self._weekly_from_snapshots(label, years)
        if len(s) >= 5:
            return s
        try:
            return self._backpage_history(label, years)
        except Exception:
            return s


# ===========================================================================
# India VIX (dedicated feed)
# ===========================================================================
class VixSource:
    name = "vix"

    def __init__(self, smartapi: "SmartApiSource | None" = None):
        self._smartapi = smartapi

    def daily_history(self, name, nse_label, token, years) -> pd.Series:
        for src in config.VIX_SOURCE_ORDER:
            try:
                if src == "smartapi" and self._smartapi is not None:
                    tok = self._smartapi.resolve_token("India VIX", "India VIX")
                    s = self._smartapi.daily_history("India VIX", "India VIX", tok, years)
                    if len(s):
                        return s
                elif src == "yfinance":
                    import yfinance as yf
                    df = yf.download("^INDIAVIX", period=f"{int(years)}y", interval="1d",
                                     progress=False, auto_adjust=False)
                    if df is not None and len(df):
                        s = df["Close"].dropna()
                        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                        s.name = "India VIX"
                        return s
            except Exception:
                continue
        return pd.Series(dtype="float64")

    def latest_close(self, name, nse_label, token):
        for src in config.VIX_SOURCE_ORDER:
            try:
                if src == "nse_all_indices":
                    import requests
                    s = requests.Session()
                    s.headers.update({"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
                    s.get("https://www.nseindia.com/", timeout=30)
                    data = s.get("https://www.nseindia.com/api/allIndices", timeout=30).json()
                    for row in data.get("data", []):
                        if _norm(row.get("index", "")) == _norm("India VIX"):
                            return (dt.date.today().strftime("%Y-%m-%d"), float(row["last"]))
            except Exception:
                continue
        s = self.daily_history(name, nse_label, token, years=0.2)
        return (s.index.max().strftime("%Y-%m-%d"), float(s.iloc[-1])) if len(s) else None


# ===========================================================================
# Yahoo Finance (primary source — no account, works from datacenter IPs)
# ===========================================================================
SEED_DIR = "data/seeds"


def _seed_path(name: str) -> str:
    fname = name.replace(" ", "_").replace("&", "and").replace("/", "_")
    return os.path.join(SEED_DIR, f"{fname}.csv")


def _load_seed(name: str) -> pd.Series:
    """Return pre-seeded historical Close series, or empty Series if not found."""
    path = _seed_path(name)
    if not os.path.exists(path):
        return pd.Series(dtype="float64")
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        s = df.iloc[:, 0].dropna()
        idx = pd.to_datetime(s.index)
        if hasattr(idx, "tz") and idx.tz is not None:
            idx = idx.tz_convert(None)
        idx = idx.normalize()
        s = pd.Series(s.values, index=idx, name=name)
        return s[~s.index.duplicated(keep="last")].sort_index()
    except Exception:
        return pd.Series(dtype="float64")


class YFinanceSource:
    """Downloads ALL tickers in ONE batch call to avoid Yahoo Finance rate-limiting.

    When called 37 times individually from a datacenter IP (GitHub Actions),
    Yahoo Finance throttles after ~14 calls and returns empty data for the rest.
    A single batch download bypasses this completely.
    """
    name = "yfinance"

    def __init__(self):
        self._cache: dict[str, pd.Series] = {}
        self._ready = False

    def _prefetch(self):
        """Individual download per ticker with 1-second delays.

        Yahoo Finance's bulk download endpoint silently drops many NSE index tickers
        (those using ^ prefix that aren't in the bulk-index whitelist). Individual
        calls with rate-limit delays are slower but fully reliable from datacenter IPs.
        """
        if self._ready:
            return
        import yfinance as yf
        import time

        ticker_map = {name: tkr for name, tkr in config.YFINANCE_TICKERS.items() if tkr}
        if not ticker_map:
            self._ready = True
            return

        print(f"  [yf] Fetching {len(ticker_map)} tickers individually...", flush=True)
        for name, ticker in ticker_map.items():
            time.sleep(1.0)   # 1 s gap — keeps us under Yahoo Finance rate limit
            s = self._fetch_one(yf, ticker, name)
            self._cache[name] = s
            if len(s) >= 10:
                print(f"  [yf] OK {name} ({ticker}): {len(s)} rows", flush=True)
            else:
                print(f"  [yf] EMPTY/SHORT {name} ({ticker}): {len(s)} rows", flush=True)

        self._ready = True

    @staticmethod
    def _fetch_one(yf, ticker: str, name: str) -> pd.Series:
        """Fetch 5y daily close for one ticker.

        Strategy:
          1. yf.download() with period="5y"  — fast, works for most ^ tickers
          2. If <10 rows and .NS ticker: Ticker().history() — different endpoint,
             works for .NS index tickers that download() underserves
          3. If still <10 rows: Ticker().history(period="max") — catches anything
             newer than 5y or with a short-history quirk
        """

        def _clean(raw) -> pd.Series:
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
            s = pd.Series(s.values, index=idx, name=name)
            return s[~s.index.duplicated(keep="last")].sort_index()

        # --- attempt 1: download() ---
        try:
            raw = yf.download(ticker, period="5y", interval="1d",
                              progress=False, auto_adjust=False)
            s = _clean(raw)
        except Exception:
            s = pd.Series(dtype="float64")

        if len(s) >= 10:
            return s

        # --- attempt 2: Ticker().history() for .NS tickers (different API path) ---
        if ticker.endswith(".NS"):
            try:
                time.sleep(0.5)
                raw = yf.Ticker(ticker).history(period="5y", interval="1d",
                                                auto_adjust=False)
                s2 = _clean(raw)
                if len(s2) > len(s):
                    s = s2
            except Exception:
                pass

        if len(s) >= 10:
            return s

        # --- attempt 3: period="max" (catches short-history indices) ---
        if ticker.endswith(".NS"):
            try:
                time.sleep(0.5)
                raw = yf.Ticker(ticker).history(period="max", interval="1d",
                                                auto_adjust=False)
                s3 = _clean(raw)
                if len(s3) > len(s):
                    s = s3
            except Exception:
                pass

        return s

    def daily_history(self, name, nse_label, token, years) -> pd.Series:
        if not config.YFINANCE_TICKERS.get(name):
            return pd.Series(dtype="float64")

        # Load seed (provides full multi-year history for SMA calculation)
        seed = _load_seed(name)

        # Always try live data too — it extends the seed with recent prices
        try:
            self._prefetch()
            live = self._cache.get(name, pd.Series(dtype="float64"))
        except Exception:
            live = pd.Series(dtype="float64")

        # Merge: seed covers history, live adds recent data on top
        if len(seed) > 0 and len(live) > 0:
            combined = pd.concat([seed, live])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            return combined
        if len(seed) >= 200:
            return seed          # no live data — seed alone is sufficient for SMA
        if len(live) > 0:
            return live          # no seed yet — use live directly
        return pd.Series(dtype="float64")

    def latest_close(self, name, nse_label, token):
        if not config.YFINANCE_TICKERS.get(name):
            return None
        # Try live cache first (today's price)
        try:
            self._prefetch()
            live = self._cache.get(name, pd.Series(dtype="float64"))
            if len(live) > 0:
                return (live.index.max().strftime("%Y-%m-%d"), float(live.iloc[-1]))
        except Exception:
            pass
        # Fall back to seed — shows last seeded price rather than a blank "—"
        seed = _load_seed(name)
        if len(seed) > 0:
            return (seed.index.max().strftime("%Y-%m-%d"), float(seed.iloc[-1]))
        return None


# ===========================================================================
# Synthetic (offline tests + demo)
# ===========================================================================
class SyntheticSource:
    name = "synthetic"

    def __init__(self, ages_years=None, seed=7):
        self.ages = ages_years or {}
        self.seed = seed

    def _age(self, name):
        if name in self.ages:
            return self.ages[name]
        return [1.2, 1.8, 3.0, 9.0][sum(ord(c) for c in name) % 4]

    def daily_history(self, name, nse_label, token, years) -> pd.Series:
        rng = np.random.default_rng(self.seed + (sum(ord(c) for c in name) % 1000))
        age = self._age(name)
        idx = pd.bdate_range(end=pd.Timestamp(dt.date.today()), periods=max(int(age * 252), 6))
        n = len(idx)                                   # use actual length (bdate_range can differ by 1)
        boosted = (sum(ord(c) for c in name) % 3) == 0
        rets = rng.normal(rng.uniform(-0.0004, 0.0009), rng.uniform(0.008, 0.02), size=n)
        if boosted:
            rets += 0.0009                             # sustained uptrend -> above all daily SMAs
            rets[-60:] += 0.002
        price = 1000 * np.exp(np.cumsum(rets))
        if name == "India VIX":
            price = np.clip(14 + np.cumsum(rng.normal(0, 0.3, size=n)), 8, 35)
        full = pd.Series(price, index=idx)
        full.name = name
        keep = max(int(min(years, age) * 252), 6)
        return full.iloc[-keep:]

    def latest_close(self, name, nse_label, token):
        s = self.daily_history(name, nse_label, token, years=self._age(name))
        return (s.index.max().strftime("%Y-%m-%d"), float(s.iloc[-1]))


# ===========================================================================
# Resolver + factory
# ===========================================================================
def resolve_mappings(primary):
    name_map, unmatched = {}, []
    for item in config.INDICES:
        name = item["name"]
        nse_label = config.NSE_LABEL_OVERRIDES.get(name, name)
        token = None
        if primary is not None:
            try:
                token = primary.resolve_token(name, nse_label)
            except Exception:
                token = None
            if token is None and not config.is_volatility(name):
                unmatched.append(name)
        name_map[name] = {"nse_label": nse_label, "smartapi_token": token}
    return name_map, unmatched


def get_sources(use_synthetic: bool = False):
    """Return (equity_source, fallback_source, vix_source, primary_for_tokens).

    Primary source is Yahoo Finance (yfinance) — no account needed, works from
    GitHub Actions / datacenter IPs.  NiftyIndices is kept as a fallback for any
    index yfinance cannot supply (YFINANCE_TICKERS entry is None).
    primary_for_tokens is None because yfinance does not use SmartAPI scrip-master
    tokens; tickers are looked up directly from config.YFINANCE_TICKERS.
    """
    if use_synthetic:
        syn = SyntheticSource()
        return syn, syn, syn, None
    yf_src = YFinanceSource()
    nifty = NiftyIndicesSource()
    return yf_src, nifty, yf_src, None
