"""PAPER-TRADING engine for the weekly momentum rotation (no real money, no exchange account, nothing is ever bought).

Why paper only: the backtest (backtest/MOMENTUM_FINDINGS.md) shows a decent-looking but over-fitted edge with 55-75% drawdowns, so it
first has to prove itself on live prices. Three simulated portfolios run side by side so the comparison is honest:
  momentum    top-5 of the 20 most liquid coins by 14-day return/volatility, equal weight, rebalanced every Monday
  btc_regime  100% BTC while BTC is above its 100-day average, otherwise cash          (the simple benchmark)
  btc_hold    100% BTC always                                                           (the do-nothing benchmark)
Both active portfolios go to cash the same day BTC closes below its 100-day average. Trades happen at the day's open, signals use
the previous daily close, every traded dollar pays 0.15% (fee + slippage). Same rules as backtest/momentum_weekly.py.

  python momentum_paper.py          one pass: fetch daily candles, act if it is a new day, mark to market, save store/state/momentum_paper.json
Safe to run every few minutes: it only trades once per UTC day and never throws (a failed fetch just skips the pass).
"""
import datetime
import html as _html
import json
import os
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "store", "state", "momentum_paper.json")
BASE = "https://data-api.binance.vision/api/v3/klines"
COINS = ("BTC ETH BNB SOL XRP DOGE ADA TRX LINK AVAX DOT LTC BCH NEAR UNI ATOM ETC APT ARB OP INJ SUI AAVE FIL HBAR XLM SHIB PEPE ICP "
         "ALGO VET THETA SAND MANA AXS EGLD FLOW CHZ GALA CRV SNX COMP RUNE ZEC DASH NEO IOTA ENJ BAT STX IMX LDO GRT 1INCH SUSHI CAKE ANKR").split()
START_CASH = 10000.0
SIDE_COST = 0.0015
REGIME_DAYS, UNIVERSE_N, LOOKBACK, PICKS, MIN_QUOTE_VOL = 100, 20, 14, 5, 2e6
KEEP_EQUITY_DAYS, KEEP_TRADES = 800, 400


# ---------------------------------------------------------------------------------------------------------------- pure logic
def regime_on(btc_closes, days=REGIME_DAYS):
    """BTC's last closed daily candle is above its `days`-day average (needs days+ candles; unknown = off)."""
    if len(btc_closes) < days:
        return False
    return btc_closes[-1] > sum(btc_closes[-days:]) / days


def score(closes, lookback=LOOKBACK):
    """Return over the last `lookback` days divided by the volatility of the daily returns in that window."""
    if len(closes) < lookback + 1:
        return None
    seg = closes[-(lookback + 1):]
    rets = [seg[i + 1] / seg[i] - 1 for i in range(lookback)]
    sd = statistics.pstdev(rets)
    return (seg[-1] / seg[0] - 1) / sd if sd > 0 else None


def pick_momentum(data, top_n=UNIVERSE_N, picks=PICKS):
    """data = {coin: {"close": [...], "qv": [...]}} of CLOSED daily candles, all ending on the same day. Returns coins to hold."""
    liquid = []
    for coin, d in data.items():
        qv = d["qv"][-30:]
        if len(qv) >= 25 and sum(qv) / len(qv) >= MIN_QUOTE_VOL:
            liquid.append((sum(qv) / len(qv), coin))
    liquid.sort(reverse=True)
    ranked = []
    for _, coin in liquid[:top_n]:
        s = score(data[coin]["close"])
        if s is not None and s > 0:
            ranked.append((s, coin))
    ranked.sort(reverse=True)
    return [coin for _, coin in ranked[:picks]]


def new_portfolio():
    return {"cash": START_CASH, "units": {}, "equity": [], "trades": []}


def value(p, prices):
    return p["cash"] + sum(u * prices.get(c, 0.0) for c, u in p["units"].items())


def rebalance(p, targets, opens, day, cost=SIDE_COST):
    """Move portfolio p to equal weight in `targets` at the given open prices; pays `cost` on every traded dollar. Mutates p."""
    held_value = {c: u * opens[c] for c, u in p["units"].items() if c in opens}
    equity = p["cash"] + sum(held_value.values())
    # a coin we hold but have no price for stays untouched (valued at 0 here, so it is never sold blind)
    targets = [c for c in targets if c in opens]
    w = equity / len(targets) if targets else 0.0
    tv = {c: w for c in targets}
    traded = sum(abs(tv.get(c, 0.0) - held_value.get(c, 0.0)) for c in set(tv) | set(held_value))
    fee = traded * cost
    scale = (equity - fee) / equity if equity > 0 else 0.0
    for c in set(tv) | set(held_value):
        before = held_value.get(c, 0.0)
        after = tv.get(c, 0.0) * scale
        if abs(after - before) > 1e-9:
            p["trades"].append({"day": day, "coin": c, "side": "BUY" if after > before else "SELL", "price": opens[c],
                                "usd": round(abs(after - before), 2)})
    p["units"] = {c: tv[c] * scale / opens[c] for c in targets}
    p["cash"] = equity - fee - sum(tv[c] * scale for c in targets)
    p["trades"] = p["trades"][-KEEP_TRADES:]


def step(state, data, opens, last_prices, today, is_monday):
    """One day's decision. `data` = closed candles up to yesterday, `opens` = today's open prices, `last_prices` = latest prices.
    Trades at most once per UTC day; always refreshes today's equity point. Returns the (mutated) state."""
    port = state["portfolios"]
    if state.get("last_action_day") != today:
        on = regime_on(data["BTC"]["close"]) if "BTC" in data else False
        state["regime_on"] = on
        for name in ("momentum", "btc_regime"):
            p = port[name]
            if p["units"] and not on:
                rebalance(p, [], opens, today)                                  # BTC lost its average: everything to cash
        if is_monday and state.get("last_rebalance") != today:
            if on:
                rebalance(port["momentum"], pick_momentum(data), opens, today)
                rebalance(port["btc_regime"], ["BTC"], opens, today)
            state["last_rebalance"] = today
        elif on and not port["btc_regime"]["units"] and port["btc_regime"]["cash"] > 0 and state.get("last_rebalance"):
            rebalance(port["btc_regime"], ["BTC"], opens, today)               # BTC just regained its average: the benchmark re-enters
        if not port["btc_hold"]["units"] and "BTC" in opens:
            rebalance(port["btc_hold"], ["BTC"], opens, today, cost=SIDE_COST)  # buy once, never sell
        state["last_action_day"] = today
    for p in port.values():
        v = round(value(p, last_prices), 2)
        if p["equity"] and p["equity"][-1][0] == today:
            p["equity"][-1][1] = v
        else:
            p["equity"].append([today, v])
        p["equity"] = p["equity"][-KEEP_EQUITY_DAYS:]
    return state


def summary(state, last_prices):
    out = {}
    for name, p in state["portfolios"].items():
        eq = [e[1] for e in p["equity"]]
        peak, dd = 0.0, 0.0
        for v in eq:
            peak = max(peak, v)
            dd = min(dd, v / peak - 1) if peak else dd
        out[name] = {"value": eq[-1] if eq else START_CASH, "return_pct": round((eq[-1] / START_CASH - 1) * 100, 2) if eq else 0.0,
                     "max_drawdown_pct": round(dd * 100, 2), "holdings": {c: round(u * last_prices.get(c, 0.0), 2) for c, u in p["units"].items()},
                     "cash": round(p["cash"], 2)}
    return {"started": state.get("started"), "regime_on": state.get("regime_on"), "last_rebalance": state.get("last_rebalance"),
            "portfolios": out}


# ---------------------------------------------------------------------------------------------------------------- display
NAMES = {"momentum": ("Momentum picks", "Top-5 strongest liquid coins, rebalanced every Monday"),
         "btc_regime": ("BTC when healthy", "All BTC while it is above its 100-day average, else cash"),
         "btc_hold": ("BTC buy & hold", "Bought once, never sold (the do-nothing yardstick)")}
COLORS = {"momentum": "#f59e0b", "btc_regime": "#3b82f6", "btc_hold": "#94a3b8"}


def _usd(x):
    return "${:,.0f}".format(x)


def _pct(x):
    return "{:+.1f}%".format(x)


def _chart(state):
    series = {k: state["portfolios"][k]["equity"] for k in NAMES}
    n = max((len(v) for v in series.values()), default=0)
    if n < 2:
        return '<p class="pp-empty">The chart appears after the second day of paper trading.</p>'
    allv = [e[1] for v in series.values() for e in v]
    lo, hi = min(allv), max(allv)
    span = (hi - lo) or 1.0
    W, H = 640, 180
    lines = []
    for k, v in series.items():
        pts = " ".join("%.1f,%.1f" % (i / (max(len(v) - 1, 1)) * W, H - (e[1] - lo) / span * (H - 12) - 6) for i, e in enumerate(v))
        lines.append('<polyline fill="none" stroke="%s" stroke-width="2.2" points="%s"/>' % (COLORS[k], pts))
    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (COLORS[k], _html.escape(NAMES[k][0])) for k in NAMES)
    return ('<div class="pp-legend">%s</div><svg class="pp-chart" viewBox="0 0 %d %d" role="img" aria-label="Paper portfolio value over time">%s</svg>'
            '<p class="pp-axis">%s to %s &middot; low %s &middot; high %s</p>'
            % (legend, W, H, "".join(lines), _html.escape(str(series["momentum"][0][0])), _html.escape(str(series["momentum"][-1][0])), _usd(lo), _usd(hi)))


def render_section(state, last_prices):
    """The 'Paper trading' tab: pre-rendered HTML (no JavaScript needed) + the raw summary as data."""
    sm = summary(state, last_prices)
    on = sm["regime_on"]
    status = ('<span class="pp-chip pp-on">BTC is above its 100-day average &mdash; the strategies are allowed to hold coins</span>' if on
              else '<span class="pp-chip pp-off">BTC is below its 100-day average &mdash; the strategies are sitting in cash</span>')
    cards = []
    for k, (title, sub) in NAMES.items():
        p = sm["portfolios"][k]
        hold = ", ".join("%s %s" % (_html.escape(c), _usd(v)) for c, v in sorted(p["holdings"].items(), key=lambda x: -x[1])) or "all cash"
        cls = "pp-up" if p["return_pct"] > 0 else ("pp-down" if p["return_pct"] < 0 else "")
        cards.append(
            '<div class="pp-card"><div class="pp-name"><i style="background:%s"></i>%s</div><div class="pp-sub">%s</div>'
            '<div class="pp-val">%s</div><div class="pp-ret %s">%s since start</div>'
            '<div class="pp-row"><span>Worst drop so far</span><b>%s</b></div><div class="pp-row"><span>Holding</span><b>%s</b></div></div>'
            % (COLORS[k], _html.escape(title), _html.escape(sub), _usd(p["value"]), cls, _pct(p["return_pct"]),
               "{:.1f}%".format(p["max_drawdown_pct"]), hold))
    trades = [dict(t, who=k) for k in ("momentum",) for t in state["portfolios"][k]["trades"]][-12:][::-1]
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td class=\"pp-n\">%s</td></tr>"
                   % (_html.escape(t["day"]), _html.escape(t["side"]), _html.escape(t["coin"]), _usd(t["usd"])) for t in trades)
    table = ('<table class="pp-table"><thead><tr><th>Day</th><th>Action</th><th>Coin</th><th>Size</th></tr></thead><tbody>%s</tbody></table>' % rows
             if rows else '<p class="pp-empty">No trades yet. The first rebalance happens on a Monday while BTC is above its 100-day average.</p>')
    body = (
        '<div class="panel panel-paper"><div class="pp">'
        '<p class="pp-note"><b>Practice money only.</b> Nothing here is bought or sold for real. Three simulated portfolios, each starting at %s, '
        'follow the rules from our backtest so we can see whether the momentum idea works on live prices before anyone risks money. '
        'Costs of 0.15%% per trade are included. Started %s.</p>%s<div class="pp-cards">%s</div>'
        '<h3 class="pp-h">Portfolio value</h3>%s<h3 class="pp-h">Latest momentum trades</h3>%s'
        '<p class="pp-note pp-small">What the backtest said: the momentum idea looked good in its best case but was over-fitted, with drops of 55&ndash;75%%. '
        'Holding BTC only while it is above its 100-day average did nearly as well on risk-adjusted terms with a smaller drop. '
        'This tab will show which one actually earns its keep.</p></div></div>'
        % (_usd(START_CASH), _html.escape(str(sm["started"])), status, "".join(cards), _chart(state), table))
    return {"title": "🧪 Paper trading", "sort_order": 8, "html": body, "data": sm}


# ---------------------------------------------------------------------------------------------------------------- I/O
def fetch(coin, limit=150):
    url = f"{BASE}?symbol={coin}USDT&interval=1d&limit={limit}"
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KairoPaper)"}), timeout=15) as r:
                rows = json.loads(r.read())
            if isinstance(rows, list) and rows:
                return rows
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def load_state(path=STATE_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def save_state(state, path=STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))
    os.replace(tmp, path)


def main(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    today_ms = int(datetime.datetime(now.year, now.month, now.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    data, opens, last_prices = {}, {}, {}
    for coin in COINS:
        rows = fetch(coin)
        if not rows:
            continue
        closed = [r for r in rows if r[0] < today_ms]
        todays = [r for r in rows if r[0] == today_ms]
        if not closed or closed[-1][0] != today_ms - 86400000 or not todays:
            continue                                    # stale / delisted / not trading today: leave it out
        data[coin] = {"close": [float(r[4]) for r in closed], "qv": [float(r[7]) for r in closed]}
        opens[coin], last_prices[coin] = float(todays[0][1]), float(todays[0][4])
    if "BTC" not in data:
        print("momentum_paper: no BTC data, skipping this pass")
        return 0
    state = load_state() or {"version": 1, "started": today, "portfolios": {n: new_portfolio() for n in ("momentum", "btc_regime", "btc_hold")}}
    step(state, data, opens, last_prices, today, now.weekday() == 0)
    save_state(state)
    s = summary(state, last_prices)
    try:
        import filestore
        backend = filestore.FileBackend.from_env()
        if backend:
            backend.publish_portions({"paper": render_section(state, last_prices)})
    except Exception as e:  # noqa: BLE001 - the tab is a nicety; the engine state is already saved
        print("momentum_paper: could not publish the tab (%s: %s)" % (type(e).__name__, e))
    print("momentum_paper:", json.dumps({k: (v["value"], v["return_pct"]) for k, v in s["portfolios"].items()}), "regime_on=%s" % s["regime_on"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - paper engine must never break the dashboard build
        print("momentum_paper: skipped (%s: %s)" % (type(e).__name__, e))
        sys.exit(0)
