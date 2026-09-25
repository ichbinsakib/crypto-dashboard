"""One SCALPING run: data -> analysis -> engine -> filters -> lifecycle -> performance rows -> payload + alerts.

Kept apart from the normal signal engine (momentum.py / dashboard.py). The scheduled job (scalping_job.py) calls run() with the
publisher's backend; tests call it with an in-memory store and canned candles. Nothing here decides what to draw: the browser
renders `payload`, and the numbers (levels, scores, outcomes) come only from analysis.py and lifecycle.py."""
import datetime as dt

from . import analysis, config, lifecycle

STORE_LIMIT = 1000
RECENT_RESULT_MIN = 60           # a finished signal stays on its coin card for this long, then the card returns to WATCH / NO SETUP


class MemoryStore:
    """Tiny in-memory stand-in for the Supabase backend (same select/upsert shape) for tests."""

    def __init__(self):
        self.tables = {}

    def select(self, table, query=""):
        return [dict(r) for r in self.tables.get(table, [])]

    def upsert(self, table, rows, on_conflict):
        cols = on_conflict.split(",")
        cur = self.tables.setdefault(table, [])
        for row in rows:
            for ex in cur:
                if all(ex.get(c) == row.get(c) for c in cols):
                    ex.update(row)
                    break
            else:
                cur.append(dict(row))


def _iso(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_price(v):
    """Price with a sensible number of decimals for its size (no fake precision)."""
    if v is None:
        return "n/a"
    d = 2 if v >= 100 else 3 if v >= 10 else 4 if v >= 1 else 5
    return f"{v:,.{d}f}"


# ---------------- data reliability ----------------

def data_status(rows, interval, now, cfg, failed=False):
    """LIVE / DELAYED / STALE / DISCONNECTED for one series, judged by how far behind the newest candle is."""
    if failed or not rows:
        return "DISCONNECTED", None
    iv = config.INTERVAL_MS[interval]
    lag_min = max(0.0, (int(now.timestamp() * 1000) - (int(rows[-1][0]) + iv)) / 60000)
    if lag_min <= 1.5:
        return "LIVE", lag_min
    return ("DELAYED" if lag_min <= cfg["stale_after_min"] else "STALE"), lag_min


def _worst(statuses):
    order = ["LIVE", "DELAYED", "STALE", "DISCONNECTED"]
    return max(statuses, key=order.index) if statuses else "DISCONNECTED"


# ---------------- alerts ----------------

def _alerts_for(prev, new, cfg):
    """Notification dicts for the meaningful state changes between the stored row and the updated row. Ids are deterministic,
    so a repeated run cannot send the same alert twice."""
    out = []
    a = cfg["alerts"]
    sid, coin, side = new["id"], new["coin"], new["direction"].title()

    def add(kind, type_, title, body, ts):
        if a.get(kind):
            out.append({"id": f"scalp:{sid}:{kind}", "ts": ts, "type": type_, "title": title, "body": body, "portion_key": "scalping"})
    if prev is None:
        if new["setup_score"] >= cfg["alert_min_score"]:
            add("setup", "scalp_setup", f"⚡ {coin} {side.upper()} setup (score {new['setup_score']:.1f}/10)",
                f"Entry {fmt_price(new['entry_low'])}–{fmt_price(new['entry_high'])} · Stop {fmt_price(new['stop'])} · "
                f"TP1 {fmt_price(new['tp1'])} · TP2 {fmt_price(new['tp2'])}", new["created_at"])
        return out
    if new.get("entry_time") and not prev.get("entry_time"):
        add("entry", "scalp_entry", f"▶ {coin} {side.upper()} entered", f"Filled near {fmt_price(new['actual_entry'])}. Stop {fmt_price(new['stop'])}.", new["entry_time"])
    if new.get("tp1_time") and not prev.get("tp1_time"):
        add("tp1", "scalp_tp1", f"✅ {coin} target 1 hit", f"{fmt_price(new['tp1'])} reached. Stop moved to breakeven and now trails the price.", new["tp1_time"])
    if new.get("exit_time") and not prev.get("exit_time"):
        pnl = new.get("pnl_pct")
        p = "" if pnl is None else f" ({pnl:+.2f}%)"
        if new["state"] == "TP2_HIT":
            add("tp2", "scalp_tp2", f"\U0001F3AF {coin} target 2 hit{p}", f"{coin} {side.lower()} finished at {fmt_price(new['exit_price'])}.", new["exit_time"])
        elif new["state"] == "STOP_LOSS":
            add("stop", "scalp_stop", f"\U0001F6D1 {coin} stop loss hit{p}", f"Exit {fmt_price(new['exit_price'])}.", new["exit_time"])
        elif new["state"] == "INVALIDATED":
            add("invalidated", "scalp_invalid", f"⚠ {coin} setup no longer valid", (new["timeline"][-1]["note"] if new["timeline"] else ""), new["exit_time"])
        elif new["state"] == "EXPIRED":
            add("expired", "scalp_expired", f"⏱ {coin} setup expired", (new["timeline"][-1]["note"] if new["timeline"] else ""), new["exit_time"])
    return out


def _regime_alert(runtime, market, cfg, now):
    """A regime change is only announced once it has held for two runs, and only if it matters (restricted, or trend flips)."""
    st = dict(runtime or {})
    confirmed, cand, n = st.get("confirmed"), st.get("candidate"), st.get("count", 0)
    if confirmed is None:
        return {"confirmed": market, "candidate": None, "count": 0}, None
    if market == confirmed:
        return {"confirmed": confirmed, "candidate": None, "count": 0}, None
    n = n + 1 if cand == market else 1
    if n < 2:
        return {"confirmed": confirmed, "candidate": market, "count": n}, None
    restricted = set(cfg["restricted_regimes"])
    important = market in restricted or confirmed in restricted or {market, confirmed} == {"TRENDING UP", "TRENDING DOWN"}
    note = None
    if important and cfg["alerts"].get("regime"):
        note = {"id": f"scalp-regime:{now:%Y%m%d%H%M}", "ts": _iso(now), "type": "scalp_regime", "portion_key": "scalping",
                "title": f"\U0001F4CA Scalping regime: {market}",
                "body": ("New scalps are restricted." if market in restricted else f"Was {confirmed}.")}
    return {"confirmed": market, "candidate": None, "count": 0}, note


# ---------------- the run ----------------

def _label(row, now):
    if row is None:
        return None
    if not lifecycle.is_final(row):
        if row["state"] == "SETUP":
            return f"{row['direction']} SETUP"
        if row["state"] == "TP1_HIT":
            return "TP1 HIT"
        et = lifecycle.parse(row["entry_time"]) if row.get("entry_time") else None
        return "ENTRY TRIGGERED" if et and (now - et).total_seconds() < 600 else "ACTIVE TRADE"
    return {"TP2_HIT": "TP2 HIT", "TP1_HIT": "TP1 HIT", "STOP_LOSS": "STOP LOSS HIT", "EXPIRED": "EXPIRED", "INVALIDATED": "INVALIDATED", "CLOSED": "CLOSED"}[row["state"]]


def run(store, fetch, now=None, runtime=None):
    """Returns (payload, notifications, runtime_state). Persists signal rows through `store`. Never raises on data problems: a coin
    whose data cannot be fetched is reported DISCONNECTED and simply produces no signal."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    srow = next(iter(store.select("scalp_settings", "select=key,value&key=eq.config")), None)
    cfg = config.effective(srow["value"] if srow else None)
    rows = sorted(store.select("scalp_signals", f"select=*&order=created_at.desc&limit={STORE_LIMIT}"), key=lambda r: r["created_at"], reverse=True)
    names = {c["symbol"]: c["name"] for c in config.COINS}
    open_coins = {r["coin"] for r in rows if lifecycle.is_open(r)}
    monitored = [c for c in cfg["enabled_coins"] if c in names]
    wanted = list(dict.fromkeys(monitored + sorted(open_coins)))

    data, dstat, lags = {}, {}, {}
    for sym in wanted:
        try:
            data[sym] = (fetch(sym, cfg["htf"], 200), fetch(sym, cfg["exec"], 300))
            st, lag = data_status(data[sym][1], cfg["exec"], now, cfg)
        except Exception:  # noqa: BLE001 - a dead feed is a status, not a crash
            st, lag = data_status(None, cfg["exec"], now, cfg, failed=True)
        dstat[sym], lags[sym] = st, lag
    overall = _worst([dstat[c] for c in monitored]) if monitored else "DISCONNECTED"

    # 1) follow every open signal to its outcome
    changed, notes = {}, []
    for r in rows:
        if lifecycle.is_open(r) and r["coin"] in data:
            upd = lifecycle.advance(r, data[r["coin"]][1], now, cfg)
            upd["updated_at"] = _iso(now)
            changed[r["id"]] = upd
            notes += _alerts_for(r, upd, cfg)
    rows = [changed.get(r["id"], r) for r in rows]

    # 2) analyse every monitored coin
    evals, regimes = {}, {}
    for sym in monitored:
        if sym in data and dstat[sym] != "DISCONNECTED":
            evals[sym] = analysis.evaluate(sym, data[sym][0], data[sym][1], cfg)
            regimes[sym] = evals[sym]["regime"]
    market = analysis.market_regime(regimes)
    restricted_market = market in cfg["restricted_regimes"]
    runtime_out, regime_note = _regime_alert(runtime, market, cfg, now)
    if regime_note:
        notes.append(regime_note)

    # 3) new setups: only fresh, unrestricted, unfiltered ones
    block = {}
    for sym, ev in evals.items():
        if ev["status"] != "SETUP":
            continue
        why = None
        if dstat[sym] not in ("LIVE", "DELAYED"):
            why = "its market data is stale: new signals are paused"
        elif restricted_market or ev["regime"] in cfg["restricted_regimes"]:
            why = f"market is {ev['regime'] if ev['regime'] in cfg['restricted_regimes'] else market}: new scalps are restricted"
        else:
            why = lifecycle.blocked(sym, ev["setup"]["direction"], ev["setup"]["level"], ev["setup"]["atr"], rows, now, cfg)
        if why:
            block[sym] = why
            continue
        last_open = int(data[sym][1][-2][0])
        row = lifecycle.new_signal(sym, ev, ev["regime"], now, cfg, last_open)
        if any(r["id"] == row["id"] for r in rows):                       # same trigger candle already handled
            continue
        rows.insert(0, row)
        changed[row["id"]] = row
        notes += _alerts_for(None, row, cfg)

    if changed:
        store.upsert("scalp_signals", list(changed.values()), "id")

    # 4) payload for the dashboard
    open_rows = [r for r in rows if lifecycle.is_open(r)]
    finals = [r for r in rows if lifecycle.is_final(r)]
    cards = []
    for sym in monitored:
        ev = evals.get(sym)
        o = next((r for r in open_rows if r["coin"] == sym), None)
        recent = next((r for r in finals if r["coin"] == sym and (now - lifecycle.parse(r["exit_time"])).total_seconds() / 60 <= RECENT_RESULT_MIN), None)
        shown = o or recent
        if shown:
            state = _label(shown, now)
        elif ev is None:
            state = "NO DATA"
        elif ev["status"] == "SETUP":
            state = "NO SETUP"                                            # a valid setup that was filtered out is not a signal
        else:
            state = "WATCH" if ev["status"] == "WATCH" else "NO SETUP"
        why = (ev or {}).get("reason") or "No data"
        if sym in block:
            why = "Setup found but blocked: " + block[sym]
        cards.append({"symbol": sym, "name": names[sym], "price": (ev or {}).get("price") or (data.get(sym, ([], []))[1][-1][4] if data.get(sym) and data[sym][1] else None),
                      "trend": (ev or {}).get("trend_word", "NEUTRAL"), "regime": (ev or {}).get("regime"), "state": state,
                      "direction": (shown or {}).get("direction") or (ev or {}).get("direction"), "score": (ev or {}).get("score"),
                      "checks": (ev or {}).get("checks", []), "reason": why, "signal_id": (shown or {}).get("id"), "data": dstat.get(sym, "DISCONNECTED")})
    live_states = ("LONG SETUP", "SHORT SETUP", "ENTRY TRIGGERED", "ACTIVE TRADE", "TP1 HIT")
    active_n = sum(1 for c in cards if c["state"] in live_states and c["signal_id"] and any(r["id"] == c["signal_id"] and lifecycle.is_open(r) for r in open_rows))
    usable = [c for c in monitored if dstat.get(c) in ("LIVE", "DELAYED")]
    if not usable:                                        # every monitored coin's data is stale or down
        mstate = "PAUSED"
    elif restricted_market:
        mstate = "RESTRICTED"
    else:
        mstate = "ACTIVE"
    newest = max((int(data[c][1][-1][0]) for c in monitored if c in data and data[c][1]), default=None)

    def compact(r, full=False):
        keys = ("id", "coin", "direction", "state", "setup_type", "timeframe", "htf", "regime", "setup_score", "quality", "created_at", "expires_at", "entry_low", "entry_high",
                "stop", "tp1", "tp2", "rr", "actual_entry", "entry_time", "tp1_time", "exit_price", "exit_time", "exit_reason", "pnl_pct", "r_multiple",
                "mfe_pct", "mae_pct", "duration_min", "last_price", "manual_close_requested", "level", "atr")
        d = {k: r.get(k) for k in keys}
        if full:
            d.update({"checks": r.get("checks"), "timeline": r.get("timeline"), "reason": r.get("reason")})
        return d
    payload = {
        "generated_at": _iso(now), "coins": cards, "coin_list": config.COINS,
        "market": {"state": mstate, "regime": market, "restricted": restricted_market, "data": overall, "newest_candle_ms": newest,
                   "lag_min": max([v for v in lags.values() if v is not None], default=None), "active_setups": active_n, "monitored": len(monitored),
                   "note": ("New scalps are temporarily restricted." if restricted_market else "New signals are paused until data recovers." if mstate == "PAUSED" else None)},
        "active": [compact(r, True) for r in open_rows],
        "recent": [compact(r, True) for r in finals[:30]],
        "history": [compact(r) for r in finals[:400]],
        "config": cfg, "defaults": config.effective({}), "limits": {k: list(v) for k, v in config.LIMITS.items()}, "regimes": list(config.REGIMES),
    }
    return payload, notes, runtime_out
