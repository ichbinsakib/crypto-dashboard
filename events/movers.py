"""'Why did the market move?': a plain-language reading of the last 24 hours built ONLY from data the app already has.

It lists the signals that lined up with the move (stocks, dollar, yields, stablecoin flows, altcoin leadership, leverage, breakouts,
data releases and the price reaction to them). These are evidence, not proof: the app cannot see news headlines, ETF flows or
liquidations, and says so. Nothing is estimated; a signal with no data is simply left out. Pure functions: no network, no database.

Every rule is a plain threshold defined below. Direction: +1 = pushes crypto up, -1 = pushes it down. Weight 1-3 = how strong."""
import datetime as dt

FLAT_PCT = 0.5               # a 24h Bitcoin move smaller than this is "flat"
STOCKS_PCT = 0.5             # Nasdaq / S&P move that counts (double = strong)
DOLLAR_PCT = 0.3
YIELD_BP = 4
STABLE_PP = 0.5              # stablecoin share change in percentage points
ALT_GAP_PP = 1.0             # altcoins vs Bitcoin gap in percentage points
OI_PCT = 3.0                 # open-interest change that matters
FUNDING_HOT = 0.0003         # 0.03% per 8h: crowded longs
FUNDING_COLD = -0.0001       # shorts paying longs
REACTION_PCT = 0.3           # Bitcoin's move within an hour of a release that counts as a reaction
HIGH_LEVELS = ("HIGH", "VERY_HIGH")
STRENGTH = {3: "STRONG", 2: "SOME", 1: "WEAK"}

CANT_SEE = ["News headlines, tweets and rumours",
            "Exchange-traded fund (ETF) money flows",
            "Forced selling and buying by leveraged traders (liquidations)",
            "Big wallets moving coins"]
DISCLAIMER = ("These are signals that lined up with the move, not proven causes. The app only sees prices and a handful of market "
              "gauges. Treat it as a starting point, and check the news before acting.")


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def size_of_move(btc_pct, typical):
    """(multiple of a normal day, plain label). `typical` = average size of Bitcoin's daily moves over the last month."""
    if btc_pct is None or not typical:
        return None, None
    m = abs(btc_pct) / typical
    label = "a small move" if m < 0.6 else "a normal-sized move" if m < 1.3 else "bigger than a normal day" if m < 2.0 else "an unusually large move"
    return round(m, 1), label


def typical_move_pct(daily_closes):
    """Average absolute daily % change over the last 30 completed days (the last value is today's forming candle and is ignored)."""
    c = [float(x) for x in daily_closes[:-1] if x]
    c = c[-31:]
    if len(c) < 10:
        return None
    moves = [abs(b / a - 1) * 100 for a, b in zip(c, c[1:]) if a]
    return sum(moves) / len(moves) if moves else None


def _factor(key, direction, weight, title, text, evidence):
    return {"key": key, "direction": direction, "weight": weight, "strength": STRENGTH[weight], "title": title, "text": text, "evidence": evidence}


def _pct_txt(v):
    return f"{v:+.1f}%"


def macro_factors(macro):
    out = []
    for sym, label in (("NDX", "the Nasdaq 100"), ("ES1!", "S&P 500 futures")):
        c = _f((macro.get(sym) or {}).get("change_pct"))
        if c is None:
            continue
        if abs(c) >= STOCKS_PCT:
            up = c > 0
            out.append(_factor("stocks_" + sym, 1 if up else -1, 2 if abs(c) >= 2 * STOCKS_PCT else 1,
                               "US stocks " + ("rose" if up else "fell"),
                               f"{label[0].upper() + label[1:]} {'rose' if up else 'fell'} {abs(c):.1f}%. Crypto has often moved with stocks, so a rising stock market usually "
                               "means investors are willing to take risk, and a falling one the opposite.", f"{label} {_pct_txt(c)}"))
        break                                             # one stock reading is enough: they move together
    d = _f((macro.get("DXY") or {}).get("change_pct"))
    if d is not None and abs(d) >= DOLLAR_PCT:
        out.append(_factor("dollar", -1 if d > 0 else 1, 2 if abs(d) >= 2 * DOLLAR_PCT else 1, "The US dollar " + ("strengthened" if d > 0 else "weakened"),
                           f"The dollar index moved {_pct_txt(d)}. A weaker dollar tends to help crypto and other risky assets; a stronger one tends to weigh on them.", f"Dollar index {_pct_txt(d)}"))
    y = _f((macro.get("US10Y") or {}).get("change_abs"))
    if y is not None and abs(y * 100) >= YIELD_BP:
        bp = y * 100
        out.append(_factor("yields", -1 if bp > 0 else 1, 2 if abs(bp) >= 2 * YIELD_BP else 1, "Interest rates " + ("rose" if bp > 0 else "fell"),
                           f"The 10-year US government interest rate moved {bp:+.0f} basis points. Lower rates usually help risky assets; higher rates usually pressure them.",
                           f"10-year yield {bp:+.0f} bp"))
    s = _f((macro.get("STABLE.C.D") or {}).get("change_abs"))
    if s is not None and abs(s) >= STABLE_PP:
        out.append(_factor("stables", -1 if s > 0 else 1, 2 if abs(s) >= 2 * STABLE_PP else 1,
                           "Money " + ("moved into stablecoins" if s > 0 else "left stablecoins"),
                           ("Stablecoins (crypto that stays at $1) took a bigger share of the market: investors are sitting on the sidelines." if s > 0 else
                            "Stablecoins lost share of the market: money is flowing out of the safe $1 coins and into other crypto."), f"Stablecoin share {s:+.2f} points"))
    return out


def breadth_factor(macro, btc_pct):
    alts = _f((macro.get("OTHERS") or {}).get("change_pct"))
    if alts is None:
        alts = _f((macro.get("TOTAL3") or {}).get("change_pct"))
    if alts is None or btc_pct is None:
        return []
    gap = alts - btc_pct
    if gap >= ALT_GAP_PP:
        return [_factor("alts_lead", 1, 1, "Smaller coins are leading", f"Coins outside the top 10 rose {gap:.1f} points more than Bitcoin. Traders only chase smaller coins when they feel confident.",
                        f"Altcoins {_pct_txt(alts)} vs Bitcoin {_pct_txt(btc_pct)}")]
    if gap <= -ALT_GAP_PP:
        return [_factor("alts_lag", -1, 1, "Smaller coins are lagging", f"Coins outside the top 10 did {abs(gap):.1f} points worse than Bitcoin. Buying is cautious and concentrated in the biggest coin.",
                        f"Altcoins {_pct_txt(alts)} vs Bitcoin {_pct_txt(btc_pct)}")]
    return []


def leverage_factors(btc, btc_pct):
    out = []
    oi, fr = _f(btc.get("oi_change_pct")), _f(btc.get("funding_rate"))
    if oi is not None and btc_pct is not None and abs(btc_pct) >= FLAT_PCT:
        up = btc_pct > 0
        if up and oi <= -OI_PCT:
            out.append(_factor("short_cover", 1, 2, "Traders betting on a fall are closing out",
                               "Prices rose while the total amount of borrowed-money bets (open interest) fell. That points to short sellers buying back to close, not fresh buyers.", f"Open interest {oi:+.1f}%"))
        elif up and oi >= OI_PCT:
            out.append(_factor("lev_build_up", -1, 1, "Part of the rise is borrowed money",
                               "Bets placed with borrowed money grew as prices rose. That can push prices further, but such rallies are fragile and can reverse quickly.", f"Open interest {oi:+.1f}%"))
        elif (not up) and oi <= -OI_PCT:
            out.append(_factor("long_flush", -1, 2, "Leveraged buyers were forced out",
                               "Prices fell while borrowed-money bets shrank quickly: traders who bought with borrowed money were closed out, which adds to the fall.", f"Open interest {oi:+.1f}%"))
        elif (not up) and oi >= OI_PCT:
            out.append(_factor("lev_build_down", -1, 1, "New bets against the price are building",
                               "Borrowed-money bets grew while prices fell: more traders are betting on further declines.", f"Open interest {oi:+.1f}%"))
    if fr is not None:
        if fr >= FUNDING_HOT:
            out.append(_factor("funding_hot", -1, 1, "Too many traders are betting on a rise", f"Buyers are paying a high fee to keep their bets open, a sign the crowd is one-sided and vulnerable to a drop.", f"Funding rate {fr * 100:+.3f}%"))
        elif fr <= FUNDING_COLD:
            out.append(_factor("funding_cold", 1, 1, "Bets against the price are crowded", "Traders betting on a fall are paying to hold their bets. If prices rise, they may rush to close, pushing prices up faster.", f"Funding rate {fr * 100:+.3f}%"))
    return out


def breakout_factor(btc, btc_pct):
    if btc.get("at_30d_high") and (btc_pct or 0) > 0:
        return [_factor("breakout_up", 1, 2, "Bitcoin pushed to a 30-day high", "Price broke above its highest level of the past month. That often attracts new buyers and forces people who were betting against it to buy back.", "New 30-day high")]
    if btc.get("at_30d_low") and (btc_pct or 0) < 0:
        return [_factor("breakout_down", -1, 2, "Bitcoin fell to a 30-day low", "Price broke below its lowest level of the past month, which tends to trigger selling from traders who had bought near the floor.", "New 30-day low")]
    return []


def event_factors(events, now):
    """(factors, notes) from data releases in the last 24 hours and what is due in the next 24."""
    out, notes, released, upcoming = [], [], [], []
    for e in events or []:
        try:
            when = dt.datetime.fromisoformat(str(e["release_datetime"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if e.get("impact_level") not in HIGH_LEVELS:
            continue
        if e.get("status") == "RELEASED" and now - dt.timedelta(hours=24) <= when <= now:
            released.append((when, e))
        elif e.get("status") != "RELEASED" and now < when <= now + dt.timedelta(hours=24):
            upcoming.append((when, e))
    for when, e in sorted(released):
        name = e.get("plain_title") or e.get("event_name") or "A major data release"
        res = ""
        if e.get("actual") is not None:
            unit = e.get("unit") or ""
            res = f"Result {e['actual']}{unit}" + (f" vs {e['forecast']}{unit} expected" if e.get("forecast") is not None else "")
        r = next((x for x in (e.get("reactions") or []) if str(x.get("asset", "")).startswith("BTC")), None)
        ret = _f((r or {}).get("return_1h"))
        if ret is None:
            ret = _f((r or {}).get("return_30m"))
        if ret is not None and abs(ret) >= REACTION_PCT:
            up = ret > 0
            out.append(_factor("event_" + str(e.get("id")), 1 if up else -1, 3 if abs(ret) >= 2 * REACTION_PCT else 2,
                               f"{name}: Bitcoin {'jumped' if up else 'dropped'} right after",
                               f"{name} was released and Bitcoin moved {ret:+.2f}% within about an hour. " + (f"{res}. " if res else "") + "Big economic numbers often move markets within minutes.",
                               f"Bitcoin {ret:+.2f}% within 1h" + (f" · {res}" if res else "")))
        else:
            notes.append(f"{name} was released" + (f" ({res})" if res else "") + ", but Bitcoin did not react much" + (" (yet)." if ret is None else "."))
    if not released:
        notes.append("No major US data release in the last 24 hours, so this was probably not a data-driven move.")
    for when, e in sorted(upcoming):
        notes.append(f"Coming up within 24 hours: {e.get('plain_title') or e.get('event_name')}. Prices often move sharply around it.")
    return out, notes


def explain(inputs, events, now=None):
    """-> the 'why it moved' block for the Market Events page, or None when there is not even a Bitcoin price change."""
    now = now or dt.datetime.now(dt.timezone.utc)
    inputs = inputs or {}
    btc, eth, macro = inputs.get("btc") or {}, inputs.get("eth") or {}, inputs.get("macro") or {}
    b = _f(btc.get("pct_24h"))
    if b is None:
        return None
    e = _f(eth.get("pct_24h"))
    total = _f((macro.get("TOTAL") or {}).get("change_pct"))
    direction = 1 if b >= FLAT_PCT else -1 if b <= -FLAT_PCT else 0
    mult, label = size_of_move(b, _f(inputs.get("typical_move_pct")))
    factors = macro_factors(macro) + breadth_factor(macro, b) + leverage_factors(btc, b) + breakout_factor(btc, b)
    ev_f, notes = event_factors(events, now)
    factors += ev_f
    factors.sort(key=lambda f: -f["weight"])
    ups = [f for f in factors if f["direction"] > 0]
    downs = [f for f in factors if f["direction"] < 0]
    if now.weekday() >= 5:
        notes.append("It is the weekend: fewer traders are active, so moves can be larger and less meaningful than on a weekday.")
    fg = inputs.get("fng") or {}
    if _f(fg.get("value")) is not None:
        v = float(fg["value"])
        if v >= 75 or v <= 25:
            notes.append(f"Crowd mood is at an extreme: {fg.get('label') or ''} ({v:.0f}/100). " + ("Very greedy crowds are more likely to be surprised by a drop." if v >= 75 else "Very fearful crowds often sell near lows."))
    word = "up" if direction > 0 else "down" if direction < 0 else "flat"
    headline = (f"Bitcoin is {word} {abs(b):.1f}% in the last 24 hours" if direction else f"Bitcoin is about flat ({b:+.1f}%) over the last 24 hours") + (f", {label}." if label else ".")
    parts = []
    if e is not None:
        parts.append(f"Ethereum {_pct_txt(e)}")
    if total is not None:
        parts.append(f"the whole crypto market {_pct_txt(total)}")
    lead = [f for f in (ups if direction >= 0 else downs)][:3]
    if direction == 0:
        summary = "Nothing pushed hard in either direction, so the market stayed quiet."
    elif lead:
        summary = "The main things that lined up with the move: " + "; ".join(f"({i}) {f['title']}" for i, f in enumerate(lead, 1)) + "."
    else:
        summary = "None of the signals the app tracks clearly explain this move: it may be news-driven or come from big traders."
    return {"as_of": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "window": "last 24 hours",
            "direction": "UP" if direction > 0 else "DOWN" if direction < 0 else "FLAT", "emoji": "\U0001F7E2" if direction > 0 else "\U0001F534" if direction < 0 else "\U0001F7E1",
            "btc_pct": round(b, 2), "eth_pct": None if e is None else round(e, 2), "total_pct": None if total is None else round(total, 2),
            "typical_pct": None if not inputs.get("typical_move_pct") else round(float(inputs["typical_move_pct"]), 2), "multiple": mult, "size_label": label,
            "headline": headline, "with": ("With " + " and ".join(parts) + ".") if parts else "", "summary": summary,
            "up": ups, "down": downs, "notes": notes, "cant_see": CANT_SEE, "disclaimer": DISCLAIMER}


def update_history(hist, m, now, keep=30):
    """One row per UTC day (today's row is overwritten as the day goes on), newest last; the log is what lets you look back."""
    day = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%d")
    lead = [f["title"] for f in (m["up"] if m["direction"] != "DOWN" else m["down"])][:2]
    row = {"date": day, "direction": m["direction"], "btc_pct": m["btc_pct"], "eth_pct": m["eth_pct"], "total_pct": m["total_pct"], "size": m.get("size_label"), "main": lead}
    hist = [r for r in (hist or []) if r.get("date") != day] + [row]
    return sorted(hist, key=lambda r: r["date"])[-keep:]
