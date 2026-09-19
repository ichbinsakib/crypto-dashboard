"""Course concepts as measurable features on Binance-style klines ([t, open, high, low, close, volume, ...],
numbers may be strings). Pure functions, no network. Each returns plain dicts so they can be shown in the UI
or tested against history."""


def _f(k, i):
    return float(k[i])


def series(klines):
    return ([_f(k, 1) for k in klines], [_f(k, 2) for k in klines], [_f(k, 3) for k in klines],
            [_f(k, 4) for k in klines], [_f(k, 5) for k in klines])


def ema(values, n):
    if len(values) < n:
        return None
    a, e = 2 / (n + 1), sum(values[:n]) / n
    for v in values[n:]:
        e = v * a + e * (1 - a)
    return e


def atr(klines, n=14):
    if len(klines) < n + 1:
        return None
    o, h, l, c, v = series(klines)
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return sum(trs[-n:]) / n


# ---- Vol 7.2 EMA framework ----
def ema_bias(klines):
    """Price vs 20/50 EMA (200 when enough candles): bull bias above a rising longer EMA, bear below."""
    c = series(klines)[3]
    e20, e50 = ema(c, 20), ema(c, 50)
    e200 = ema(c, 200)
    if e20 is None or e50 is None:
        return None
    px = c[-1]
    prev50 = ema(c[:-5], 50) if len(c) >= 56 else None
    bias = "bull" if px > e50 and e20 > e50 else "bear" if px < e50 and e20 < e50 else "mixed"
    return {"bias": bias, "above_20": px > e20, "above_50": px > e50, "ema20_over_50": e20 > e50,
            "rising_50": (e50 > prev50) if prev50 else None, "above_200": (px > e200) if e200 else None}


# ---- Vol 7.4 highs & lows ----
def swings(klines, k=3):
    """Swing highs/lows: a candle whose high (low) is the extreme of k candles either side."""
    _, h, l, _, _ = series(klines)
    hs, ls = [], []
    for i in range(k, len(h) - k):
        if h[i] == max(h[i - k:i + k + 1]):
            hs.append((i, h[i]))
        if l[i] == min(l[i - k:i + k + 1]):
            ls.append((i, l[i]))
    return hs, ls


def structure(klines, k=3):
    hs, ls = swings(klines, k)
    if len(hs) < 2 or len(ls) < 2:
        return {"trend": "unclear"}
    up = hs[-1][1] > hs[-2][1] and ls[-1][1] > ls[-2][1]
    down = hs[-1][1] < hs[-2][1] and ls[-1][1] < ls[-2][1]
    return {"trend": "up" if up else "down" if down else "range", "last_swing_low": ls[-1][1], "last_swing_high": hs[-1][1]}


# ---- Vol 4 Fair Value Gap ----
def fair_value_gaps(klines, max_age=60):
    """Bullish FVG: candle i's low is above candle i-2's high (gap = [high(i-2), low(i)]). 'Unfilled' while
    price has not traded back into the gap's bottom. Returns gaps newest first."""
    _, h, l, c, _ = series(klines)
    out = []
    start = max(2, len(h) - max_age)
    for i in range(start, len(h)):
        if l[i] > h[i - 2]:
            lo, hi = h[i - 2], l[i]
            filled = any(l[j] <= lo for j in range(i + 1, len(l)))
            out.append({"type": "bull", "index": i, "low": lo, "high": hi, "filled": filled})
        elif h[i] < l[i - 2]:
            lo, hi = h[i], l[i - 2]
            filled = any(h[j] >= hi for j in range(i + 1, len(h)))
            out.append({"type": "bear", "index": i, "low": lo, "high": hi, "filled": filled})
    return list(reversed(out))


def fvg_retest(klines, max_age=60):
    """Is price inside / just above an unfilled bullish FVG (the course's retest entry zone)?"""
    px = _f(klines[-1], 4)
    a = atr(klines) or 0
    for g in fair_value_gaps(klines, max_age):
        if g["type"] == "bull" and not g["filled"] and g["index"] < len(klines) - 1:
            if g["low"] <= px <= g["high"] + 0.5 * a:
                return {"in_zone": True, "gap_low": g["low"], "gap_high": g["high"]}
    return {"in_zone": False}


# ---- Vol 7.5 parabolic curve / god candle ----
def parabolic(klines, n=10, atr_multiple=4.0):
    a = atr(klines)
    if not a or len(klines) < n + 1:
        return {"parabolic": False}
    c = series(klines)[3]
    rise = c[-1] - c[-1 - n]
    god = max(abs(_f(k, 4) - _f(k, 1)) for k in klines[-3:]) > 3 * a
    return {"parabolic": rise > atr_multiple * a, "god_candle": god, "rise_atr": round(rise / a, 2)}


# ---- Vol 9.1 Fibonacci ----
def fib_position(klines, lookback=60):
    """Where price sits in the retracement of the last swing low -> high (course golden zone 0.5-0.786)."""
    o, h, l, c, _ = series(klines[-lookback:])
    hi_i, lo_i = h.index(max(h)), l.index(min(l))
    if lo_i >= hi_i:                                    # need the low first, then the high (an up-leg)
        return {"valid": False}
    swing = h[hi_i] - l[lo_i]
    if swing <= 0:
        return {"valid": False}
    retr = (h[hi_i] - c[-1]) / swing
    return {"valid": True, "retracement": round(retr, 3), "golden_zone": 0.5 <= retr <= 0.786,
            "shallow": 0.382 <= retr < 0.5, "broken": retr > 1.0}


# ---- volume ----
def volume_spike(klines, n=20, multiple=2.0):
    v = series(klines)[4]
    if len(v) < n + 1:
        return {"spike": False}
    base = sum(v[-n - 1:-1]) / n
    return {"spike": base > 0 and v[-1] > multiple * base, "ratio": round(v[-1] / base, 2) if base else None}


# ---- Vol 5 risk rules ----
def position_size(account, risk_pct, entry, stop):
    """Course rule: size so that being stopped out costs only `risk_pct` (1-2%) of the account."""
    per_unit = abs(entry - stop)
    if per_unit <= 0 or account <= 0:
        return None
    units = account * risk_pct / 100 / per_unit
    notional = units * entry
    return {"units": units, "notional": notional, "leverage_needed": notional / account, "risk_amount": account * risk_pct / 100}


def features(klines):
    """All course features for the latest candle, for display and for backtests."""
    return {"ema": ema_bias(klines), "structure": structure(klines), "fvg": fvg_retest(klines),
            "parabolic": parabolic(klines), "fib": fib_position(klines), "volume": volume_spike(klines)}
