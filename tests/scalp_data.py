"""Candle builders shared by the SCALPING tests (deterministic, no network)."""
import math
import random

T0 = 1_800_000_000_000            # an arbitrary UTC millisecond timestamp aligned to 15 minutes


def series(closes, vols=None, t0=T0, iv=300_000, wick=0.0022, seed=1, buy_share=0.62):
    """Binance-style klines from a list of closes (open = previous close)."""
    rnd = random.Random(seed)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        hi = max(o, c) * (1 + wick * (0.5 + rnd.random()))
        lo = min(o, c) * (1 - wick * (0.5 + rnd.random()))
        v = vols[i] if vols else 100.0
        rows.append([t0 + i * iv, o, hi, lo, c, v, t0 + (i + 1) * iv - 1, v * c, 100, v * buy_share, 0, 0])
        prev = c
    return rows


def wave(n, start, drift, amp, per, seed=1):
    rnd = random.Random(seed)
    return [start + drift * i + amp * math.sin(i / per) + rnd.uniform(-amp * .15, amp * .15) for i in range(n)]


def breakout_scenario():
    """(15m rows, 5m rows): a steady 15m uptrend and a 5m series whose last CLOSED candle breaks its 20-candle high on heavy volume."""
    h = wave(200, 100, 0.15, 0.6, 5)
    x = wave(300, 100, 0.08, 0.7, 7)
    x[-2] = max(x[-22:-2]) * 1.0035
    x[-1] = x[-2] * 1.0002
    vols = [100.0] * 300
    for i in (-4, -3, -2):
        vols[i] = 260.0
    return series(h, iv=900_000, seed=1), series(x, vols, seed=1)


def downtrend_scenario():
    h = wave(200, 130, -0.15, 0.6, 5)
    x = wave(300, 130, -0.08, 0.7, 7)
    return series(h, iv=900_000), series(x)


def candle(t, o, h, l, c, v=100.0, iv=300_000):
    return [t, o, h, l, c, v, t + iv - 1, v * c, 10, v * 0.6, 0, 0]
