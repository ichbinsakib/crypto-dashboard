"""
Teka Live Dashboard - generates dashboard/index.html from free crypto data sources.
Data: CoinGecko (price/market), Binance Futures public API (funding/OI/premium),
Alternative.me (Fear & Greed Index).

Rows that need paid on-chain data (MVRV Z-Score, NUPL, exchange flows, ETF flows)
are explicitly marked unavailable rather than faked.

Run manually:  python dashboard.py
Hosted:        .github/workflows/deploy.yml runs this on a schedule and publishes
               site/index.html to GitHub Pages. data/ is committed back each run
               so state and alerts persist between runs.
"""

import json
import os
import datetime
import random
import subprocess
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")   # build output -> deployed to GitHub Pages, not committed
DATA_DIR = os.path.join(BASE_DIR, "data")   # persisted between runs -> committed to the repo
os.makedirs(SITE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

STATE_PATH = os.path.join(DATA_DIR, "state.json")
OUTPUT_PATH = os.path.join(SITE_DIR, "index.html")
LOG_PATH = os.path.join(BASE_DIR, "dashboard.log")
ALERTS_CONFIG_PATH = os.path.join(DATA_DIR, "alerts_config.json")
IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"

COINS = [
    {"key": "BTC", "name": "Bitcoin", "cg_id": "bitcoin", "symbol": "BTCUSDT", "emoji": "₿"},
    {"key": "ETH", "name": "Ethereum", "cg_id": "ethereum", "symbol": "ETHUSDT", "emoji": "Ξ"},
]

REFRESH_SECONDS = 120  # in-browser auto-reload interval
DATA_REFRESH_LABEL = "every ~10 min (GitHub Actions, best-effort)"  # keep in sync with .github/workflows/deploy.yml

SCREENER_SIZE = 15  # how many coins to rank; raising this adds run time and CoinGecko rate-limit risk
# GitHub Actions runners share IP pools hammered by countless other CI jobs hitting CoinGecko,
# so they get throttled harder than a residential IP -- back off more there.
SCREENER_RATE_LIMIT_DELAY = 12 if IS_CI else 6
SCREENER_RETRY_BACKOFF = 15 if IS_CI else 8
SCREENER_EXCLUDE_IDS = {
    # stablecoins -- an accumulate/distribute reading is meaningless for these
    "tether", "usd-coin", "binance-usd", "dai", "true-usd", "frax", "usdd",
    "first-digital-usd", "ethena-usde", "paypal-usd", "usds", "susds",
    # yield-bearing/tokenized-treasury dollar (or other fiat) products -- pegged near $1
    # (or 1 EUR etc), same problem as stables
    "ondo-us-dollar-yield", "hashnote-usyc", "global-dollar", "united-stables",
    "spiko-amundi-overnight-swap-fund-eur",
    # wrapped/staked duplicates of coins already covered on their own tabs
    "wrapped-bitcoin", "weth", "staked-ether", "wrapped-steth",
    "coinbase-wrapped-btc", "wrapped-eeth", "weeth",
}


def log(msg):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def http_get_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "teka-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def safe_fetch(label, fn):
    try:
        return fn(), None
    except Exception as e:
        log(f"FETCH FAIL [{label}]: {e}")
        return None, str(e)


def fetch_coingecko_markets():
    ids = ",".join(c["cg_id"] for c in COINS)
    url = (f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
           f"&ids={ids}&price_change_percentage=1h,24h,7d,30d")
    data = http_get_json(url)
    return {d["id"]: d for d in data}


def fetch_market_chart(cg_id, days=210):
    url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
    data = http_get_json(url)
    return [p[1] for p in data.get("prices", [])]


def sma(values, window):
    if not values or len(values) < window:
        return None
    return sum(values[-window:]) / window


def fetch_binance_premium(symbol):
    return http_get_json(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}")


def fetch_binance_oi_hist(symbol, period="1h", limit=25):
    return http_get_json(
        f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period={period}&limit={limit}")


def fetch_fng():
    data = http_get_json("https://api.alternative.me/fng/?limit=2&format=json")
    return data.get("data", [])


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"STATE SAVE FAIL: {e}")


def load_alerts_config():
    if not os.path.exists(ALERTS_CONFIG_PATH):
        return None
    try:
        with open(ALERTS_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"ALERTS CONFIG LOAD FAIL: {e}")
        return {"alerts": []}


def save_alerts_config(config):
    try:
        with open(ALERTS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        log(f"ALERTS CONFIG SAVE FAIL: {e}")


def seed_default_alerts(coins_data):
    """First-run only: create starter alerts from the 30d support/resistance we just computed."""
    alerts = []
    for c in coins_data:
        if c.get("resistance_30d"):
            alerts.append({
                "id": f"{c['key'].lower()}-resistance-break",
                "coin": c["key"], "condition": "above",
                "price": round(c["resistance_30d"], 2),
                "label": f"{c['key']} breaks 30-day resistance",
                "enabled": True,
            })
        if c.get("support_30d"):
            alerts.append({
                "id": f"{c['key'].lower()}-support-break",
                "coin": c["key"], "condition": "below",
                "price": round(c["support_30d"], 2),
                "label": f"{c['key']} breaks 30-day support",
                "enabled": True,
            })
    return {"alerts": alerts}


def evaluate_alerts(coins_data, alerts_config, prev_alerts_state, generated_at):
    """Level-triggered: an alert shows TRIGGERED for as long as the condition holds true."""
    price_by_coin = {c["key"]: c.get("price") for c in coins_data}
    results = []
    new_alerts_state = {}
    newly_triggered = []
    for rule in alerts_config.get("alerts", []):
        if not rule.get("enabled", True):
            continue
        rid = rule.get("id")
        coin = rule.get("coin")
        price = price_by_coin.get(coin)
        cond = rule.get("condition")
        target = rule.get("price")
        if price is None or target is None or rid is None:
            continue
        triggered = (price >= target) if cond == "above" else (price <= target)
        was_triggered = prev_alerts_state.get(rid, {}).get("triggered", False)
        if triggered and not was_triggered:
            newly_triggered.append({**rule, "current_price": price})
        dist_pct = (price - target) / target * 100 if target else None
        results.append({
            "id": rid, "coin": coin, "condition": cond, "target": target,
            "label": rule.get("label", rid), "triggered": triggered,
            "current_price": price, "dist_pct": dist_pct,
        })
        new_alerts_state[rid] = {
            "triggered": triggered,
            "last_triggered_at": generated_at if triggered else prev_alerts_state.get(rid, {}).get("last_triggered_at"),
        }
    return results, new_alerts_state, newly_triggered


def ps_safe(s):
    return str(s).replace('"', "'").replace("`", "'")


def fire_toast_notifications(newly_triggered):
    """Best-effort native Windows toast, fire-and-forget. Never blocks; failures are silent
    (e.g. if the scheduled task runs in a non-interactive session). The dashboard banner is
    the reliable alert channel regardless of whether this succeeds."""
    if not newly_triggered or IS_CI:
        return  # no desktop to notify when running on a GitHub Actions runner
    lines = "; ".join(f"{ps_safe(r.get('label'))} (${r['current_price']:,.2f})" for r in newly_triggered)
    title = "Teka Price Alert"
    ps_script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null;"
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$textNodes = $template.GetElementsByTagName('text');"
        f"$textNodes.Item(0).AppendChild($template.CreateTextNode(\"{title}\")) > $null;"
        f"$textNodes.Item(1).AppendChild($template.CreateTextNode(\"{lines}\")) > $null;"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Teka Live Dashboard').Show($toast)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log(f"TOAST FIRED: {lines}")
    except Exception as e:
        log(f"TOAST NOTIFY FAIL: {e}")


def fmt_usd(v, decimals=2):
    if v is None:
        return "N/A"
    return f"${v:,.{decimals}f}"


def fmt_usd_adaptive(v):
    """Scales decimal places to the coin's price so sub-$1 coins (ADA, DOGE, meme coins)
    don't lose all precision under a fixed 2-decimal format."""
    if v is None:
        return "N/A"
    if v >= 1:
        return f"${v:,.2f}"
    if v >= 0.01:
        return f"${v:,.4f}"
    return f"${v:,.6f}"


def fmt_pct(v, decimals=2, sign=True):
    if v is None:
        return "N/A"
    s = "+" if (sign and v > 0) else ""
    return f"{s}{v:.{decimals}f}%"


def badge(label, status):
    # status: bullish, bearish, neutral, locked
    return {"label": label, "status": status}


def classify_price_structure(pct_24h, pct_7d):
    if pct_7d is None:
        return "Unknown", "neutral"
    if pct_7d >= 20 and (pct_24h or 0) >= 5:
        return "Parabolic (blow-off risk)", "bearish"
    if pct_7d >= 8:
        return "Uptrend", "bullish"
    if pct_7d <= -8:
        return "Downtrend", "bearish"
    return "Range / Consolidation", "neutral"


def classify_funding(rate):
    if rate is None:
        return "N/A", "neutral"
    pct = rate * 100
    if pct >= 0.03:
        return f"{pct:.4f}% - overheated longs", "bearish"
    if pct <= -0.01:
        return f"{pct:.4f}% - shorts paying (squeeze risk)", "bullish"
    return f"{pct:.4f}% - healthy/neutral", "neutral"


def classify_oi(oi_change_pct, price_change_pct):
    if oi_change_pct is None or price_change_pct is None:
        return "N/A", "neutral"
    if price_change_pct > 1 and oi_change_pct < 1:
        return f"OI {oi_change_pct:+.1f}% - spot-led rally", "bullish"
    if price_change_pct > 1 and oi_change_pct >= 3:
        return f"OI {oi_change_pct:+.1f}% - leverage buildup", "bearish"
    if price_change_pct < -1 and oi_change_pct < -1:
        return f"OI {oi_change_pct:+.1f}% - long flush", "neutral"
    if price_change_pct < -1 and oi_change_pct >= 2:
        return f"OI {oi_change_pct:+.1f}% - short buildup", "neutral"
    return f"OI {oi_change_pct:+.1f}% - flat", "neutral"


def classify_premium(mark, index):
    if mark is None or index is None or index == 0:
        return "N/A", "neutral"
    bps = (mark - index) / index * 10000
    if bps > 30:
        return f"{bps:.1f} bps - elevated bullish basis", "bearish"
    if bps < -10:
        return f"{bps:.1f} bps - backwardation (bearish)", "bearish"
    if bps > 5:
        return f"{bps:.1f} bps - healthy bullish basis", "bullish"
    return f"{bps:.1f} bps - flat", "neutral"


def classify_fng(value, classification):
    if value is None:
        return "N/A", "neutral"
    v = int(value)
    if v >= 75:
        return f"{v} - {classification} (euphoria risk)", "bearish"
    if v <= 25:
        return f"{v} - {classification} (contrarian accumulation zone)", "bullish"
    return f"{v} - {classification}", "neutral"


def classify_liquidation_risk(funding_pct, oi_change_pct):
    if funding_pct is None or oi_change_pct is None:
        return "N/A (model estimate)", "neutral"
    crowded_long = funding_pct >= 0.03 and oi_change_pct >= 3
    crowded_short = funding_pct <= -0.02 and oi_change_pct >= 3
    if crowded_long:
        return "Elevated - crowded longs (model estimate)", "bearish"
    if crowded_short:
        return "Elevated - crowded shorts (model estimate)", "bullish"
    return "Low/Moderate (model estimate)", "neutral"


def cycle_stage(price, sma50, sma200, pct_30d):
    if price is None or sma200 is None:
        return "Unknown"
    dist_pct = (price - sma200) / sma200 * 100
    p30 = pct_30d or 0
    if dist_pct > 40 and p30 > 15:
        return "Distribution"
    if dist_pct > 5 and p30 > 5:
        return "Markup"
    if dist_pct < -15 and p30 < -10:
        return "Markdown"
    return "Accumulation"


def heat_score(pct_30d, dist_from_sma200_pct, funding_pct, fng_value):
    parts = []
    if pct_30d is not None:
        parts.append(max(0, min(10, (pct_30d + 20) / 4)))
    if dist_from_sma200_pct is not None:
        parts.append(max(0, min(10, (dist_from_sma200_pct + 20) / 6)))
    if funding_pct is not None:
        parts.append(max(0, min(10, (funding_pct + 0.03) * 100)))
    if fng_value is not None:
        parts.append(fng_value / 10)
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)


def compute_spot_signal(c, price_struct_label, stage, fng_value, funding_pct):
    """
    Educational, rule-based spot (no-leverage) reading: does the current mix of
    conditions historically resemble an accumulation zone, a distribution zone,
    or neither? Every factor below is shown to the user alongside its point
    contribution -- this is a teaching aid, not a trade instruction.
    """
    rows = []
    total = 0

    price = c.get("price")
    support = c.get("support_30d")
    resistance = c.get("resistance_30d")
    dist_sma200_pct = None
    if price and c.get("sma200"):
        dist_sma200_pct = (price - c["sma200"]) / c["sma200"] * 100

    # 1. Distance to recent price floor/ceiling (mean-reversion zone)
    if price and support and price <= support * 1.05:
        pts, reading = 2, f"Near its 30-day low (~{fmt_usd_adaptive(support)}) - historically a better entry"
    elif price and resistance and price >= resistance * 0.95:
        pts, reading = -1, f"Near its 30-day high (~{fmt_usd_adaptive(resistance)}) - less room to run"
    else:
        pts, reading = 0, "Sitting in the middle of its 30-day range"
    rows.append(("Price vs. recent range", reading, pts))
    total += pts

    # 2. Fear & Greed (contrarian sentiment)
    if fng_value is None:
        pts, reading = 0, "No sentiment data"
    elif fng_value <= 25:
        pts, reading = 2, f"{fng_value}/100 - crowd is very fearful (contrarians buy here)"
    elif fng_value <= 45:
        pts, reading = 1, f"{fng_value}/100 - crowd is cautious/fearful"
    elif fng_value <= 54:
        pts, reading = 0, f"{fng_value}/100 - crowd mood is neutral"
    elif fng_value <= 74:
        pts, reading = -1, f"{fng_value}/100 - crowd is greedy"
    else:
        pts, reading = -2, f"{fng_value}/100 - crowd is very greedy (euphoria risk)"
    rows.append(("Crowd mood (Fear & Greed)", reading, pts))
    total += pts

    # 3. Cycle stage heuristic
    stage_points = {"Accumulation": 2, "Markup": 1, "Markdown": -1, "Distribution": -2}
    stage_plain = {
        "Accumulation": "Basing near the bottom - phase where smart money accumulates",
        "Markup": "Established uptrend - phase where price marks up",
        "Markdown": "Established downtrend - still falling, not yet a base",
        "Distribution": "Very extended after a big run - phase where smart money sells",
    }
    pts = stage_points.get(stage, 0)
    rows.append(("Market phase (best guess)", stage_plain.get(stage, stage), pts))
    total += pts

    # 4. Price structure
    struct_points = {"Uptrend": 1, "Range / Consolidation": 0, "Downtrend": -1,
                      "Parabolic (blow-off risk)": -2}
    struct_plain = {
        "Uptrend": "Trending up steadily - healthy",
        "Range / Consolidation": "Chopping sideways - no clear trend",
        "Downtrend": "Trending down - avoid catching a falling knife",
        "Parabolic (blow-off risk)": "Shooting straight up - classic blow-off top risk, don't chase",
    }
    pts = struct_points.get(price_struct_label, 0)
    rows.append(("Recent trend", struct_plain.get(price_struct_label, price_struct_label), pts))
    total += pts

    # 5. Extension from the 200-day average (overheat / capitulation check)
    if dist_sma200_pct is None:
        pts, reading = 0, "No long-term average data"
    elif dist_sma200_pct > 30:
        pts, reading = -2, f"{dist_sma200_pct:+.1f}% above its long-term average - very stretched"
    elif dist_sma200_pct > 10:
        pts, reading = -1, f"{dist_sma200_pct:+.1f}% above its long-term average - a bit stretched"
    elif dist_sma200_pct < -15:
        pts, reading = -1, f"{dist_sma200_pct:+.1f}% below its long-term average - confirmed downtrend"
    else:
        pts, reading = 0, f"{dist_sma200_pct:+.1f}% vs its long-term average - not stretched either way"
    rows.append(("Stretch from long-term average", reading, pts))
    total += pts

    # 6. Futures funding/crowd positioning (confluence only, small weight)
    if funding_pct is None:
        pts, reading = 0, "No leverage data"
    elif funding_pct >= 0.03 and (fng_value or 0) >= 75:
        pts, reading = -1, "Too many leveraged buyers piled in - pullback risk"
    elif funding_pct <= -0.01:
        pts, reading = 1, "Leveraged short-sellers paying up - could get squeezed higher"
    else:
        pts, reading = 0, "Leveraged traders roughly balanced"
    rows.append(("Leverage traders' bias", reading, pts))
    total += pts

    if total >= 5:
        label, status = "🟢 ACCUMULATION ZONE", "bullish"
        plain = "Strong historical buy-the-dip setup: fear is high and price is cheap relative to its range."
    elif total >= 2:
        label, status = "🟢 LEAN ACCUMULATE", "bullish"
        plain = "Leans toward a decent spot to slowly add (DCA) - not a strong signal, just a lean."
    elif total >= -1:
        label, status = "🟡 HOLD / NEUTRAL", "neutral"
        plain = "No real edge either way right now - fine to just wait and watch."
    elif total >= -4:
        label, status = "🔴 CAUTION - REDUCE NEW BUYS", "bearish"
        plain = "Getting risky - I'd hold off on new buys until this cools down."
    else:
        label, status = "🔴 DISTRIBUTION ZONE", "bearish"
        plain = "Looks stretched and euphoric - historically the zone where smart money sells, not buys."

    return {"label": label, "status": status, "score": total, "rows": rows, "plain": plain}


STOP_BUFFER_PCT = 0.08  # how far below support the pullback stop sits
BREAKOUT_ENTRY_PCT = 0.01  # how far above resistance confirms a breakout entry
BREAKOUT_STOP_PCT = 0.04  # how far below the breakout entry the stop sits


def compute_trade_levels(c):
    """
    Formula-based entry/stop/target levels, derived only from the 30-day support
    and resistance this dashboard already computes. Two explicit scenarios, same
    structure as a manual IF/THEN trade plan: pull back to support, or confirmed
    breakout above resistance. Not a recommendation -- a transparent calculator.
    """
    price = c.get("price")
    support = c.get("support_30d")
    resistance = c.get("resistance_30d")
    if not (price and support and resistance and resistance > support):
        return None

    # Scenario A: pullback to support
    pb_entry_low, pb_entry_high = support, support * 1.03
    pb_stop = support * (1 - STOP_BUFFER_PCT)
    pb_risk = pb_entry_low - pb_stop
    pb_target1 = resistance
    pb_target2 = pb_entry_low + 2 * pb_risk
    pb_risk_pct = (pb_risk / pb_entry_low) * 100 if pb_entry_low else None

    # Scenario B: confirmed breakout above resistance
    bo_entry = resistance * (1 + BREAKOUT_ENTRY_PCT)
    bo_stop = resistance * (1 - BREAKOUT_STOP_PCT)
    bo_risk = bo_entry - bo_stop
    bo_target1 = bo_entry + bo_risk
    bo_target2 = bo_entry + 2 * bo_risk
    bo_risk_pct = (bo_risk / bo_entry) * 100 if bo_entry else None

    return {
        "pullback": {
            "entry_low": pb_entry_low, "entry_high": pb_entry_high, "stop": pb_stop,
            "target1": pb_target1, "target2": pb_target2, "risk_pct": pb_risk_pct,
        },
        "breakout": {
            "entry": bo_entry, "stop": bo_stop,
            "target1": bo_target1, "target2": bo_target2, "risk_pct": bo_risk_pct,
        },
    }


SCREENER_POOL_SIZE = 80  # candidate pool to rotate through -- one bulk API call regardless of size,
                          # so widening this costs nothing extra (only the per-coin calls below are rate-limited)


def fetch_screener_markets(limit=SCREENER_SIZE):
    """Fetches a wide pool of top-market-cap coins in a single call, then randomly rotates
    which `limit` of them get the (expensive, per-coin) detailed analysis each cycle. Without
    this, the screener would greedily take the same first N coins by market-cap rank every
    single run -- the top ~15 non-BTC/ETH coins by market cap barely change hour to hour, so
    the list would look permanently "stuck" even though each coin's own data is fresh."""
    url = (f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
           f"&order=market_cap_desc&per_page={SCREENER_POOL_SIZE}&page=1"
           f"&price_change_percentage=1h,24h,7d,30d")
    data = http_get_json(url)
    covered_ids = {c["cg_id"] for c in COINS}
    candidates = [
        d for d in data
        if d["id"] not in SCREENER_EXCLUDE_IDS
        and d["id"] not in covered_ids
        and not _looks_pegged(d)
    ]
    if len(candidates) <= limit:
        return candidates
    return random.sample(candidates, limit)


def _looks_pegged(d):
    """Catches tokenized money-market/treasury funds and stablecoin-likes that keep showing
    up under new names (BUIDL, Janus Henderson's fund, BFUSD, ...) without having to chase
    each one by id: price glued near $1 AND barely moved in a week is the signature of a peg,
    not a real speculative asset. A genuinely volatile coin rarely sits still like that."""
    price = d.get("current_price")
    if price is None:
        return False
    pct_7d = d.get("price_change_percentage_7d_in_currency")
    return 0.97 <= price <= 1.03 and pct_7d is not None and abs(pct_7d) < 3


def compute_spot_signal_lite(m, chart, fng_value):
    """Same rule-based model as compute_spot_signal, minus the futures crowd-positioning
    factor (that needs a per-symbol Binance call, too expensive to do for a whole screener
    universe on the free tier). Reuses compute_spot_signal by building a compatible dict."""
    price = m.get("current_price")
    pct_24h = m.get("price_change_percentage_24h_in_currency")
    pct_7d = m.get("price_change_percentage_7d_in_currency")
    pct_30d = m.get("price_change_percentage_30d_in_currency")

    sma50_v = sma(chart, 50)
    sma200_v = sma(chart, 200)
    support = min(chart[-30:]) if len(chart) >= 30 else None
    resistance = max(chart[-30:]) if len(chart) >= 30 else None

    price_struct_label, _ = classify_price_structure(pct_24h, pct_7d)
    stage = cycle_stage(price, sma50_v, sma200_v, pct_30d)

    fake_c = {"price": price, "support_30d": support, "resistance_30d": resistance, "sma200": sma200_v}
    result = compute_spot_signal(fake_c, price_struct_label, stage, fng_value, funding_pct=None)
    result.update({
        "id": m.get("id"), "symbol": (m.get("symbol") or "").upper(), "name": m.get("name"),
        "price": price, "pct_24h": pct_24h, "pct_7d": pct_7d,
        "support_30d": support, "resistance_30d": resistance,
    })
    return result


def build_screener(fng_value, prev_screener_state, generated_at, markets=None):
    """Ranks the top-market-cap universe by the lite spot signal. If a coin's live fetch
    fails (CoinGecko free-tier rate limiting is common), falls back to its last successful
    reading rather than dropping it -- so a coin like SOL or XRP getting rate-limited on one
    run doesn't just vanish from the table, it shows up marked as cached."""
    prev_screener_state = prev_screener_state or {}
    if markets is None:
        markets, err = safe_fetch("screener markets", fetch_screener_markets)
    if not markets:
        cached = []
        for v in prev_screener_state.values():
            stale_sig = dict(v)
            stale_sig["stale"] = True
            cached.append(stale_sig)
        cached.sort(key=lambda r: r["score"], reverse=True)
        return cached, prev_screener_state

    results = []
    # Start from the full accumulated history (not just this cycle's picks) so a coin's cache
    # survives being rotated out and back in later -- otherwise random rotation would mean a
    # coin only ever has a fallback if it happened to be selected last cycle too.
    new_state = dict(prev_screener_state)
    issues = []
    for m in markets:
        cid = m["id"]
        label = f"screener chart {cid}"
        chart, cerr = safe_fetch(label, lambda mid=cid: fetch_market_chart(mid, days=210))
        if not chart:
            log(f"Retrying {label} after rate-limit backoff...")
            time.sleep(SCREENER_RETRY_BACKOFF)
            chart, cerr = safe_fetch(label, lambda mid=cid: fetch_market_chart(mid, days=210))
        time.sleep(SCREENER_RATE_LIMIT_DELAY)

        if chart and len(chart) >= 50:
            try:
                sig = compute_spot_signal_lite(m, chart, fng_value)
                sig["as_of"] = generated_at
                sig["stale"] = False
                results.append(sig)
                new_state[cid] = sig
                continue
            except Exception as e:
                log(f"SCREENER SIGNAL FAIL [{cid}]: {e}")

        prev = prev_screener_state.get(cid)
        if prev:
            stale_sig = dict(prev)
            stale_sig["stale"] = True
            results.append(stale_sig)
            new_state[cid] = prev  # keep the last *good* snapshot, don't overwrite with a stale copy
            issues.append(f"{cid} (using cached)")
        else:
            issues.append(f"{cid} (no cache, dropped)")

    if issues:
        log(f"Screener live-fetch issues: {issues}")
    results.sort(key=lambda r: r["score"], reverse=True)
    return results, new_state


BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
INTRADAY_TIMEFRAMES = {
    # interval -> (binance klines interval string, candles to fetch, candles used for range/ATR)
    "15m": {"binance_interval": "15m", "fetch_limit": 100, "lookback": 30, "window_label": "last ~7.5 hours"},
    "1h": {"binance_interval": "1h", "fetch_limit": 100, "lookback": 24, "window_label": "last 24 hours"},
}
INTRADAY_RATE_LIMIT_DELAY = 0.35  # Binance's public spot API is far more permissive than CoinGecko's


def fetch_binance_spot_klines(symbol, interval, limit):
    url = f"{BINANCE_SPOT_KLINES_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    return http_get_json(url)


def compute_intraday_signal(klines, lookback, window_label):
    """
    Lean, technicals-only version of the spot signal for short timeframes -- no Fear & Greed
    or cycle-stage factors, since those are daily-sentiment concepts that don't mean much on a
    15-minute or 1-hour chart. Uses only price action from the candles themselves: where price
    sits in its recent range, momentum vs a short average, and direction over the window.
    Trade levels are ATR-based (scaled to actual recent volatility) instead of the fixed
    percentage buffers used on the daily model, which matters far more at this timeframe.
    """
    if not klines or len(klines) < lookback + 2:
        return None
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    price = closes[-1]

    recent_high = max(highs[-lookback:])
    recent_low = min(lows[-lookback:])
    avg_close = sum(closes[-lookback:]) / lookback
    atr = sum(highs[i] - lows[i] for i in range(-lookback, 0)) / lookback
    if atr <= 0:
        return None

    rows = []
    total = 0

    if price <= recent_low + atr:
        pts, reading = 2, f"Near the low of its {window_label} (~{fmt_usd_adaptive(recent_low)})"
    elif price >= recent_high - atr:
        pts, reading = -1, f"Near the high of its {window_label} (~{fmt_usd_adaptive(recent_high)})"
    else:
        pts, reading = 0, f"Mid-range for its {window_label}"
    rows.append(("Price vs. recent range", reading, pts))
    total += pts

    dist_avg_pct = (price - avg_close) / avg_close * 100 if avg_close else 0
    if dist_avg_pct > 3:
        pts, reading = -1, f"{dist_avg_pct:+.1f}% above its short-term average - a bit stretched"
    elif dist_avg_pct < -3:
        pts, reading = -1, f"{dist_avg_pct:+.1f}% below its short-term average - weak right now"
    else:
        pts, reading = 1, f"{dist_avg_pct:+.1f}% vs its short-term average - trading near it"
    rows.append(("Momentum vs. short-term average", reading, pts))
    total += pts

    move_pct = (closes[-1] - closes[-lookback]) / closes[-lookback] * 100 if closes[-lookback] else 0
    if move_pct > 1:
        pts, reading = 1, f"Up {move_pct:.1f}% over its {window_label} - short-term uptrend"
    elif move_pct < -1:
        pts, reading = -1, f"Down {move_pct:.1f}% over its {window_label} - short-term downtrend"
    else:
        pts, reading = 0, f"{move_pct:+.1f}% over its {window_label} - flat, no clear direction"
    rows.append(("Direction over this window", reading, pts))
    total += pts

    if total >= 3:
        label, status = "🟢 NEAR-TERM DIP ZONE", "bullish"
        plain = "Near the bottom of its short-term range with improving momentum."
    elif total >= 1:
        label, status = "🟢 LEAN LONG (short-term)", "bullish"
        plain = "Mildly favorable for a quick, tightly-managed trade -- not a strong signal."
    elif total >= -1:
        label, status = "🟡 NO CLEAR EDGE", "neutral"
        plain = "Choppy on this timeframe -- no clean setup right now."
    else:
        label, status = "🔴 STRETCHED - AVOID CHASING", "bearish"
        plain = "Extended on this timeframe; chasing here has poor risk/reward."

    entry = recent_low
    stop = recent_low - atr
    risk = entry - stop
    target1 = entry + risk
    target2 = entry + 2 * risk

    return {
        "label": label, "status": status, "score": total, "rows": rows, "plain": plain,
        "price": price, "atr": atr,
        "trade": {"entry": entry, "stop": stop, "target1": target1, "target2": target2,
                  "risk_pct": (risk / entry * 100) if entry else None},
    }


def build_intraday_screener(markets, timeframe_key):
    """Runs the lean intraday model over the same coin universe as the daily screener,
    using Binance's public spot klines (far more generous rate limits than CoinGecko).
    Coins without a liquid BINANCE-quoted USDT pair (small-caps, tokenized RWA products
    like FIGR_HELOC, etc.) are silently skipped rather than shown broken."""
    cfg = INTRADAY_TIMEFRAMES[timeframe_key]
    results = []
    skipped = []
    for m in markets or []:
        symbol = (m.get("symbol") or "").upper()
        if not symbol:
            continue
        pair = f"{symbol}USDT"
        klines, err = safe_fetch(
            f"{timeframe_key} klines {pair}",
            lambda p=pair: fetch_binance_spot_klines(p, cfg["binance_interval"], cfg["fetch_limit"]))
        time.sleep(INTRADAY_RATE_LIMIT_DELAY)
        if not klines:
            skipped.append(pair)
            continue
        try:
            sig = compute_intraday_signal(klines, cfg["lookback"], cfg["window_label"])
            if sig:
                sig.update({"id": m.get("id"), "symbol": symbol, "name": m.get("name")})
                results.append(sig)
        except Exception as e:
            log(f"INTRADAY SIGNAL FAIL [{pair}]: {e}")
    if skipped:
        log(f"Intraday ({timeframe_key}) skipped (no Binance pair or fetch failed): {skipped}")
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def badge_html(status, text):
    icon = {"bullish": "↗", "bearish": "↘", "neutral": "–", "locked": "\U0001F512"}.get(status, "")
    return f'<span class="badge {status}">{icon} {text}</span>'


def build_coin_data(coin, markets, fng_latest, fng_prev, state):
    cg_id, symbol, key = coin["cg_id"], coin["symbol"], coin["key"]
    prev = state.get(key, {})
    out = {"key": key, "name": coin["name"], "emoji": coin["emoji"], "stale": []}

    m = markets.get(cg_id) if markets else None
    if m:
        price = m.get("current_price")
        high_24h = m.get("high_24h")
        low_24h = m.get("low_24h")
        pct_24h = m.get("price_change_percentage_24h_in_currency")
        pct_7d = m.get("price_change_percentage_7d_in_currency")
        pct_30d = m.get("price_change_percentage_30d_in_currency")
        out.update(price=price, high_24h=high_24h, low_24h=low_24h,
                    pct_24h=pct_24h, pct_7d=pct_7d, pct_30d=pct_30d)
    else:
        out.update(price=prev.get("price"), high_24h=prev.get("high_24h"), low_24h=prev.get("low_24h"),
                    pct_24h=prev.get("pct_24h"), pct_7d=prev.get("pct_7d"), pct_30d=prev.get("pct_30d"))
        out["stale"].append("price")

    chart, err = safe_fetch(f"{key} market_chart", lambda: fetch_market_chart(cg_id))
    if chart:
        out["sma50"] = sma(chart, 50)
        out["sma200"] = sma(chart, 200)
        out["support_30d"] = min(chart[-30:]) if len(chart) >= 30 else None
        out["resistance_30d"] = max(chart[-30:]) if len(chart) >= 30 else None
    else:
        out["sma50"] = prev.get("sma50")
        out["sma200"] = prev.get("sma200")
        out["support_30d"] = prev.get("support_30d")
        out["resistance_30d"] = prev.get("resistance_30d")
        out["stale"].append("moving averages / range")

    prem, err = safe_fetch(f"{key} premiumIndex", lambda: fetch_binance_premium(symbol))
    if prem:
        out["mark_price"] = float(prem.get("markPrice", 0)) or None
        out["index_price"] = float(prem.get("indexPrice", 0)) or None
        out["funding_rate"] = float(prem.get("lastFundingRate", 0))
    else:
        out["mark_price"] = prev.get("mark_price")
        out["index_price"] = prev.get("index_price")
        out["funding_rate"] = prev.get("funding_rate")
        out["stale"].append("funding rate / futures premium")

    oi_hist, err = safe_fetch(f"{key} oi_hist", lambda: fetch_binance_oi_hist(symbol))
    if oi_hist and len(oi_hist) >= 2:
        first = float(oi_hist[0]["sumOpenInterest"])
        last = float(oi_hist[-1]["sumOpenInterest"])
        out["oi_change_pct"] = ((last - first) / first * 100) if first else None
        out["oi_now"] = last
    else:
        out["oi_change_pct"] = prev.get("oi_change_pct")
        out["oi_now"] = prev.get("oi_now")
        out["stale"].append("open interest")

    out["fng_value"] = fng_latest
    out["fng_class"] = fng_prev

    return out


def render(coins_data, fng_value, fng_classification, generated_at, any_stale,
           alerts_results=None, screener_results=None, intraday_results=None):
    total_stale = any_stale
    generated_at_iso = generated_at.replace(" ", "T") + "Z"  # generated_at is naive UTC (GH runners run in UTC)
    alerts_results = alerts_results or []
    screener_results = screener_results or []
    intraday_results = intraday_results or {}
    triggered_now = [a for a in alerts_results if a["triggered"]]

    banner_html = ""
    if triggered_now:
        items = "".join(
            f'<div class="alert-banner-item">🚨 {a["coin"]} {a["condition"]} '
            f'{fmt_usd(a["target"], 0)} &mdash; {a["label"]} (now {fmt_usd(a["current_price"], 2)})</div>'
            for a in triggered_now
        )
        banner_html = f'<div class="alert-banner">{items}</div>'
    tabs_inputs = "\n".join(
        f'<input type="radio" name="tabs" id="tab-{c["key"].lower()}"{" checked" if i == 0 else ""}>'
        for i, c in enumerate(coins_data)
    )
    tabs_inputs += '\n<input type="radio" name="tabs" id="tab-screener">'
    tabs_labels = "\n".join(
        f'<label for="tab-{c["key"].lower()}">{c["emoji"]} {c["key"]}</label>' for c in coins_data
    )
    tabs_labels += '\n<label for="tab-screener">🔍 Screener</label>'

    panels = []
    spot_signals_by_coin = {}
    for c in coins_data:
        price_struct_label, price_struct_status = classify_price_structure(c.get("pct_24h"), c.get("pct_7d"))
        funding_pct = (c.get("funding_rate") or 0) * 100 if c.get("funding_rate") is not None else None
        funding_label, funding_status = classify_funding(c.get("funding_rate"))
        oi_label, oi_status = classify_oi(c.get("oi_change_pct"), c.get("pct_24h"))
        premium_label, premium_status = classify_premium(c.get("mark_price"), c.get("index_price"))
        fng_label, fng_status = classify_fng(fng_value, fng_classification)
        liq_label, liq_status = classify_liquidation_risk(funding_pct, c.get("oi_change_pct"))

        dist_sma200_pct = None
        if c.get("price") and c.get("sma200"):
            dist_sma200_pct = (c["price"] - c["sma200"]) / c["sma200"] * 100

        stage = cycle_stage(c.get("price"), c.get("sma50"), c.get("sma200"), c.get("pct_30d"))
        score = heat_score(c.get("pct_30d"), dist_sma200_pct, funding_pct, fng_value)
        spot_signal = compute_spot_signal(c, price_struct_label, stage, fng_value, funding_pct)
        spot_signals_by_coin[c["key"]] = spot_signal

        stages = ["Accumulation", "Markup", "Distribution", "Markdown"]
        cycle_html = "".join(
            f'<div class="cyc-box{" cyc-here" if s == stage else ""}">{s}'
            f'{"<div class=\'cyc-here-tag\'>WE ARE HERE</div>" if s == stage else ""}</div>'
            + ("<div class='cyc-arrow'>&#8594;</div>" if idx < 3 else "")
            for idx, s in enumerate(stages)
        )

        summary_bits = []
        summary_bits.append(f"{c['key']} is at {fmt_usd(c.get('price'))}, {fmt_pct(c.get('pct_24h'))} on the day "
                             f"and {fmt_pct(c.get('pct_7d'))} over 7 days.")
        summary_bits.append(f"Price structure reads {price_struct_label.lower()}.")
        if c.get("sma200"):
            rel = "above" if (dist_sma200_pct or 0) >= 0 else "below"
            summary_bits.append(f"Price is {abs(dist_sma200_pct):.1f}% {rel} the 200-day average "
                                 f"({fmt_usd(c['sma200'])}), placing the cycle model in the {stage} stage.")
        summary_bits.append(f"Funding is {funding_label.lower()}; open interest is {oi_label.lower()}.")
        summary_bits.append(f"Sentiment (Fear & Greed proxy) reads {fng_label.lower()}.")
        summary = " ".join(summary_bits)

        stale_note = ""
        if c["stale"]:
            stale_note = (f'<div class="stale-note">&#9888; Live fetch failed for: {", ".join(c["stale"])} '
                          f'&mdash; showing last known value.</div>')

        rows = [
            ("Price Structure", "Blow-off move / vertical trend", price_struct_label, price_struct_status),
            ("Funding Rate", "Overheated longs / short squeeze", funding_label, funding_status),
            ("Open Interest (24h)", "Leverage buildup vs spot-led move", oi_label, oi_status),
            ("Futures Premium", "Mark vs index spread", premium_label, premium_status),
            ("Retail Sentiment", "Fear & Greed proxy for euphoria/panic", fng_label, fng_status),
            ("Liquidation Risk", "Crowded one-sided leverage (model estimate)", liq_label, liq_status),
            ("MVRV Z-Score", "Valuation overheating", "Unavailable – requires paid on-chain data", "locked"),
            ("NUPL", "Net unrealized profit/loss, euphoria zone", "Unavailable – requires paid on-chain data", "locked"),
            ("Exchange Inflow/Outflow", "Coins moving to/from exchanges", "Unavailable – requires paid on-chain data", "locked"),
            ("ETF Flows", "Sustained spot demand", "Unavailable – requires paid on-chain data", "locked"),
        ]
        rows_html = "\n".join(
            f'<tr><td>{i+1}</td><td>{name}</td><td class="watch">{watch}</td>'
            f'<td>{badge_html(status, read)}</td></tr>'
            for i, (name, watch, read, status) in enumerate(rows)
        )

        score_pct = (score / 10 * 100) if score is not None else 0
        score_display = f"{score}/10" if score is not None else "N/A"

        coin_alerts = [a for a in alerts_results if a["coin"] == c["key"]]
        if coin_alerts:
            alert_rows_html = "\n".join(
                f'<tr><td>{a["label"]}</td>'
                f'<td>{a["condition"].capitalize()} {fmt_usd(a["target"], 0)}</td>'
                f'<td>{fmt_pct(a["dist_pct"])} away</td>'
                f'<td><span class="badge {"alert-triggered" if a["triggered"] else "alert-armed"}">'
                f'{"🚨 TRIGGERED" if a["triggered"] else "Armed"}</span></td></tr>'
                for a in coin_alerts
            )
        else:
            alert_rows_html = ('<tr><td colspan="4" class="watch">No alerts configured for '
                                f'{c["key"]}.</td></tr>')

        alerts_card = f"""
  <div class="cycle-map" style="margin-bottom:20px;">
    <div class="card-title">🔔 PRICE ALERTS</div>
    <table class="signal-table" style="margin-top:10px; margin-bottom:0;">
      <thead><tr><th>Alert</th><th>Condition</th><th>Distance</th><th>Status</th></tr></thead>
      <tbody>{alert_rows_html}</tbody>
    </table>
    <div class="sub" style="margin-top:10px;">To add or edit alerts: edit <strong>data/alerts_config.json</strong> in the GitHub repo (web editor works fine), or run <strong>add_alert.py</strong> locally if you have this repo cloned.</div>
  </div>
"""

        def _pts_badge(pts):
            if pts > 0:
                return f'<span class="badge bullish">+{pts}</span>'
            if pts < 0:
                return f'<span class="badge bearish">{pts}</span>'
            return '<span class="badge neutral">0</span>'

        spot_rows_html = "\n".join(
            f'<tr><td>{name}</td><td class="watch">{reading}</td><td>{_pts_badge(pts)}</td></tr>'
            for name, reading, pts in spot_signal["rows"]
        )

        spot_signal_card = f"""
  <div class="cycle-map spot-signal-card spot-{spot_signal['status']}" style="margin-bottom:20px;">
    <div class="card-title">🎓 SPOT SIGNAL (educational, rule-based model)</div>
    <div class="spot-signal-headline">
      <div class="spot-signal-label {spot_signal['status']}">{spot_signal['label']}</div>
      <div class="spot-signal-score">Score: {spot_signal['score']:+d}</div>
    </div>
    <div class="screener-plain" style="margin-top:6px;">{spot_signal['plain']}</div>
    <table class="signal-table" style="margin-top:14px; margin-bottom:0;">
      <thead><tr><th>Factor</th><th>Current reading</th><th>Points</th></tr></thead>
      <tbody>{spot_rows_html}</tbody>
    </table>
    <details class="screener-details" style="margin-top:12px;">
      <summary>What do the score bands mean?</summary>
      <table class="signal-table score-legend" style="margin-top:10px; margin-bottom:0;">
        <thead><tr><th>Score range</th><th>Label</th><th>What it means</th></tr></thead>
        <tbody>
          <tr><td>&ge; +5</td><td><span class="badge bullish">🟢 ACCUMULATION ZONE</span></td><td class="watch">Strong historical buy-the-dip setup</td></tr>
          <tr><td>+2 to +4</td><td><span class="badge bullish">🟢 LEAN ACCUMULATE</span></td><td class="watch">Leans favorable, not a strong signal</td></tr>
          <tr><td>-1 to +1</td><td><span class="badge neutral">🟡 HOLD / NEUTRAL</span></td><td class="watch">No real edge either way</td></tr>
          <tr><td>-4 to -2</td><td><span class="badge bearish">🔴 CAUTION</span></td><td class="watch">Getting risky, hold off on new buys</td></tr>
          <tr><td>&le; -5</td><td><span class="badge bearish">🔴 DISTRIBUTION ZONE</span></td><td class="watch">Stretched/euphoric, historical selling zone</td></tr>
        </tbody>
      </table>
    </details>
    <div class="sub" style="margin-top:10px;">
      This is a transparent teaching model, not a trade instruction: it mechanically applies the course framework
      (contrarian sentiment, cycle stage, trend structure, distance from key levels) to today's numbers and shows its
      full reasoning above. It has not been backtested, carries no accuracy guarantee, and says nothing about
      leverage or timing &mdash; it only speaks to whether conditions resemble a historical spot accumulation or
      distribution zone. Education only, not financial advice.
    </div>
  </div>
"""

        trade_levels = compute_trade_levels(c)
        if trade_levels:
            pb, bo = trade_levels["pullback"], trade_levels["breakout"]
            trade_levels_card = f"""
  <div class="cycle-map trade-levels-card" style="margin-bottom:20px;">
    <div class="card-title">🎯 TRADE LEVELS (formula-based, educational)</div>
    <div class="sub" style="margin-bottom:12px;">
      Derived only from the 30-day support (~{fmt_usd(c.get('support_30d'), 0)}) and resistance
      (~{fmt_usd(c.get('resistance_30d'), 0)}) shown above. Two scenarios &mdash; pick whichever one
      actually happens, don't force either. <strong>Entry</strong> is where you'd consider buying,
      <strong>stop</strong> is where the idea is proven wrong and you exit, <strong>targets</strong> are
      where you'd take profit. This is arithmetic on today's levels, not a prediction &mdash; it has not
      been backtested and is not a recommendation to place any trade.
    </div>
    <div class="trade-scenarios">
      <div class="trade-scenario">
        <div class="trade-scenario-title">Scenario A &mdash; pulls back to support</div>
        <div class="kv"><span>Entry zone</span><span>{fmt_usd(pb['entry_low'], 2)} &ndash; {fmt_usd(pb['entry_high'], 2)}</span></div>
        <div class="kv"><span>Stop loss</span><span class="neg">{fmt_usd(pb['stop'], 2)} ({pb['risk_pct']:.1f}% below entry)</span></div>
        <div class="kv"><span>Target 1 (resistance)</span><span class="pos">{fmt_usd(pb['target1'], 2)}</span></div>
        <div class="kv"><span>Target 2 (2R)</span><span class="pos">{fmt_usd(pb['target2'], 2)}</span></div>
      </div>
      <div class="trade-scenario">
        <div class="trade-scenario-title">Scenario B &mdash; confirmed breakout above resistance</div>
        <div class="kv"><span>Entry</span><span>{fmt_usd(bo['entry'], 2)} (1% above resistance)</span></div>
        <div class="kv"><span>Stop loss</span><span class="neg">{fmt_usd(bo['stop'], 2)} ({bo['risk_pct']:.1f}% below entry)</span></div>
        <div class="kv"><span>Target 1 (1R)</span><span class="pos">{fmt_usd(bo['target1'], 2)}</span></div>
        <div class="kv"><span>Target 2 (2R)</span><span class="pos">{fmt_usd(bo['target2'], 2)}</span></div>
      </div>
    </div>
    <div class="sub" style="margin-top:12px;">
      Position size so the stop distance only costs 1-2% of your account &mdash; never the leverage, the position
      size is what controls your risk. If price is already above the pullback entry zone and below the breakout
      entry, this model isn't suggesting either scenario is live right now; wait for one to actually trigger.
    </div>
  </div>
"""
        else:
            trade_levels_card = ""

        panel = f"""
<div class="panel panel-{c['key'].lower()}">
  {stale_note}
  {spot_signal_card}
  {trade_levels_card}
  <div class="top-grid">
    <div class="card">
      <div class="card-title">PRICE ACTION</div>
      <div class="big-price">{fmt_usd(c.get('price'))}</div>
      <div class="sub">24h Range: {fmt_usd(c.get('low_24h'), 0)} &ndash; {fmt_usd(c.get('high_24h'), 0)}</div>
      <div class="kv"><span>24h</span><span class="{'pos' if (c.get('pct_24h') or 0) >= 0 else 'neg'}">{fmt_pct(c.get('pct_24h'))}</span></div>
      <div class="kv"><span>7d</span><span class="{'pos' if (c.get('pct_7d') or 0) >= 0 else 'neg'}">{fmt_pct(c.get('pct_7d'))}</span></div>
      <div class="kv"><span>30d</span><span class="{'pos' if (c.get('pct_30d') or 0) >= 0 else 'neg'}">{fmt_pct(c.get('pct_30d'))}</span></div>
      <div class="kv"><span>Key Support (30d)</span><span class="pos">{fmt_usd(c.get('support_30d'), 0)}</span></div>
      <div class="kv"><span>Key Resistance (30d)</span><span class="neg">{fmt_usd(c.get('resistance_30d'), 0)}</span></div>
    </div>
    <div class="card">
      <div class="card-title">CURRENT MARKET READ</div>
      <div class="read-text">{summary}</div>
    </div>
    <div class="card">
      <div class="card-title">TEKA HEAT SCORE (model estimate)</div>
      <div class="gauge-wrap">
        <div class="gauge-track"><div class="gauge-fill" style="width:{score_pct}%"></div></div>
        <div class="gauge-score">{score_display}</div>
      </div>
      <div class="sub">1 = fear/oversold &middot; 10 = euphoria/overheated</div>
    </div>
  </div>

  <table class="signal-table">
    <thead><tr><th>#</th><th>Signal</th><th>What it measures</th><th>Current Read</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>

  <div class="cycle-map" style="margin-bottom:20px;">
    <div class="card-title">CYCLE MAP (heuristic, price vs 50/200-day average)</div>
    <div class="cyc-row">{cycle_html}</div>
  </div>

  {alerts_card}
</div>
"""
        panels.append(panel)

    def _pts_badge2(pts):
        if pts > 0:
            return f'<span class="badge bullish">+{pts}</span>'
        if pts < 0:
            return f'<span class="badge bearish">{pts}</span>'
        return '<span class="badge neutral">0</span>'

    if screener_results:
        top_pick = screener_results[0]
        bottom_pick = screener_results[-1]

        def _screener_card(r, rank):
            tl = compute_trade_levels(r)
            if tl:
                pb, bo = tl["pullback"], tl["breakout"]
                trade_html = f"""
      <div class="screener-trade-grid">
        <div class="screener-trade">
          <div class="screener-trade-title">🎯 If it pulls back to support</div>
          <div class="kv"><span>Buy</span><span>{fmt_usd_adaptive(pb['entry_low'])}&ndash;{fmt_usd_adaptive(pb['entry_high'])}</span></div>
          <div class="kv"><span>Stop</span><span class="neg">{fmt_usd_adaptive(pb['stop'])}</span></div>
          <div class="kv"><span>Target</span><span class="pos">{fmt_usd_adaptive(pb['target1'])} / {fmt_usd_adaptive(pb['target2'])}</span></div>
        </div>
        <div class="screener-trade">
          <div class="screener-trade-title">🎯 If it breaks out above resistance</div>
          <div class="kv"><span>Buy</span><span>{fmt_usd_adaptive(bo['entry'])}</span></div>
          <div class="kv"><span>Stop</span><span class="neg">{fmt_usd_adaptive(bo['stop'])}</span></div>
          <div class="kv"><span>Target</span><span class="pos">{fmt_usd_adaptive(bo['target1'])} / {fmt_usd_adaptive(bo['target2'])}</span></div>
        </div>
      </div>"""
            else:
                trade_html = '<div class="screener-trade sub">Not enough range data yet for trade levels.</div>'

            reasoning_rows = "\n".join(
                f'<tr><td>{name}</td><td class="watch">{reading}</td><td>{_pts_badge2(pts)}</td></tr>'
                for name, reading, pts in r.get("rows", [])
            )
            reasoning_html = f"""
      <details class="screener-details">
        <summary>Why this score? ({len(r.get('rows', []))} factors)</summary>
        <table class="signal-table" style="margin-top:10px; margin-bottom:0;">
          <thead><tr><th>Factor</th><th>Current reading</th><th>Points</th></tr></thead>
          <tbody>{reasoning_rows}</tbody>
        </table>
      </details>""" if r.get("rows") else ""

            cached_tag = ' <span class="watch">&middot; cached</span>' if r.get("stale") else ""
            return f"""
    <div class="screener-card {r['status']}">
      <div class="screener-card-top">
        <div class="screener-rank">#{rank}</div>
        <div>
          <div class="screener-name">{r['name']} <span class="watch">({r['symbol']})</span>{cached_tag}</div>
          <div class="sub">{fmt_usd_adaptive(r['price'])} &middot; <span class="{'pos' if (r.get('pct_24h') or 0) >= 0 else 'neg'}">{fmt_pct(r.get('pct_24h'))}</span> 24h</div>
        </div>
      </div>
      <div class="screener-signal">
        <span class="badge {r['status']}">{r['label']}</span>
        <span class="sub">Score {_pts_badge2(r['score'])}</span>
      </div>
      <div class="screener-plain">{r.get('plain', '')}</div>
      {trade_html}
      {reasoning_html}
    </div>"""

        callouts_html = f"""
    <div class="top-grid" style="grid-template-columns:1fr 1fr; margin-bottom:20px;">
      <div class="card">
        <div class="card-title">🏆 CLOSEST TO ACCUMULATION ZONE</div>
        <div class="spot-signal-label bullish" style="font-size:19px;">{top_pick['name']} ({top_pick['symbol']})</div>
        <div class="sub">Score {top_pick['score']:+d} &middot; {fmt_usd_adaptive(top_pick['price'])} &middot; {top_pick['label']}</div>
      </div>
      <div class="card">
        <div class="card-title">⚠️ CLOSEST TO DISTRIBUTION ZONE</div>
        <div class="spot-signal-label bearish" style="font-size:19px;">{bottom_pick['name']} ({bottom_pick['symbol']})</div>
        <div class="sub">Score {bottom_pick['score']:+d} &middot; {fmt_usd_adaptive(bottom_pick['price'])} &middot; {bottom_pick['label']}</div>
      </div>
    </div>
"""
        screener_table_html = ('<div class="screener-grid">'
                                + "".join(_screener_card(r, i + 1) for i, r in enumerate(screener_results))
                                + '</div>')
    else:
        callouts_html = ""
        screener_table_html = ('<div class="stale-note">&#9888; Screener data unavailable this run '
                                '(fetch failed or rate-limited) &mdash; will retry next cycle.</div>')

    def _intraday_card(r, rank):
        t = r["trade"]
        reasoning_rows = "\n".join(
            f'<tr><td>{name}</td><td class="watch">{reading}</td><td>{_pts_badge2(pts)}</td></tr>'
            for name, reading, pts in r.get("rows", [])
        )
        return f"""
    <div class="screener-card {r['status']}">
      <div class="screener-card-top">
        <div class="screener-rank">#{rank}</div>
        <div>
          <div class="screener-name">{r['name']} <span class="watch">({r['symbol']})</span></div>
          <div class="sub">{fmt_usd_adaptive(r['price'])}</div>
        </div>
      </div>
      <div class="screener-signal">
        <span class="badge {r['status']}">{r['label']}</span>
        <span class="sub">Score {_pts_badge2(r['score'])}</span>
      </div>
      <div class="screener-plain">{r.get('plain', '')}</div>
      <div class="screener-trade">
        <div class="screener-trade-title">🎯 Buy the recent low, ATR-based stop</div>
        <div class="kv"><span>Buy</span><span>{fmt_usd_adaptive(t['entry'])}</span></div>
        <div class="kv"><span>Stop</span><span class="neg">{fmt_usd_adaptive(t['stop'])} ({t['risk_pct']:.1f}% below entry)</span></div>
        <div class="kv"><span>Target</span><span class="pos">{fmt_usd_adaptive(t['target1'])} / {fmt_usd_adaptive(t['target2'])}</span></div>
      </div>
      <details class="screener-details">
        <summary>Why this score? ({len(r.get('rows', []))} factors)</summary>
        <table class="signal-table" style="margin-top:10px; margin-bottom:0;">
          <thead><tr><th>Factor</th><th>Current reading</th><th>Points</th></tr></thead>
          <tbody>{reasoning_rows}</tbody>
        </table>
      </details>
    </div>"""

    def _intraday_panel_html(tf_key, tf_name, window_desc):
        results = intraday_results.get(tf_key, [])
        if not results:
            return (f'<div class="stale-note">&#9888; {tf_name} data unavailable this run '
                     '(no Binance-listed pairs matched, or fetch failed) &mdash; will retry next cycle.</div>')
        cards = "".join(_intraday_card(r, i + 1) for i, r in enumerate(results))
        return f"""
    <div class="sub" style="margin-bottom:14px;">
      {tf_name} setups from Binance's public {window_desc} candles &mdash; pure price-action model (no
      sentiment/cycle factors, those are daily concepts). Coins without a liquid Binance USDT pair are skipped.
      Buy/stop/target use each coin's own recent volatility (ATR), not a fixed percentage.
    </div>
    <div class="screener-grid">{cards}</div>"""

    intraday_15m_html = _intraday_panel_html("15m", "15-Minute", "15-minute")
    intraday_1h_html = _intraday_panel_html("1h", "1-Hour", "1-hour")
    daily_html = f"{callouts_html}{screener_table_html}"

    screener_panel = f"""
<div class="panel panel-screener">
  <div class="cycle-map spot-signal-card" style="margin-bottom:20px;">
    <div class="card-title">🔍 COIN SCREENER (educational, rule-based ranking)</div>
    <div class="sub">
      Scans the top {SCREENER_SIZE} coins by market cap (excluding stablecoins and BTC/ETH wrappers).
      Pick a timeframe below &mdash; each uses a model suited to that horizon, not the same numbers just relabeled.
      This is <strong>not a recommendation to trade any coin listed</strong>: small/mid-cap coins carry far higher
      risk than BTC/ETH, none of this is backtested, and a high score means "resembles a historically favorable
      setup by this simple rule set" &mdash; nothing more. Education only, not financial advice.
    </div>
    <table class="signal-table score-legend" style="margin-top:14px; margin-bottom:0;">
      <thead><tr><th>Score range</th><th>Label</th><th>What it means</th></tr></thead>
      <tbody>
        <tr><td>&ge; +5</td><td><span class="badge bullish">🟢 ACCUMULATION ZONE</span></td><td class="watch">Strong historical buy-the-dip setup</td></tr>
        <tr><td>+2 to +4</td><td><span class="badge bullish">🟢 LEAN ACCUMULATE</span></td><td class="watch">Leans favorable, not a strong signal</td></tr>
        <tr><td>-1 to +1</td><td><span class="badge neutral">🟡 HOLD / NEUTRAL</span></td><td class="watch">No real edge either way</td></tr>
        <tr><td>-4 to -2</td><td><span class="badge bearish">🔴 CAUTION</span></td><td class="watch">Getting risky, hold off on new buys</td></tr>
        <tr><td>&le; -5</td><td><span class="badge bearish">🔴 DISTRIBUTION ZONE</span></td><td class="watch">Stretched/euphoric, historical selling zone</td></tr>
      </tbody>
    </table>
  </div>

  <input type="radio" name="tf" id="tf-15m">
  <input type="radio" name="tf" id="tf-1h">
  <input type="radio" name="tf" id="tf-1d" checked>
  <div class="tabbar" style="padding-left:0;">
    <label for="tf-15m">⏱ 15 Min</label>
    <label for="tf-1h">🕐 1 Hour</label>
    <label for="tf-1d">📅 1 Day</label>
  </div>
  <div class="tf-panel tf-panel-15m">{intraday_15m_html}</div>
  <div class="tf-panel tf-panel-1h">{intraday_1h_html}</div>
  <div class="tf-panel tf-panel-1d">{daily_html}</div>
</div>
"""

    fng_top = f"{fng_value} ({fng_classification})" if fng_value is not None else "N/A"

    glance_cards = []
    for c in coins_data:
        sig = spot_signals_by_coin.get(c["key"])
        if sig:
            glance_cards.append(f"""
    <div class="glance-card {sig['status']}">
      <div class="glance-coin">{c['emoji']} {c['key']}</div>
      <div class="glance-verdict">{sig['label']}</div>
      <div class="glance-plain">{sig['plain']}</div>
    </div>""")
    if screener_results:
        top_pick, bottom_pick = screener_results[0], screener_results[-1]
        glance_cards.append(f"""
    <div class="glance-card {top_pick['status']}">
      <div class="glance-coin">🏆 Best of {len(screener_results)} scanned</div>
      <div class="glance-verdict">{top_pick['name']} ({top_pick['symbol']}) {top_pick['label']}</div>
      <div class="glance-plain">{top_pick['plain']}</div>
    </div>""")
        glance_cards.append(f"""
    <div class="glance-card {bottom_pick['status']}">
      <div class="glance-coin">⚠️ Worst of {len(screener_results)} scanned</div>
      <div class="glance-verdict">{bottom_pick['name']} ({bottom_pick['symbol']}) {bottom_pick['label']}</div>
      <div class="glance-plain">{bottom_pick['plain']}</div>
    </div>""")
    glance_html = f"""
<div class="glance-bar">
  <div class="glance-title">AT A GLANCE &mdash; no clicking required</div>
  <div class="glance-row">{"".join(glance_cards)}</div>
  <div class="glance-footnote">Educational rule-based model, not financial advice. Full reasoning for each verdict is on its tab below.</div>
</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Teka Live Dashboard</title>
<style>
  :root {{
    --bg: #0a0e14; --panel: #10151f; --border: #1f2937; --text: #e5e7eb; --muted: #9ca3af;
    --green: #34d399; --red: #f87171; --yellow: #fbbf24; --gray: #6b7280; --accent: #38bdf8;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background: var(--bg); color: var(--text); font-family: 'Segoe UI', Arial, sans-serif; }}
  header {{ padding: 20px 24px; border-bottom: 1px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; }}
  header h1 {{ margin:0; font-size: 22px; letter-spacing: 1px; }}
  header .meta {{ color: var(--muted); font-size: 13px; }}
  .tabbar {{ display:flex; gap:8px; padding: 12px 24px; }}
  .tabbar label {{ padding:8px 20px; border:1px solid var(--border); border-radius:8px; cursor:pointer; color:var(--muted); font-weight:600; }}
  input[type=radio] {{ display:none; }}
  #tab-btc:checked ~ .tabbar label[for=tab-btc],
  #tab-eth:checked ~ .tabbar label[for=tab-eth],
  #tab-screener:checked ~ .tabbar label[for=tab-screener] {{ background: var(--accent); color:#04121c; border-color:var(--accent); }}
  .panel {{ display:none; padding: 8px 24px 32px; }}
  #tab-btc:checked ~ .panel-btc {{ display:block; }}
  #tab-eth:checked ~ .panel-eth {{ display:block; }}
  #tab-screener:checked ~ .panel-screener {{ display:block; }}
  .tf-panel {{ display:none; }}
  #tf-15m:checked ~ .tf-panel-15m {{ display:block; }}
  #tf-1h:checked ~ .tf-panel-1h {{ display:block; }}
  #tf-1d:checked ~ .tf-panel-1d {{ display:block; }}
  #tf-15m:checked ~ .tabbar label[for=tf-15m],
  #tf-1h:checked ~ .tabbar label[for=tf-1h],
  #tf-1d:checked ~ .tabbar label[for=tf-1d] {{ background: var(--accent); color:#04121c; border-color:var(--accent); }}
  .stale-note {{ background:#3f2d0f; border:1px solid #8a5a00; color:#fbbf24; padding:8px 12px; border-radius:8px; margin-bottom:16px; font-size:13px; }}
  .top-grid {{ display:grid; grid-template-columns: 1.1fr 1.3fr 1fr; gap:16px; margin-bottom: 20px; }}
  .card {{ background: var(--panel); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }}
  .card-title {{ font-size:12px; color:var(--muted); letter-spacing:1px; margin-bottom:10px; font-weight:700; }}
  .big-price {{ font-size:30px; font-weight:800; color: var(--green); }}
  .sub {{ font-size:12px; color:var(--muted); margin-top:4px; }}
  .kv {{ display:flex; justify-content:space-between; font-size:13px; padding:4px 0; border-top:1px solid var(--border); margin-top:6px; }}
  .pos {{ color: var(--green); font-weight:700; }}
  .neg {{ color: var(--red); font-weight:700; }}
  .read-text {{ font-size:13.5px; line-height:1.6; color: var(--text); }}
  .gauge-wrap {{ display:flex; align-items:center; gap:12px; margin-top:8px; }}
  .gauge-track {{ flex:1; height:10px; border-radius:6px; background: linear-gradient(90deg,#22c55e,#fbbf24,#f87171); opacity:0.35; position:relative; overflow:hidden; }}
  .gauge-fill {{ position:absolute; left:0; top:0; bottom:0; background: linear-gradient(90deg,#22c55e,#fbbf24,#f87171); opacity:1; }}
  .gauge-score {{ font-size:20px; font-weight:800; color: var(--accent); min-width:52px; text-align:right; }}
  table.signal-table {{ width:100%; border-collapse: collapse; background: var(--panel); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin-bottom:24px; }}
  table.signal-table th {{ text-align:left; font-size:11px; color:var(--muted); letter-spacing:1px; padding:12px 14px; border-bottom:1px solid var(--border); }}
  table.signal-table td {{ padding:12px 14px; border-bottom:1px solid var(--border); font-size:13.5px; }}
  table.signal-table td.watch {{ color: var(--muted); font-size:12.5px; }}
  table.signal-table tr:last-child td {{ border-bottom:none; }}
  .badge {{ padding:4px 10px; border-radius:20px; font-size:12.5px; font-weight:700; display:inline-block; }}
  .badge.bullish {{ background:#0f2e20; color: var(--green); }}
  .badge.bearish {{ background:#3a1414; color: var(--red); }}
  .badge.neutral {{ background:#332b0d; color: var(--yellow); }}
  .badge.locked  {{ background:#1c2230; color: var(--gray); }}
  .badge.alert-armed {{ background:#182233; color: var(--accent); }}
  .badge.alert-triggered {{ background:#4a1010; color:#fff; animation: pulse 1.4s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.55; }} }}
  .alert-banner {{ margin: 14px 24px 0; padding: 12px 18px; background:#3a0d0d; border:1px solid #ef4444; border-radius:10px; color:#fecaca; font-weight:700; font-size:13.5px; animation: pulse 1.6s infinite; }}
  .alert-banner-item {{ padding: 2px 0; }}
  .glance-bar {{ margin: 16px 24px 0; padding: 16px 20px; background: var(--panel); border:2px solid var(--border); border-radius:14px; }}
  .glance-title {{ font-size:11px; color:var(--muted); letter-spacing:1.5px; font-weight:800; margin-bottom:12px; }}
  .glance-row {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:14px; }}
  .glance-card {{ border-radius:10px; padding:14px 16px; border:2px solid var(--border); background:#0d1320; }}
  .glance-card.bullish {{ border-color:#1f6a4a; background:#0d1c15; }}
  .glance-card.bearish {{ border-color:#7a2e2e; background:#1c0f0f; }}
  .glance-card.neutral {{ border-color:#5a4d18; background:#1c1810; }}
  .glance-coin {{ font-size:12px; color:var(--muted); font-weight:700; letter-spacing:0.5px; margin-bottom:4px; }}
  .glance-verdict {{ font-size:16px; font-weight:800; margin-bottom:6px; }}
  .glance-plain {{ font-size:12.5px; color:var(--text); line-height:1.5; }}
  .glance-footnote {{ font-size:11px; color:var(--muted); margin-top:12px; }}
  @media (max-width: 700px) {{ .glance-row {{ grid-template-columns: 1fr; }} }}
  .cycle-map {{ background: var(--panel); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }}
  .spot-signal-card {{ border-width:2px; }}
  .spot-signal-card.spot-bullish {{ border-color:#1f6a4a; }}
  .spot-signal-card.spot-bearish {{ border-color:#7a2e2e; }}
  .spot-signal-card.spot-neutral {{ border-color:#5a4d18; }}
  .spot-signal-headline {{ display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-top:4px; }}
  .spot-signal-label {{ font-size:22px; font-weight:800; letter-spacing:0.5px; }}
  .spot-signal-label.bullish {{ color: var(--green); }}
  .spot-signal-label.bearish {{ color: var(--red); }}
  .spot-signal-label.neutral {{ color: var(--yellow); }}
  .spot-signal-score {{ font-size:13px; color: var(--muted); font-weight:700; }}
  .trade-levels-card {{ border-width:2px; border-color:#2a4a5a; }}
  .trade-scenarios {{ display:grid; grid-template-columns: 1fr 1fr; gap:16px; }}
  .trade-scenario {{ background:#0d1320; border:1px solid var(--border); border-radius:10px; padding:14px 16px; }}
  .trade-scenario-title {{ font-size:13px; font-weight:800; color: var(--accent); margin-bottom:10px; }}
  @media (max-width: 700px) {{ .trade-scenarios {{ grid-template-columns: 1fr; }} }}
  .screener-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:16px; }}
  .screener-card {{ background: var(--panel); border:2px solid var(--border); border-radius:12px; padding:16px; }}
  .screener-card.bullish {{ border-color:#1f6a4a; }}
  .screener-card.bearish {{ border-color:#7a2e2e; }}
  .screener-card.neutral {{ border-color:#5a4d18; }}
  .screener-card-top {{ display:flex; gap:10px; align-items:flex-start; margin-bottom:10px; }}
  .screener-rank {{ font-size:12px; font-weight:800; color: var(--muted); background:#0d1320; border-radius:6px; padding:3px 8px; white-space:nowrap; }}
  .screener-name {{ font-size:15px; font-weight:800; }}
  .screener-signal {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }}
  .screener-trade {{ background:#0d1320; border:1px solid var(--border); border-radius:8px; padding:10px 12px; }}
  .screener-trade-title {{ font-size:12px; font-weight:800; color: var(--accent); margin-bottom:6px; }}
  .screener-trade-grid {{ display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:10px; }}
  .screener-plain {{ font-size:12.5px; color: var(--text); line-height:1.5; margin-bottom:10px; }}
  .screener-details {{ font-size:12.5px; }}
  .screener-details summary {{ cursor:pointer; color: var(--accent); font-weight:700; padding:4px 0; }}
  .score-legend th, .score-legend td {{ font-size:12px; padding:8px 12px; }}
  @media (max-width: 480px) {{ .screener-trade-grid {{ grid-template-columns: 1fr; }} }}
  .cyc-row {{ display:flex; align-items:center; gap:6px; margin-top:10px; }}
  .cyc-box {{ flex:1; text-align:center; padding:14px 8px; border-radius:8px; border:1px solid var(--border); color:var(--muted); font-size:13px; font-weight:700; position:relative; }}
  .cyc-here {{ border-color: var(--accent); color: var(--accent); background:#0d1c26; }}
  .cyc-here-tag {{ position:absolute; bottom:-22px; left:0; right:0; font-size:10px; color:var(--accent); letter-spacing:1px; }}
  .cyc-arrow {{ color: var(--muted); font-size:16px; }}
  footer {{ padding: 18px 24px; color: var(--muted); font-size: 11.5px; border-top:1px solid var(--border); line-height:1.6; }}
  @media (max-width: 900px) {{ .top-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
  <h1>&#9889; TEKA LIVE DASHBOARD</h1>
  <div class="meta">Market Fear &amp; Greed: {fng_top} &nbsp;|&nbsp; Generated: {generated_at} UTC
    (<span id="updated-ago">just now</span>) &nbsp;|&nbsp; Data regenerated {DATA_REFRESH_LABEL}</div>
</header>
{glance_html}
{banner_html}
{tabs_inputs}
<div class="tabbar">{tabs_labels}</div>
{"".join(panels)}
{screener_panel}
<footer>
  Data sources: CoinGecko (price/market), Binance Futures public API (funding rate, open interest, mark/index premium), Alternative.me (Fear &amp; Greed Index). No paid subscriptions used.<br>
  Rows marked <strong>Unavailable</strong> (MVRV Z-Score, NUPL, exchange flows, ETF flows) require a paid on-chain data provider (e.g. Glassnode, CryptoQuant, Coinglass) that is not connected to this dashboard.<br>
  Cycle Map, Heat Score, and Liquidation Risk are Teka's own heuristic models built from the numbers above &mdash; not the output of a proprietary or third-party analytics service.<br>
  Education only, not financial advice. You trade at your own risk.
</footer>
<script>
(function() {{
  var generatedAt = new Date("{generated_at_iso}");
  function tick() {{
    var mins = Math.max(0, Math.round((Date.now() - generatedAt.getTime()) / 60000));
    var el = document.getElementById('updated-ago');
    if (el) el.textContent = mins <= 0 ? 'just now' : ('updated ' + mins + 'm ago');
  }}
  tick();
  setInterval(tick, 15000);
  // Cache-busting reload: a plain meta-refresh can be served from browser/CDN cache and
  // silently show stale content. Appending a unique query string forces a real network fetch.
  setTimeout(function() {{
    location.href = location.pathname + '?t=' + Date.now();
  }}, {REFRESH_SECONDS * 1000});
}})();
</script>
</body>
</html>
"""
    return html


def main():
    log("--- run start ---")
    state = load_state()
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    markets, err_m = safe_fetch("coingecko markets", fetch_coingecko_markets)

    fng_data, err_f = safe_fetch("fear_greed", fetch_fng)
    fng_value = fng_classification = None
    if fng_data:
        fng_value = int(fng_data[0]["value"])
        fng_classification = fng_data[0]["value_classification"]
    else:
        fng_value = state.get("_fng_value")
        fng_classification = state.get("_fng_classification")

    coins_data = []
    any_stale = False
    for coin in COINS:
        cd = build_coin_data(coin, markets or {}, fng_value, fng_classification, state)
        if cd["stale"]:
            any_stale = True
        coins_data.append(cd)

    alerts_config = load_alerts_config()
    if alerts_config is None:
        alerts_config = seed_default_alerts(coins_data)
        save_alerts_config(alerts_config)
        log("Seeded default alerts_config.json from initial 30d support/resistance levels")

    prev_alerts_state = state.get("_alerts_state", {})
    alerts_results, new_alerts_state, newly_triggered = evaluate_alerts(
        coins_data, alerts_config, prev_alerts_state, generated_at)
    if newly_triggered:
        log(f"ALERTS NEWLY TRIGGERED: {[a['id'] for a in newly_triggered]}")
        fire_toast_notifications(newly_triggered)

    log(f"Running screener over top {SCREENER_SIZE} coins by market cap...")
    screener_markets, _ = safe_fetch("screener markets", fetch_screener_markets)
    prev_screener_state = state.get("_screener", {})
    screener_results, new_screener_state = build_screener(
        fng_value, prev_screener_state, generated_at, markets=screener_markets)
    log(f"Screener produced {len(screener_results)} ranked coins "
        f"({sum(1 for r in screener_results if r.get('stale'))} cached/stale)")

    log("Running intraday screeners (15m, 1h) via Binance spot klines...")
    intraday_results = {}
    for tf_key in INTRADAY_TIMEFRAMES:
        intraday_results[tf_key] = build_intraday_screener(screener_markets, tf_key)
        log(f"Intraday {tf_key} produced {len(intraday_results[tf_key])} ranked coins")

    html = render(coins_data, fng_value, fng_classification, generated_at, any_stale,
                   alerts_results, screener_results, intraday_results)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    new_state = {"_fng_value": fng_value, "_fng_classification": fng_classification,
                 "_alerts_state": new_alerts_state, "_screener": new_screener_state}
    for cd in coins_data:
        new_state[cd["key"]] = {k: v for k, v in cd.items() if k != "stale"}
    save_state(new_state)

    log(f"--- run ok, wrote {OUTPUT_PATH} ---")


if __name__ == "__main__":
    main()
