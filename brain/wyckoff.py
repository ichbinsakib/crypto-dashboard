"""Wyckoff distribution schematic (the topping structure): what it is, and a rule-based detector on candles.

Schematic (Richard Wyckoff / Wyckoff Method, distribution after an advance):
  Phase A  stopping the uptrend    PSY preliminary supply -> BC buying climax (high volume, wide spread) ->
                                   AR automatic reaction (sharp drop that sets the range low, "ice"/support) ->
                                   ST secondary test of the BC zone (demand weaker, volume lower)
  Phase B  building the cause      range-bound trading; upper-range tests; supply absorbs demand
  Phase C  the test                UT / UTAD: a poke above the range high that closes back inside (a trap for breakout buyers)
  Phase D  the trend inside range  SOW sign of weakness (drop through ice on volume) -> LPSY last point of supply
                                   (weak rally that fails under the broken support, lower high)
  Phase E  markdown                price leaves the range downward

The detector is heuristic: it reports the most advanced stage it can evidence, with the evidence listed.
Informational unless a signal explicitly uses it - and whether that helps is a backtest question."""

# Scores follow the backtest (see BACKTEST in course.py): a distribution range after a climax lags the baseline on
# daily and 4h data; the later stages were bearish vs baseline on 4h but noisy on daily, so they only score -2 with confidence.
DIST_SCORE = {"none": 0, "range": -1, "utad": -2, "sow": -2, "lpsy": -2, "markdown": 0}

SCHEMATIC = [
    {"phase": "A", "events": ["PSY", "BC", "AR", "ST"], "meaning": "Demand runs out: a high-volume buying climax, a sharp automatic reaction, then a weaker retest of the high."},
    {"phase": "B", "events": ["UT", "ST"], "meaning": "Sideways range in which large holders distribute into strength; upper-range tests."},
    {"phase": "C", "events": ["UTAD"], "meaning": "Upthrust after distribution: a poke above the range high that closes back inside - the trap."},
    {"phase": "D", "events": ["SOW", "LPSY"], "meaning": "Sign of weakness through support, then a weak rally that fails (last point of supply)."},
    {"phase": "E", "events": ["markdown"], "meaning": "Price trends down out of the range."},
]


def _series(klines):
    h = [float(k[2]) for k in klines]
    l = [float(k[3]) for k in klines]
    c = [float(k[4]) for k in klines]
    v = [float(k[5]) for k in klines]
    return h, l, c, v


def _atr(h, l, c, n=14):
    trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return sum(trs[-n:]) / n if len(trs) >= n else None


def _fmt(x):
    return f"{x:,.2f}" if x >= 1 else f"{x:.4g}"


def detect_distribution(klines, min_after_bc=10, uptrend_lookback=25, uptrend_atr=3.0, ar_window=15):
    """-> {stage, score, evidence[], levels{}, confidence}. stage in none|range|utad|sow|lpsy|markdown."""
    none = {"stage": "none", "score": 0, "evidence": [], "levels": {}, "confidence": "LOW"}
    if len(klines) < 40:
        return none
    h, l, c, v = _series(klines)
    n = len(c)
    atr = _atr(h, l, c)
    if not atr:
        return none
    avg_v = sum(v[-60:]) / min(60, n) or 1

    # Buying climax: highest high with a prior advance and room after it for a range to form.
    bc_i = max(range(n - min_after_bc), key=lambda i: h[i])
    if bc_i < uptrend_lookback:
        return none
    if c[bc_i] - c[bc_i - uptrend_lookback] < uptrend_atr * atr:
        return none                                                   # no prior advance: not a topping structure
    bc_high = h[bc_i]
    # Automatic reaction: the lowest low soon after the climax sets the range floor.
    ar_end = min(n, bc_i + ar_window + 1)
    ar_i = min(range(bc_i + 1, ar_end), key=lambda i: l[i]) if bc_i + 1 < ar_end else None
    if ar_i is None:
        return none
    ar_low = l[ar_i]
    width = bc_high - ar_low
    if width < 2 * atr:
        return none                                                   # too shallow to be a real reaction
    evidence = [f"Buying climax high {_fmt(bc_high)} after an advance of {(c[bc_i] - c[bc_i - uptrend_lookback]) / atr:.1f} ATR"]
    points = 1
    if v[bc_i] >= 1.3 * avg_v or max(v[max(0, bc_i - 1):bc_i + 2]) >= 1.5 * avg_v:
        evidence.append("Climactic volume at the high")
        points += 1
    evidence.append(f"Automatic reaction to {_fmt(ar_low)} sets the range floor (range {width / bc_high * 100:.1f}% tall)")

    after = range(ar_i + 1, n)
    inside = [i for i in after if ar_low * 0.99 <= c[i] <= bc_high * 1.01]
    if not after or len(inside) / max(1, len(after)) < 0.5 and c[-1] >= ar_low:
        return none                                                   # price left the box upward: not distribution
    if c[-1] > bc_high:
        return none                                                   # closed above the climax high: distribution failed, it is a breakout
    tests = sum(1 for i in after if h[i] >= bc_high * 0.97 and c[i] <= bc_high)
    if tests:
        evidence.append(f"{min(tests, 9)} test(s) of the upper range (secondary tests)")
        points += 1
    levels = {"bc_high": bc_high, "range_low": ar_low, "range_mid": (bc_high + ar_low) / 2}

    # Upthrust: poked above the climax high, closed back inside.
    ut = [i for i in after if h[i] > bc_high and c[i] < bc_high and h[i] <= bc_high * 1.06]
    # Sign of weakness: a close below the range floor.
    sow = [i for i in after if c[i] < ar_low]
    last = n - 1
    stage = "range"
    if ut and (not sow or ut[-1] < sow[0]):
        stage = "utad" if last - ut[-1] <= 12 else "range"
        if stage == "utad":
            evidence.append("Upthrust: price poked above the highs and closed back inside (bull trap)")
            points += 1
            if v[ut[-1]] >= 1.2 * avg_v:
                evidence.append("on heavy volume")
                points += 1
    if sow:
        s0 = sow[0]
        evidence.append("Sign of weakness: closed below the range floor" + (" on heavy volume" if v[s0] >= 1.2 * avg_v else ""))
        points += 2 if v[s0] >= 1.2 * avg_v else 1
        recent = last - s0 <= 12
        stage = "sow" if recent else "markdown"
        if c[last] >= ar_low:
            if not recent:
                stage = "range"                                           # price recovered into the box: the break failed
        elif recent and last - s0 >= 2:
            # After the break, a rally that fails under the broken support on lighter volume = last point of supply.
            post = range(s0 + 1, last + 1)
            bounce_hi = max(h[i] for i in post)
            bounce_vol = sum(v[i] for i in post) / len(post)
            if bounce_hi <= ar_low * 1.02 + 0.5 * atr and bounce_hi > min(l[i] for i in post) + 0.3 * atr and bounce_vol < v[s0]:
                stage = "lpsy"
                evidence.append("Weak rally on lighter volume failed under the broken support (last point of supply)")
                points += 1
    conf = "HIGH" if points >= 6 else "MEDIUM" if points >= 4 else "LOW"
    return {"stage": stage, "score": DIST_SCORE[stage], "evidence": evidence, "levels": levels, "confidence": conf}


def spot_factor(det, weight=1.0):
    """(points, reading) for the BTC/ETH spot-signal table."""
    if not det or det["stage"] == "none":
        return 0, "No Wyckoff distribution structure detected"
    names = {"range": "possible distribution range (Phase A/B)", "utad": "upthrust after distribution (Phase C)",
             "sow": "sign of weakness (Phase D)", "lpsy": "last point of supply (Phase D)", "markdown": "markdown (Phase E) - the drop has already happened"}
    pts = det["score"]
    if pts < -1 and det["confidence"] == "LOW":
        pts = -1                                                       # late-stage read with thin evidence: only a mild lean
    pts = round(pts * weight)
    return pts, f"{names[det['stage']][0].upper() + names[det['stage']][1:]}, {det['confidence'].lower()} confidence: " + "; ".join(det["evidence"][:3])
