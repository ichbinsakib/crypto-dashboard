"""Aster DEX public market data (asterdex/api-docs, Futures V3, no key needed) as a second venue for the scanner.

One bulk call each for mark/index price + funding (`premiumIndex`) and 24h stats (`ticker/24hr`) per run, so the 5-minute job
stays far below the documented IP limits. Used only as CONTEXT on scanner cards and as a data-quality check:
  * funding rate and mark-vs-index basis on the perpetual (are longs crowded or shorts paying?)
  * price divergence between the scanner's Binance price and Aster's mark price (a big gap means a stale, illiquid or broken feed)
Back-tests on 37 coins (1h) found no reliable effect of funding or taker-buy flow on outcomes, so none of this changes a score."""
import json
import urllib.request

BASE = "https://fapi.asterdex.com/fapi/v3"
UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}
HOT_FUNDING_PCT = 0.05        # per 8h interval; above = crowded longs
COLD_FUNDING_PCT = -0.05      # below = shorts paying a lot
MAX_PRICE_GAP_PCT = 2.0       # beyond this the two venues disagree too much to trust either quietly

SNAPSHOT = {}


def _get(path, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def parse_snapshot(premium, tickers):
    """-> {BASE: {funding_pct, basis_bps, mark, quote_volume, change_pct}} for USDT perpetuals."""
    out = {}
    for p in premium or []:
        sym = p.get("symbol", "")
        if not sym.endswith("USDT"):
            continue
        try:
            mark, index = float(p["markPrice"]), float(p["indexPrice"])
            out[sym[:-4]] = {"funding_pct": float(p.get("lastFundingRate") or 0) * 100, "mark": mark,
                             "basis_bps": (mark - index) / index * 1e4 if index else None}
        except (KeyError, ValueError, TypeError):
            continue
    for t in tickers or []:
        sym = t.get("symbol", "")
        base = sym[:-4] if sym.endswith("USDT") else None
        if base in out:
            try:
                out[base]["quote_volume"] = float(t.get("quoteVolume") or 0)
                out[base]["change_pct"] = float(t.get("priceChangePercent") or 0)
            except ValueError:
                pass
    return out


def refresh():
    """Fetch and store the snapshot; failures leave it empty (the scanner just shows nothing extra)."""
    global SNAPSHOT
    try:
        SNAPSHOT = parse_snapshot(_get("/premiumIndex"), _get("/ticker/24hr"))
    except Exception:  # noqa: BLE001
        SNAPSHOT = {}
    return SNAPSHOT


def lookup(symbol, binance_price=None):
    """Aster context for one scanner coin, or None if it has no Aster perpetual."""
    a = SNAPSHOT.get((symbol or "").upper())
    if not a:
        return None
    out = dict(a)
    gap = None
    if binance_price and a.get("mark"):
        gap = (a["mark"] - binance_price) / binance_price * 100
    out["price_gap_pct"] = gap
    flags = []
    if a["funding_pct"] >= HOT_FUNDING_PCT:
        flags.append("crowded longs")
    elif a["funding_pct"] <= COLD_FUNDING_PCT:
        flags.append("shorts paying heavily")
    if gap is not None and abs(gap) > MAX_PRICE_GAP_PCT:
        flags.append("price mismatch between venues")
    out["flags"] = flags
    return out


def card_html(a):
    """One compact line for a scanner card; empty when the coin has no Aster perpetual."""
    if not a:
        return ""
    from html import escape as esc
    bits = [f"funding {a['funding_pct']:+.4f}%"]
    if a.get("basis_bps") is not None:
        bits.append(f"basis {a['basis_bps']:+.1f} bps")
    if a.get("price_gap_pct") is not None:
        bits.append(f"price gap vs Binance {a['price_gap_pct']:+.2f}%")
    warn = f' <b class="neg">Caution: {esc(", ".join(a["flags"]))}.</b>' if a.get("flags") else ""
    return (f'<div class="sub" style="margin-top:6px;">Aster perpetual: {esc(" \u00B7 ".join(bits))}.{warn}'
            f' <span class="wl-note">context only, does not change the score</span></div>')


def cell_html(a):
    """Compact table cell: funding and basis, with a warning marker when a caution flag is set."""
    if not a:
        return '<span class="watch">n/a</span>'
    from html import escape as esc
    txt = f"{a['funding_pct']:+.3f}%"
    if a.get("basis_bps") is not None:
        txt += f" &middot; {a['basis_bps']:+.0f}bp"
    if a.get("flags"):
        return f'<span class="neg" title="{esc(", ".join(a["flags"]))}">{txt} &#9888;</span>'
    return f'<span title="Aster perpetual funding rate and futures basis">{txt}</span>'


def klines(symbol, interval, limit=100):
    """Perpetual candles in Binance kline layout (Aster's API is Binance-compatible), or raise. None if no such perpetual."""
    if (symbol or "").upper() not in SNAPSHOT:
        return None
    return _get(f"/klines?symbol={symbol.upper()}USDT&interval={interval}&limit={limit}")
