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
    "fomc_reaction_checklist": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2100283427769799117",
        "date": "2026-09-16",
        "valid_days": 60,
        "families": ["FOMC"],
        "claim": ("After an FOMC decision, watch two things: (1) the bond market - if US02Y and US10Y yields fall after the decision, "
                  "the market tends to react bullishly; (2) the decision versus consensus - a decision that is unexpected (for example a "
                  "pause when a hike was the consensus) would be a surprise and can move markets sharply. He also flagged upcoming "
                  "cycle dates and Bank of Japan rate hikes as further catalysts."),
        "implication": "Rate-path surprises and the yield reaction matter more than the decision itself.",
        "how_to_use": ("After the release, check whether 2Y and 10Y yields rose or fell (Big Coins watchlist) and whether the outcome "
                       "matched the CME FedWatch probabilities you recorded; a yield drop plus a surprise is the pattern he calls out."),
    },
    "fomc_sep_2026_hike_call": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2100285353202716765",
        "date": "2026-09-16",
        "valid_days": 30,
        "families": ["FOMC"],
        "claim": ("Before the Sept 16 FOMC he cited a 92% CME-implied chance of a 25 bp hike (his figure, not verified here), expected the "
                  "decision to be a hike delivered with a very dovish speech (ample reserves, strong economy and productivity, "
                  "unemployment unchanged, uncertainty elevated but controlled), and after it posted that the bond market disagreed "
                  "with the Fed's message (\"tell that to the bond market\")."),
        "implication": "A hawkish action with a dovish tone is the pattern he expected; the bond market reaction was his test of it.",
        "how_to_use": "Compare the Fed's action and tone with what yields did next; disagreement between the two is the signal to watch.",
    },
    "rate_cuts_and_market_bottoms": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/1867986836028580053",
        "date": "2024-12-14",
        "families": ["FOMC", "CPI", "PCE"],
        "claim": ("Long-term thesis (pinned post): markets have never bottomed until rate cuts start, a pattern he says holds since the "
                  "1920s; when he wrote it he called US equities the second most expensive market by the Shiller PE ratio and said the "
                  "top is closer to the bottom."),
        "implication": "Big bottoms are expected to follow the start of a cutting cycle, not precede it.",
        "how_to_use": "A long-horizon lens for cycle context only; it says nothing about the next hours or days.",
    },
}


# Dated context. `kind` is "opinion" (one person's view) or "news" (reported by a named outlet, entered by the
# owner from a screenshot; the system has not verified it). Items expire so old context is never shown as current.
NEWS = {
    "reuters_fed_vs_treasury_2026_09_16": {
        "kind": "news",
        "author": "Reuters",
        "source": "Reuters, Sept 16, 2026 (owner-supplied screenshot; no link stored)",
        "date": "2026-09-16",
        "valid_days": 30,
        "families": ["FOMC", "CPI", "PPI", "PCE"],
        "claim": ("Reuters reports that surging government bond yields are raising credit costs across the US economy and could "
                  "factor into Fed deliberations, but analysts expect the Fed to resist any explicit call from the Trump "
                  "administration to bail out the bond market. Treasury Secretary Scott Bessent has taken an unusually "
                  "activist role in trying to tamp down yields he considers misaligned with the economic outlook."),
        "points": [
            "Analysts: the Fed is likely to strongly resist Treasury pressure on bond buying.",
            "Fed buying bonds to cap yields would conflict with its inflation fight.",
            "Some argue the Fed may need to give more weight to rising government interest costs.",
        ],
        "how_to_use": ("Watch for any Fed language on its balance sheet or bond buying and for the yield reaction. A Fed that holds firm "
                       "keeps rate-cut hopes tied to inflation data; a shift toward capping yields would be a policy change worth "
                       "treating as high-volatility."),
    },
}


def _active(item, now):
    import datetime as _dt
    if now is None or "valid_days" not in item:
        return True
    return now.date() <= _dt.date.fromisoformat(item["date"]) + _dt.timedelta(days=item["valid_days"])


def context_items(now=None, family=None):
    """Opinions and news still within their validity window (optionally for one event family)."""
    out = []
    for key, v in list(VIEWPOINTS.items()) + list(NEWS.items()):
        if _active(v, now) and (family is None or family in v["families"]):
            out.append(dict(v, id=key, kind=v.get("kind", "opinion")))
    return out


def viewpoint_for(family, now=None):
    """Labelled evidence lines for an event family from active opinions and news."""
    out = []
    for v in context_items(now, family):
        label = "News" if v["kind"] == "news" else "Analyst viewpoint (opinion, not fact"
        head = (f"News context (reported by {v['author']}, {v['date']}; not verified by this system): "
                if v["kind"] == "news" else f"Analyst viewpoint (opinion, not fact; {v['author']}, {v['date']}): ")
        out.append(f"{head}{v['claim']} Use as context only - {v['how_to_use']}")
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
