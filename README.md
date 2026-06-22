# Index SMA Tracker

Tracks 38 NSE indices + India VIX and scores each by how many of six **weekly** SMAs
(5 / 10 / 20 / 50 / 100 / 200 weeks) the price is currently above.

- **Strict /6 scoring.** A SMA that doesn't exist yet (not enough weekly history) counts
  as *not crossed*, so the score is always `n/6` and the green panel is reserved for a
  true `6/6`. Newer indices stay below 6/6 until they mature — by design.
- **Three views.** A `Green Alert · 6/6` panel, an `Everything else` panel, and an
  `Entered 6/6 today` strip that resets every trading day.
- **Weekly history** per index (live row + completed weeks), matching the reference UI.
- **Unattended daily updates** from free sources on a cloud server.

## How it works

```
data_sources.py  ─ SmartApiSource (primary) · NiftyIndicesSource (fallback + daily
                    all-index snapshot) · VixSource (India VIX) · SyntheticSource (demo)
compute.py       ─ weekly resample, weekly SMAs, strict /6 scoring, archive (no look-ahead),
                    panel assignment + "entered 6/6 today"
store.py         ─ SQLite: daily prices, weekly archive, previous scores, snapshot
jobs/run_daily.py─ trading-day gate -> backfill/refresh -> score -> snapshot (idempotent)
app.py           ─ Streamlit dashboard (VPS / Streamlit Cloud)
build_static.py  ─ self-contained dashboard.html (GitHub Pages path)
selftest.py      ─ deterministic correctness checks
```

The score colour by count: 6 dark green, 5 light green, 4 yellow, 3 orange, 2 red,
1 maroon, 0 near-black; grey = insufficient history.

## 1. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Try it offline first (no credentials, no network)

```bash
python selftest.py                              # all scoring checks
python -m jobs.run_daily --synthetic --force    # builds data/tracker.db on fake data
python build_static.py                          # writes data/dashboard.html
streamlit run app.py                            # or open data/dashboard.html
```

## 3. Credentials (live data)

Primary data is Angel One **SmartAPI** (free; an authenticated API is far more reliable
from a cloud/datacenter IP than scraping). Sign up at `https://smartapi.angelone.in/`,
create an API app, then `cp .env.example .env` and fill in:

| Variable | What it is |
|---|---|
| `SMARTAPI_KEY` | the API key from your SmartAPI app |
| `SMARTAPI_CLIENT_CODE` | your Angel One login / client ID |
| `SMARTAPI_MPIN` | your 4-digit MPIN (or login password) |
| `SMARTAPI_TOTP_SECRET` | the base32 secret shown when you enable TOTP |

`load .env` however you prefer (e.g. `export $(grep -v '^#' .env | xargs)` or `python-dotenv`).
India VIX uses, in order, the SmartAPI India VIX token → NSE all-indices → `yfinance ^INDIAVIX`.

## 4. First run (deep backfill) + smoke test

```bash
python -m jobs.run_daily --force --backfill-years 8
```

- Pulls the deepest available daily history per index, resamples to weekly, computes
  scores, and writes the snapshot.
- Watch the log for **`UNMATCHED names`** — those are indices whose name didn't match the
  SmartAPI scrip master or the snapshot label. Fix them in `config.py`
  (`NSE_LABEL_OVERRIDES` / `SMARTAPI_TOKEN_OVERRIDES`) and re-run.
- If SmartAPI's daily candles don't go back far enough for a real 200-week SMA on the
  mature indices, the code falls back to the niftyindices historical endpoint. If that
  endpoint's payload format has changed it will raise per-index (logged, not fatal);
  update `NiftyIndicesSource.daily_history`.

> The live HTTP/auth paths were written to spec but could **not** be exercised from the
> build machine (no outbound access to the exchanges). Treat the first live run as a smoke
> test and check the log.

## 5. Schedule it (unattended, daily)

The data job is independent of the web app. Run it every trading day after ~18:30 IST.

**A — VPS (cron):**
```cron
30 18 * * 1-5  cd /opt/index-sma-tracker && /opt/index-sma-tracker/.venv/bin/python -m jobs.run_daily >> data/cron.log 2>&1
```
Serve the dashboard with `streamlit run app.py` under systemd/pm2.

**B — Free (GitHub Actions + Pages):** run `jobs.run_daily` on a cron schedule, commit
`data/tracker.db`, then `python build_static.py` and publish `data/dashboard.html` to
GitHub Pages. Sketch:
```yaml
on:
  schedule: [{cron: "0 13 * * 1-5"}]   # 13:00 UTC = 18:30 IST
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: python -m jobs.run_daily
        env:
          SMARTAPI_KEY: ${{ secrets.SMARTAPI_KEY }}
          SMARTAPI_CLIENT_CODE: ${{ secrets.SMARTAPI_CLIENT_CODE }}
          SMARTAPI_MPIN: ${{ secrets.SMARTAPI_MPIN }}
          SMARTAPI_TOTP_SECRET: ${{ secrets.SMARTAPI_TOTP_SECRET }}
      - run: python build_static.py
      # then commit data/ and/or deploy data/dashboard.html with actions/deploy-pages
```

**C — Single box, no cron:** `apscheduler` inside the app process (see requirements).

## Notes & limitations

- "Entered 6/6 today" needs at least one prior run to have a baseline; it's empty on the
  very first run and on a brand-new trading day until something flips.
- India VIX is scored mechanically but a high value means expected volatility (fear), not
  strength — the UI flags it.
- All the locked behaviour lives in `config.py`. To experiment with the "available"
  policy instead of strict /6, that's where it would go (currently unused).
