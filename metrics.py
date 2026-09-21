"""Per-signal market-structure readout shown under each row of the Signal Scanner.

Every number is computed from public data (Binance spot candles and order book, Aster perpetual candles and funding, OKX
open interest). Anything a coin has no data for shows as unavailable - never estimated. Definitions (also in the UI tooltip):

  Price change   last candle's close vs the previous close
  OI change      24h change in futures open interest, in coin terms (price move removed); OKX, when the coin has a swap there
  Spot VR        volume ratio: average volume of the last 3 candles / average over the scan window (1.0x = normal)
  Futures VR     the same ratio on the Aster perpetual
  Funding        latest Aster perpetual funding rate
  LDR            liquidity depth ratio: bid-side value / ask-side value within 1% of the price in the Binance order book
                 (above 1 = more resting buy liquidity, below 1 = more resting sell liquidity)
  Absorption     Spot VR / (1 + |price move of the last 3 candles| / ATR%): heavy volume that failed to move price scores high
  Spot / Futures delta   taker-buy value minus taker-sell value over the last 3 candles (USD): who is hitting the book
  Typical candle move   the average size of a candle over the scan window, as % of price and in price"""
import json
import urllib.request

RECENT = 3
UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}


def _get(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def _f(x):
    return float(x)


def volume_ratio(klines, window):
    v = [_f(k[5]) for k in klines]
    if len(v) < window + 1:
        return None
    avg = sum(v[-window:]) / window
    return (sum(v[-RECENT:]) / RECENT / avg) if avg > 0 else None


def taker_delta_usd(klines):
    """Taker-buy quote volume minus taker-sell quote volume over the last RECENT candles (needs Binance-style rows)."""
    rows = klines[-RECENT:]
    try:
        total = sum(_f(k[7]) for k in rows)
        buy = sum(_f(k[10]) for k in rows)
    except (IndexError, ValueError):
        return None
    return 2 * buy - total


def atr_abs(klines, window):
    rows = klines[-window:]
    if len(rows) < window:
        return None
    return sum(_f(k[2]) - _f(k[3]) for k in rows) / window


def depth_ratio(depth, price, band=0.01):
    """Bid value / ask value within +-band of price from an order-book snapshot {'bids': [[p,q]], 'asks': [[p,q]]}."""
    bids = sum(_f(p) * _f(q) for p, q in depth.get("bids", []) if _f(p) >= price * (1 - band))
    asks = sum(_f(p) * _f(q) for p, q in depth.get("asks", []) if _f(p) <= price * (1 + band))
    return bids / asks if asks > 0 else None


def absorption(spot_vr, closes, atr_pct):
    if spot_vr is None or len(closes) <= RECENT or not atr_pct:
        return None
    move_pct = abs(closes[-1] / closes[-1 - RECENT] - 1) * 100
    return spot_vr / (1 + move_pct / atr_pct)


def regime_word(macro_label):
    return {"RISK-ON": "BULLISH", "RISK-OFF": "BEARISH", "MIXED": "NEUTRAL"}.get((macro_label or "").upper(), "N/A")


def score_100(points):
    """Dip-scanner points (-5..+5) on a 0-100 scale."""
    return max(0, min(100, round((points + 5) * 10)))


def compute(symbol, interval, lookback, price, spot_klines, fut_klines=None, depth=None, oi_change_pct=None, funding_pct=None, macro_label=None):
    """Assemble the readout from already-fetched data; every missing input stays None."""
    closes = [_f(k[4]) for k in spot_klines]
    atr = atr_abs(spot_klines, lookback)
    atr_pct = (atr / price * 100) if atr and price else None
    svr = volume_ratio(spot_klines, lookback)
    chg = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 and closes[-2] else None
    return {
        "symbol": symbol, "price": price, "regime": regime_word(macro_label), "price_change_pct": chg,
        "oi_change_pct": oi_change_pct, "spot_vr": svr,
        "fut_vr": volume_ratio(fut_klines, lookback) if fut_klines else None, "funding_pct": funding_pct,
        "ldr": depth_ratio(depth, price) if depth else None, "absorption": absorption(svr, closes, atr_pct),
        "spot_delta": taker_delta_usd(spot_klines), "fut_delta": taker_delta_usd(fut_klines) if fut_klines else None,
        "atr": atr, "atr_pct": atr_pct}


def gather(symbol, interval, lookback, price, spot_klines, macro_label=None, aster_mod=None, deriv_mod=None, pct_24h=None):
    """Fetch the extras (Aster candles, order book, OKX open interest) - each optional - and compute. Never raises."""
    fut = depth = oi = None
    try:
        if aster_mod is not None:
            fut = aster_mod.klines(symbol, interval)
    except Exception:  # noqa: BLE001
        fut = None
    try:
        depth = _get(f"https://data-api.binance.vision/api/v3/depth?symbol={symbol}USDT&limit=100")
    except Exception:  # noqa: BLE001
        depth = None
    try:
        if deriv_mod is not None:
            oi = deriv_mod.okx_oi(symbol, pct_24h)["oi_change_pct"]
    except Exception:  # noqa: BLE001
        oi = None
    funding = None
    try:
        a = aster_mod.SNAPSHOT.get(symbol.upper()) if aster_mod is not None else None
        funding = a["funding_pct"] if a else None
    except Exception:  # noqa: BLE001
        funding = None
    return compute(symbol, interval, lookback, price, spot_klines, fut, depth, oi, funding, macro_label)


# ---------------- display ----------------

def _num(v, fmt, dash="n/a"):
    return dash if v is None else fmt.format(v)


def _usd_compact(v):
    if v is None:
        return "n/a"
    s = "-" if v < 0 else "+"
    a = abs(v)
    return f"{s}${a / 1e6:.2f}M" if a >= 1e6 else f"{s}${a / 1e3:.1f}K" if a >= 1e3 else f"{s}${a:.0f}"


def display_rows(m, signal_label, score_text, tf_label, time_text, price_text):
    """[(label, value)] in the order of the reference readout, plus time and timeframe."""
    return [
        ("Symbol", m["symbol"] + "USDT"), ("Timeframe", tf_label), ("Time", time_text), ("Price", price_text),
        ("Signal", signal_label), ("Score", score_text), ("Market Regime", m["regime"]),
        ("Price Change", _num(m["price_change_pct"], "{:+.2f}%")), ("OI Change", _num(m["oi_change_pct"], "{:+.2f}%")),
        ("Futures VR", _num(m["fut_vr"], "{:.2f}x")), ("Spot VR", _num(m["spot_vr"], "{:.2f}x")),
        ("Funding", _num(m["funding_pct"], "{:+.4f}%")), ("LDR", _num(m["ldr"], "{:.2f}")),
        ("Absorption", _num(m["absorption"], "{:.2f}")), ("Spot Delta", _usd_compact(m["spot_delta"])),
        ("Futures Delta", _usd_compact(m["fut_delta"])),
        ("Typical candle move", "n/a" if m["atr"] is None else (f"{m['atr_pct']:.2f}%" if m["atr_pct"] is not None else "n/a") + f" ({m['atr']:.6g})")]
