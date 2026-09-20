"""Plain-English display layer.

Only VISIBLE TEXT is rewritten (the text between tags). Tooltips (data-tip / title attributes), class names, ids and the
underlying calculations are never touched, so the technical wording still lives in the (i) tips. Longest phrases run first.
Applied to a section's HTML just before it is published; it changes words, never numbers or logic."""
import re

PHRASES = [
    # ceiling / floor instead of resistance / support
    ("Key Resistance (30d high)", "Ceiling (30-day high)"), ("Key Support (30d low)", "Floor (30-day low)"),
    ("Key Resistance (30d)", "Ceiling (30-day high)"), ("Key Support (30d)", "Floor (30-day low)"),
    ("30-day resistance", "30-day ceiling"), ("30-day support", "30-day floor"),
    ("breakout above resistance", "breakout above the ceiling"), ("pulls back to support", "pulls back to the floor"),
    ("above resistance", "above the ceiling"), ("Target 1 (resistance)", "Target 1 (ceiling)"),
    # selling / buying pressure instead of distribution / accumulation
    ("WATCH THE OVERHEAD RANGE (POSSIBLE DISTRIBUTION)", "WATCH THE CEILING (SELLING MAY BE INCREASING)"),
    ("possible Wyckoff distribution pattern", "possible pattern of selling increasing"),
    ("No Wyckoff distribution structure detected", "No sign of selling increasing"),
    ("Wyckoff structure (distribution)", "Selling-increasing pattern"),
    ("No distribution", "No heavy selling"),
    ("ACCUMULATION ZONE", "BUYING INCREASING"), ("DISTRIBUTION ZONE", "SELLING INCREASING"),
    ("Basing near the bottom - phase where smart money accumulates", "Flat near the bottom while big buyers build positions"),
    ("Very extended after a big run - phase where smart money sells", "Very stretched after a big run; big holders may be selling"),
    ("10 = accumulation end, 1 = markdown risk", "10 = buying is increasing, 1 = price falling"),
    ("Accumulation", "Buying increasing"), ("Distribution", "Selling increasing"), ("Markup", "Rising"), ("Markdown", "Falling"),
    # spikes and crowding
    ("Parabolic price + overheated funding + exploding open interest.", "Vertical price spike + crowded buyers + fast-rising leverage."),
    ("No parabolic price.", "No vertical price spike."),
    ("Blow-off move / vertical trend", "Sudden vertical spike"), ("Parabolic breakout", "Vertical spike"),
    ("Overheated longs / short squeeze", "Crowded buyers / sudden squeeze"), ("Overheated longs", "Too many crowded buyers"),
    ("Excessive bullish basis", "Futures priced far above spot"), ("Premium sharply elevated", "Futures much dearer than spot"),
    ("OI exploding higher", "Leverage rising fast"), ("Valuation overheating", "Price looks overheated"),
    ("Euphoric crowd behavior", "Crowd very greedy"), ("FOMO mania everywhere", "Extreme greed everywhere"),
    ("Net unrealized profit/loss, euphoria zone", "How much holders are in profit"), ("Euphoric zone", "Very optimistic"),
    ("Sustained spot demand", "Steady buying"), ("Heavy inflows / balance rise", "Lots of coins moving onto exchanges"),
    # row and card titles (the technical name stays in brackets)
    ("SIGNAL TABLE (CORE OF DASHBOARD)", "MARKET CHECKS"), ("Top Warning Level", "Warning sign"),
    ("Funding Rates", "Trader crowding (funding)"), ("Open Interest (OI)", "Leverage buildup (open interest)"),
    ("Futures Premium", "Futures vs spot price"), ("MVRV Z-Score", "Valuation (MVRV)"), ("NUPL", "Holder profit (NUPL)"),
    ("Retail Mania (Fear &amp; Greed)", "Crowd mood (Fear &amp; Greed)"), ("Exchange Inflows / Outflows", "Coins moving to / from exchanges"),
    ("KAIRO HEAT SCORE (model estimate)", "OVERHEAT METER (model estimate)"),
    ("CYCLE MAP (heuristic, price vs 50/200-day average)", "MARKET PHASE (rough estimate)"), ("CYCLE MAP", "MARKET PHASE"),
    ("MARKET CYCLE SCORE", "MARKET PHASE SCORE"), ("Cycle stage:", "Phase:"), ("NOT A CYCLE TOP YET", "NOT AT A TOP YET"),
    ("SPOT SIGNAL (educational, rule-based model)", "BUY / WAIT SIGNAL"), ("TRADE LEVELS (formula-based, educational)", "ENTRY, STOP AND TARGETS"),
]
PHRASES.sort(key=lambda p: -len(p[0]))

_TEXT = re.compile(r">([^<>]+)<")


def simplify_text(text):
    for old, new in PHRASES:
        if old in text:
            text = text.replace(old, new)
    return text


def simplify(html):
    """Rewrite the visible text of an HTML fragment. Attributes (tooltips included) are left exactly as they are."""
    return _TEXT.sub(lambda m: ">" + simplify_text(m.group(1)) + "<", html or "")
