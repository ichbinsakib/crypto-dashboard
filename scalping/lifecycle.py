"""Signal lifecycle for the SCALPING engine: create a signal, follow it to its outcome, and guard against spam.

States
  SETUP        waiting for price to enter the entry zone          (a LONG SETUP / SHORT SETUP on the dashboard)
  ACTIVE       entered; stop and targets are being tracked        (ENTRY TRIGGERED, then ACTIVE TRADE)
  TP1_HIT      target 1 reached: part of the position is closed and the stop moves to breakeven, then trails the price
               (final once the trailing stop is hit, at or above breakeven -- see post_tp1_trail_atr)
  TP2_HIT      target 2 reached                                    (final)
  STOP_LOSS    stopped out before target 1                         (final)
  EXPIRED      not entered in time, or an active trade hit its time limit (final)
  INVALIDATED  the setup broke before entry: stop hit, target hit without entry, or price ran away (final)
  CLOSED       closed by the admin                                 (final)
A signal is final once it has an exit_time. Rows are never deleted.

`advance` REPLAYS the closed candles since the signal was created, so the result is deterministic: a late or repeated run cannot
double-count, and a stop hit while nobody was looking is still found. If one candle touches both the stop and a target, the
stop is assumed to come first (conservative). Only closed candles decide outcomes; the forming candle only supplies last_price."""
import datetime as dt

from . import config

FINAL_STATES = ("TP2_HIT", "STOP_LOSS", "EXPIRED", "INVALIDATED", "CLOSED", "TP1_HIT")
OPEN_STATES = ("SETUP", "ACTIVE", "TP1_HIT")     # TP1_HIT is open until it has an exit_time


def _iso(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(ts):
    if isinstance(ts, dt.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def is_final(sig):
    return bool(sig.get("exit_time"))


def is_open(sig):
    return not is_final(sig)


def _ms(d):
    return int(d.timestamp() * 1000)


def _from_ms(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc)


# ---------------- creation and anti-spam ----------------

def _loss_streak(finals_newest_first):
    """How many STOP_LOSS results in a row, counting back from the most recent finished signal."""
    streak = 0
    for r in finals_newest_first:
        if r["state"] != "STOP_LOSS":
            break
        streak += 1
    return streak


def blocked(symbol, direction, level, atr, rows, now, cfg):
    """None if a new signal is allowed, otherwise a short plain reason. rows = all stored signals (any coin)."""
    open_rows = [r for r in rows if is_open(r)]
    if len(open_rows) >= cfg["max_simultaneous"]:
        return "already at the maximum number of open scalps"
    if any(r["coin"] == symbol for r in open_rows):
        return "already has an open signal"
    finals = sorted((r for r in rows if r["coin"] == symbol and is_final(r)), key=lambda r: r["exit_time"], reverse=True)
    if finals:
        last = finals[0]
        since = (now - parse(last["exit_time"])).total_seconds() / 60
        # A losing streak on this coin extends the cooldown, and keeps extending it with each further loss (capped): it
        # may point at a real, ongoing problem (e.g. news) the engine cannot see, so a single flat pause is not enough
        # once losses are already hours apart naturally -- back off further each time rather than resetting to one fixed wait.
        streak = _loss_streak(finals)
        if streak >= cfg["loss_streak_limit"]:
            wait = cfg["loss_streak_cooldown_min"] * min(streak - cfg["loss_streak_limit"] + 1, 4)
            reason = f"{streak} losses in a row on this coin"
        else:
            wait = cfg["sl_cooldown_min"] if last["state"] == "STOP_LOSS" else cfg["cooldown_min"]
            reason = "cooling down after its last signal"
        if since < wait:
            return f"{reason} ({int(wait - since) + 1} min left)"
        if (last["state"] == "STOP_LOSS" and last["direction"] == direction and since < 360 and last.get("level") is not None
                and atr and abs(level - last["level"]) < cfg["min_level_change_atr"] * atr):
            return "same setup as the one that just stopped out"
    return None


def new_signal(symbol, ev, regime, now, cfg, last_closed_open_ms):
    """Build the stored row for a fresh setup found by analysis.evaluate (ev['status'] == 'SETUP')."""
    su = ev["setup"]
    iv = config.INTERVAL_MS[cfg["exec"]]
    created = _from_ms(last_closed_open_ms + iv)          # the moment the trigger candle closed
    row = {
        "id": f"{symbol}-{su['direction'][0]}-{last_closed_open_ms}", "coin": symbol, "direction": su["direction"], "state": "SETUP",
        "setup_type": su["type"], "timeframe": cfg["exec"], "htf": cfg["htf"], "regime": regime, "setup_score": ev["score"], "quality": ev["quality"],
        "created_at": _iso(created), "expires_at": _iso(created + dt.timedelta(minutes=cfg["signal_expiry_min"])),
        "level": su["level"], "entry_low": su["entry_low"], "entry_high": su["entry_high"], "stop": su["stop"], "tp1": su["tp1"], "tp2": su["tp2"],
        "rr": su["rr"], "atr": su["atr"], "actual_entry": None, "entry_time": None, "tp1_time": None, "exit_price": None, "exit_time": None,
        "exit_reason": None, "pnl_pct": None, "r_multiple": None, "mfe_pct": None, "mae_pct": None, "duration_min": None,
        "last_price": ev["price"], "checks": ev["checks"], "reason": ev["reason"],
        "timeline": [{"ts": _iso(created), "state": "SETUP", "price": ev["price"], "note": f"{su['direction'].title()} {su['type']} setup created (score {ev['score']:.1f}/10)"}],
        "manual_close_requested": False, "updated_at": _iso(now),
    }
    return row


# ---------------- following a signal ----------------

def _finish(sig, state, price, ts, reason, cfg, tl_note):
    """Close the signal: fill exit fields and compute P&L (partial exit at target 1 counted), R multiple and duration."""
    sig["state"], sig["exit_price"], sig["exit_time"], sig["exit_reason"] = state, price, _iso(ts), reason
    sig["timeline"].append({"ts": _iso(ts), "state": state, "price": price, "note": tl_note})
    s = 1 if sig["direction"] == "LONG" else -1
    if sig.get("actual_entry"):
        e = sig["actual_entry"]
        g_exit = (price - e) / e * 100 * s
        if sig.get("tp1_time"):
            frac = cfg["partial_tp1_pct"] / 100
            g_tp1 = (sig["tp1"] - e) / e * 100 * s
            gross = frac * g_tp1 + (1 - frac) * g_exit
        else:
            gross = g_exit
        sig["pnl_pct"] = round(gross - cfg["fee_pct"], 4)
        risk_pct = abs(e - sig["stop"]) / e * 100
        sig["r_multiple"] = round(sig["pnl_pct"] / risk_pct, 3) if risk_pct else None
        sig["duration_min"] = round((ts - parse(sig["entry_time"])).total_seconds() / 60, 1)
    else:                                                # never entered: no trade, no P&L
        sig["duration_min"] = round((ts - parse(sig["created_at"])).total_seconds() / 60, 1)
    return sig


def advance(sig, candles, now, cfg):
    """Replay closed candles for one open signal. Returns the updated row (a new dict). `candles` are exec-timeframe klines,
    oldest first, the last one still forming."""
    sig = dict(sig)
    sig["timeline"] = [t for t in sig["timeline"][:1]]           # rebuilt below, deterministically
    for k in ("actual_entry", "entry_time", "tp1_time", "exit_price", "exit_time", "exit_reason", "pnl_pct", "r_multiple", "mfe_pct", "mae_pct", "duration_min"):
        sig[k] = None
    sig["state"] = "SETUP"
    iv = config.INTERVAL_MS[sig["timeframe"]]
    created, expires = parse(sig["created_at"]), parse(sig["expires_at"])
    s = 1 if sig["direction"] == "LONG" else -1
    zl, zh, stop, tp1, tp2, atr = sig["entry_low"], sig["entry_high"], sig["stop"], sig["tp1"], sig["tp2"], sig["atr"] or 0
    entry = None
    tp1_hit = False
    mfe = mae = 0.0
    peak = None            # best price reached since TP1 (for the trailing stop below); None until TP1 hits
    closed = candles[:-1] if candles else []
    sig["last_price"] = float(candles[-1][4]) if candles else sig.get("last_price")

    for k in closed:
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        close_ts = _from_ms(int(k[0]) + iv)
        if close_ts <= created:
            continue
        adv_x, fav_x = (l, h) if s > 0 else (h, l)                # worst / best price of the candle for this direction
        if entry is None:                                          # ---- waiting for entry ----
            if l <= zh and h >= zl:
                entry = o if zl <= o <= zh else (zh if o > zh else zl)
                sig["actual_entry"], sig["entry_time"], sig["state"] = entry, _iso(close_ts - dt.timedelta(milliseconds=iv)), "ACTIVE"
                sig["timeline"].append({"ts": sig["entry_time"], "state": "ACTIVE", "price": entry, "note": "Entry triggered"})
            elif (adv_x - stop) * s <= 0:
                return _finish(sig, "INVALIDATED", None, close_ts, "stop_before_entry", cfg, "Setup invalidated: price hit the stop before entry")
            elif (fav_x - tp1) * s >= 0:
                return _finish(sig, "INVALIDATED", None, close_ts, "target_without_entry", cfg, "Setup invalidated: target reached without entry")
            elif (c - (zh if s > 0 else zl)) * s > atr:
                return _finish(sig, "INVALIDATED", None, close_ts, "ran_away", cfg, "Setup invalidated: price ran away from the entry zone")
            elif close_ts >= expires:
                return _finish(sig, "EXPIRED", None, close_ts, "not_entered", cfg, "Expired: not entered in time")
            if entry is None:
                continue
        # ---- trade management (also runs on the entry candle) ----
        fav = (fav_x - entry) / entry * 100 * s
        adv = (entry - adv_x) / entry * 100 * s
        mfe, mae = max(mfe, fav), max(mae, adv)
        sig["mfe_pct"], sig["mae_pct"] = round(mfe, 3), round(mae, 3)
        if not tp1_hit:
            if (adv_x - stop) * s <= 0:
                px = stop if (o - stop) * s > 0 else o
                return _finish(sig, "STOP_LOSS", px, close_ts, "stop", cfg, "Stop loss hit")
            if (fav_x - tp1) * s >= 0:
                tp1_hit = True
                peak = fav_x                                  # the TP1 candle itself may have wicked past tp1
                sig["tp1_time"], sig["state"] = _iso(close_ts), "TP1_HIT"
                sig["timeline"].append({"ts": sig["tp1_time"], "state": "TP1_HIT", "price": tp1, "note": "Target 1 hit; stop moved to breakeven and now trails the price"})
                if (fav_x - tp2) * s >= 0:
                    return _finish(sig, "TP2_HIT", tp2, close_ts, "tp2", cfg, "Target 2 hit")
        else:
            # The stop never gives back the breakeven floor, but it also trails behind the best price reached since TP1,
            # so a winner that pushes on toward TP2 locks in more than flat breakeven instead of round-tripping to zero.
            # The trail level used here is fixed as of the START of this candle (not updated with this candle's own high/low
            # first), matching the file's stop-first, no-look-ahead-within-a-candle convention.
            trail = entry
            if peak is not None and atr:
                candidate = peak - s * cfg["post_tp1_trail_atr"] * atr
                trail = max(entry, candidate) if s > 0 else min(entry, candidate)
            if (adv_x - trail) * s <= 0:
                px = trail if (o - trail) * s > 0 else o
                if trail == entry:
                    return _finish(sig, "TP1_HIT", px, close_ts, "tp1_then_breakeven", cfg, "Stopped at breakeven after target 1")
                return _finish(sig, "TP1_HIT", px, close_ts, "tp1_then_trail", cfg, "Stopped after target 1, with extra profit locked in above breakeven")
            if (fav_x - tp2) * s >= 0:
                return _finish(sig, "TP2_HIT", tp2, close_ts, "tp2", cfg, "Target 2 hit")
            peak = max(peak, fav_x) if s > 0 else min(peak, fav_x)
        if (close_ts - parse(sig["entry_time"])).total_seconds() / 60 >= cfg["trade_max_min"]:
            return _finish(sig, "EXPIRED", c, close_ts, "time_limit", cfg, "Closed at the time limit")

    # ---- wall clock and manual close (only if still open) ----
    last_px = sig["last_price"]
    if entry is None and now >= expires:
        return _finish(sig, "EXPIRED", None, now, "not_entered", cfg, "Expired: not entered in time")
    if entry is not None and (now - parse(sig["entry_time"])).total_seconds() / 60 >= cfg["trade_max_min"] and last_px:
        return _finish(sig, "EXPIRED", last_px, now, "time_limit", cfg, "Closed at the time limit")
    if sig.get("manual_close_requested"):
        if entry is None:
            return _finish(sig, "CLOSED", None, now, "manual", cfg, "Cancelled by the admin before entry")
        return _finish(sig, "CLOSED", last_px, now, "manual", cfg, "Closed by the admin")
    return sig
