"""Futures data (funding, mark vs index, open interest) with fallbacks.

Binance's futures API answers HTTP 451 from GitHub Actions' IP ranges, so on the scheduled job the dashboard used to
fall back to 'last known values' that could be days old. These helpers add public exchanges that do answer there
(Aster, OKX) so the numbers stay live; each result says which exchange it came from.
Every function raises on failure (the caller tries the next source) and never returns invented numbers."""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}
OKX = "https://www.okx.com/api/v5"
ASTER = "https://fapi.asterdex.com/fapi/v3"


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def aster_premium(symbol):
    """Same shape as Binance premiumIndex: markPrice, indexPrice, lastFundingRate."""
    d = _get(f"{ASTER}/premiumIndex?symbol={symbol}")
    if not d.get("markPrice") or not d.get("indexPrice"):
        raise ValueError("Aster returned no price")
    return {"markPrice": d["markPrice"], "indexPrice": d["indexPrice"], "lastFundingRate": d.get("lastFundingRate", "0")}


def okx_premium(key):
    inst = f"{key}-USDT-SWAP"
    mark = _get(f"{OKX}/public/mark-price?instType=SWAP&instId={inst}")["data"][0]["markPx"]
    index = _get(f"{OKX}/market/index-tickers?instId={key}-USDT")["data"][0]["idxPx"]
    funding = _get(f"{OKX}/public/funding-rate?instId={inst}")["data"][0]["fundingRate"]
    return {"markPrice": mark, "indexPrice": index, "lastFundingRate": funding}


def okx_oi(key, pct_24h=None):
    """-> {oi_now (in coins), oi_change_pct (24h)}. OKX publishes hourly open interest in USD; the coin-terms change is
    the USD change with the price move over the same 24h removed (approximate, and labelled as such by the caller)."""
    now = _get(f"{OKX}/public/open-interest?instType=SWAP&instId={key}-USDT-SWAP")["data"][0]
    hist = _get(f"{OKX}/rubik/stat/contracts/open-interest-volume?ccy={key}&period=1H")["data"]
    series = sorted((int(r[0]), float(r[1])) for r in hist)
    if len(series) < 20:
        raise ValueError("not enough OKX open-interest history")
    first, last = series[-24][1] if len(series) >= 24 else series[0][1], series[-1][1]
    usd_change = (last / first - 1) if first else None
    if usd_change is None:
        raise ValueError("bad OKX history")
    price_change = (pct_24h or 0) / 100
    coin_change = ((1 + usd_change) / (1 + price_change) - 1) * 100 if price_change > -0.99 else usd_change * 100
    return {"oi_now": float(now["oiCcy"]), "oi_change_pct": coin_change}
