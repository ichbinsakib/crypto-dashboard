"""Everything an admin might want to tune lives here. Add a coin by adding one line to COINS (it must have a Binance USDT spot pair)."""

COINS = [
    {"symbol": "SOL", "name": "Solana"},
    {"symbol": "LINK", "name": "Chainlink"},
    {"symbol": "XRP", "name": "XRP"},
    {"symbol": "ONDO", "name": "Ondo"},
]

FEE_PCT = 0.2          # round-trip trading cost assumed everywhere (same as the rest of the app)

# Read by static/scalping.js so the rules are defined once. Long-only.
PARAMS = {
    "ema_fast": 20, "ema_slow": 50,
    "vol_recent": 3, "vol_base": 20, "vol_mult": 1.2,     # last 3 candles vs the 20 before them
    "book_min_ratio": 1.0, "book_band_pct": 1.0,          # bid value / ask value within +-1% of price
    "funding_hot_pct": 0.03,                              # funding above this = crowded longs
    "atr_len": 14, "atr_stop": 1.0, "atr_t1": 1.5, "atr_t2": 2.5,
    "min_net_t1_pct": 0.3,                                # target 1 must clear fees by at least this much
    "fee_pct": FEE_PCT,
    "intervals": ["1m", "5m", "15m"], "default_interval": "5m", "refresh_seconds": 10,
}
