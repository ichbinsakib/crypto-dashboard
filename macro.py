"""Live cross-market data for the Big Coins tab (the watchlist a discretionary crypto trader watches):
crypto totals/dominance (CoinGecko), majors (Binance mirror), macro/equities/rates (Yahoo Finance chart API,
unofficial but keyless), unemployment (latest BLS release stored by the Market Events job).

Every fetch is independent: a source that fails is reported as unavailable and never guessed. Pure functions
(`crypto_totals`, `macro_regime`) take the fetched data so they can be tested without the network."""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}

# label -> (Yahoo symbol, group, unit)   change is % for prices, absolute points for yields/spreads
YAHOO = {
    "DXY": ("DX-Y.NYB", "Macro", "index"), "US10Y": ("^TNX", "Rates", "pct"), "US02Y": ("2YY=F", "Rates", "pct"),
    "US03MY": ("^IRX", "Rates", "pct"), "USOIL": ("CL=F", "Macro", "usd"), "XAUUSD": ("GC=F", "Macro", "usd"),
    "XAGUSD": ("SI=F", "Macro", "usd"), "ES1!": ("ES=F", "Equities", "index"), "NDX": ("^NDX", "Equities", "index"),
    "NVDA": ("NVDA", "Equities", "usd"),
}
# How much the macro backdrop counts in the BTC/ETH spot score: 1 = as shown (-2..+2), 0 = display only.
# A 3-year test of dollar/yield/Nasdaq moves against next-day and 3-day BTC returns found no reliable
# predictive power (results flipped between the train and test halves), so this is a judgement call, not proof.
import os as _os
MACRO_WEIGHT = float(_os.environ.get("MACRO_SPOT_WEIGHT", "1"))
BINANCE = {"BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT", "XRPUSDT": "XRPUSDT", "SOLUSDT": "SOLUSDT", "SOLBTC": "SOLBTC"}


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read())


def fetch_yahoo(symbol):
    """-> {price, prev, change_abs, change_pct} using the last two daily closes plus the live price."""
    d = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('^', '%5E')}?interval=1d&range=10d")
    r = d["chart"]["result"][0]
    price = r["meta"]["regularMarketPrice"]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    # closes[-1] is today's (in-progress) bar when the market is open; the previous session is the one before it.
    prev = closes[-2] if len(closes) >= 2 and abs(closes[-1] - price) / price < 0.02 else closes[-1]
    return {"price": price, "prev": prev, "change_abs": price - prev, "change_pct": (price / prev - 1) * 100 if prev else None,
            "closes": closes}


def fetch_binance(symbol):
    d = _get(f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}")
    return {"price": float(d["lastPrice"]), "change_abs": float(d["priceChange"]), "change_pct": float(d["priceChangePercent"]),
            "volume_usd": float(d.get("quoteVolume", 0))}


def fetch_coingecko_globals():
    g = _get("https://api.coingecko.com/api/v3/global")["data"]
    markets = _get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1")
    stable = _get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=stablecoins&order=market_cap_desc&per_page=50&page=1")
    return {"global": g, "markets": markets, "stables": stable}


def fetch_all(unrate=None):
    """Fetch everything; returns (data, errors). A failing source lands in errors and its rows are simply absent."""
    data, errors = {"yahoo": {}, "binance": {}, "crypto": None, "unrate": unrate}, {}
    for label, (sym, _, _) in YAHOO.items():
        try:
            data["yahoo"][label] = fetch_yahoo(sym)
        except Exception as e:  # noqa: BLE001
            errors[label] = type(e).__name__
    for label, sym in BINANCE.items():
        try:
            data["binance"][label] = fetch_binance(sym)
        except Exception as e:  # noqa: BLE001
            errors[label] = type(e).__name__
    try:
        data["crypto"] = fetch_coingecko_globals()
    except Exception as e:  # noqa: BLE001
        errors["coingecko"] = type(e).__name__
    return data, errors


# ---------------- derived crypto totals (TradingView-style) ----------------

def _cap(m):
    return float(m.get("market_cap") or 0)


def _prev_cap(m):
    return _cap(m) - float(m.get("market_cap_change_24h") or 0)


def crypto_totals(cg):
    """TOTAL, TOTAL3, OTHERS (excl. top 10), dominances and stablecoin share, each with its 24h change.
    Prior values are rebuilt from each coin's 24h market-cap change, so all changes are consistent."""
    g, markets = cg["global"], cg["markets"]
    total = float(g["total_market_cap"]["usd"])
    # Level from CoinGecko's global figure; the 24h change is rebuilt from the top-250 coins' own market-cap
    # changes (the long tail, ~3% of the total, is assumed unchanged) so every total/dominance is consistent.
    top_now = sum(_cap(m) for m in markets)
    total = max(total, top_now)                       # CoinGecko's global figure can lag the per-coin caps
    total_prev = (total - top_now) + sum(_prev_cap(m) for m in markets)
    by_sym = {m["symbol"].lower(): m for m in markets}
    btc, eth, usdt = by_sym.get("btc"), by_sym.get("eth"), by_sym.get("usdt")
    if not (btc and eth and usdt and total_prev):
        return {}
    stable = sum(_cap(m) for m in cg.get("stables", []))
    stable_prev = sum(_prev_cap(m) for m in cg.get("stables", []))
    top10 = sorted(markets, key=_cap, reverse=True)[:10]
    t3, t3p = total - _cap(btc) - _cap(eth), total_prev - _prev_cap(btc) - _prev_cap(eth)
    oth, othp = total - sum(_cap(m) for m in top10), total_prev - sum(_prev_cap(m) for m in top10)
    t3u, t3up = t3 - _cap(usdt), t3p - _prev_cap(usdt)

    def cap_row(now, prev):
        return {"price": now, "change_abs": now - prev, "change_pct": (now / prev - 1) * 100 if prev else None}

    def share(now_num, now_den, prev_num, prev_den):
        n, p = now_num / now_den * 100, prev_num / prev_den * 100
        return {"price": n, "change_abs": n - p, "change_pct": (n / p - 1) * 100 if p else None}

    return {
        "TOTAL": cap_row(total, total_prev), "TOTAL3": cap_row(t3, t3p), "OTHERS": cap_row(oth, othp),
        "TOTAL3-USDT": cap_row(t3u, t3up),
        "BTC.D": share(_cap(btc), total, _prev_cap(btc), total_prev),
        "USDT.D": share(_cap(usdt), total, _prev_cap(usdt), total_prev),
        "STABLE.C.D": share(stable, total, stable_prev, total_prev) if stable else None,
        "TOTAL/BTC": {"price": total / _cap(btc), "change_abs": total / _cap(btc) - total_prev / _prev_cap(btc),
                      "change_pct": ((total / _cap(btc)) / (total_prev / _prev_cap(btc)) - 1) * 100},
    }


def build_rows(data):
    """Watchlist rows in the trader's order: [{symbol, group, price, change_abs, change_pct, unit}] (missing -> skipped)."""
    ct = crypto_totals(data["crypto"]) if data.get("crypto") else {}
    y, b = data["yahoo"], data["binance"]
    rows = []

    def add(sym, group, d, unit="", note=None):
        if d and d.get("price") is not None:
            rows.append({"symbol": sym, "group": group, "price": d["price"], "change_abs": d.get("change_abs"),
                         "change_pct": d.get("change_pct"), "unit": unit, "note": note})
    add("TOTAL", "Crypto market", ct.get("TOTAL"), "usd_cap")
    add("BTCUSDT", "Crypto market", b.get("BTCUSDT"), "usd")
    add("ETHUSDT", "Crypto market", b.get("ETHUSDT"), "usd")
    add("DXY", "Macro", y.get("DXY"), "index")
    add("BTC.D", "Crypto market", ct.get("BTC.D"), "pct")
    add("USDT.D", "Crypto market", ct.get("USDT.D"), "pct")
    add("US10Y", "Rates", y.get("US10Y"), "pct")
    add("USOIL", "Macro", y.get("USOIL"), "usd")
    add("XAUUSD", "Macro", y.get("XAUUSD"), "usd", "gold futures")
    add("XAGUSD", "Macro", y.get("XAGUSD"), "usd", "silver futures")
    add("ES1!", "Equities", y.get("ES1!"), "index")
    add("NDX", "Equities", y.get("NDX"), "index")
    add("NVDA", "Equities", y.get("NVDA"), "usd")
    add("XRPUSDT", "Crypto market", b.get("XRPUSDT"), "usd")
    add("SOLUSDT", "Crypto market", b.get("SOLUSDT"), "usd")
    add("SOLBTC", "Crypto market", b.get("SOLBTC"), "btc")
    add("TOTAL3", "Crypto market", ct.get("TOTAL3"), "usd_cap")
    add("OTHERS", "Crypto market", ct.get("OTHERS"), "usd_cap")
    add("STABLE.C.D", "Crypto market", ct.get("STABLE.C.D"), "pct")
    add("TOTAL3-USDT", "Crypto market", ct.get("TOTAL3-USDT"), "usd_cap")
    add("TOTAL/BTC", "Crypto market", ct.get("TOTAL/BTC"), "ratio")
    if data.get("unrate") is not None:
        rows.append({"symbol": "UNRATE", "group": "Rates", "price": data["unrate"], "change_abs": None, "change_pct": None,
                     "unit": "pct", "note": "latest BLS release"})
    if "US10Y" in y and "US02Y" in y:
        a, p = y["US10Y"]["price"] - y["US02Y"]["price"], y["US10Y"]["prev"] - y["US02Y"]["prev"]
        rows.append({"symbol": "US10Y-US02Y", "group": "Rates", "price": a, "change_abs": a - p, "change_pct": None, "unit": "pct",
                     "note": "inverted" if a < 0 else "positive slope"})
    if "US10Y" in y and "US03MY" in y:
        a, p = y["US10Y"]["price"] - y["US03MY"]["price"], y["US10Y"]["prev"] - y["US03MY"]["prev"]
        rows.append({"symbol": "US10Y-US03MY", "group": "Rates", "price": a, "change_abs": a - p, "change_pct": None, "unit": "pct",
                     "note": "inverted" if a < 0 else "positive slope"})
    order = ["Crypto market", "Macro", "Equities", "Rates"]
    rows.sort(key=lambda r: order.index(r["group"]) if r["group"] in order else len(order))   # stable: keeps the watchlist order inside a group
    return rows


# ---------------- macro regime (feeds the Big Coins spot signal) ----------------

def macro_regime(rows):
    """Transparent risk-on / risk-off reading from the fetched rows.
    Each factor is -1, 0 or +1 with a plain reason; returns {score, label, factors, missing}.
    Rules of thumb (not validated on history): a stronger dollar, rising yields, falling equities and rising
    stablecoin dominance are risk-off for crypto; the reverse is risk-on."""
    by = {r["symbol"]: r for r in rows}
    factors, missing = [], []

    def factor(name, sym, fn):
        r = by.get(sym)
        if not r or r.get("change_pct") is None and r.get("change_abs") is None:
            missing.append(sym)
            return
        pts, reading = fn(r)
        factors.append({"factor": name, "reading": reading, "points": pts, "symbol": sym})

    def dollar(r):
        c = r["change_pct"]
        return (-1, f"Dollar up {c:+.2f}% - tighter liquidity, usually a headwind") if c >= 0.3 else \
               (1, f"Dollar down {c:+.2f}% - easier liquidity, usually a tailwind") if c <= -0.3 else (0, f"Dollar flat ({c:+.2f}%)")

    def yields(r):
        d = r["change_abs"] * 100                                   # basis points
        return (-1, f"10Y yield up {d:+.0f} bp - rising rates pressure risk assets") if d >= 4 else \
               (1, f"10Y yield down {d:+.0f} bp - falling rates support risk assets") if d <= -4 else (0, f"10Y yield steady ({d:+.0f} bp)")

    def stocks(r):
        c = r["change_pct"]
        return (1, f"Nasdaq up {c:+.2f}% - risk appetite") if c >= 0.5 else \
               (-1, f"Nasdaq down {c:+.2f}% - risk aversion") if c <= -0.5 else (0, f"Nasdaq flat ({c:+.2f}%)")

    def stables(r):
        c = r["change_pct"]
        return (-1, f"Stablecoin dominance up {c:+.2f}% - money moving to the sidelines") if c >= 0.5 else \
               (1, f"Stablecoin dominance down {c:+.2f}% - money moving into crypto") if c <= -0.5 else (0, f"Stablecoin dominance steady ({c:+.2f}%)")

    def total(r):
        c = r["change_pct"]
        return (1, f"Total crypto market cap {c:+.2f}% in 24h - inflows") if c >= 2 else \
               (-1, f"Total crypto market cap {c:+.2f}% in 24h - outflows") if c <= -2 else (0, f"Total crypto market cap {c:+.2f}% in 24h")

    factor("US dollar (DXY)", "DXY", dollar)
    factor("US 10Y yield", "US10Y", yields)
    factor("US stocks (NDX)", "NDX", stocks)
    factor("Stablecoin dominance", "STABLE.C.D", stables)
    factor("Total crypto market", "TOTAL", total)
    score = sum(f["points"] for f in factors)
    n = len(factors)
    if n < 3:
        label = "NOT ENOUGH DATA"
    elif score >= 2:
        label = "RISK-ON"
    elif score <= -2:
        label = "RISK-OFF"
    else:
        label = "MIXED"
    curve = by.get("US10Y-US02Y")
    return {"score": score, "label": label, "factors": factors, "missing": missing, "n": n,
            "curve": curve["price"] if curve else None}


# ---------------- HTML for the Big Coins tab ----------------

from html import escape as _esc  # noqa: E402


def _fmt_value(v, unit):
    if unit == "usd_cap":
        return f"${v / 1e12:.2f}T" if v >= 1e12 else f"${v / 1e9:,.1f}B"
    if unit == "pct":
        return f"{v:.2f}%"
    if unit == "btc":
        return f"{v:.8f}".rstrip("0")
    if unit == "ratio":
        return f"{v:.2f}"
    if unit == "usd":
        return f"{v:,.2f}" if v >= 1 else f"{v:.4f}"
    return f"{v:,.2f}"


def _fmt_change(r):
    c, a, unit = r.get("change_pct"), r.get("change_abs"), r["unit"]
    if unit == "pct" and r["symbol"] not in ("BTC.D", "USDT.D", "STABLE.C.D"):    # yields / spreads move in points
        return (a, f"{a * 100:+.0f} bp") if a is not None else (None, "-")
    if c is None:
        return None, "-"
    return c, f"{c:+.2f}%"


def watchlist_html(macro):
    """Watchlist card + regime summary. `macro` = {rows, regime, errors, fetched_at}."""
    if not macro or not macro.get("rows"):
        return ('<div class="card wl-card"><div class="card-title">CROSS-MARKET WATCHLIST</div>'
                '<div class="sub">Cross-market data is unavailable right now (all sources failed); nothing is estimated.</div></div>')
    rg = macro["regime"]
    tone = {"RISK-ON": "pos", "RISK-OFF": "neg"}.get(rg["label"], "watch")
    factors = "".join(
        f'<tr><td>{_esc(f["factor"])}</td><td class="watch">{_esc(f["reading"])}</td>'
        f'<td><span class="badge {"bullish" if f["points"] > 0 else "bearish" if f["points"] < 0 else "neutral"}">'
        f'{f["points"]:+d}</span></td></tr>' for f in rg["factors"])
    body, current = [], None
    for r in macro["rows"]:
        if r["group"] != current:
            current = r["group"]
            body.append(f'<tr class="wl-group"><td colspan="3">{_esc(current)}</td></tr>')
        chg, txt = _fmt_change(r)
        cls = "watch" if chg is None else ("pos" if chg > 0 else "neg" if chg < 0 else "watch")
        live = f' data-live="{_esc(r["symbol"])}"' if r["symbol"] in BINANCE else ""
        note = f'<span class="wl-note">{_esc(r["note"])}</span>' if r.get("note") else ""
        body.append(f'<tr{live}><td>{_esc(r["symbol"])}{note}</td><td class="wl-price">{_fmt_value(r["price"], r["unit"])}</td>'
                    f'<td class="wl-chg {cls}">{txt}</td></tr>')
    curve = ""
    if rg.get("curve") is not None:
        curve = (f'<div class="sub">Yield curve (10Y-2Y): {rg["curve"]:+.2f} pts - '
                 f'{"inverted, a classic slowdown warning" if rg["curve"] < 0 else "positive slope"}.</div>')
    missing = ""
    if macro.get("errors"):
        missing = f'<div class="sub">Unavailable right now: {_esc(", ".join(sorted(macro["errors"])))}.</div>'
    tip = ("Crypto totals and dominance come from CoinGecko (top-250 coins, so TOTAL3 and OTHERS are close to but not identical "
           "to TradingView), majors from Binance (those five rows also refresh in your browser every 20 seconds), stocks, oil, gold, "
           "dollar and yields from Yahoo Finance (futures or delayed quotes). Changes are versus the previous close (24h for crypto). "
           "Unemployment is the latest BLS release.")
    return f"""
<div class="card wl-card">
  <div class="card-title">CROSS-MARKET WATCHLIST<span class="info-tip" tabindex="0" data-tip="{_esc(tip)}">&#9432;</span></div>
  <div class="sub">Server snapshot {_esc(macro.get("fetched_at", ""))} UTC &middot; <span id="wl-live-stamp">Binance rows update live</span></div>
  <table class="signal-table wl-table"><thead><tr><th>Symbol</th><th>Last</th><th>Change</th></tr></thead><tbody>
  {"".join(body)}
  </tbody></table>
  {curve}{missing}
  <div class="card-title" style="margin-top:14px;">MACRO BACKDROP: <span class="{tone}">{_esc(rg["label"])}</span> (score {rg["score"]:+d} from {rg["n"]} factors)</div>
  <div class="sub">This feeds one row of the BTC/ETH spot signals (worth -2 to +2 points). Simple rules of thumb - a rising dollar and yields, falling stocks or rising stablecoin share are risk-off for crypto - not a validated edge.</div>
  <table class="signal-table"><thead><tr><th>Factor</th><th>Current reading</th><th>Points</th></tr></thead><tbody>{factors}</tbody></table>
</div>
"""


def spot_factor(regime):
    """(points, reading) for the spot-signal table from a macro_regime() result."""
    if not regime or regime.get("label") == "NOT ENOUGH DATA":
        return 0, "Cross-market data unavailable - no points given"
    s = regime["score"]
    pts = round((2 if s >= 3 else 1 if s == 2 else -2 if s <= -3 else -1 if s == -2 else 0) * MACRO_WEIGHT)
    return pts, f"{regime['label'].title()} (score {s:+d} of {regime['n']}): " + "; ".join(f["reading"] for f in regime["factors"][:3])
