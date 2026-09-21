"""Market analysis for the SCALPING engine: indicators, market structure, regime, and the seven-check setup evaluation.

Pure functions on Binance-style kline rows [openTime, open, high, low, close, volume, closeTime, quoteVol, trades, takerBuyBase, ...].
The last row of a series is the still-forming candle: every indicator is computed on CLOSED candles only, and the forming
candle supplies just the current price. Nothing here touches the network or the database.

SETUP SCORE (out of 10; not a probability). Seven checks, each worth up to:
  Trend 2.0 (15m: averages stacked +1.0, higher-highs/higher-lows structure +1.0)   Momentum 1.5 (RSI band, MACD histogram, acceleration)
  Volume 1.5 (volume vs 20-candle average, with taker buy/sell pressure)             Structure 1.5 (higher low + break of structure on 5m)
  Volatility 1.0 (target clears fees, ATR not exploding)                            Entry trigger 1.5 (breakout close or pullback bounce)
  Risk/Reward 1.0 (blended reward:risk after fees meets the minimum)
A setup needs ALL of: Trend, Entry trigger, Volatility (fees) and Risk/Reward to pass, AND a score >= the configured minimum.
Quality: HIGH >= 8.5, MEDIUM below that. Shorts mirror every rule and only run when allow_short is switched on."""


def _f(x):
    return float(x)


# ---------------- indicators ----------------

def ema(values, n):
    """EMA seeded with the first n-value average; None until n values exist."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = values[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g, l = g / n, l / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def macd_hist(closes, fast=12, slow=26, sig=9):
    """MACD histogram series (None until enough data)."""
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [(a - b) if a is not None and b is not None else None for a, b in zip(ef, es)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    out = [None] * len(closes)
    if first is None:
        return out
    seg = line[first:]
    es_sig = ema(seg, sig)
    for i, s in enumerate(es_sig):
        if s is not None:
            out[first + i] = seg[i] - s
    return out


def atr_series(rows, n=14):
    """Wilder ATR (None until n candles exist)."""
    if len(rows) < n + 1:
        return [None] * len(rows)
    tr = []
    for i in range(1, len(rows)):
        h, l, pc = _f(rows[i][2]), _f(rows[i][3]), _f(rows[i - 1][4])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    out = [None] * len(rows)
    a = sum(tr[:n]) / n
    out[n] = a
    for i in range(n + 1, len(rows)):
        a = (a * (n - 1) + tr[i - 1]) / n
        out[i] = a
    return out


def pivots(rows, k=2):
    """Confirmed swing points [(index, 'H'|'L', price)] in time order. A pivot needs k candles on each side."""
    out = []
    hs, ls = [_f(r[2]) for r in rows], [_f(r[3]) for r in rows]
    for i in range(k, len(rows) - k):
        if all(hs[i] > hs[i - j] and hs[i] > hs[i + j] for j in range(1, k + 1)):
            out.append((i, "H", hs[i]))
        if all(ls[i] < ls[i - j] and ls[i] < ls[i + j] for j in range(1, k + 1)):
            out.append((i, "L", ls[i]))
    return out


def _last_two(piv, kind):
    p = [x for x in piv if x[1] == kind]
    return (p[-2], p[-1]) if len(p) >= 2 else (None, None)


def trend_structure(rows, sign):
    """True if the last two swing highs AND lows are stepping in the direction of `sign` (+1 up, -1 down)."""
    piv = pivots(rows)
    h0, h1 = _last_two(piv, "H")
    l0, l1 = _last_two(piv, "L")
    if not (h0 and h1 and l0 and l1):
        return False
    return (h1[2] - h0[2]) * sign > 0 and (l1[2] - l0[2]) * sign > 0


# ---------------- regime ----------------

def _flips(rows, n=10):
    """How many times the candle colour changed over the last n candles (choppy = many)."""
    seg = rows[-n:]
    dirs = [1 if _f(r[4]) >= _f(r[1]) else -1 for r in seg]
    return sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)


def regime_of(htf_closed, exec_closed, cfg):
    """One of TRENDING UP / TRENDING DOWN / SIDEWAYS / HIGH VOLATILITY / LOW VOLATILITY / BREAKOUT / UNSTABLE, from closed candles."""
    if len(htf_closed) < 60 or len(exec_closed) < 30:
        return "SIDEWAYS"
    atrs = [a for a in atr_series(htf_closed) if a is not None]
    ratio = atrs[-1] / (sum(atrs[-50:]) / len(atrs[-50:])) if atrs else 1.0
    if _flips(exec_closed) >= cfg["unstable_flips"] and ratio >= 1.2:
        return "UNSTABLE"
    if ratio >= cfg["high_vol_ratio"]:
        return "HIGH VOLATILITY"
    closes = [_f(r[4]) for r in htf_closed]
    highs, lows = [_f(r[2]) for r in htf_closed], [_f(r[3]) for r in htf_closed]
    vols = [_f(r[5]) for r in htf_closed]
    vr = vols[-1] / (sum(vols[-21:-1]) / 20) if sum(vols[-21:-1]) > 0 else 1.0
    if vr >= 1.5 and (closes[-1] > max(highs[-41:-1]) or closes[-1] < min(lows[-41:-1])):
        return "BREAKOUT"
    e9, e21, e50 = ema(closes, 9)[-1], ema(closes, 21)[-1], ema(closes, 50)[-1]
    if e9 > e21 > e50 and closes[-1] > e21:
        return "TRENDING UP"
    if e9 < e21 < e50 and closes[-1] < e21:
        return "TRENDING DOWN"
    if ratio <= 0.6:
        return "LOW VOLATILITY"
    return "SIDEWAYS"


def market_regime(per_coin):
    """Plurality of the monitored coins' regimes; a tie is SIDEWAYS. per_coin: {symbol: regime}."""
    if not per_coin:
        return "SIDEWAYS"
    counts = {}
    for r in per_coin.values():
        counts[r] = counts.get(r, 0) + 1
    top = max(counts.values())
    leaders = [r for r, c in counts.items() if c == top]
    return leaders[0] if len(leaders) == 1 else "SIDEWAYS"


# ---------------- evaluation ----------------

def _check(key, label, state, text, points=0.0, max_points=0.0):
    return {"key": key, "label": label, "state": state, "text": text, "points": round(points, 2), "max": max_points}


def _closed(rows):
    return rows[:-1]


def evaluate(symbol, htf_rows, exec_rows, cfg):
    """Evaluate one coin. -> dict with status NO_SETUP | WATCH | SETUP, direction, score, quality, checks, reason, setup (levels) or None.
    `setup` is only present for status SETUP. The same call also reports the coin's regime and plain trend word."""
    base = {"symbol": symbol, "status": "NO_SETUP", "direction": None, "score": 0.0, "quality": None, "checks": [], "reason": "Not enough data yet",
            "setup": None, "price": None, "trend_word": "NEUTRAL", "regime": "SIDEWAYS", "atr": None, "atr_pct": None}
    if not htf_rows or not exec_rows or len(htf_rows) < 61 or len(exec_rows) < 61:
        return base
    hc, xc = _closed(htf_rows), _closed(exec_rows)
    price = _f(exec_rows[-1][4])
    base["price"] = price
    h_close = [_f(r[4]) for r in hc]
    he9, he21, he50 = ema(h_close, 9)[-1], ema(h_close, 21)[-1], ema(h_close, 50)[-1]
    up_stack = he9 > he21 > he50 and h_close[-1] > he21
    dn_stack = he9 < he21 < he50 and h_close[-1] < he21
    base["trend_word"] = "BULLISH" if up_stack else "BEARISH" if dn_stack else "NEUTRAL"
    base["regime"] = regime_of(hc, xc, cfg)
    atrs = atr_series(xc)
    atr = atrs[-1]
    if not atr or price <= 0:
        return base
    base["atr"], base["atr_pct"] = atr, atr / price * 100

    best = None
    for d in (("LONG", 1),) + ((("SHORT", -1),) if cfg["allow_short"] else ()):
        cand = _evaluate_side(d[0], d[1], hc, xc, price, atr, atrs, up_stack, dn_stack, cfg)
        if best is None or cand["score"] > best["score"]:
            best = cand
    base.update({k: best[k] for k in ("status", "direction", "score", "quality", "checks", "reason", "setup")})
    return base


def _evaluate_side(name, s, hc, xc, price, atr, atrs, up_stack, dn_stack, cfg):
    fee = cfg["fee_pct"]
    closes = [_f(r[4]) for r in xc]
    opens = [_f(r[1]) for r in xc]
    highs = [_f(r[2]) for r in xc]
    lows = [_f(r[3]) for r in xc]
    vols = [_f(r[5]) for r in xc]
    h_close = [_f(r[4]) for r in hc]
    word = "up" if s > 0 else "down"
    checks = []

    # ---- Trend (15m) ----
    stack = up_stack if s > 0 else dn_stack
    struct = trend_structure(hc, s)
    t_pts = (1.0 if stack else 0.0) + (1.0 if struct else 0.0)
    checks.append(_check("trend", "Trend", "pass" if stack else "fail",
                         (f"15m is in an {word}trend" + (" with a clean staircase of swings" if struct else "")) if stack
                         else f"15m is not in a clear {word}trend", t_pts, 2.0))

    # ---- Momentum (5m) ----
    r = rsi(closes)
    hist = macd_hist(closes)
    hnow, hprev = hist[-1], hist[-2]
    band = r is not None and ((50 <= r <= 75) if s > 0 else (25 <= r <= 50))
    hist_ok = hnow is not None and hnow * s > 0
    accel = hnow is not None and hprev is not None and (hnow - hprev) * s > 0
    m_pts = 0.5 * band + 0.5 * hist_ok + 0.5 * accel
    m_pass = band and hist_ok
    checks.append(_check("momentum", "Momentum", "pass" if m_pass else "fail" if r is not None else "na",
                         "n/a" if r is None else (f"Momentum is {'building' if accel else 'steady'} in the trade direction" if m_pass
                                                  else "Momentum is not confirming yet"), m_pts, 1.5))

    # ---- Volume (5m) ----
    base20 = sum(vols[-23:-3]) / 20
    vr = (sum(vols[-3:]) / 3) / base20 if base20 > 0 else None
    tb_total = sum(vols[-3:])
    tb = (sum(_f(x[9]) for x in xc[-3:]) / tb_total) if tb_total > 0 and all(len(x) > 9 for x in xc[-3:]) else None
    opposing = tb is not None and (tb - 0.5) * s < -0.05
    v_pass = vr is not None and vr >= cfg["vol_min"] and not opposing
    v_pts = 0.0 if vr is None else (1.5 if vr >= 1.5 else 1.0 if vr >= cfg["vol_min"] else 0.5 if vr >= 1.0 else 0.0)
    if opposing:
        v_pts = min(v_pts, 0.5)
    checks.append(_check("volume", "Volume", "pass" if v_pass else "fail" if vr is not None else "na",
                         "n/a" if vr is None else (("Trading is busier than normal" if vr >= cfg["vol_min"] else "Trading is quiet")
                                                   + (", but traders are leaning the other way" if opposing else "")), v_pts, 1.5))

    # ---- Structure (5m) ----
    piv = pivots(xc)
    ph = [p for p in piv if p[1] == "H"]
    pl = [p for p in piv if p[1] == "L"]
    l0, l1 = _last_two(piv, "L")
    h0, h1 = _last_two(piv, "H")
    if s > 0:
        step_ok = bool(l0 and l1 and l1[2] > l0[2])
        bos = bool(ph and closes[-1] > ph[-1][2])
    else:
        step_ok = bool(h0 and h1 and h1[2] < h0[2])
        bos = bool(pl and closes[-1] < pl[-1][2])
    st_pts = 1.5 if (step_ok and bos) else 0.75 if (step_ok or bos) else 0.0
    checks.append(_check("structure", "Structure", "pass" if st_pts > 0 else "fail",
                         ("Price has broken its last swing and holds a " + ("higher low" if s > 0 else "lower high")) if (step_ok and bos)
                         else ("Swings are stepping the right way" if step_ok else "Price just broke its last swing" if bos else "No clean structure yet"), st_pts, 1.5))

    # ---- Entry trigger (5m) ----
    e9, e21 = ema(closes, 9)[-1], ema(closes, 21)[-1]
    trig, level, swing = None, None, None
    rng = highs[-1] - lows[-1]
    pos_in_range = (closes[-1] - lows[-1]) / rng if rng > 0 else 0.5
    if s > 0:
        prior_hi = max(highs[-21:-1])
        if closes[-1] > prior_hi and pos_in_range >= 0.6 and closes[-1] - prior_hi <= atr:
            trig, level, swing = "breakout", prior_hi, prior_hi          # a failed breakout = back below the level
        elif e21 and e9 and min(lows[-6:]) <= e21 + 0.3 * atr and closes[-1] > opens[-1] and closes[-1] > e9 and stack:
            trig, level, swing = "pullback", max(highs[-6:]), min(lows[-6:])
    else:
        prior_lo = min(lows[-21:-1])
        if closes[-1] < prior_lo and pos_in_range <= 0.4 and prior_lo - closes[-1] <= atr:
            trig, level, swing = "breakout", prior_lo, prior_lo
        elif e21 and e9 and max(highs[-6:]) >= e21 - 0.3 * atr and closes[-1] < opens[-1] and closes[-1] < e9 and stack:
            trig, level, swing = "pullback", min(lows[-6:]), max(highs[-6:])
    checks.append(_check("trigger", "Entry trigger", "pass" if trig else "fail",
                         ("A strong candle just closed beyond the recent " + ("high" if s > 0 else "low") if trig == "breakout"
                          else "Price dipped to its average and bounced" if trig == "pullback" else "No entry signal yet"), 1.5 if trig else 0.0, 1.5))

    # ---- levels, volatility (fees), risk/reward ----
    zone = (price - 0.15 * atr, price + 0.10 * atr) if s > 0 else (price - 0.10 * atr, price + 0.15 * atr)
    setup, risk_note, rr = None, None, None
    ratio_atr = atr / (sum(a for a in atrs[-50:] if a) / len([a for a in atrs[-50:] if a]))
    tp1 = price + s * cfg["tp1_atr"] * atr
    cand = [p[2] for p in piv if p[1] == ("H" if s > 0 else "L") and (p[2] - price) * s > 0.8 * atr and (p[2] - price) * s <= cfg["tp1_atr"] * atr]
    if cand:
        tp1 = min(cand) if s > 0 else max(cand)
    tp2 = price + s * cfg["tp2_atr"] * atr
    if (tp2 - tp1) * s < 0.5 * atr:
        tp2 = tp1 + s * 0.5 * atr
    net_tp1 = abs(tp1 - price) / price * 100 - fee
    vol_pass = net_tp1 >= cfg["min_net_tp1_pct"] and ratio_atr < cfg["high_vol_ratio"]
    checks.append(_check("volatility", "Volatility", "pass" if vol_pass else "fail",
                         ("Moves are big enough to beat fees" if net_tp1 >= cfg["min_net_tp1_pct"] else "Typical move is too small to beat fees")
                         + ("" if ratio_atr < cfg["high_vol_ratio"] else "; prices are swinging too fast"), 1.0 if vol_pass else 0.0, 1.0))

    if swing is not None:
        stop = swing - s * cfg["stop_buffer_atr"] * atr
        risk = (price - stop) * s
        if risk < cfg["stop_atr_min"] * atr:
            stop, risk = price - s * cfg["stop_atr_min"] * atr, cfg["stop_atr_min"] * atr
        if risk > cfg["stop_atr_max"] * atr:
            risk_note = f"stop would sit {risk / price * 100:.1f}% away (max {cfg['stop_atr_max'] * atr / price * 100:.1f}%)"
        else:
            frac = cfg["partial_tp1_pct"] / 100
            gain = frac * abs(tp1 - price) + (1 - frac) * abs(tp2 - price)
            fee_px = fee / 100 * price
            rr = (gain - fee_px) / (risk + fee_px)
            setup = {"direction": name, "type": trig, "level": level, "entry_low": min(zone), "entry_high": max(zone), "entry": price,
                     "stop": stop, "tp1": tp1, "tp2": tp2, "rr": rr, "atr": atr, "risk_pct": risk / price * 100}
    rr_pass = rr is not None and rr >= cfg["min_rr"]
    checks.append(_check("rr", "Risk / Reward", "pass" if rr_pass else "fail",
                         (f"About 1 : {rr:.1f} after fees" if rr is not None else (risk_note or "No valid stop/target yet"))
                         if rr is None or rr_pass else f"Only 1 : {rr:.1f} after fees (needs {cfg['min_rr']:g})", 1.0 if rr_pass else 0.0, 1.0))

    score = round(sum(c["points"] for c in checks), 1)
    st = {c["key"]: c["state"] for c in checks}
    must = st["trend"] == "pass" and st["trigger"] == "pass" and st["volatility"] == "pass" and st["rr"] == "pass"
    quality = "HIGH" if score >= 8.5 else "MEDIUM" if score >= cfg["min_score"] else "LOW"
    if must and score >= cfg["min_score"] and setup:
        status, reason = "SETUP", f"{name.title()} setup: all required checks pass"
    else:
        missing = [c["label"] for c in checks if c["state"] != "pass"]
        if st["trend"] == "pass" and (st["structure"] == "pass" or st["momentum"] == "pass"):
            status = "WATCH"
        else:
            status = "NO_SETUP"
        if must and score < cfg["min_score"]:
            reason = f"Score {score:.1f} is below the minimum {cfg['min_score']:g}"
        else:
            reason = (missing[0] + " missing") if len(missing) == 1 else ((missing[0] + " and " + missing[1] + " missing") if missing else "Waiting")
        setup = None
    return {"status": status, "direction": name if status != "NO_SETUP" else None, "score": score, "quality": quality if status == "SETUP" else None,
            "checks": checks, "reason": reason, "setup": setup}
