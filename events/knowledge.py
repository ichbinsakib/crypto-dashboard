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
    "anticipate_dont_chase": {
        "title": "Anticipate, don't chase (scale in small, wait for capitulation)",
        "meaning": ("Plan entries in advance around fear zones instead of buying after a move has already run. Put only a small first "
                    "tranche (10-20%) to work to control FOMO, and keep the rest for the capitulation phase."),
        "how_it_helps": "Avoids paying up in euphoria and leaves cash for the real washout; you do not need the exact bottom.",
        "risk": "Waiting can mean missing a V-shaped recovery, and a planned zone can fail; size the first tranche so that is acceptable.",
        "signs_in_data": [
            "Price reaches a pre-planned zone on falling volume after a sharp weekly drop (35%+ weeks are normal for Bitcoin).",
            "Sentiment (Fear & Greed) in the fear range while price is far below its long-term average.",
        ],
        "assessment_rule": "Context only: the app shows sentiment and stretch factors already; this concept adds the scale-in discipline.",
    },
    "wyckoff_distribution": {
        "title": "Wyckoff distribution schematic",
        "meaning": ("A topping structure after an advance. Phase A: preliminary supply, a buying climax (heavy volume, wide spread), an "
                    "automatic reaction that sets the range floor, and a weaker secondary test. Phase B: a sideways range while large holders "
                    "sell into strength. Phase C: an upthrust after distribution (UTAD), a poke above the highs that closes back inside. "
                    "Phase D: a sign of weakness through the floor on volume, then a last point of supply (a weak rally that fails under the "
                    "broken support). Phase E: markdown."),
        "how_it_helps": "Explains why a strong-looking breakout above a range can be a trap, and where support gives way.",
        "risk": "The stages are subjective and overlap in time; a range can also resolve upward (re-accumulation), so a Wyckoff read is a lean, not a call.",
        "signs_in_data": [
            "A high-volume climax after a long advance, then a sharp drop and a range holding below the high.",
            "A break above the range high that closes back inside, followed by a close below the range floor on volume.",
        ],
        "assessment_rule": ("brain/wyckoff.py detects it; on 40 coins a post-climax range preceded weaker-than-average returns on daily "
                            "and 4h data in both halves of history, so it scores 0 to -2 in the BTC/ETH spot signal."),
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
    "btc_levels_sep_2026": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2101284410406703601",
        "date": "2026-09-19",
        "valid_days": 14,
        "families": [],
        "claim": ("Levels he gave in replies on Sept 19: if BTC holds above about $77.5k a rally is possible, because after a range "
                  "breakout, when BTC keeps a tight sideways range the other asset classes tend to catch up. A break above about $83k "
                  "would point toward $90k (TAO and other quality alts would follow), while a break below about $77k means being careful. "
                  "He also said \"blackout dates\" (discussed in his live stream, dates not stated) are coming the following week and that "
                  "if the market survives them it is going higher."),
        "implication": "Key levels he is watching: $77k-77.5k support, $83k breakout, $90k target.",
        "how_to_use": ("Compare with the live BTC price in the Big Coins watchlist. These are his levels and dates, not verified; the "
                       "'blackout dates' are unknown to this app, so ask him or check his live before relying on them."),
    },
    "policy_drives_money": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2101276481091448996",
        "date": "2026-09-19",
        "families": ["FOMC", "CPI", "PPI", "PCE"],
        "claim": ("His one-word answer to what drives markets is policy: easing or tightening. Monetary policy is the Fed's and fiscal "
                  "policy is the government's, and more money flowing into an asset (for example legal, easy access to crypto) means more "
                  "participants and more money."),
        "implication": "Liquidity direction (easing versus tightening) is the master variable in his framework.",
        "how_to_use": "Read Fed and inflation events through 'is policy easing or tightening' before reading the chart.",
    },
    "bitcoin_cycle_article_feb_2026": {
        "author": "Crypto Dada (@YTCryptoDada)",
        "source": "https://x.com/YTCryptoDada/status/2019685345399623985",
        "date": "2026-02-06",
        "families": [],
        "claim": ("Article 'Bitcoin cycle: this time is NOT different'. He says he sold over 80% of his spot bags in Aug 2025 near $124k "
                  "(not the Altcoins, which he says lost most of their value), and had warned of market complacency since Nov 2025. His "
                  "framework: 'Anticipate, don't chase'. Weekly drops of 35% or more are normal for Bitcoin, and the emotional path after a "
                  "top is fear, then panic, anger and depression, with capitulation still to come when he wrote it. He suggested only "
                  "10-20% invested in the $58-62k zone to control FOMO, no DCA without understanding when and how, no shitcoins in this "
                  "cycle ('assets the white collars decided to pump' did well), and said you don't need the exact bottom (last cycle he "
                  "called for buying 20-30% at $16,670). He named quantum computing as a long-term threat to the code."),
        "implication": "Patience: scale in small near fear zones, wait for capitulation, favour large institution-backed assets over small alts.",
        "how_to_use": ("A cycle lens written in Feb 2026 when BTC was near $60k; BTC has since moved, so treat the price zones as dated "
                       "and use the framework (small first tranche, wait for capitulation, avoid chasing) rather than the numbers."),
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
