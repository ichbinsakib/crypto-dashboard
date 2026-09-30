"""4h Trend Breakout tier - the opposite of the dip-buy scanner.

The dip scanner needs price near the bottom of its range, so it stays silent in a rally. This tier looks for a coin
that has just closed above its 55-candle (4h) high while trading above its 200-candle average, and rides it with a
chandelier trailing stop (no fixed target). It is tracked separately (own win/loss record and cooldown) so its real
results can be judged on their own. Nothing here changes the dip scanner. Educational, not advice.

An earlier 15-minute / 1-hour breakout rule (compute_momentum_signal) ran alongside this one; it was retired for
being about break-even after fees and removed once its last open calls resolved -- see git history if it is ever
worth revisiting."""

MOMENTUM_TIMEFRAMES = {
    # slow trend-following breakout: the only rule that stayed (barely) positive out-of-sample in backtest/run.py
    "4h": {"interval": "4h", "lookback": 55, "limit": 320, "window_label": "last ~9 days", "kind": "trend"},
}
# how long the 4h trend rule held trades in the 2-year backtest (782 trades, backtest/hold.py), in hours
TREND_HOLD_HOURS = {"p25": 56, "median": 92, "p75": 148, "loser_median": 64, "winner_median": 156}
TREND_STOP_ATR = 4.0       # chandelier trailing stop: highest high since entry minus 4 ATR (no fixed target)
TREND_EMA = 200            # only take breakouts above the 200-candle average
TREND_MAX_AGE_MIN = 60     # enter only shortly after the breakout candle closed (the backtest entered at the next open)
FEE_PCT = 0.2              # round-trip, same as the dip model
TREND_COOL_HOURS = 48      # no re-signal on the same coin for this long after a loss
TREND_EXPIRY_HOURS = 1600  # how long a call may run before it counts as expired (also the loss cooldown)


def _atr_series(klines, n=14):
    tr = [float(klines[0][2]) - float(klines[0][3])]
    for i in range(1, len(klines)):
        h, l, pc = float(klines[i][2]), float(klines[i][3]), float(klines[i - 1][4])
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    k, e, out = 2 / (n + 1), tr[0], []
    for x in tr:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def _ema_last(vals, n):
    k, e = 2 / (n + 1), vals[0]
    for x in vals:
        e = x * k + e * (1 - k)
    return e


def compute_trend_signal(klines, lookback, window_label="", now_ms=None, direction="LONG"):
    """4h breakout beyond the prior `lookback`-candle high/low while on the right side of the
    200-candle average -- above it for LONG, below it for SHORT (every rule mirrors exactly, sign-
    flipped). The last row is the still-forming candle: the signal uses the last CLOSED candle and
    only fires within TREND_MAX_AGE_MIN of its close."""
    if not klines or len(klines) < TREND_EMA + 30:
        return None
    s = 1 if direction == "LONG" else -1
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    closed, forming = klines[:-1], klines[-1]
    age_min = (now_ms - float(forming[0])) / 60000
    extreme = [float(k[2] if s > 0 else k[3]) for k in closed]   # highs for LONG, lows for SHORT
    c = [float(k[4]) for k in closed]
    atr = _atr_series(closed)[-1]
    price = float(forming[4])
    if not atr or price <= 0:
        return None
    level = (max if s > 0 else min)(extreme[-lookback - 1:-1])
    checks = {"breakout": (c[-1] - level) * s > 0, "above_ema200": (c[-1] - _ema_last(c, TREND_EMA)) * s > 0,
              "fresh": 0 <= age_min <= TREND_MAX_AGE_MIN}
    failed = [k for k, ok in checks.items() if not ok]
    out = {"status": "momentum" if not failed else "none", "checks": checks, "failed": failed, "price": price, "breakout_level": level,
           "atr": atr, "window_label": window_label, "score": len(checks) - len(failed), "kind": "trend", "direction": direction,
           "label": f"TREND BREAKOUT {direction} (experimental)" if not failed else "No trend setup"}
    if not failed:
        stop = price - s * TREND_STOP_ATR * atr
        out["trade"] = {"entry": price, "stop": stop, "target1": None, "target2": None, "riskPct": abs(price - stop) / price * 100,
                        "target1NetPct": None, "target2NetPct": None}
        word = "high" if s > 0 else "low"
        out["reasons"] = [f"Closed {'above' if s > 0 else 'below'} the prior {lookback}-candle (4h) {word} {level:.6g}",
                          f"{'Above' if s > 0 else 'Below'} the 200-candle average"]
    return out


# ---------------- scanning, tracking, display ----------------
import datetime
import math
import random
import time


def price_text(v):
    """Price with enough digits to tell entry, stop and target apart, including sub-cent coins (SHIB, PEPE...)."""
    if v is None:
        return "n/a"
    if v >= 1000:
        return f"${v:,.0f}"
    if v >= 1:
        return f"${v:,.2f}"
    decimals = min(10, max(4, 2 - math.floor(math.log10(abs(v)))))
    return f"${v:.{decimals}f}"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


MAX_OPEN_PER_TF = 5
MAX_ATTEMPTS = 40
RETENTION_DAYS = 120   # same reach as the dip tracker so Performance can show both over the same windows


def scan(pool, tf_key, fetch_ohlc, skip_symbols=(), max_new=MAX_OPEN_PER_TF, attempts=MAX_ATTEMPTS, sleep=0.15, pinned=(), allow_short=False):
    """Look through the coin pool and return coins that currently qualify. `pinned` symbols are
    always checked first, outside the random draw and its `attempts` budget -- and regardless of
    whether they're even in `pool` this run -- so a coin an admin cares about can't be missed just
    because the random rotation never landed on it. Real breakouts on QNT and MOVR were each
    confirmed after the fact to have passed every check; neither was ever scanned.

    `allow_short` also checks each candidate for a downside breakout (mirrors the long rule exactly,
    sign-flipped) when it doesn't qualify long -- off by default until validated against history."""
    cfg = MOMENTUM_TIMEFRAMES[tf_key]
    skip = {str(s).upper() for s in skip_symbols}
    pool = pool or []
    name_by_symbol = {}
    for m in pool:
        sym = (m.get("symbol") or "").upper()
        if sym and sym not in name_by_symbol:
            name_by_symbol[sym] = m.get("name") or sym

    def _check(sym, name):
        try:
            klines = fetch_ohlc(sym, cfg["interval"], cfg["limit"]) if cfg.get("limit") else fetch_ohlc(sym, cfg["interval"])
        except Exception:                                    # no liquid Binance pair: skip quietly
            return None
        finally:
            time.sleep(sleep)
        for direction in (("LONG", "SHORT") if allow_short else ("LONG",)):
            sig = compute_trend_signal(klines, cfg["lookback"], cfg["window_label"], direction=direction)
            if sig and sig["status"] == "momentum":
                sig.update(symbol=sym, name=name, tf=tf_key)
                return sig
        return None

    found, checked = [], set()
    for sym in (str(s).upper() for s in pinned if s):
        if len(found) >= max_new or sym in skip or sym in checked:
            continue
        checked.add(sym)
        sig = _check(sym, name_by_symbol.get(sym, sym))
        if sig:
            found.append(sig)

    cands = [m for m in pool if (m.get("symbol") or "").upper() not in skip and (m.get("symbol") or "").upper() not in checked]
    random.shuffle(cands)
    tried = 0
    for m in cands:
        if len(found) >= max_new or tried >= attempts:
            break
        sym = (m.get("symbol") or "").upper()
        if not sym:
            continue
        tried += 1
        sig = _check(sym, m.get("name") or sym)
        if sig:
            found.append(sig)
    return found


def cooling(resolved, now=None):
    """{"tf:COIN"} that lost or expired recently and must not be re-signalled yet."""
    now = now or _now()
    out = set()
    for r in resolved:
        if r["result"] in ("loss", "expired"):
            until = datetime.datetime.fromisoformat(r["resolved_at"]) + datetime.timedelta(hours=TREND_COOL_HOURS)
            if until > now:
                out.add(f"{r['tf']}:{r['coin']}")
    return out


def update_tracker(prev, new_signals, fetch_ohlc, now=None, sleep=0.15):
    """-> (state, newly_opened, newly_resolved). Resolution walks the candles since the call opened, so a spike or
    dip between two runs is not missed; if one candle touches both stop and target the stop counts (conservative)."""
    now = now or _now()
    prev = prev or {}
    resolved = list(prev.get("resolved", []))
    still_open, newly_resolved = {}, []
    for key, pos in prev.get("open", {}).items():
        try:
            cfg = MOMENTUM_TIMEFRAMES[pos["tf"]]
            klines = fetch_ohlc(pos["coin"], cfg["interval"], cfg["limit"]) if cfg.get("limit") else fetch_ohlc(pos["coin"], cfg["interval"])
        except Exception:
            still_open[key] = pos                           # could not check: leave open, retry next run
            continue
        finally:
            time.sleep(sleep)
        opened = datetime.datetime.fromisoformat(pos["opened_at"])
        opened_ms = opened.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
        result, exit_p = None, None
        sgn = 1 if pos.get("direction", "LONG") == "LONG" else -1
        # the trailing stop is re-walked from the initial stop every run (it only ratchets toward
        # profit, never back), so an earlier adverse wick can't fake a stop-out
        atrs = _atr_series(klines)
        stop, best = pos.get("stop0", pos["stop"]), pos["entry"]
        for k, a in zip(klines, atrs):
            if float(k[0]) + 1 < opened_ms:
                continue
            o, hi, lo = float(k[1]), float(k[2]), float(k[3])
            adv_x, fav_x = (lo, hi) if sgn > 0 else (hi, lo)   # worst / best price of the candle for this direction
            if (adv_x - stop) * sgn <= 0:
                exit_p = stop if (o - stop) * sgn > 0 else o
                result = "win" if (exit_p / pos["entry"] - 1) * 100 * sgn - FEE_PCT > 0 else "loss"
                break
            best = max(best, fav_x) if sgn > 0 else min(best, fav_x)
            stop = max(stop, best - sgn * TREND_STOP_ATR * a) if sgn > 0 else min(stop, best - sgn * TREND_STOP_ATR * a)
        pos = {**pos, "stop": stop}
        if result is None and (now - opened).total_seconds() / 3600 >= TREND_EXPIRY_HOURS:
            result, exit_p = "expired", float(klines[-1][4])
        if result:
            row = {**pos, "result": result, "resolved_at": now.isoformat(), "exit_price": exit_p}
            resolved.append(row)
            newly_resolved.append(row)
        else:
            still_open[key] = pos
    cool = cooling(resolved, now)
    newly_opened = []
    for s in new_signals or []:
        key = f"{s['tf']}:{s['symbol']}"
        if key in still_open or key in cool:
            continue
        t = s["trade"]
        pos = {"coin": s["symbol"], "name": s.get("name") or s["symbol"], "tf": s["tf"], "direction": s.get("direction", "LONG"),
               "entry": t["entry"], "stop": t["stop"], "target1": t["target1"], "target2": t["target2"], "net1": t["target1NetPct"],
               "opened_at": now.isoformat(), "net2": t.get("target2NetPct"), "risk_pct": t.get("riskPct"),
               "why": [k for k, ok in (s.get("checks") or {}).items() if ok]}
        if s.get("kind") == "trend":
            pos.update(kind="trend", atr=s.get("atr"), stop0=t["stop"])
        still_open[key] = pos
        newly_opened.append(pos)
    cutoff = now - datetime.timedelta(days=RETENTION_DAYS)
    resolved = [r for r in resolved if datetime.datetime.fromisoformat(r["resolved_at"]) >= cutoff]
    return {"open": still_open, "resolved": resolved}, newly_opened, newly_resolved


def stats(resolved):
    wins = sum(1 for r in resolved if r["result"] == "win")
    losses = sum(1 for r in resolved if r["result"] == "loss")
    expired = sum(1 for r in resolved if r["result"] == "expired")
    nets = [(r["exit_price"] - r["entry"]) / r["entry"] * 100 * (1 if r.get("direction", "LONG") == "LONG" else -1) - FEE_PCT for r in resolved]
    return {"wins": wins, "losses": losses, "expired": expired, "n": len(resolved),
            "win_rate": wins / (wins + losses) * 100 if wins + losses else None,
            "avg_net": sum(nets) / len(nets) if nets else None}


def notification_events(opened, resolved_rows, fmt_price=None):
    fmt_price = fmt_price or price_text
    ev = []
    for p in opened:
        ev.append({"id": f"momentum:{p['tf']}:{p['coin']}:{p['opened_at']}", "ts": p["opened_at"], "type": "signal",
                   "title": f"\U0001F680 Momentum signal (experimental): {p['coin']} ({p['tf']})",
                   "body": f"4h trend breakout entry {fmt_price(p['entry'])}, trailing stop {p.get('risk_pct') or 0:.1f}% below the high (starts {fmt_price(p['stop'])}), no fixed target",
                   "portion_key": "screener"})
    for r in resolved_rows:
        emoji = {"win": "✅", "loss": "\U0001F6D1", "expired": "⏱"}.get(r["result"], "")
        ev.append({"id": f"mresult:{r['coin']}:{r['tf']}:{r['opened_at']}", "ts": r["resolved_at"], "type": r["result"],
                   "title": f"{emoji} Momentum {r['coin']} ({r['tf']}) {r['result'].upper()}",
                   "body": f"Exit {fmt_price(r['exit_price'])} vs. entry {fmt_price(r['entry'])}", "portion_key": "performance"})
    return ev
