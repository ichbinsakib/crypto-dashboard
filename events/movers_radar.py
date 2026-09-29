"""Admin-only 'Big Movers' radar: which coins moved the most, recently -- raw price action, not a signal.

Binance's own 24hr ticker (all USDT pairs, one call, no market-cap curation needed) is the primary
source: it costs no extra API calls beyond what dashboard.py already fetches for other features, covers
far more coins than the CoinGecko top-~80-by-market-cap pool, and isn't subject to CoinGecko's free-tier
rate limits. The CoinGecko screener pool is kept as a fallback for the rare run where Binance itself is
unreachable. This never predicts anything and never recommends a trade: it only lists what already
happened, sorted by size. Chasing a coin that already made its move is exactly what this app's own
trend-following rules are designed to avoid (a fresh breakout above a NEW high, not a jump into an
already-extended one) -- see the disclaimer below. Pure functions: no network.
"""

TOP_N = 10
MIN_QUOTE_VOLUME_USDT = 10_000_000   # 24h USDT volume floor: filters out illiquid/thinly-traded noise
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
NON_CRYPTO_BASES = {                 # stablecoins and fiat currencies traded against USDT on Binance
    "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "PYUSD", "USDE", "GUSD", "USTC", "UST", "EUR", "EURI",
    "GBP", "TRY", "BRL", "RUB", "UAH", "ZAR", "AUD", "MXN", "ARS", "COP", "NGN", "IDRT", "BIDR",
}
DISCLAIMER = ("Raw price moves only — not a trading signal or a recommendation. A coin already up a lot has, by "
              "definition, already made its move; buying into it here is chasing, which this app's own rules are "
              "built to avoid. Use this list to notice a coin worth watching for its next setup, not to buy the pump directly.")


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _from_rows(rows, top_n):
    gainers = sorted(rows, key=lambda r: -r["pct_24h"])[:top_n]
    losers = [r for r in sorted(rows, key=lambda r: r["pct_24h"]) if r["pct_24h"] < 0][:top_n]
    return {"gainers": gainers, "losers": losers, "disclaimer": DISCLAIMER}


def _coingecko_row(d):
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
    rows = [r for r in (_coingecko_row(d) for d in (pool or [])) if r is not None]
    return _from_rows(rows, top_n)


def _binance_base(t):
    """The bare coin symbol (e.g. "QNT") for a Binance ticker row, or None if it's not a plain USDT
    spot pair on a real crypto asset (excludes stablecoins/fiat and leveraged tokens)."""
    sym = str(t.get("symbol") or "")
    if not sym.endswith("USDT"):
        return None
    base = sym[:-4]
    if not base or base in NON_CRYPTO_BASES or base.endswith(LEVERAGED_SUFFIXES):
        return None
    return base


def _binance_row(t, min_quote_volume):
    base = _binance_base(t)
    if base is None:
        return None
    pct24, price, qv = _f(t.get("priceChangePercent")), _f(t.get("lastPrice")), _f(t.get("quoteVolume"))
    if pct24 is None or price is None or (qv or 0) < min_quote_volume:
        return None
    return {"symbol": base, "name": base, "price": price, "pct_1h": None, "pct_24h": round(pct24, 1), "pct_7d": None}


def liquid_pool(tickers, limit):
    """A fresh candidate pool of the `limit` highest-24h-volume real USDT pairs, shaped like the
    CoinGecko screener pool's minimal id/symbol/name cache (id is always None -- nothing here needs
    a CoinGecko id). Used as a fallback when CoinGecko's own pool fetch fails, so the coin rotation
    stays fresh instead of freezing on a possibly-days-old cached list. Never raises: an empty or
    missing ticker list just means an empty pool."""
    rows = []
    for t in tickers or []:
        base = _binance_base(t)
        qv = _f(t.get("quoteVolume"))
        if base is not None and qv is not None:
            rows.append((qv, base))
    rows.sort(key=lambda r: -r[0])
    return [{"id": None, "symbol": base.lower(), "name": base} for _, base in rows[:limit]]


def top_movers_binance(tickers, top_n=TOP_N, min_quote_volume=MIN_QUOTE_VOLUME_USDT):
    """(gainers, losers) among `tickers` (Binance's GET /api/v3/ticker/24hr, all pairs), sorted by 24h
    % size. Restricted to USDT pairs, with stablecoins/fiat and leveraged tokens (UP/DOWN/BULL/BEAR)
    excluded and a minimum 24h quote volume so a thinly-traded coin can't dominate the list on noise.
    Never raises: a missing or empty ticker list just means an empty result."""
    rows = [r for r in (_binance_row(t, min_quote_volume) for t in (tickers or [])) if r is not None]
    return _from_rows(rows, top_n)


def build_report(binance_tickers=None, coingecko_pool=None, top_n=TOP_N):
    """Binance first; CoinGecko's screener pool only as a fallback for the rare run where Binance's
    own ticker endpoint is unreachable. Either source returning zero rows (not just a failed fetch)
    falls through too, so a good-but-empty Binance response doesn't hide a working CoinGecko pool."""
    if binance_tickers:
        report = top_movers_binance(binance_tickers, top_n)
        if report["gainers"] or report["losers"]:
            return report
    if coingecko_pool:
        report = top_movers(coingecko_pool, top_n)
        if report["gainers"] or report["losers"]:
            return report
    return {"gainers": [], "losers": [], "disclaimer": DISCLAIMER}
