"""
Daily job.

Run on every NSE trading day after ~18:30 IST:
  python -m jobs.run_daily                  # live sources
  python -m jobs.run_daily --force          # ignore the trading-day gate
  python -m jobs.run_daily --synthetic --force   # offline demo data
  python -m jobs.run_daily --backfill-years 8

Idempotent: safe to re-run; the same input produces the same stored state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys

import pandas as pd

# allow running both as "python -m jobs.run_daily" and "python jobs/run_daily.py"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import compute
import store
import data_sources as ds

# Best-effort NSE trading holidays (edit per year / auto-fetch if you prefer).
NSE_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-06", "2026-03-25", "2026-04-01", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-08-15", "2026-09-04", "2026-10-02",
    "2026-10-20", "2026-11-09", "2026-11-24", "2026-12-25",
}


def is_trading_day(d: dt.date) -> bool:
    if d.weekday() >= 5:          # Sat/Sun
        return False
    return d.strftime("%Y-%m-%d") not in NSE_HOLIDAYS_2026


def setup_logging():
    os.makedirs(os.path.dirname(config.log_path()), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(config.log_path()), logging.StreamHandler()],
    )


def fetch_for_index(name, meta, equity, fallback, vix, backfill_years):
    """Ensure history for one index is in the store, then return its daily series."""
    nse_label, token = meta["nse_label"], meta["smartapi_token"]
    src = vix if config.is_volatility(name) else equity

    if store.latest_daily_date(name) is None:
        # no history yet -> deep backfill
        s = src.daily_history(name, nse_label, token, backfill_years)
        if len(s) == 0 and not config.is_volatility(name):
            s = fallback.daily_history(name, nse_label, token, backfill_years)
        store.upsert_daily(name, s)

    # ALWAYS refresh the most recent close so the current (forming) week is live,
    # even on the very first run.
    latest = src.latest_close(name, nse_label, token)
    if latest is None and not config.is_volatility(name):
        latest = fallback.latest_close(name, nse_label, token)
    if latest:
        d, c = latest
        store.upsert_daily(name, pd.Series([c], index=[pd.Timestamp(d)]))

    return store.load_daily(name)


def build_payload(results, panels, name_map, as_of):
    full = len(config.SMA_PERIODS)
    indices = {}
    for r in results:
        arch = store.load_archive(r["name"], limit=config.ARCHIVE_DISPLAY_WEEKS)
        for row in arch:
            row["color"] = compute.color_for(int(row["crossed"]))
        indices[r["name"]] = {
            "group": next(i.get("group", "") for i in config.INDICES if i["name"] == r["name"]),
            "is_volatility": config.is_volatility(r["name"]),
            "nse_label": name_map[r["name"]]["nse_label"],
            "status": r["status"],
            "close": r["close"],
            "crossed": r["crossed"],
            "available": r.get("available", 0),
            "score_label": r["score_label"],
            "color": r["color"],
            "smas": {str(k): v for k, v in r.get("smas", {}).items()},
            "entered_full_today": r.get("entered_full_today", False),
            "archive": arch,
        }
    return {
        "as_of": as_of,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "policy": config.SCORING_POLICY,
        "basis": config.SMA_BASIS,
        "ma_type": config.MA_TYPE,
        "full": full,
        "color_map": {str(k): v for k, v in config.COLOR_MAP.items()},
        "insufficient_color": config.INSUFFICIENT_COLOR,
        "panels": panels,
        "indices": indices,
    }


def run(force=False, synthetic=False, backfill_years=None, fresh=False, ma="sma"):
    config.MA_TYPE = ma.upper()
    setup_logging()
    log = logging.getLogger("run_daily")
    backfill_years = backfill_years or config.BACKFILL_TARGET_YEARS

    today = dt.date.today()
    if not force and not is_trading_day(today):
        log.info("not a trading day (%s); exiting.", today)
        return

    store.reset() if fresh else store.init()
    equity, fallback, vix, primary = ds.get_sources(use_synthetic=synthetic)
    name_map, unmatched = ds.resolve_mappings(primary)
    if unmatched:
        log.warning("UNMATCHED names (fix NSE_LABEL/TOKEN overrides): %s", unmatched)

    results, as_of_dates = [], []
    total = len(config.INDICES)
    for i, item in enumerate(config.INDICES, 1):
        name = item["name"]
        log.info("[%d/%d] %s: fetching...", i, total, name)
        try:
            daily = fetch_for_index(name, name_map[name], equity, fallback, vix, backfill_years)
            res = compute.evaluate_index(name, daily)
            if res["status"] == "ok":
                store.write_archive(name, res["archive"])
            results.append(res)
            if len(daily):
                as_of_dates.append(daily.index.max())
            log.info("%-32s %s", name, res["score_label"])
        except Exception as e:                       # per-index isolation
            log.exception("FAILED %s: %s", name, e)
            results.append({"name": name, "status": "nodata", "crossed": None,
                            "score_label": "—", "color": config.INSUFFICIENT_COLOR,
                            "close": None, "available": 0, "smas": {}})

    prev = store.load_prev_scores()
    panels = compute.assign_panels(results, prev)

    as_of = max(as_of_dates).strftime("%Y-%m-%d") if as_of_dates else today.strftime("%Y-%m-%d")
    payload = build_payload(results, panels, name_map, as_of)
    store.save_snapshot(payload)

    # snapshot this run's scores so tomorrow can detect "entered 6/6 today"
    store.save_prev_scores({r["name"]: r["crossed"] for r in results}, as_of)

    log.info("done. green=%d rest=%d entered_today=%d as_of=%s",
             len(panels["green"]), len(panels["rest"]), len(panels["entered_today"]), as_of)
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--backfill-years", type=int, default=None)
    ap.add_argument("--fresh", action="store_true", help="wipe the DB and rebuild from scratch")
    ap.add_argument("--ma", choices=["sma", "ema"], default="sma", help="moving-average type")
    a = ap.parse_args()
    run(force=a.force, synthetic=a.synthetic, backfill_years=a.backfill_years, fresh=a.fresh, ma=a.ma)
