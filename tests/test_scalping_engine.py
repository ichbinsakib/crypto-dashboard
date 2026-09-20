"""SCALPING engine: config, analysis, lifecycle, anti-spam and a full run against an in-memory store."""
import copy
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from scalping import analysis as A, config as C, lifecycle as L, service as S  # noqa: E402
import scalp_data as D  # noqa: E402

UTC = dt.timezone.utc
CFG = C.effective({})


def at(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=UTC)


class ConfigTests(unittest.TestCase):
    def test_only_the_four_coins_can_ever_be_enabled(self):
        self.assertEqual([c["symbol"] for c in C.COINS], ["SOL", "LINK", "XRP", "ONDO"])
        self.assertEqual(C.effective({"enabled_coins": ["SOL", "DOGE", "BTC", "ONDO"]})["enabled_coins"], ["SOL", "ONDO"])

    def test_overrides_are_clamped_and_bad_input_falls_back(self):
        cfg = C.effective({"min_score": 99, "min_rr": "x", "cooldown_min": -5, "max_simultaneous": True, "allow_short": "yes", "htf": "4h"})
        self.assertEqual(cfg["min_score"], 10.0)
        self.assertEqual(cfg["min_rr"], C.DEFAULTS["min_rr"])
        self.assertEqual(cfg["cooldown_min"], 0)
        self.assertEqual(cfg["max_simultaneous"], C.DEFAULTS["max_simultaneous"])
        self.assertIs(cfg["allow_short"], False)
        self.assertEqual(cfg["htf"], "15m")
        self.assertEqual(C.effective(None)["min_score"], C.DEFAULTS["min_score"])

    def test_shorts_are_off_by_default(self):
        self.assertFalse(C.DEFAULTS["allow_short"])


class AnalysisTests(unittest.TestCase):
    def test_breakout_in_an_uptrend_is_a_long_setup_with_sane_levels(self):
        h, x = D.breakout_scenario()
        ev = A.evaluate("SOL", h, x, CFG)
        self.assertEqual(ev["status"], "SETUP", ev["checks"])
        su = ev["setup"]
        self.assertEqual(su["direction"], "LONG")
        self.assertLess(su["stop"], su["entry_low"])
        self.assertLess(su["entry_high"], su["tp1"])
        self.assertLess(su["tp1"], su["tp2"])
        self.assertGreaterEqual(su["rr"], CFG["min_rr"])
        self.assertGreaterEqual(ev["score"], CFG["min_score"])
        self.assertEqual(len(ev["checks"]), 7)
        self.assertLessEqual(ev["score"], 10)

    def test_no_setup_when_the_higher_timeframe_trend_is_down(self):
        h, x = D.downtrend_scenario()
        ev = A.evaluate("SOL", h, x, CFG)
        self.assertNotEqual(ev["status"], "SETUP")
        self.assertIsNone(ev["setup"])
        self.assertEqual(ev["trend_word"], "BEARISH")

    def test_a_raised_minimum_score_blocks_the_same_market(self):
        h, x = D.breakout_scenario()
        ev = A.evaluate("SOL", h, x, C.effective({"min_score": 9.9}))
        self.assertNotEqual(ev["status"], "SETUP")
        self.assertIn("below the minimum", ev["reason"])

    def test_a_high_minimum_rr_blocks_it_too(self):
        h, x = D.breakout_scenario()
        self.assertNotEqual(A.evaluate("SOL", h, x, C.effective({"min_rr": 4.0}))["status"], "SETUP")

    def test_fees_that_swallow_the_target_block_the_setup(self):
        h, x = D.breakout_scenario()
        ev = A.evaluate("SOL", h, x, C.effective({"fee_pct": 1.0}))
        self.assertNotEqual(ev["status"], "SETUP")
        self.assertEqual({c["key"]: c["state"] for c in ev["checks"]}["volatility"], "fail")

    def test_missing_or_short_data_never_produces_a_setup(self):
        h, x = D.breakout_scenario()
        self.assertEqual(A.evaluate("SOL", h[:30], x, CFG)["status"], "NO_SETUP")
        self.assertEqual(A.evaluate("SOL", None, x, CFG)["status"], "NO_SETUP")

    def test_shorts_only_when_allowed(self):
        h, x = D.downtrend_scenario()
        # make the last closed 5m candle a breakdown on heavy volume
        closes = [r[4] for r in x]
        closes[-2] = min(r[3] for r in x[-22:-2]) * 0.9965
        closes[-1] = closes[-2] * 0.9998
        vols = [100.0] * len(closes)
        for i in (-4, -3, -2):
            vols[i] = 260.0
        x2 = D.series(closes, vols, buy_share=0.35)
        long_only = A.evaluate("SOL", h, x2, CFG)
        self.assertNotEqual(long_only["direction"], "SHORT")
        both = A.evaluate("SOL", h, x2, C.effective({"allow_short": True}))
        self.assertEqual(both["direction"], "SHORT", both["checks"])

    def test_indicator_basics(self):
        self.assertEqual(A.ema([1, 2, 3, 4, 5, 6], 3)[2:], [2.0, 3.0, 4.0, 5.0])
        self.assertEqual(A.rsi([1, 2, 3], 14), None)
        self.assertGreater(A.rsi([float(i) for i in range(1, 40)]), 90)
        self.assertEqual(A.market_regime({"A": "SIDEWAYS", "B": "TRENDING UP", "C": "TRENDING UP"}), "TRENDING UP")
        self.assertEqual(A.market_regime({"A": "SIDEWAYS", "B": "TRENDING UP"}), "SIDEWAYS")     # tie -> no claim


def signal(direction="LONG", **kw):
    """A stored setup created at T0, zone 100.0-100.2, stop 99, tp1 101.5, tp2 103 (long) or mirrored (short)."""
    s = 1 if direction == "LONG" else -1
    row = {"id": "SOL-X-1", "coin": "SOL", "direction": direction, "state": "SETUP", "setup_type": "breakout", "timeframe": "5m", "htf": "15m",
           "regime": "TRENDING UP", "setup_score": 8.0, "quality": "MEDIUM", "created_at": S._iso(at(D.T0)), "expires_at": S._iso(at(D.T0 + 30 * 60_000)),
           "level": 100.0, "entry_low": 100.0 if s > 0 else 99.8, "entry_high": 100.2 if s > 0 else 100.0, "stop": 100 - s * 1.0, "tp1": 100 + s * 1.5, "tp2": 100 + s * 3.0,
           "rr": 1.6, "atr": 1.0, "actual_entry": None, "entry_time": None, "tp1_time": None, "exit_price": None, "exit_time": None, "exit_reason": None,
           "pnl_pct": None, "r_multiple": None, "mfe_pct": None, "mae_pct": None, "duration_min": None, "last_price": 100.1, "checks": [], "reason": "",
           "timeline": [{"ts": S._iso(at(D.T0)), "state": "SETUP", "price": 100.1, "note": "created"}], "manual_close_requested": False, "updated_at": ""}
    row.update(kw)
    return row


def run5(sig, bars, now_min=None, cfg=CFG):
    """Replay `bars` = [(o,h,l,c), ...] as consecutive 5m candles from T0 plus one forming candle; now defaults to just after them."""
    rows = [D.candle(D.T0 + i * 300_000, *b) for i, b in enumerate(bars)]
    forming = D.candle(D.T0 + len(bars) * 300_000, bars[-1][3], bars[-1][3], bars[-1][3], bars[-1][3])
    now = at(D.T0 + (len(bars) * 5 + (now_min if now_min is not None else 1)) * 60_000)
    return L.advance(sig, rows + [forming], now, cfg)


class LifecycleTests(unittest.TestCase):
    def test_entry_then_target_two(self):
        r = run5(signal(), [(100.1, 100.3, 99.9, 100.1), (100.1, 101.6, 100.0, 101.4), (101.4, 103.2, 101.3, 103.0)])
        self.assertEqual((r["state"], r["exit_reason"]), ("TP2_HIT", "tp2"))
        self.assertIsNotNone(r["tp1_time"])
        self.assertAlmostEqual(r["actual_entry"], 100.1)
        # half out at 101.5 (+1.4%), half at 103 (+2.9%) minus 0.2% fees
        self.assertAlmostEqual(r["pnl_pct"], 0.5 * (101.5 / 100.1 - 1) * 100 + 0.5 * (103 / 100.1 - 1) * 100 - 0.2, places=2)
        self.assertGreater(r["r_multiple"], 1.0)
        self.assertGreater(r["mfe_pct"], 2.0)
        self.assertEqual([t["state"] for t in r["timeline"]], ["SETUP", "ACTIVE", "TP1_HIT", "TP2_HIT"])

    def test_entry_then_stop_loss_is_kept_with_a_negative_result(self):
        r = run5(signal(), [(100.1, 100.3, 99.9, 100.1), (100.1, 100.2, 98.8, 99.0)])
        self.assertEqual((r["state"], r["exit_reason"], r["exit_price"]), ("STOP_LOSS", "stop", 99.0))
        self.assertLess(r["pnl_pct"], 0)
        self.assertLess(r["r_multiple"], 0)
        self.assertGreater(r["mae_pct"], 1.0)

    def test_target_one_then_breakeven_is_a_small_win_not_a_loss(self):
        r = run5(signal(), [(100.1, 100.3, 99.9, 100.1), (100.1, 101.6, 100.0, 101.2), (101.2, 101.3, 100.0, 100.3)])
        self.assertEqual((r["state"], r["exit_reason"]), ("TP1_HIT", "tp1_then_breakeven"))
        self.assertAlmostEqual(r["exit_price"], 100.1)
        self.assertGreater(r["pnl_pct"], 0)

    def test_same_candle_touching_stop_and_target_counts_as_the_stop(self):
        r = run5(signal(), [(100.1, 101.8, 98.5, 101.0)])
        self.assertEqual(r["state"], "STOP_LOSS")

    def test_setup_that_is_never_entered_expires_and_is_recorded(self):
        bars = [(100.5, 100.7, 100.4, 100.6)] * 7                        # hovers just above the zone, never enters it
        r = run5(signal(), bars)
        self.assertEqual(r["state"], "EXPIRED")
        self.assertIsNone(r["actual_entry"])
        self.assertIsNone(r["pnl_pct"])                                  # no trade, no P&L
        self.assertIsNotNone(r["exit_time"])

    def test_stop_hit_before_entry_invalidates(self):
        r = run5(signal(), [(99.5, 99.7, 98.5, 98.8)])                   # falls straight through the stop without touching the zone
        self.assertEqual((r["state"], r["exit_reason"]), ("INVALIDATED", "stop_before_entry"))

    def test_target_reached_without_entry_invalidates(self):
        r = run5(signal(), [(101.0, 101.8, 100.5, 101.7)])
        self.assertEqual((r["state"], r["exit_reason"]), ("INVALIDATED", "target_without_entry"))

    def test_price_running_away_invalidates(self):
        r = run5(signal(tp1=110.0, tp2=112.0), [(101.0, 101.7, 100.9, 101.6)])
        self.assertEqual((r["state"], r["exit_reason"]), ("INVALIDATED", "ran_away"))

    def test_active_trade_past_its_time_limit_is_closed_not_left_open(self):
        cfg = C.effective({"trade_max_min": 15})
        bars = [(100.1, 100.3, 99.9, 100.1)] + [(100.1, 100.4, 99.95, 100.2)] * 5
        r = run5(signal(), bars, cfg=cfg)
        self.assertEqual((r["state"], r["exit_reason"]), ("EXPIRED", "time_limit"))
        self.assertIsNotNone(r["pnl_pct"])

    def test_open_trade_stays_open_and_reports_max_excursions(self):
        r = run5(signal(), [(100.1, 100.6, 99.7, 100.3), (100.3, 100.9, 100.0, 100.6)])
        self.assertIsNone(r["exit_time"])
        self.assertEqual(r["state"], "ACTIVE")
        self.assertGreater(r["mfe_pct"], 0.7)
        self.assertGreater(r["mae_pct"], 0.3)

    def test_manual_close_of_an_active_trade_and_of_a_setup(self):
        r = run5(signal(manual_close_requested=True), [(100.1, 100.4, 99.95, 100.3)])
        self.assertEqual((r["state"], r["exit_reason"]), ("CLOSED", "manual"))
        self.assertIsNotNone(r["actual_entry"])
        r2 = run5(signal(manual_close_requested=True), [(100.5, 100.7, 100.4, 100.6)], now_min=1)
        self.assertEqual((r2["state"], r2["actual_entry"], r2["pnl_pct"]), ("CLOSED", None, None))

    def test_replay_is_deterministic_and_never_double_counts(self):
        bars = [(100.1, 100.3, 99.9, 100.1), (100.1, 101.6, 100.0, 101.4), (101.4, 101.5, 100.9, 101.0)]
        a = run5(signal(), bars)
        b = run5(a, bars)                                                # feeding the result back in changes nothing
        for k in ("state", "actual_entry", "tp1_time", "exit_price", "exit_time", "pnl_pct", "mfe_pct", "mae_pct", "timeline"):
            self.assertEqual(a[k], b[k], k)

    def test_short_mirrors_the_long(self):
        r = run5(signal("SHORT"), [(99.9, 100.1, 99.7, 99.9), (99.9, 100.0, 98.3, 98.6), (98.6, 98.7, 96.8, 97.0)])
        self.assertEqual(r["state"], "TP2_HIT")
        self.assertGreater(r["pnl_pct"], 0)
        s2 = run5(signal("SHORT"), [(99.9, 100.1, 99.7, 99.9), (99.9, 101.3, 99.8, 101.0)])
        self.assertEqual(s2["state"], "STOP_LOSS")
        self.assertLess(s2["pnl_pct"], 0)

    def test_gap_through_the_stop_exits_at_the_worse_open(self):
        r = run5(signal(), [(100.1, 100.3, 99.9, 100.1), (98.0, 98.4, 97.8, 98.1)])
        self.assertEqual(r["exit_price"], 98.0)


class AntiSpamTests(unittest.TestCase):
    NOW = at(D.T0 + 3 * 3600_000)

    def finished(self, state="STOP_LOSS", minutes_ago=10, **kw):
        return signal(id="old", state=state, exit_time=S._iso(self.NOW - dt.timedelta(minutes=minutes_ago)), actual_entry=100.1, **kw)

    def test_no_second_signal_while_one_is_open_on_the_same_coin(self):
        self.assertIn("open signal", L.blocked("SOL", "LONG", 100.0, 1.0, [signal()], self.NOW, CFG))
        self.assertIsNone(L.blocked("LINK", "LONG", 100.0, 1.0, [signal()], self.NOW, CFG))

    def test_max_simultaneous_scalps(self):
        rows = [signal(id="a", coin="SOL"), signal(id="b", coin="XRP")]
        self.assertIn("maximum", L.blocked("LINK", "LONG", 100.0, 1.0, rows, self.NOW, CFG))

    def test_cooldown_after_a_finished_signal_and_a_longer_one_after_a_stop(self):
        self.assertIn("cooling", L.blocked("SOL", "LONG", 100.0, 1.0, [self.finished("TP2_HIT", 20)], self.NOW, CFG))
        self.assertIsNone(L.blocked("SOL", "LONG", 100.0, 1.0, [self.finished("TP2_HIT", 40)], self.NOW, CFG))
        self.assertIn("cooling", L.blocked("SOL", "LONG", 100.0, 1.0, [self.finished("STOP_LOSS", 60)], self.NOW, CFG))

    def test_after_a_stop_the_same_setup_is_refused_but_a_new_structure_is_allowed(self):
        row = self.finished("STOP_LOSS", 120)
        self.assertIn("same setup", L.blocked("SOL", "LONG", 100.3, 1.0, [row], self.NOW, CFG))
        self.assertIsNone(L.blocked("SOL", "LONG", 102.5, 1.0, [row], self.NOW, CFG))

    def test_cooldowns_are_configurable(self):
        cfg = C.effective({"cooldown_min": 0, "sl_cooldown_min": 0, "min_level_change_atr": 0})
        self.assertIsNone(L.blocked("SOL", "LONG", 100.0, 1.0, [self.finished("STOP_LOSS", 1)], self.NOW, cfg))


class FakeMarket:
    """fetch(symbol, interval, limit) over canned candles; can simulate a stale or dead feed."""

    def __init__(self, scenario=D.breakout_scenario, stale=False, dead=()):
        self.h, self.x = scenario()
        self.stale, self.dead = stale, set(dead)
        self.now = at(self.x[-1][0] + 60_000)                            # one minute into the forming candle

    def fetch(self, sym, interval, limit):
        if sym in self.dead:
            raise ConnectionError("down")
        return self.h if interval == "15m" else self.x


def run_service(market, store=None, now=None, runtime=None):
    store = store or S.MemoryStore()
    fresh = now or (market.now + dt.timedelta(minutes=45) if market.stale else market.now)
    return store, S.run(store, market.fetch, fresh, runtime)


class ServiceTests(unittest.TestCase):
    def test_a_valid_setup_becomes_one_stored_signal_one_alert_and_a_card(self):
        m = FakeMarket()
        store, (payload, notes, _rt) = run_service(m)
        rows = store.tables["scalp_signals"]
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(r["coin"] in {"SOL", "LINK", "XRP", "ONDO"} for r in rows))
        sol = next(c for c in payload["coins"] if c["symbol"] == "SOL")
        self.assertEqual(sol["state"], "LONG SETUP")
        self.assertEqual(len(sol["checks"]), 7)
        self.assertEqual(payload["market"]["data"], "LIVE")
        self.assertEqual([n["type"] for n in notes if n["portion_key"] == "scalping"].count("scalp_setup"), len(rows))
        self.assertTrue(all(n["portion_key"] == "scalping" for n in notes))

    def test_running_again_does_not_duplicate_signals_or_alerts(self):
        m = FakeMarket()
        store, (_p1, n1, _r) = run_service(m)
        count = len(store.tables["scalp_signals"])
        _, (_p2, n2, _r2) = run_service(m, store=store, now=m.now + dt.timedelta(minutes=2))
        self.assertEqual(len(store.tables["scalp_signals"]), count)
        self.assertEqual([n for n in n2 if n["type"] == "scalp_setup"], [])
        self.assertEqual(len({n["id"] for n in n1}), len(n1))            # deterministic, unique alert ids

    def test_stale_data_pauses_new_signals(self):
        m = FakeMarket(stale=True)
        store, (payload, notes, _r) = run_service(m)
        self.assertEqual(store.tables.get("scalp_signals", []), [])
        self.assertEqual(payload["market"]["data"], "STALE")
        self.assertEqual(payload["market"]["state"], "PAUSED")
        self.assertEqual(notes, [])

    def test_a_dead_feed_is_reported_and_produces_nothing(self):
        m = FakeMarket(dead={"SOL", "LINK", "XRP", "ONDO"})
        store, (payload, _n, _r) = run_service(m)
        self.assertEqual(payload["market"]["data"], "DISCONNECTED")
        self.assertEqual(store.tables.get("scalp_signals", []), [])
        self.assertTrue(all(c["state"] == "NO DATA" for c in payload["coins"]))

    def test_one_dead_coin_does_not_stop_the_others(self):
        m = FakeMarket(dead={"LINK"})
        store, (payload, _n, _r) = run_service(m)
        states = {c["symbol"]: c["state"] for c in payload["coins"]}
        self.assertEqual(states["LINK"], "NO DATA")
        self.assertEqual(states["SOL"], "LONG SETUP")

    def test_admin_settings_change_what_the_engine_does(self):
        m = FakeMarket()
        store = S.MemoryStore()
        store.upsert("scalp_settings", [{"key": "config", "value": {"enabled_coins": ["SOL"], "min_score": 9.9}}], "key")
        _, (payload, _n, _r) = run_service(m, store=store)
        self.assertEqual([c["symbol"] for c in payload["coins"]], ["SOL"])
        self.assertEqual(store.tables.get("scalp_signals", []), [])
        self.assertEqual(payload["config"]["min_score"], 9.9)

    def test_max_simultaneous_limits_new_signals(self):
        m = FakeMarket()
        store = S.MemoryStore()
        store.upsert("scalp_settings", [{"key": "config", "value": {"max_simultaneous": 1}}], "key")
        run_service(m, store=store)
        self.assertEqual(len(store.tables["scalp_signals"]), 1)

    def test_restricted_market_regime_blocks_new_scalps(self):
        m = FakeMarket()
        store = S.MemoryStore()
        store.upsert("scalp_settings", [{"key": "config", "value": {"restricted_regimes": ["TRENDING UP", "BREAKOUT"]}}], "key")
        _, (payload, _n, _r) = run_service(m, store=store)
        self.assertEqual(store.tables.get("scalp_signals", []), [])
        self.assertTrue(payload["market"]["restricted"])
        self.assertEqual(payload["market"]["state"], "RESTRICTED")

    def test_open_signal_is_followed_and_its_outcome_kept_in_history(self):
        m = FakeMarket()
        store, _ = run_service(m)
        sol = next(r for r in store.tables["scalp_signals"] if r["coin"] == "SOL")
        # price collapses through the stop in the next closed candles
        last = m.x[-1]
        t = last[0]
        crash = [D.candle(t + i * 300_000, sol["stop"] + 0.5, sol["stop"] + 0.6, sol["stop"] - 2, sol["stop"] - 1.5, 100) for i in range(0, 3)]
        m.x = m.x[:-1] + crash + [D.candle(t + 3 * 300_000, sol["stop"] - 1.5, sol["stop"] - 1.4, sol["stop"] - 1.6, sol["stop"] - 1.5, 100)]
        _, (payload, notes, _r) = run_service(m, store=store, now=at(m.x[-1][0] + 60_000))
        row = next(r for r in store.tables["scalp_signals"] if r["id"] == sol["id"])
        self.assertIn(row["state"], ("INVALIDATED", "STOP_LOSS"))
        self.assertIsNotNone(row["exit_time"])
        self.assertIn(row["id"], [h["id"] for h in payload["history"]])
        self.assertTrue(any(n["id"].startswith(f"scalp:{row['id']}:") for n in notes))
        self.assertEqual(next(c for c in payload["coins"] if c["symbol"] == "SOL")["state"] in ("STOP LOSS HIT", "INVALIDATED"), True)

    def test_regime_alert_needs_two_consecutive_runs_and_a_meaningful_change(self):
        cfg = C.effective({})
        now = at(D.T0)
        st1, n1 = S._regime_alert({"confirmed": "SIDEWAYS"}, "HIGH VOLATILITY", cfg, now)
        self.assertIsNone(n1)
        st2, n2 = S._regime_alert(st1, "HIGH VOLATILITY", cfg, now)
        self.assertEqual(n2["portion_key"], "scalping")
        self.assertEqual(st2["confirmed"], "HIGH VOLATILITY")
        _, n3 = S._regime_alert({"confirmed": "SIDEWAYS", "candidate": "LOW VOLATILITY", "count": 1}, "LOW VOLATILITY", cfg, now)
        self.assertIsNone(n3)                                            # not a meaningful change: no spam

    def test_alert_toggles_are_respected(self):
        cfg = C.effective({"alerts": {"setup": False}})
        row = signal()
        self.assertEqual(S._alerts_for(None, row, cfg), [])
        prev = copy.deepcopy(row)
        new = dict(row, entry_time=S._iso(at(D.T0)), actual_entry=100.1)
        self.assertEqual([n["type"] for n in S._alerts_for(prev, new, cfg)], ["scalp_entry"])

    def test_price_formatting_has_no_fake_precision(self):
        self.assertEqual(S.fmt_price(185.2049), "185.20")
        self.assertEqual(S.fmt_price(25.2), "25.200")
        self.assertEqual(S.fmt_price(2.9123456), "2.9123")
        self.assertEqual(S.fmt_price(0.9412345), "0.94123")


if __name__ == "__main__":
    unittest.main()
