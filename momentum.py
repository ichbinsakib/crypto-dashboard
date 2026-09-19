"""EXPERIMENTAL momentum / breakout tier - the opposite of the dip-buy scanner.

The dip scanner needs price near the bottom of its range, so it stays silent in a rally. This tier looks for coins
that have just broken to a new short-term high with the trend, volume and structure behind them, and that are not yet
stretched. It is tracked separately (own win/loss record and cooldown) so its real results can be judged on their own.
Nothing here changes the dip scanner. Educational, not advice."""
from brain import patterns as P
from brain import wyckoff as W

MOMENTUM_TIMEFRAMES = {
    "15m": {"interval": "15m", "lookback": 30, "window_label": "last ~7.5 hours"},
    "1h": {"interval": "1h", "lookback": 24, "window_label": "last 24 hours"},
}
TARGET_ATR = 1.5           # same geometry as the dip model so results are comparable
TARGET2_ATR = 3.0
STOP_ATR = 1.0
MAX_CHASE_ATR = 1.0        # entry must be within this many ATR of the breakout level, or it is chasing
VOLUME_MULTIPLE = 1.3      # recent volume vs the prior 20 candles
FEE_PCT = 0.2              # round-trip, same as the dip model
MIN_NET_PCT = 0.15         # target must clear fees by this much (matches MIN_NET_PROFIT_PCT)


def compute_momentum_signal(klines, lookback, window_label=""):
    """-> dict with status 'momentum' (+ trade levels, checks) or status 'none' with the failed checks; None if too little data."""
    if not klines or len(klines) < max(lookback + 5, 55):
        return None
    h = [float(k[2]) for k in klines]
    c = [float(k[4]) for k in klines]
    v = [float(k[5]) for k in klines]
    atr = P.atr(klines)
    if not atr or c[-1] <= 0:
        return None
    price = c[-1]
    level = max(h[-lookback - 1:-1])                          # highest high of the previous `lookback` candles
    checks = {}

    checks["breakout"] = price > level
    checks["fresh"] = 0 <= price - level <= MAX_CHASE_ATR * atr and all(x <= level for x in c[-4:-1])   # just broke, not run away
    ema = P.ema_bias(klines)
    checks["trend"] = bool(ema and ema["bias"] == "bull" and ema["above_20"])
    base = sum(v[-24:-4]) / 20 or 0
    checks["volume"] = base > 0 and sum(v[-3:]) / 3 >= VOLUME_MULTIPLE * base
    para = P.parabolic(klines)
    checks["not_parabolic"] = not para["parabolic"]
    wy = W.detect_distribution(klines)
    checks["not_distribution"] = not (wy["stage"] in ("utad", "sow", "lpsy") and wy["confidence"] != "LOW")

    stop, target1, target2 = price - STOP_ATR * atr, price + TARGET_ATR * atr, price + TARGET2_ATR * atr
    net1 = (target1 - price) / price * 100 - FEE_PCT
    checks["fee_ok"] = net1 >= MIN_NET_PCT

    failed = [k for k, ok in checks.items() if not ok]
    out = {"status": "momentum" if not failed else "none", "checks": checks, "failed": failed, "price": price,
           "breakout_level": level, "atr": atr, "window_label": window_label,
           "label": "🚀 MOMENTUM BREAKOUT (experimental)" if not failed else "No momentum setup",
           "score": len(checks) - len(failed)}
    if not failed:
        out["trade"] = {"entry": price, "stop": stop, "target1": target1, "target2": target2,
                        "riskPct": (price - stop) / price * 100, "target1NetPct": net1,
                        "target2NetPct": (target2 - price) / price * 100 - FEE_PCT}
        out["reasons"] = [f"Closed above the prior {lookback}-candle high ({level:.6g}), {(price - level) / atr:.2f} ATR past it",
                          "Trend up (price above rising 20/50 averages)", "Volume above 1.3x normal",
                          "Not parabolic, no distribution pattern"]
    return out


# ---------------- scanning, tracking, display ----------------
import datetime
import math
import random
import time
from html import escape as _esc

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


EXPIRY_HOURS = {"15m": 6, "1h": 24}       # how long a call may run before it counts as expired (also the loss cooldown)
MAX_OPEN_PER_TF = 5
MAX_ATTEMPTS = 40
RETENTION_DAYS = 30


def scan(pool, tf_key, fetch_ohlc, skip_symbols=(), max_new=MAX_OPEN_PER_TF, attempts=MAX_ATTEMPTS, sleep=0.15):
    """Look through a shuffled slice of the coin pool and return coins that currently qualify."""
    cfg = MOMENTUM_TIMEFRAMES[tf_key]
    cands = [m for m in (pool or []) if (m.get("symbol") or "").upper() not in skip_symbols]
    random.shuffle(cands)
    found, tried = [], 0
    for m in cands:
        if len(found) >= max_new or tried >= attempts:
            break
        sym = (m.get("symbol") or "").upper()
        if not sym:
            continue
        tried += 1
        try:
            klines = fetch_ohlc(sym, cfg["interval"])
        except Exception:                                    # no liquid Binance pair: skip quietly
            continue
        finally:
            time.sleep(sleep)
        sig = compute_momentum_signal(klines, cfg["lookback"], cfg["window_label"])
        if sig and sig["status"] == "momentum":
            sig.update(symbol=sym, name=m.get("name") or sym, tf=tf_key)
            found.append(sig)
    return found


def cooling(resolved, now=None):
    """{"tf:COIN"} that lost or expired recently and must not be re-signalled yet."""
    now = now or _now()
    out = set()
    for r in resolved:
        if r["result"] in ("loss", "expired"):
            until = datetime.datetime.fromisoformat(r["resolved_at"]) + datetime.timedelta(hours=EXPIRY_HOURS.get(r["tf"], 24))
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
            klines = fetch_ohlc(pos["coin"], MOMENTUM_TIMEFRAMES[pos["tf"]]["interval"])
        except Exception:
            still_open[key] = pos                           # could not check: leave open, retry next run
            continue
        finally:
            time.sleep(sleep)
        opened = datetime.datetime.fromisoformat(pos["opened_at"])
        opened_ms = opened.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
        result, exit_p = None, None
        for k in klines:
            if float(k[0]) + 1 < opened_ms:
                continue                                    # candle finished before the call opened
            lo, hi = float(k[3]), float(k[2])
            if lo <= pos["stop"]:
                result, exit_p = "loss", pos["stop"]
                break
            if hi >= pos["target1"]:
                result, exit_p = "win", pos["target1"]
                break
        if result is None and (now - opened).total_seconds() / 3600 >= EXPIRY_HOURS.get(pos["tf"], 24):
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
        pos = {"coin": s["symbol"], "name": s.get("name") or s["symbol"], "tf": s["tf"], "entry": t["entry"], "stop": t["stop"],
               "target1": t["target1"], "target2": t["target2"], "net1": t["target1NetPct"], "opened_at": now.isoformat()}
        still_open[key] = pos
        newly_opened.append(pos)
    cutoff = now - datetime.timedelta(days=RETENTION_DAYS)
    resolved = [r for r in resolved if datetime.datetime.fromisoformat(r["resolved_at"]) >= cutoff]
    return {"open": still_open, "resolved": resolved}, newly_opened, newly_resolved


def stats(resolved):
    wins = sum(1 for r in resolved if r["result"] == "win")
    losses = sum(1 for r in resolved if r["result"] == "loss")
    expired = sum(1 for r in resolved if r["result"] == "expired")
    nets = [(r["exit_price"] - r["entry"]) / r["entry"] * 100 - FEE_PCT for r in resolved]
    return {"wins": wins, "losses": losses, "expired": expired, "n": len(resolved),
            "win_rate": wins / (wins + losses) * 100 if wins + losses else None,
            "avg_net": sum(nets) / len(nets) if nets else None}


def notification_events(opened, resolved_rows, fmt_price=None):
    fmt_price = fmt_price or price_text
    ev = []
    for p in opened:
        ev.append({"id": f"momentum:{p['tf']}:{p['coin']}:{p['opened_at']}", "ts": p["opened_at"], "type": "signal",
                   "title": f"\U0001F680 Momentum signal (experimental): {p['coin']} ({p['tf']})",
                   "body": f"Breakout entry {fmt_price(p['entry'])}, stop {fmt_price(p['stop'])}, target {fmt_price(p['target1'])}",
                   "portion_key": "screener"})
    for r in resolved_rows:
        emoji = {"win": "✅", "loss": "\U0001F6D1", "expired": "⏱"}.get(r["result"], "")
        ev.append({"id": f"mresult:{r['coin']}:{r['tf']}:{r['opened_at']}", "ts": r["resolved_at"], "type": r["result"],
                   "title": f"{emoji} Momentum {r['coin']} ({r['tf']}) {r['result'].upper()}",
                   "body": f"Exit {fmt_price(r['exit_price'])} vs. entry {fmt_price(r['entry'])}", "portion_key": "performance"})
    return ev


def panel_html(tracker, fmt_price=None, now=None):
    """Card for the top of the Screener tab: open momentum calls plus the tier's own record."""
    now = now or _now()
    fmt_price = fmt_price or price_text
    tracker = tracker or {}
    rows = []
    for pos in sorted(tracker.get("open", {}).values(), key=lambda p: p["opened_at"], reverse=True):
        mins = max(0, int((now - datetime.datetime.fromisoformat(pos["opened_at"])).total_seconds() / 60))
        rows.append(f'<tr><td><b>{_esc(pos["coin"])}</b><span class="wl-note">{_esc(pos["tf"])}</span></td>'
                    f'<td>{fmt_price(pos["entry"])}</td><td class="neg">{fmt_price(pos["stop"])}</td>'
                    f'<td class="pos">{fmt_price(pos["target1"])}<span class="wl-note">{pos["net1"]:+.2f}% net of fees</span></td>'
                    f'<td class="watch">{mins}m ago</td></tr>')
    if rows:
        table = ('<table class="signal-table"><thead><tr><th>Coin</th><th>Entry</th><th>Stop</th><th>Target 1</th><th>Opened</th></tr></thead><tbody>'
                 + "".join(rows) + '</tbody></table>')
    else:
        table = '<div class="sub">No coin has just broken to a new high with trend and volume behind it (and not yet stretched) right now.</div>'
    s = stats(tracker.get("resolved", []))
    if s["n"]:
        wr = f'{s["win_rate"]:.0f}% wins' if s["win_rate"] is not None else "no decided calls yet"
        an = f'{s["avg_net"]:+.2f}%' if s["avg_net"] is not None else "n/a"
        record = (f'Own record, last {RETENTION_DAYS} days: {s["wins"]} won, {s["losses"]} lost, {s["expired"]} expired '
                  f'({wr}); average result {an} per call after fees.')
    else:
        record = f'Own record: no finished calls yet (kept for {RETENTION_DAYS} days).'
    tip = ("The dip scanner stays quiet in a rally because it wants price near its lows. This tier does the opposite: it flags a coin "
           "that has just closed above its recent high, with the trend up, volume above normal, not yet stretched (within 1 ATR of the "
           "breakout), no parabolic run and no distribution pattern. Levels use the same ATR stop/target geometry as the dip scanner. "
           "Tracked separately from the dip scanner.")
    return f"""
<div class="card wl-card" style="margin-bottom:12px;">
  <div class="card-title">&#128640; MOMENTUM BREAKOUTS &middot; EXPERIMENTAL<span class="info-tip" tabindex="0" data-tip="{_esc(tip)}">&#9432;</span></div>
  <div class="sub">In back-tests on 40 coins this rule set was about break-even after fees (average result within about &plusmn;0.3% of zero on both 15m and 1h), so there is no proven edge yet. Judge it by its own record below, not by the idea.</div>
  {table}
  <div class="sub">{_esc(record)}</div>
</div>
"""
