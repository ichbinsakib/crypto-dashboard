"""Stored market concepts the engine can cite. Plain data so entries can be added without touching logic.

Each concept has: what it means, how to recognise it in data we actually hold, and how it changes how much
weight an assessment deserves. Concepts only add cautions/evidence text; they never change trading signals."""

CONCEPTS = {
    "propping_up": {
        "title": "Propping up the market",
        "meaning": ("Big buyers (whales, large traders or groups) keep buying to stop a price falling too fast, "
                    "so it looks stronger than the organic demand behind it. It also protects the value of their own holdings."),
        "how_it_helps": "If the support is real the price can hold for a while; it is temporary help, not proof of strength.",
        "risk": "If the buying stops, the price can fall again - often quickly.",
        "signs_in_data": [
            "Price repeatedly holds the same low on high volume (absorption) while making no progress upward.",
            "A dip is bought within minutes, but volume fades on the following bounces.",
            "A strong move that lacks follow-through volume after the first hour.",
        ],
        "assessment_rule": ("A bullish reading that rests only on a price bounce is capped at MEDIUM confidence "
                            "and carries this caution, because a bounce can be support rather than demand."),
    },
}


def caution(name="propping_up"):
    c = CONCEPTS[name]
    return f"Caution ({c['title'].lower()}): {c['risk']} A bounce can be temporary support, not organic strength."


def support_check(candles, lookback=60):
    """Experimental, informational only. From 1-minute candles [{t,high,low,close,volume?}] after an event:
    does the lowest low get retested (absorption) while later volume fades? Returns None without enough data."""
    if len(candles) < lookback or "volume" not in candles[0]:
        return None
    win = candles[-lookback:]
    low = min(c["low"] for c in win)
    tests = sum(1 for c in win if c["low"] <= low * 1.0005)
    half = lookback // 2
    v1 = sum(c["volume"] for c in win[:half]) or 0
    v2 = sum(c["volume"] for c in win[half:]) or 0
    fading = v1 > 0 and v2 < 0.7 * v1
    return {"low_retests": tests, "volume_fading": fading,
            "note": "Repeated defence of a low with fading volume can indicate temporary support." if tests >= 3 and fading
                    else "No clear sign of temporary support."}
