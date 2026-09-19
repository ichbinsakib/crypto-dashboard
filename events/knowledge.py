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


# Attributed opinions. These are NOT facts and never change a signal; the engine may show them as
# context next to related events, always labelled as one analyst's view with its date and source.
VIEWPOINTS = {
    "yields_demand_for_us_debt": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2100299248881529267",
        "date": "2026-09-17",
        "families": ["FOMC", "CPI", "PPI", "PCE"],
        "claim": ("Higher US yields are read as weak demand for US debt (buyers stepping away from USD assets) "
                  "rather than economic strength, competition for capital or geopolitics, which are the reasons "
                  "cited by the Fed side. Raising rates to attract buyers may not work if nobody is buying, and the "
                  "central bank buying its own bonds is seen as a sign of that weakness."),
        "implication": ("The view expects markets to be held up until the US midterm elections, with an outside shock "
                        "(for example from Japan's or China's central bank/bond selling) being the main way that changes."),
        "how_to_use": ("Treat as a macro lens for rate-driven events: if yields rise after a hawkish surprise, ask whether it is "
                       "growth or falling demand for debt. Confirm with data (auction results, yield moves) before acting."),
    },
}


def viewpoint_for(family):
    """Attributed opinions relevant to an event family, as short labelled evidence lines."""
    out = []
    for v in VIEWPOINTS.values():
        if family in v["families"]:
            out.append(f"Analyst viewpoint (opinion, not fact; {v['author']}, {v['date']}): {v['claim']} "
                       f"Use as context only - {v['how_to_use']}")
    return out


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
