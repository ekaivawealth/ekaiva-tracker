"""Deterministic correctness checks for the scoring engine (no network)."""
import numpy as np
import pandas as pd

import config
import compute as C


def bdays(values, start="2024-01-01"):
    return pd.Series(np.asarray(values, dtype="float64"),
                     index=pd.bdate_range(start, periods=len(values)))


def wk(values, start="2018-01-05"):
    return pd.Series(np.asarray(values, dtype="float64"),
                     index=pd.date_range(start, periods=len(values), freq="W-FRI"))


def ref_crossed(series):
    close = float(series.iloc[-1]); n = len(series); c = 0
    for p in config.SMA_PERIODS:
        if n >= p and close > float(series.iloc[-p:].mean()):
            c += 1
    return c


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    assert cond, name


# ===================== DAILY basis (the active default) =====================
config.SMA_BASIS = "daily"
print("DAILY basis")

d300 = bdays(np.linspace(100, 200, 300))         # all 6 daily SMAs exist, rising
r = C.evaluate_index("X", d300)
check("rising 300d -> 6/6 green", r["crossed"] == 6 and r["score_label"] == "6/6")
check("color dark green", r["color"] == config.COLOR_MAP[6])
check("in green panel", "X" in C.assign_panels([r], {})["green"])
check("score_last matches reference", C.score_last(d300)["crossed"] == ref_crossed(d300))

d100 = bdays(np.linspace(100, 160, 100))         # SMA5..100 exist, SMA200 does not
r100 = C.evaluate_index("Y", d100)
check("rising 100d -> 5/6 (no 200d SMA)", r100["crossed"] == 5 and r100["score_label"] == "5/6")
check("5/6 in rest, not green", "Y" in C.assign_panels([r100], {})["rest"])

# below all daily SMAs -> 0/6 (this is the IT/MoneyControl-style case)
falling = bdays(list(np.linspace(200, 100, 260)))
rf = C.evaluate_index("Z", falling)
check("falling series -> 0/6 near-black", rf["crossed"] == 0 and rf["color"] == config.COLOR_MAP[0])

arch = C.archive_daily_sampled_weekly(d300, config.SMA_PERIODS)
check("daily archive sampled weekly: latest week 6/6", int(arch.iloc[-1]["crossed"]) == 6)
check("daily archive: early week < 6 (no look-ahead on 200d SMA)", int(arch.iloc[0]["crossed"]) < 6)
check("daily archive rows are weekly (Fridays)", all(ts.weekday() == 4 for ts in arch.index))

d3 = bdays(np.linspace(100, 101, 3))
check("under 5 days -> insufficient", C.evaluate_index("Tiny", d3)["status"] == "insufficient")

# ===================== WEEKLY basis =====================
config.SMA_BASIS = "weekly"
print("WEEKLY basis")

s30 = wk(np.linspace(100, 130, 30))              # only 5/10/20-wk SMAs exist
r30 = C.score_last(s30)
check("len30 -> crossed 3, label /6 not /3", r30["crossed"] == 3 and r30["score_label"] == "3/6")

daily60w = pd.Series(np.linspace(100, 160, 300), index=pd.bdate_range("2024-09-02", periods=300))
res = C.evaluate_index("Nifty India Tourism", daily60w)   # ~60 weeks -> 5/10/20/50-wk only
check("new index ~60wk -> 4/6, not green",
      res["crossed"] == 4 and "Nifty India Tourism" in C.assign_panels([res], {})["rest"])

s260 = wk(np.linspace(50, 250, 260))
check("mature -> 6/6", C.score_last(s260)["crossed"] == 6)

base = list(np.linspace(50, 200, 255)) + [205, 206, 207, 208, 203]   # final below SMA5 only
s5 = wk(base)
check("exactly 5/6", C.score_last(s5)["crossed"] == 5 == ref_crossed(s5))

arch_w = C.archive_weekly(wk(np.linspace(50, 250, 260)), config.SMA_PERIODS)
check("weekly archive week 60 == 4", int(arch_w.iloc[59]["crossed"]) == 4)
check("weekly archive week 210 == 6", int(arch_w.iloc[209]["crossed"]) == 6)

daily_mid = pd.Series(np.linspace(100, 120, 200), index=pd.bdate_range(end="2026-06-17", periods=200))
inc = C.to_weekly(daily_mid, include_forming=True)
exc = C.to_weekly(daily_mid, include_forming=False)
check("forming week adds one bucket using latest close",
      len(inc) == len(exc) + 1 and abs(inc.iloc[-1] - float(daily_mid.iloc[-1])) < 1e-9)

# ===================== basis-independent =====================
print("panels + entered + colours")
def mk(name, crossed):
    return {"name": name, "status": "ok", "crossed": crossed, "available": 6,
            "score_label": f"{crossed}/6", "color": C.color_for(crossed), "close": 1.0, "smas": {}}
pan = C.assign_panels([mk("A", 6), mk("B", 6), mk("C", 6), mk("D", 5)],
                      {"A": 5, "B": 6, "C": None, "D": 4})
check("A entered (5->6)", "A" in pan["entered_today"])
check("B not entered (already 6)", "B" not in pan["entered_today"])
check("C not entered (no baseline)", "C" not in pan["entered_today"])
check("color_for(0)/(6) endpoints", C.color_for(0) == "#2d0a0a" and C.color_for(6) == "#1a7f37")

# ===================== EMA model =====================
config.MA_TYPE = "EMA"; config.SMA_BASIS = "weekly"
print("EMA model (weekly)")
s260e = wk(np.linspace(50, 250, 260))
check("EMA rising -> 6/6", C.score_last(s260e)["crossed"] == 6)
check("EMA falling -> 0/6", C.score_last(wk(np.linspace(250, 50, 260)))["crossed"] == 0)
_curved = wk((np.arange(1, 261, dtype="float64")) ** 2)   # accelerating -> EMA != SMA
config.MA_TYPE = "SMA"; _sma5 = float(C._ma(_curved, 5).iloc[-1])
config.MA_TYPE = "EMA"; _ema5 = float(C._ma(_curved, 5).iloc[-1])
check("EMA value differs from SMA on curved data", abs(_ema5 - _sma5) > 1e-6)
check("EMA strict: 30wk rising -> 3/6 (50/100/200 not yet)",
      C.score_last(wk(np.linspace(100, 130, 30)))["crossed"] == 3)

config.MA_TYPE = "SMA"; config.SMA_BASIS = "weekly"
print("\nALL CHECKS PASSED")
