"""
Scoring logic. Pure functions — unit-testable, no I/O.

Two SMA bases (config.SMA_BASIS):
  * "daily"  : SMAs on DAILY closes, periods 5/10/20/50/100/200 DAYS  (matches
               MoneyControl-style daily technicals). Score = today's close vs those.
  * "weekly" : SMAs on WEEKLY closes, periods in WEEKS.

Strict /6 either way: a SMA that can't be computed yet counts as NOT crossed; score is
always "n/6"; green panel == crossed == 6. The history table always shows one row per
week (Friday); under the daily basis each weekly row is scored on daily SMAs as of that day.
"""
from __future__ import annotations

import pandas as pd

import config


def _clean(daily_close: pd.Series) -> pd.Series:
    if daily_close is None or len(daily_close) == 0:
        return pd.Series(dtype="float64")
    s = daily_close.dropna().sort_index()
    s.index = pd.to_datetime(s.index)
    return s


# ---------------------------------------------------------------------------
# Weekly series (weekly basis only)
# ---------------------------------------------------------------------------
def to_weekly(daily_close: pd.Series, include_forming: bool) -> pd.Series:
    s = _clean(daily_close)
    if len(s) == 0:
        return s
    weekly = s.resample(f"W-{config.WEEK_ENDING_DAY}").last().dropna()
    if not include_forming and len(weekly) > 0:
        if s.index.max() < weekly.index.max():      # final bucket still forming
            weekly = weekly.iloc[:-1]
    return weekly


# ---------------------------------------------------------------------------
# Moving average (SMA or EMA per config.MA_TYPE)
# ---------------------------------------------------------------------------
def _ma(closes: pd.Series, period: int) -> pd.Series:
    """Moving-average series. NaN until `period` observations exist (so EMA stays
    strict-symmetric with SMA: a line that doesn't have enough history is 'not crossed')."""
    if config.MA_TYPE.upper() == "EMA":
        ema = closes.ewm(span=period, adjust=False).mean()
        enough = pd.Series(range(1, len(closes) + 1), index=closes.index) >= period
        return ema.where(enough)
    return closes.rolling(period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Score a single point (generic: pass whichever series — weekly or daily)
# ---------------------------------------------------------------------------
def score_last(series: pd.Series, periods=None) -> dict:
    periods = periods or config.SMA_PERIODS
    close = float(series.iloc[-1])
    crossed = available = 0
    smas = {}
    for p in periods:
        v = _ma(series, p).iloc[-1]
        if pd.notna(v):
            v = float(v)
            smas[p] = v
            available += 1
            if close > v:
                crossed += 1
        else:
            smas[p] = None
    return {"close": close, "crossed": crossed, "available": available,
            "score_label": f"{crossed}/{len(periods)}", "smas": smas}


def color_for(crossed: int) -> str:
    return config.COLOR_MAP.get(crossed, config.COLOR_MAP[0])


# ---------------------------------------------------------------------------
# Archive: score every week with NO look-ahead
# ---------------------------------------------------------------------------
def _crossed_series(closes: pd.Series, periods) -> pd.Series:
    """Per-row strict crossed-count over `closes` (rolling, no look-ahead)."""
    crossed = pd.Series(0, index=closes.index, dtype="int64")
    for p in periods:
        ma = _ma(closes, p)
        crossed = crossed + (closes > ma).fillna(False).astype("int64")
    return crossed


def archive_weekly(weekly_completed: pd.Series, periods) -> pd.DataFrame:
    """Weekly-basis archive: weekly close vs weekly SMAs, one row per completed week."""
    if len(weekly_completed) == 0:
        return pd.DataFrame(columns=["close", "crossed", "score_label"])
    close = weekly_completed.astype("float64")
    crossed = _crossed_series(close, periods)
    out = pd.DataFrame({"close": close, "crossed": crossed})
    out["score_label"] = out["crossed"].astype(str) + f"/{len(periods)}"
    return out


def archive_daily_sampled_weekly(daily_close: pd.Series, periods) -> pd.DataFrame:
    """Daily-basis archive: daily SMAs computed on the daily series, then sampled at each
    week-end (Friday / last trading day) so the table still shows one row per week."""
    s = _clean(daily_close)
    if len(s) == 0:
        return pd.DataFrame(columns=["close", "crossed", "score_label"])
    crossed_daily = _crossed_series(s, periods)
    wk_close = s.resample(f"W-{config.WEEK_ENDING_DAY}").last()
    wk_crossed = crossed_daily.resample(f"W-{config.WEEK_ENDING_DAY}").last()
    out = pd.DataFrame({"close": wk_close, "crossed": wk_crossed}).dropna()
    out["crossed"] = out["crossed"].astype("int64")
    out["score_label"] = out["crossed"].astype(str) + f"/{len(periods)}"
    return out


# ---------------------------------------------------------------------------
# Evaluate one index (branches on SMA basis)
# ---------------------------------------------------------------------------
def _nodata(name):
    return {"name": name, "status": "nodata", "crossed": None, "score_label": "—",
            "color": config.INSUFFICIENT_COLOR, "close": None, "available": 0,
            "smas": {}, "archive": pd.DataFrame()}


def _insufficient(name, close):
    return {"name": name, "status": "insufficient", "crossed": None,
            "score_label": "insufficient", "color": config.INSUFFICIENT_COLOR,
            "close": close, "available": 0, "smas": {}, "archive": pd.DataFrame()}


def evaluate_index(name: str, daily_close: pd.Series, periods=None) -> dict:
    periods = periods or config.SMA_PERIODS
    s = _clean(daily_close)
    if len(s) == 0:
        return _nodata(name)
    need = min(periods)   # need at least the smallest SMA to score at all

    if config.SMA_BASIS == "daily":
        if len(s) < need:
            return _insufficient(name, float(s.iloc[-1]))
        live = score_last(s, periods)                       # today vs daily SMAs
        arch = archive_daily_sampled_weekly(s, periods)
    else:
        weekly_completed = to_weekly(s, include_forming=False)
        if len(weekly_completed) < config.MIN_WEEKS_TO_SCORE:
            last = float(weekly_completed.iloc[-1]) if len(weekly_completed) else float(s.iloc[-1])
            return _insufficient(name, last)
        weekly_live = to_weekly(s, include_forming=config.WEEKLY_SMA_INCLUDES_FORMING_WEEK)
        live = score_last(weekly_live, periods)             # forming week vs weekly SMAs
        arch = archive_weekly(weekly_completed, periods)

    return {"name": name, "status": "ok", "close": live["close"],
            "crossed": live["crossed"], "available": live["available"],
            "score_label": live["score_label"], "color": color_for(live["crossed"]),
            "smas": live["smas"], "archive": arch}


# ---------------------------------------------------------------------------
# Panels + "entered 6/6 today"
# ---------------------------------------------------------------------------
def assign_panels(results: list[dict], prev_crossed: dict | None) -> dict:
    prev_crossed = prev_crossed or {}
    full = len(config.SMA_PERIODS)
    green, rest, entered = [], [], []
    for r in results:
        r["entered_full_today"] = False
        if r["status"] == "ok" and r["crossed"] == full:
            green.append(r["name"])
            prev = prev_crossed.get(r["name"])
            if prev is not None and prev < full:
                entered.append(r["name"])
                r["entered_full_today"] = True
        else:
            rest.append(r["name"])
    green.sort()
    order = {r["name"]: r for r in results}

    def rest_key(n):
        c = order[n]["crossed"]
        return (-(c if c is not None else -1), n)

    rest.sort(key=rest_key)
    entered.sort()
    return {"green": green, "rest": rest, "entered_today": entered}
