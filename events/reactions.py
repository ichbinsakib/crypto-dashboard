"""Market reaction of BTC/ETH around a release, computed only from stored 1-minute candles."""
import statistics

HORIZON_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "24h": 1440}
EXCURSION_WINDOW_MIN = 240          # MFE/MAE measured over the 4 hours after the release
VOL_WINDOW_MIN = 60


def _close_at(by_t, ms):
    """Close of the candle that ends at `ms` (i.e. opens 60s earlier)."""
    c = by_t.get(ms - 60_000)
    return c["close"] if c else None


def _pct(a, b):
    return None if a in (None, 0) or b is None else round((b / a - 1) * 100, 4)


def compute_reaction(candles, release_ms, now_ms):
    """candles: [{t, high, low, close}] 1m, covering release-60m .. release+24h. Returns the reaction
    row fields; horizons not yet elapsed (or missing data) stay None. `complete` means all 6 horizons are known."""
    by_t = {c["t"]: c for c in candles}
    before = _close_at(by_t, release_ms)
    out = {"price_before": before}
    for h, mins in HORIZON_MIN.items():
        t = release_ms + mins * 60_000
        p = _close_at(by_t, t) if t <= now_ms else None
        out["price_" + h] = p
        out["return_" + h] = _pct(before, p)
    win_end = min(now_ms, release_ms + EXCURSION_WINDOW_MIN * 60_000)
    win = [c for c in candles if release_ms <= c["t"] < win_end]
    if before and win:
        out["max_favorable_excursion"] = _pct(before, max(c["high"] for c in win))
        out["max_adverse_excursion"] = _pct(before, min(c["low"] for c in win))
    else:
        out["max_favorable_excursion"] = out["max_adverse_excursion"] = None

    def avg_range(cs):
        rs = [(c["high"] - c["low"]) / c["close"] * 100 for c in cs if c["close"]]
        return statistics.fmean(rs) if rs else None
    pre = [c for c in candles if release_ms - VOL_WINDOW_MIN * 60_000 <= c["t"] < release_ms]
    post = [c for c in candles if release_ms <= c["t"] < min(now_ms, release_ms + VOL_WINDOW_MIN * 60_000)]
    a, b = avg_range(pre), avg_range(post)
    full_post = len(post) >= VOL_WINDOW_MIN - 1
    out["volatility_change"] = round((b / a - 1) * 100, 1) if a and b and full_post else None
    out["complete"] = all(out["return_" + h] is not None for h in HORIZON_MIN)
    return out
