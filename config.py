"""
Central configuration for the Index SMA Tracker.

All the "locked decisions" live here so behaviour is changed in exactly one place.
Nothing in this file requires network access.
"""

# ---------------------------------------------------------------------------
# Scoring / SMA behaviour  (LOCKED: weekly SMAs, strict /6)
# ---------------------------------------------------------------------------
SCORING_POLICY = "strict6"          # active policy. ("available" is documented but unused.)
SMA_BASIS = "weekly"               # "weekly" | "daily".  weekly = matches MoneyControl MC Technicals "Weekly" tab.
MA_TYPE = "SMA"                    # "SMA" | "EMA".  Set per run via the --ma flag (separate dashboards).
WEEKLY_SMA_INCLUDES_FORMING_WEEK = True   # (weekly basis only) in-progress week uses today's close
WEEK_ENDING_DAY = "FRI"             # weekly history rows end Friday (resample alias W-FRI)
SMA_PERIODS = [5, 10, 20, 50, 100, 200]   # DAYS when SMA_BASIS="daily", WEEKS when "weekly"
MIN_WEEKS_TO_SCORE = 5              # weekly basis: fewer completed weekly bars than this -> "insufficient"

# ---------------------------------------------------------------------------
# History / backfill
# ---------------------------------------------------------------------------
BACKFILL_TARGET_YEARS = 8          # weekly basis: SMA200 needs ~4yr, archive wants ~6-8yr. (daily wants ~3)
ARCHIVE_DISPLAY_WEEKS = 104        # number of completed weekly rows shown in the per-index history

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
TIMEZONE = "Asia/Kolkata"
DAILY_RUN_AFTER = "18:30"          # IST; niftyindices snapshot publishes in the evening

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
DATA_PRIMARY = "smartapi"          # "smartapi" | "niftyindices"
DATA_FALLBACK = "niftyindices"     # used for any index the primary cannot supply
VIX_SOURCE_ORDER = ["smartapi", "nse_all_indices", "yfinance"]   # ^INDIAVIX on yfinance

# ---------------------------------------------------------------------------
# Colours: number of the six SMAs the close is above  ->  hex
# ---------------------------------------------------------------------------
COLOR_MAP = {
    6: "#1a7f37",  # dark green   (6/6)
    5: "#3fb950",  # light green
    4: "#d4a017",  # yellow
    3: "#e8590c",  # orange
    2: "#e5484d",  # red
    1: "#8b1a1a",  # maroon
    0: "#2d0a0a",  # near-black (below all SMAs)
}
INSUFFICIENT_COLOR = "#6b7280"     # grey, for indices without enough history to score

# ---------------------------------------------------------------------------
# The universe.  group is only used for ordering / readability in the UI.
# ---------------------------------------------------------------------------
INDICES = [
    # broad / size
    {"name": "Nifty 50",                         "group": "Broad"},
    {"name": "Nifty Next 50",                    "group": "Broad"},
    {"name": "Nifty 500",                        "group": "Broad"},
    {"name": "Nifty Midcap 150",                 "group": "Broad"},
    {"name": "Nifty Smallcap 250",               "group": "Broad"},
    {"name": "Nifty Microcap 250",               "group": "Broad"},
    {"name": "Nifty LargeMidcap 250",            "group": "Broad"},
    {"name": "Nifty Alpha 50",                   "group": "Broad"},
    # sectoral
    {"name": "Nifty Pharma",                     "group": "Sectoral"},
    {"name": "Nifty Healthcare",                 "group": "Sectoral"},
    {"name": "Nifty MidSmall Healthcare",        "group": "Sectoral"},
    {"name": "Nifty IT",                         "group": "Sectoral"},
    {"name": "Nifty Auto",                       "group": "Sectoral"},
    {"name": "Nifty Metal",                      "group": "Sectoral"},
    {"name": "Nifty FMCG",                       "group": "Sectoral"},
    {"name": "Nifty Media",                      "group": "Sectoral"},
    {"name": "Nifty Energy",                     "group": "Sectoral"},
    {"name": "Nifty Oil & Gas",                  "group": "Sectoral"},
    {"name": "Nifty Chemicals",                  "group": "Sectoral"},
    {"name": "Nifty Private Bank",               "group": "Sectoral"},
    {"name": "Nifty PSU Bank",                   "group": "Sectoral"},
    {"name": "Nifty Financial Services",         "group": "Sectoral"},
    {"name": "Nifty MidSmall Financial Services","group": "Sectoral"},
    {"name": "Nifty Capital Market",             "group": "Sectoral"},
    {"name": "Nifty Consumer Durables",          "group": "Sectoral"},
    {"name": "Nifty Realty",                     "group": "Sectoral"},
    # thematic
    {"name": "Nifty CPSE",                       "group": "Thematic"},
    {"name": "Nifty India Tourism",              "group": "Thematic"},
    {"name": "Nifty Commodities",                "group": "Thematic"},
    {"name": "Nifty India Consumption",          "group": "Thematic"},
    {"name": "Nifty Rural",                      "group": "Thematic"},
    {"name": "Nifty Housing",                    "group": "Thematic"},
    {"name": "Nifty Infrastructure",             "group": "Thematic"},
    {"name": "Nifty Defence",                    "group": "Thematic"},
    {"name": "Nifty India Manufacturing",        "group": "Thematic"},
    {"name": "Nifty MNC",                        "group": "Thematic"},
    # volatility (dedicated feed; scored mechanically, but "high = fear, not strength")
    {"name": "India VIX",                        "group": "Volatility", "is_volatility": True},
]

# Exact label as it appears in the niftyindices daily-snapshot "Index Name" column.
# These are best-known values; the resolver verifies them against the live snapshot and
# reports anything it cannot match so you can correct it here.
NSE_LABEL_OVERRIDES = {
    "Nifty Healthcare":                  "Nifty Healthcare Index",
    "Nifty Capital Market":              "Nifty Capital Markets",
    "Nifty Defence":                     "Nifty India Defence",
    "Nifty Transport & Logistics":       "Nifty India Transportation & Logistics",
    "India VIX":                         "India VIX",
}

# SmartAPI symboltoken per friendly name. Leave empty to let the resolver auto-match
# against the SmartAPI scrip master; fill in here to pin a token that auto-match misses.
SMARTAPI_TOKEN_OVERRIDES = {
    # "Nifty 50": "99926000",
    # "India VIX": "99926017",
}

# Yahoo Finance tickers for each index.
# None  -> index is not available on Yahoo Finance; will show as "insufficient".
YFINANCE_TICKERS = {
    # Broad / Size
    "Nifty 50":                          "^NSEI",
    "Nifty Next 50":                     "^NSMIDCP",
    "Nifty 500":                         "^CRSLDX",              # ^CNX500 doesn't exist on YF
    "Nifty Midcap 150":                  "NIFTYMIDCAP150.NS",     # ^NSEMDCP150 doesn't exist
    "Nifty Smallcap 250":                "NIFTYSMLCAP250.NS",     # ^CNXSC was returning 1 row
    "Nifty Microcap 250":                "NIFTY_MICROCAP250.NS",  # ^NIFTYMICROCAP250 doesn't exist
    "Nifty LargeMidcap 250":             "NIFTY_LARGEMID250.NS",  # ^NIFTY_LARGEMIDCAP_250 doesn't exist
    "Nifty Alpha 50":                    "^NIFTYALPHA50",
    # Sectoral
    "Nifty Pharma":                      "^CNXPHARMA",
    "Nifty Healthcare":                  "NIFTY_HEALTHCARE.NS",   # ^CNXHEALTH doesn't exist
    "Nifty MidSmall Healthcare":         "^NIFTY_MIDSMALL_HLTHCRE",
    "Nifty IT":                          "^CNXIT",
    "Nifty Auto":                        "^CNXAUTO",
    "Nifty Metal":                       "^CNXMETAL",
    "Nifty FMCG":                        "^CNXFMCG",
    "Nifty Media":                       "^CNXMEDIA",
    "Nifty Energy":                      "^CNXENERGY",
    "Nifty Oil & Gas":                   "NIFTY_OIL_AND_GAS.NS",  # ^CNXOILGAS doesn't exist
    "Nifty Chemicals":                   "^CNXCHEM",
    "Nifty Private Bank":                "NIFTYPVTBANK.NS",        # ^CNXPVTBANK doesn't exist
    "Nifty PSU Bank":                    "^CNXPSUBNK",
    "Nifty Financial Services":          "NIFTY_FIN_SERVICE.NS",  # ^CNXFIN = FINSRV25/50 (wrong index)
    "Nifty MidSmall Financial Services": "^NIFTY_MIDSMALL_FINSRV",
    "Nifty Capital Market":              "^NIFTY_CAP_MARKET",
    "Nifty Consumer Durables":           "NIFTY_CONSR_DURBL.NS",  # ^CNXCONSDUR doesn't exist
    "Nifty Realty":                      "^CNXREALTY",
    # Thematic
    "Nifty CPSE":                        "^CNXCPSE",
    "Nifty India Tourism":               "NIFTY_IND_TOURISM.NS",  # ^NIFTYINDIATUR doesn't exist
    "Nifty Commodities":                 "^CNXCMDT",
    "Nifty India Consumption":           "^CNXCONSUM",
    "Nifty Rural":                       "^NIFTYRURAL",
    "Nifty Housing":                     "^NIFTYHOUSING",
    "Nifty Infrastructure":              "^CNXINFRA",
    "Nifty Defence":                     "^NIFTYDEFENCE",
    "Nifty India Manufacturing":         "NIFTY_INDIA_MFG.NS",    # ^NIFTYINDMFG doesn't exist
    "Nifty MNC":                         "^CNXMNC",
    # Volatility
    "India VIX":                         "^INDIAVIX",
}

# Paths — separated per MA type so SMA and EMA are fully independent models.
def _suffix():
    return MA_TYPE.lower()

def db_path():
    return f"data/tracker_{_suffix()}.db"

def static_html():
    return f"data/dashboard_{_suffix()}.html"

def log_path():
    return f"data/tracker_{_suffix()}.log"


def index_names():
    return [i["name"] for i in INDICES]


def is_volatility(name):
    for i in INDICES:
        if i["name"] == name:
            return bool(i.get("is_volatility", False))
    return False
