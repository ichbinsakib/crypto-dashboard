"""One-line overall crypto market status, shown under the price alerts.

Built only from data the dashboard already fetches (no new source):
  * BTC and ETH: price, 24h/7d/30d change, 50/200-day averages, 30-day high/low   (CoinGecko, in coins_data)
  * BTC/ETH daily candles (already fetched for the Wyckoff check): normal daily range and volume
  * Wyckoff topping-pattern detector for BTC/ETH
  * Whole-market 24h change (TOTAL market cap) from the macro rows, used only as a caution note

Plain rules, checked in this order; the first that matches wins. Each state says what is happening and what it means.
Educational, not advice. "Accumulation" is not offered because nothing here can detect it reliably.

  1. HIGH VOLATILITY  BTC/ETH moved much more than usual over 24h
  2. DISTRIBUTION     price near its 30-day high and the topping-pattern detector fires
  3. BREAKOUT         BTC or ETH is at a new 30-day high and green today
  4. BULLISH TREND    BTC trend is up and ETH is not down
  5. BEARISH TREND    BTC trend is down and ETH is not up
  6. SIDEWAYS / SCALPING CONDITIONS  no trend: quiet = sideways, active = scalping conditions
  7. NO CLEAR SIGNAL  BTC and ETH disagree, or data is missing

A coin's trend = 4 votes (above/below 50-day avg, above/below 200-day avg, up/down over 7d, up/down over 30d; a tiny
weekly or monthly change abstains): 3+ up = up, 3+ down = down, otherwise mixed."""

VOL_RATIO_HIGH = 1.8         # 24h range vs the normal daily range
VOL_MIN_RANGE_PCT = 4.0      # ... and at least this big in absolute terms
ACTIVE_RATIO = 1.2           # "active" = range or volume this much above normal
NEAR_HIGH = 0.99             # within 1% of the 30-day high counts as at the high
DIST_NEAR_HIGH = 0.90        # topping pattern only matters while price is still within 10% of the high
MOVE_7D, MOVE_30D = 1.5, 3.0     # a weekly/monthly change smaller than this is noise, not a vote
SIDEWAYS_7D, SIDEWAYS_30D = 4.0, 10.0
WEAK_MARKET_24H = -2.0       # whole-market 24h change that triggers the "others are weak" note
STRONG_MARKET_24H = 2.0

STATES = {
    "BREAKOUT": ("\U0001F535", "breakout"),
    "BULLISH TREND": ("\U0001F7E2", "bullish"),
    "BEARISH TREND": ("\U0001F534", "bearish"),
    "DISTRIBUTION": ("\U0001F7E3", "distribution"),
    "HIGH VOLATILITY": ("⚠️", "volatile"),
    "SCALPING CONDITIONS": ("\U0001F7E0", "scalping"),
    "SIDEWAYS": ("\U0001F7E1", "sideways"),
    "NO CLEAR SIGNAL": ("⚪", "none"),
}


def _daily_stats(klines):
    """-> (normal daily range %, latest completed day's volume vs its 20-day average). Last row is today's forming candle."""
    try:
        done = klines[:-1]
        if len(done) < 25:
            return None, None
        rng = [(float(k[2]) - float(k[3])) / float(k[4]) * 100 for k in done[-30:] if float(k[4]) > 0]
        vols = [float(k[5]) for k in done]
        base = sum(vols[-21:-1]) / 20
        return (sum(rng) / len(rng) if rng else None), (vols[-1] / base if base > 0 else None)
    except (TypeError, ValueError, IndexError):
        return None, None


def _coin(c, klines):
    """Reduce one coin's data to the few facts the rules use. Missing inputs stay None."""
    c = c or {}
    price = c.get("price")
    votes_up = votes_down = known = 0
    # each vote is +1 (up), -1 (down) or 0 (too small to count: inside the dead zone)
    votes = []
    if c.get("sma50") is not None and price is not None:
        votes.append(1 if price > c["sma50"] else -1)
    if c.get("sma200") is not None and price is not None:
        votes.append(1 if price > c["sma200"] else -1)
    if c.get("pct_7d") is not None:
        votes.append(1 if c["pct_7d"] >= MOVE_7D else -1 if c["pct_7d"] <= -MOVE_7D else 0)
    if c.get("pct_30d") is not None:
        votes.append(1 if c["pct_30d"] >= MOVE_30D else -1 if c["pct_30d"] <= -MOVE_30D else 0)
    known = len(votes)
    votes_up, votes_down = votes.count(1), votes.count(-1)
    trend = "unknown" if known < 3 else "up" if votes_up >= 3 else "down" if votes_down >= 3 else "mixed"
    res = c.get("resistance_30d")
    at_high = bool(price and res and price >= NEAR_HIGH * res)
    rng24 = ((c["high_24h"] - c["low_24h"]) / price * 100) if price and c.get("high_24h") and c.get("low_24h") else None
    normal_rng, vol_ratio = _daily_stats(klines) if klines else (None, None)
    return {"price": price, "trend": trend, "at_high": at_high, "near_high": bool(price and res and price >= DIST_NEAR_HIGH * res),
            "pct_24h": c.get("pct_24h"), "pct_7d": c.get("pct_7d"), "pct_30d": c.get("pct_30d"),
            "range_24h": rng24, "normal_range": normal_rng, "range_ratio": (rng24 / normal_rng) if rng24 and normal_rng else None,
            "vol_ratio": vol_ratio, "above50": (price > c["sma50"]) if price and c.get("sma50") else None,
            "above200": (price > c["sma200"]) if price and c.get("sma200") else None}


ENTRY = {"GOOD": "\u2705 GOOD TIME", "WAIT": "\U0001F7E1 WAIT", "BAD": "\u26D4 BAD TIME"}
# what the main screen shows (plain English); the longer wording stays behind the (i)
ENTRY_WORD = {"GOOD": "Good time to buy", "WAIT": "Better to wait", "BAD": "Bad time to buy"}
DISPLAY = {   # state -> (headline word, one short sentence)
    "BREAKOUT": ("BREAKOUT", "Price just broke above its 30-day high."),
    "BULLISH TREND": ("BULLISH", "Buyers are stronger."),
    "BEARISH TREND": ("BEARISH", "Sellers are stronger."),
    "DISTRIBUTION": ("SELLING PRESSURE", "Big holders may be selling."),
    "HIGH VOLATILITY": ("HIGH VOLATILITY", "Prices are swinging; signals are less reliable."),
    "SCALPING CONDITIONS": ("SIDEWAYS", "Quick moves, but no clear direction."),
    "SIDEWAYS": ("SIDEWAYS", "No clear direction yet."),
    "NO CLEAR SIGNAL": ("NO CLEAR DIRECTION", "Signals are mixed."),
}


def _fmt(state, text, why, entry=("WAIT", "no clear edge, so waiting costs nothing.", "No clear edge."), short=None):
    """entry = (GOOD|WAIT|BAD, longer reason, short reason). This is about buying (long-only, spot), not shorting."""
    emoji, css = STATES[state]
    rating, reason = entry[0], entry[1]
    entry_short = entry[2] if len(entry) > 2 else reason
    title, default_short = DISPLAY[state]
    return {"state": state, "title": title, "short": short or default_short, "emoji": emoji, "css": css, "text": text, "why": why,
            "entry": rating, "entry_text": reason, "entry_short": entry_short, "entry_word": ENTRY_WORD[rating],
            "line": f"{emoji} MARKET STATUS: {state} \u2014 {text} Entry: {ENTRY[rating]} \u2014 {reason}"}


def assess(coins_data, klines_by_coin=None, wyckoff_by_coin=None, total_change_24h=None):
    """-> {state, emoji, css, text, why[], line}. Never raises on missing data: it says NO CLEAR SIGNAL instead."""
    klines_by_coin = klines_by_coin or {}
    wyckoff_by_coin = wyckoff_by_coin or {}
    by_key = {c.get("key"): c for c in (coins_data or [])}
    btc = _coin(by_key.get("BTC"), klines_by_coin.get("BTC"))
    eth = _coin(by_key.get("ETH"), klines_by_coin.get("ETH"))
    if btc["trend"] == "unknown":
        return _fmt("NO CLEAR SIGNAL", "Not enough Bitcoin data right now to read the market.", ["Bitcoin price history is unavailable"],
                    ("WAIT", "without a reading, do not enter on this app's say-so.", "Not enough data."), short="Not enough data yet.")

    def pct(v):
        return "n/a" if v is None else f"{v:+.1f}%"
    why = [f"BTC: 7d {pct(btc['pct_7d'])}, 30d {pct(btc['pct_30d'])}, trend {btc['trend']}",
           f"ETH: 7d {pct(eth['pct_7d'])}, 30d {pct(eth['pct_30d'])}, trend {eth['trend']}"]
    if total_change_24h is not None:
        why.append(f"Whole crypto market 24h: {total_change_24h:+.1f}%")

    def others_note(bullish):
        if total_change_24h is None:
            return ""
        if bullish and total_change_24h <= WEAK_MARKET_24H:
            return " But the wider market is down today, so it is not broad."
        if not bullish and total_change_24h >= STRONG_MARKET_24H:
            return " But the wider market is up today, so watch for a turn."
        return ""

    # 1. unusually fast moves make every signal less reliable
    wild = [(n, c) for n, c in (("Bitcoin", btc), ("Ethereum", eth))
            if c["range_ratio"] and c["range_ratio"] >= VOL_RATIO_HIGH and (c["range_24h"] or 0) >= VOL_MIN_RANGE_PCT]
    if wild:
        n, c = wild[0]
        return _fmt("HIGH VOLATILITY", f"{n} is swinging about {c['range_ratio']:.1f}× more than a normal day, so signals are less reliable; "
                    "trade smaller or wait for it to calm down.", why + [f"{n} 24h range {c['range_24h']:.1f}% vs normal {c['normal_range']:.1f}%"],
                    ("BAD", "prices jump around, so a bad fill or a stop-out is more likely; wait for calmer moves.", "Prices jump around."))

    # 2. still near the highs, but the topping-pattern detector says big sellers are unloading
    w = wyckoff_by_coin.get("BTC") or {}
    if btc["near_high"] and w.get("stage") in ("utad", "sow", "lpsy") and w.get("confidence") != "LOW":
        return _fmt("DISTRIBUTION", "Price is still high, but large holders look like they are selling into it (a topping pattern); "
                    "the rise may be running out of steam.", why + [f"Bitcoin chart pattern: {w.get('stage')} ({w.get('confidence')})"],
                    ("BAD", "buying near a top is the classic mistake; avoid new buys here.", "Avoid buying near a top."))

    # 3. a new 30-day high on a green day
    for n, c in (("Bitcoin", btc), ("Ethereum", eth)):
        if c["at_high"] and (c["pct_24h"] or 0) > 0:
            vol = " with above-normal trading volume" if (c["vol_ratio"] or 0) >= 1.2 else ""
            return _fmt("BREAKOUT", f"{n} just pushed to a new 30-day high{vol}: buyers broke through the recent ceiling. "
                        "Breakouts can fail." + others_note(True), why + [f"{n} is at its 30-day high"],
                        ("WAIT", "chasing a fresh high often gets reversed; a better entry is after it holds above the old ceiling or dips back to it.", "Don't chase; wait for it to hold."))

    res_btc = (by_key.get("BTC") or {}).get("resistance_30d")

    # 4/5. clear direction
    if btc["trend"] == "up" and eth["trend"] != "down":
        entry = ("GOOD", "the trend is up, so buying small dips has the odds on its side; still use a stop.", "Uptrend; small dips are usual entries.")
        if btc["price"] and res_btc and btc["price"] >= 0.97 * res_btc:
            entry = ("WAIT", "the trend is up but price is right at its 30-day high; a small dip is a safer place to buy.", "Price is at its high; a dip is safer.")
        elif total_change_24h is not None and total_change_24h <= WEAK_MARKET_24H:
            entry = ("WAIT", "the trend is up but the wider market is falling today; wait for it to steady.", "The wider market is falling today.")
        return _fmt("BULLISH TREND", "Buyers are stronger: Bitcoin is above its 50- and 200-day average prices and rising over the past week and month."
                    + others_note(True), why, entry)
    if btc["trend"] == "down" and eth["trend"] != "up":
        return _fmt("BEARISH TREND", "Sellers are stronger: Bitcoin is below its long-term average prices and falling."
                    + others_note(False), why, ("BAD", "catching a falling market usually loses money; wait until it stops making new lows.", "The market is falling."))

    # 6/7. no clear trend
    if btc["trend"] in ("up", "down") and eth["trend"] in ("up", "down") and btc["trend"] != eth["trend"]:
        return _fmt("NO CLEAR SIGNAL", "Bitcoin and Ethereum are pointing in opposite directions, so there is nothing reliable to read right now.", why,
                    ("WAIT", "with no agreement there is no edge; wait for both to point the same way.", "No agreement yet."), short="Bitcoin and Ethereum disagree.")
    flat = abs(btc["pct_7d"] or 0) <= SIDEWAYS_7D and abs(btc["pct_30d"] or 0) <= SIDEWAYS_30D
    active = (btc["range_ratio"] or 0) >= ACTIVE_RATIO or (btc["vol_ratio"] or 0) >= ACTIVE_RATIO
    if flat and active:
        return _fmt("SCALPING CONDITIONS", "Short-term moves are active but there is no larger trend: only quick, small trades make sense, "
                    "and trading fees eat much of them.", why,
                    ("WAIT", "not a good time for a normal buy-and-hold entry; only quick, small trades, and fees take a big share.", "Only quick trades; fees eat them."))
    if flat:
        return _fmt("SIDEWAYS", "Buyers and sellers are balanced: price is drifting in a range with no clear direction yet.", why,
                    ("WAIT", "no edge in the middle of a range; better to wait for a breakout, or buy only near the bottom of the range.", "No edge mid-range."))
    return _fmt("NO CLEAR SIGNAL", "Signs are mixed (some up, some down), so there is no dominant direction to read.", why,
                    ("WAIT", "wait for a clearer direction.", "Wait for a clearer picture."))


ACTION = {"BREAKOUT": "Watch", "BULLISH": "Watch", "BEARISH": "Avoid", "SELLING PRESSURE": "Avoid", "SIDEWAYS": "Wait", "NO CLEAR DIRECTION": "Wait"}


def coin_status(c, wy=None):
    """Simple per-coin read for the overview and coin cards -> {word, emoji, css, note, action}. Same rules as the market line,
    for one coin: 30-day high, selling-pressure pattern, then trend."""
    k = _coin(c, None)
    if k["trend"] == "unknown":
        return {"word": "NO CLEAR DIRECTION", "emoji": "\u26AA", "css": "none", "note": "Not enough data yet.", "action": "Wait"}
    if k["at_high"] and (k["pct_24h"] or 0) > 0:
        r = ("BREAKOUT", "\U0001F535", "breakout", "Above its 30-day ceiling")
    elif k["near_high"] and (wy or {}).get("stage") in ("utad", "sow", "lpsy") and (wy or {}).get("confidence") != "LOW":
        r = ("SELLING PRESSURE", "\U0001F7E3", "distribution", "Selling may be increasing")
    elif k["trend"] == "up":
        r = ("BULLISH", "\U0001F7E2", "bullish", "Buyers are stronger")
    elif k["trend"] == "down":
        r = ("BEARISH", "\U0001F534", "bearish", "Sellers are stronger")
    elif abs(k["pct_7d"] or 0) <= SIDEWAYS_7D:
        r = ("SIDEWAYS", "\U0001F7E1", "sideways", "No clear direction yet")
    else:
        r = ("NO CLEAR DIRECTION", "\u26AA", "none", "Signals are mixed")
    return {"word": r[0], "emoji": r[1], "css": r[2], "note": r[3], "action": ACTION[r[0]]}


def card_html(status, esc):
    """The market-status card: a headline, one short sentence and the entry verdict. Reasons sit behind the (i)."""
    tip = ("How this was decided: " + "; ".join(status["why"]) + ". Entry: " + status["entry_text"] +
           " Simple rules on Bitcoin/Ethereum trend, volatility, volume and 30-day highs. The entry verdict is about buying "
           "(not shorting) and is a rule of thumb, not a prediction or advice: none of it is proven to make money.")
    return (f'<div class="ms-card ms-{status["css"]}" role="status">'
            f'<div class="ms-head"><span class="ms-title">{status["emoji"]} MARKET: {esc(status["title"])}</span>'
            f'<span class="info-tip" tabindex="0" data-tip="{esc(tip)}">&#9432;</span></div>'
            f'<div class="ms-sub">{esc(status["short"])}</div>'
            f'<div class="ms-entry ms-e-{status["entry"].lower()}"><span class="ms-e-label">Buying now</span> '
            f'<b>{ENTRY[status["entry"]].split(" ", 1)[0]} {esc(status["entry_word"])}</b> '
            f'<span class="ms-e-why">\u00B7 {esc(status["entry_short"])}</span></div></div>')


def line_html(status, esc):
    """Kept for compatibility: the card is the one place the status is drawn now."""
    return card_html(status, esc)
