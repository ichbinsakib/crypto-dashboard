"""Configuration: defaults live here, environment variables override, and the admin can edit
`impact`, `thresholds`, `notifications` and `weights` at runtime (stored in the event_config table;
DB values are layered over these defaults). Nothing below is hard-coded elsewhere."""
import copy
import os

USER_AGENT = os.environ.get("EVENTS_USER_AGENT",
                            "KairoDashboard/1.0 (personal market-calendar reader; contact: ichbinsakib@gmail.com)")
HTTP_TIMEOUT = float(os.environ.get("EVENTS_HTTP_TIMEOUT", "20"))
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")            # optional; fredgraph.csv is used without it
BLS_API_KEY = os.environ.get("BLS_API_KEY", "")              # optional; v1 works without a key (25 queries/day)
REACTION_ASSETS = [a.strip() for a in os.environ.get("EVENTS_REACTION_ASSETS", "BTCUSDT,ETHUSDT").split(",") if a.strip()]
CALENDAR_MONTHS_AHEAD = int(os.environ.get("EVENTS_MONTHS_AHEAD", "2"))
CALENDAR_MONTHS_BACK = int(os.environ.get("EVENTS_MONTHS_BACK", "3"))
REACTION_BACKFILL_DAYS = int(os.environ.get("EVENTS_REACTION_BACKFILL_DAYS", "90"))
PAYLOAD_DAYS_BACK = int(os.environ.get("EVENTS_PAYLOAD_DAYS_BACK", "45"))     # window shipped to the browser
PAYLOAD_DAYS_AHEAD = int(os.environ.get("EVENTS_PAYLOAD_DAYS_AHEAD", "75"))

# How long a source's data is trusted before it is shown as RECENT / STALE (minutes).
FRESHNESS = {"live_minutes": 30, "recent_minutes": 24 * 60}
# Minimum refresh spacing per source (minutes) so a 5-minute job never hammers an official site.
REFRESH_MINUTES = {"bls_schedule": 12 * 60, "fed_calendar": 24 * 60, "bls_actuals": 10, "fedwatch": 60, "reactions": 5}
BACKOFF = {"base_minutes": 10, "max_minutes": 6 * 60}

DEFAULTS = {
    # First matching rule wins. `match` is a case-insensitive substring of the event name.
    "impact": {
        "rules": [
            {"match": "FOMC", "family": "FOMC", "level": "VERY_HIGH", "score": 10},
            {"match": "Employment Situation", "family": "NFP", "level": "VERY_HIGH", "score": 9},
            {"match": "Consumer Price Index", "family": "CPI", "level": "VERY_HIGH", "score": 9},
            {"match": "Producer Price Index", "family": "PPI", "level": "HIGH", "score": 7},
            {"match": "Personal Income and Outlays", "family": "PCE", "level": "HIGH", "score": 7},
            {"match": "Real Earnings", "family": "OTHER", "level": "LOW", "score": 2},
            {"match": "Job Openings and Labor Turnover", "family": "JOLTS", "level": "MEDIUM", "score": 5},
            {"match": "Employment Cost Index", "family": "ECI", "level": "MEDIUM", "score": 5},
            {"match": "Productivity and Costs", "family": "PRODUCTIVITY", "level": "MEDIUM", "score": 4},
            {"match": "Import and Export Price", "family": "IMPORT_PRICES", "level": "MEDIUM", "score": 4},
        ],
        "default": {"family": "OTHER", "level": "LOW", "score": 1},
    },
    # Surprise = (actual - forecast) in the event's own unit. |surprise| below `inline` is INLINE,
    # up to `moderate` is MODERATE, above is LARGE. Per-family so a 0.1pp CPI miss and a 50k payroll
    # miss are each judged on their own scale.
    "thresholds": {
        "CPI": {"unit": "pp", "inline": 0.05, "moderate": 0.15},
        "CORE_CPI": {"unit": "pp", "inline": 0.05, "moderate": 0.15},
        "PPI": {"unit": "pp", "inline": 0.1, "moderate": 0.3},
        "NFP": {"unit": "thousand jobs", "inline": 25, "moderate": 75},
        "UNEMPLOYMENT": {"unit": "pp", "inline": 0.05, "moderate": 0.15},
        "default": {"unit": "", "inline": 0.05, "moderate": 0.15},
    },
    # Which direction of an upside surprise is read as pressure on risk assets (inflation up / jobs up
    # -> fewer cuts -> BEARISH_PRESSURE; unemployment up -> easier policy -> BULLISH_PRESSURE).
    "weights": {
        "risk_direction": {"CPI": -1, "CORE_CPI": -1, "PPI": -1, "PCE": -1, "NFP": -1, "UNEMPLOYMENT": 1,
                           "FOMC": -1},
        "density": {"events_24h_high": 3, "events_3d_high": 6, "events_7d_high": 10},
        "min_sample": 5,                 # no historical statistic is shown below this many events
        "min_sample_confident": 12,
    },
    "notifications": {
        "upcoming_high_impact": True, "upcoming_lead_minutes": 60, "actual_released": True,
        "large_surprise": True, "fedwatch_shift": True, "fedwatch_shift_pp": 10.0,
        "high_event_density": True, "data_unavailable": True,
    },
}


def merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def effective(db_config=None):
    """Defaults layered with {key: value} rows from event_config."""
    return merge(DEFAULTS, db_config or {})
