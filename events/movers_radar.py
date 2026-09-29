"""Admin-only 'Big Movers' radar: which coins moved the most, recently -- raw price action, not a signal.

Built from the same CoinGecko screener pool the Trend Breakout engine already scans (top ~80 coins by
market cap), so this costs no extra API calls. It never predicts anything and never recommends a trade:
it only lists what already happened, sorted by size. Chasing a coin that already made its move is
exactly what this app's own trend-following rules are designed to avoid (a fresh breakout above a NEW
high, not a jump into an already-extended one) -- see the disclaimer below. Pure function: no network.
"""

TOP_N = 10
DISCLAIMER = ("Raw price moves only — not a trading signal or a recommendation. A coin already up a lot has, by "
              "definition, already made its move; buying into it here is chasing, which this app's own rules are "
              "built to avoid. Use this list to notice a coin worth watching for its next setup, not to buy the pump directly.")


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _row(d):
    pct24 = _f(d.get("price_change_percentage_24h_in_currency"))
    if pct24 is None:
        return None
    return {"symbol": str(d.get("symbol") or "").upper(), "name": d.get("name") or d.get("symbol"),
            "price": _f(d.get("current_price")), "pct_1h": _f(d.get("price_change_percentage_1h_in_currency")),
            "pct_24h": round(pct24, 1), "pct_7d": _f(d.get("price_change_percentage_7d_in_currency"))}


def top_movers(pool, top_n=TOP_N):
    """(gainers, losers) among `pool` (a CoinGecko /coins/markets list), sorted by 24h % size. A coin
    with no 24h % (a dead feed or brand-new listing) is skipped rather than guessed at. Losers only
    includes coins actually down; an all-green pool yields an empty losers list, not padding. Never
    raises: a missing or empty pool just means an empty result."""
    rows = [r for r in (_row(d) for d in (pool or [])) if r is not None]
    gainers = sorted(rows, key=lambda r: -r["pct_24h"])[:top_n]
    losers = [r for r in sorted(rows, key=lambda r: r["pct_24h"]) if r["pct_24h"] < 0][:top_n]
    return {"gainers": gainers, "losers": losers, "disclaimer": DISCLAIMER}
