"""SCALPING engine configuration. Everything an admin may tune lives here (defaults + allowed ranges).

Add or remove a coin by editing COINS (each needs a Binance USDT spot pair). Which coins are switched on is a setting
(`enabled_coins`); coins outside COINS can never be enabled, so no signal is ever produced for any other coin.
Admin overrides (from the scalp_settings table) are merged over DEFAULTS and clamped to LIMITS by `effective()`."""
import copy

COINS = [
    {"symbol": "SOL", "name": "Solana"},
    {"symbol": "LINK", "name": "Chainlink"},
    {"symbol": "XRP", "name": "XRP"},
    {"symbol": "ONDO", "name": "Ondo"},
]

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}

DEFAULTS = {
    "enabled_coins": [c["symbol"] for c in COINS],
    "htf": "15m",                    # higher timeframe: trend, structure       (15m or 1h)
    "exec": "5m",                    # execution timeframe: entry, momentum, volume
    "min_score": 7.5,                # minimum Setup Score (out of 10) to publish a setup
    "alert_min_score": 8.0,          # only setups at least this good raise a "new setup" alert
    "min_rr": 1.5,                   # minimum reward:risk after fees
    "signal_expiry_min": 30,         # a setup not entered within this many minutes expires
    "trade_max_min": 240,            # an active trade older than this is closed at market
    "max_simultaneous": 2,           # open setups + active trades at once
    "cooldown_min": 30,              # pause on a coin after any finished signal
    "sl_cooldown_min": 90,           # longer pause after a stop-loss
    "loss_streak_limit": 2,          # this many stop-losses in a row on one coin trips the circuit breaker below
    "loss_streak_cooldown_min": 240, # ...pauses new signals on that coin for this long, doubling/tripling/etc with each
                                      # further consecutive loss (capped at 4x), instead of one fixed wait that a bad
                                      # streak can just wait out
    "min_level_change_atr": 1.0,     # after a stop-loss, the new setup's trigger level must differ by this many ATR
    "allow_short": False,            # long-only until an admin switches shorts on
    "fee_pct": 0.2,                  # round-trip trading cost assumed everywhere
    "min_net_tp1_pct": 0.3,          # target 1 must clear fees by at least this much
    "stop_buffer_atr": 0.25,         # stop sits this far beyond the structure point
    "stop_atr_min": 0.8, "stop_atr_max": 2.5,   # stop distance must be within this many ATR
    "tp1_atr": 1.5, "tp2_atr": 3.0,  # targets in ATR from entry (target 1 snaps to a nearer swing level if one exists)
    "partial_tp1_pct": 50,           # share of the position closed at target 1; the rest trails (see post_tp1_trail_atr)
    "post_tp1_trail_atr": 0.8,       # after target 1, the stop trails this many ATR behind the highest price since, never below breakeven
    "vol_min": 1.2,                  # volume vs its 20-candle average must be at least this
    "restricted_regimes": ["HIGH VOLATILITY", "UNSTABLE"],
    "high_vol_ratio": 2.0,           # ATR vs its 50-candle average: at/above this = HIGH VOLATILITY
    "unstable_flips": 8,             # direction changes in the last 10 candles that mark UNSTABLE
    "stale_after_min": 15,           # candle data older than this = STALE: no new signals
    "alerts": {"setup": True, "entry": True, "tp1": True, "tp2": True, "stop": True, "invalidated": True, "regime": True, "expired": False},
}

# (min, max) for numbers; anything outside is clamped, anything of the wrong type falls back to the default
LIMITS = {
    "min_score": (5.0, 10.0), "alert_min_score": (5.0, 10.0), "min_rr": (0.5, 5.0), "signal_expiry_min": (5, 240), "trade_max_min": (15, 1440),
    "max_simultaneous": (1, 4), "cooldown_min": (0, 720), "sl_cooldown_min": (0, 1440), "min_level_change_atr": (0.0, 5.0),
    "loss_streak_limit": (1, 5), "loss_streak_cooldown_min": (30, 1440),
    "fee_pct": (0.0, 1.0), "min_net_tp1_pct": (0.0, 3.0), "stop_buffer_atr": (0.0, 1.5), "stop_atr_min": (0.3, 3.0), "stop_atr_max": (0.5, 5.0),
    "tp1_atr": (0.5, 5.0), "tp2_atr": (1.0, 10.0), "partial_tp1_pct": (0, 100), "post_tp1_trail_atr": (0.2, 2.0), "vol_min": (0.5, 5.0), "high_vol_ratio": (1.2, 5.0),
    "unstable_flips": (5, 10), "stale_after_min": (5, 120),
}
CHOICES = {"htf": ("15m", "1h"), "exec": ("5m",)}
REGIMES = ("TRENDING UP", "TRENDING DOWN", "SIDEWAYS", "HIGH VOLATILITY", "LOW VOLATILITY", "BREAKOUT", "UNSTABLE")


def effective(overrides=None):
    """DEFAULTS with the admin's overrides applied and clamped. Never raises on bad input."""
    cfg = copy.deepcopy(DEFAULTS)
    o = overrides if isinstance(overrides, dict) else {}
    valid_coins = {c["symbol"] for c in COINS}
    if isinstance(o.get("enabled_coins"), list):
        cfg["enabled_coins"] = [c for c in o["enabled_coins"] if c in valid_coins]
    for k, (lo, hi) in LIMITS.items():
        v = o.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cfg[k] = min(hi, max(lo, v))
    for k, allowed in CHOICES.items():
        if o.get(k) in allowed:
            cfg[k] = o[k]
    if isinstance(o.get("allow_short"), bool):
        cfg["allow_short"] = o["allow_short"]
    if isinstance(o.get("restricted_regimes"), list):
        cfg["restricted_regimes"] = [r for r in o["restricted_regimes"] if r in REGIMES]
    if isinstance(o.get("alerts"), dict):
        for k in cfg["alerts"]:
            if isinstance(o["alerts"].get(k), bool):
                cfg["alerts"][k] = o["alerts"][k]
    if cfg["stop_atr_max"] < cfg["stop_atr_min"]:
        cfg["stop_atr_max"] = cfg["stop_atr_min"]
    if cfg["tp2_atr"] <= cfg["tp1_atr"]:
        cfg["tp2_atr"] = cfg["tp1_atr"] + 0.5
    return cfg
