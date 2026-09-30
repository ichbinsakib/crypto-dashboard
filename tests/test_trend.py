import datetime
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import momentum as M  # noqa: E402

H4 = 4 * 3600 * 1000


def rows(closes, t0=0, spread=0.01):
    return [[t0 + i * H4, c, c * (1 + spread), c * (1 - spread), c, 100.0] for i, c in enumerate(closes)]


def uptrend_then_break():
    closes = [100 + i * 0.05 for i in range(280)]            # gentle uptrend, flat-ish highs
    closes[-2] = max(closes) * 1.06                           # last CLOSED candle breaks out
    closes[-1] = closes[-2]                                   # forming candle
    return closes


def downtrend_then_break():
    closes = [300 - i * 0.05 for i in range(280)]            # gentle downtrend, flat-ish lows
    closes[-2] = min(closes) * 0.94                           # last CLOSED candle breaks down
    closes[-1] = closes[-2]                                   # forming candle
    return closes


class TrendSignalTest(unittest.TestCase):
    def test_fires_shortly_after_breakout_close(self):
        k = rows(uptrend_then_break())
        now = k[-1][0] + 10 * 60000                           # forming candle is 10 min old
        s = M.compute_trend_signal(k, 80, "", now_ms=now)
        self.assertEqual(s["status"], "momentum")
        self.assertIsNone(s["trade"]["target1"])
        self.assertLess(s["trade"]["stop"], s["price"])

    def test_stale_breakout_does_not_fire(self):
        k = rows(uptrend_then_break())
        s = M.compute_trend_signal(k, 80, "", now_ms=k[-1][0] + 3 * 3600 * 1000)
        self.assertEqual(s["status"], "none")
        self.assertIn("fresh", s["failed"])

    def test_below_200_average_does_not_fire(self):
        closes = [200.0] * 150 + [100.0] * 130                # crashed, now basing far below its 200 average
        closes[-2] = 101.6
        k = rows(closes)
        s = M.compute_trend_signal(k, 80, "", now_ms=k[-1][0] + 60000)
        self.assertIn("above_ema200", s["failed"])

    def test_too_little_data(self):
        self.assertIsNone(M.compute_trend_signal(rows([1.0] * 50), 80))

    def test_short_fires_on_a_downside_breakout_below_a_falling_200_average(self):
        k = rows(downtrend_then_break())
        now = k[-1][0] + 10 * 60000
        s = M.compute_trend_signal(k, 80, "", now_ms=now, direction="SHORT")
        self.assertEqual(s["status"], "momentum", s["failed"])
        self.assertEqual(s["direction"], "SHORT")
        self.assertGreater(s["trade"]["stop"], s["price"])          # stop sits above entry for a short

    def test_short_does_not_fire_on_an_uptrend(self):
        k = rows(uptrend_then_break())
        s = M.compute_trend_signal(k, 80, "", now_ms=k[-1][0] + 10 * 60000, direction="SHORT")
        self.assertEqual(s["status"], "none")
        self.assertIn("breakout", s["failed"])
        self.assertIn("above_ema200", s["failed"])


class TrendTrackerTest(unittest.TestCase):
    def _open(self, now, entry=100.0, atr=1.0):
        return {"open": {"4h:AAA": {"coin": "AAA", "name": "Aaa", "tf": "4h", "kind": "trend", "entry": entry, "stop": entry - 4 * atr,
                                    "stop0": entry - 4 * atr, "target1": None, "target2": None, "net1": None, "atr": atr,
                                    "opened_at": (now - datetime.timedelta(hours=40)).isoformat()}}, "resolved": []}

    def _open_short(self, now, entry=100.0, atr=1.0):
        return {"open": {"4h:AAA": {"coin": "AAA", "name": "Aaa", "tf": "4h", "kind": "trend", "direction": "SHORT",
                                    "entry": entry, "stop": entry + 4 * atr, "stop0": entry + 4 * atr, "target1": None,
                                    "target2": None, "net1": None, "atr": atr,
                                    "opened_at": (now - datetime.timedelta(hours=40)).isoformat()}}, "resolved": []}

    def _klines(self, now, closes):
        base = int((now - datetime.timedelta(hours=len(closes) * 4)).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        return rows(closes, t0=base, spread=0.004)

    def test_trailing_stop_ratchets_and_exits_in_profit(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        closes = [100 + i * 0.5 for i in range(20)] + [100 + 19 * 0.5 - 8] * 3   # run up ~9.5, then a drop through the trail
        k = self._klines(now, closes)
        st, opened, done = M.update_tracker(self._open(now), [], lambda s, i, l=None: k, now=now, sleep=0)
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["result"], "win")
        self.assertGreater(done[0]["exit_price"], 100)

    def test_open_position_keeps_ratcheted_stop_and_no_false_stopout(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        closes = [100 + i * 0.5 for i in range(10)]
        k = self._klines(now, closes)
        st, opened, done = M.update_tracker(self._open(now), [], lambda s, i, l=None: k, now=now, sleep=0)
        self.assertEqual(done, [])
        self.assertGreaterEqual(st["open"]["4h:AAA"]["stop"], 96.0)
        self.assertEqual(st["open"]["4h:AAA"]["stop0"], 96.0)

    def test_short_trailing_stop_ratchets_down_and_exits_in_profit(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        closes = [100 - i * 0.5 for i in range(20)] + [100 - 19 * 0.5 + 8] * 3   # falls ~9.5, then a bounce through the trail
        k = self._klines(now, closes)
        st, opened, done = M.update_tracker(self._open_short(now), [], lambda s, i, l=None: k, now=now, sleep=0)
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["result"], "win")            # price fell, so a short exiting below entry is a win
        self.assertLess(done[0]["exit_price"], 100)

    def test_short_stop_loss_when_price_rises_through_the_initial_stop(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        closes = [100 + i * 2.0 for i in range(10)]            # rallies hard against the short
        k = self._klines(now, closes)
        st, opened, done = M.update_tracker(self._open_short(now), [], lambda s, i, l=None: k, now=now, sleep=0)
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["result"], "loss")
        self.assertGreater(done[0]["exit_price"], 100)

    def test_stats_treats_a_short_price_drop_as_a_positive_net(self):
        rows_ = [{"result": "win", "entry": 100, "exit_price": 90, "direction": "SHORT", "coin": "A", "tf": "4h", "opened_at": "o1", "resolved_at": "r1"}]
        s = M.stats(rows_)
        self.assertAlmostEqual(s["avg_net"], (100 - 90) / 100 * 100 - M.FEE_PCT)

    def test_cooldown_after_trend_loss_is_48h(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        res = [{"coin": "AAA", "tf": "4h", "result": "loss", "resolved_at": (now - datetime.timedelta(hours=30)).isoformat()}]
        self.assertIn("4h:AAA", M.cooling(res, now))
        res[0]["resolved_at"] = (now - datetime.timedelta(hours=60)).isoformat()
        self.assertNotIn("4h:AAA", M.cooling(res, now))

    def test_a_call_that_never_hits_the_stop_expires_after_1600h(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        closes = [100 + i * 0.01 for i in range(10)]           # drifts up a little, never touches the trailing stop
        k = self._klines(now, closes)
        opened_long_ago = self._open(now, entry=100.0)
        opened_long_ago["open"]["4h:AAA"]["opened_at"] = (now - datetime.timedelta(hours=1601)).isoformat()
        st, opened, done = M.update_tracker(opened_long_ago, [], lambda s, i, l=None: k, now=now, sleep=0)
        self.assertEqual([r["result"] for r in done], ["expired"])
        self.assertEqual(st["open"], {})

    def test_fetch_failure_leaves_the_position_open_for_a_retry(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)

        def boom(sym, interval, limit=None):
            raise RuntimeError("down")
        st, opened, done = M.update_tracker(self._open(now), [], boom, now=now, sleep=0)
        self.assertEqual(len(st["open"]), 1)
        self.assertEqual(done, [])

    def test_a_fresh_signal_is_not_reopened_while_already_open(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        sig = {"symbol": "AAA", "name": "Aaa", "tf": "4h", "kind": "trend", "atr": 1.0,
               "trade": {"entry": 100.0, "stop": 96.0, "target1": None, "target2": None, "target1NetPct": None}, "checks": {}}
        st, opened, done = M.update_tracker(self._open(now), [sig], lambda s, i, l=None: self._klines(now, [100.0] * 5), now=now, sleep=0)
        self.assertEqual(opened, [])
        self.assertEqual(len(st["open"]), 1)


class ScanTrendTest(unittest.TestCase):
    def test_scan_skips_symbols_with_no_liquid_pair_and_tags_the_timeframe(self):
        closes = uptrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4    # forming candle timestamped "now" so the freshness check passes
        k = rows(closes, t0=t0)

        def fetch(sym, interval, limit=None):
            if sym == "NOPE":
                raise ValueError("no pair")
            return k
        pool = [{"symbol": "AAA", "name": "A"}, {"symbol": "nope", "name": "N"}, {"symbol": "SKIP", "name": "S"}]
        found = M.scan(pool, "4h", fetch, skip_symbols={"SKIP"}, sleep=0)
        self.assertEqual([f["symbol"] for f in found], ["AAA"])
        self.assertEqual(found[0]["tf"], "4h")

    def test_short_is_ignored_unless_allow_short_is_set(self):
        closes = downtrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4
        k = rows(closes, t0=t0)
        pool = [{"symbol": "AAA", "name": "A"}]
        self.assertEqual(M.scan(pool, "4h", lambda sym, interval, limit=None: k, sleep=0), [])
        found = M.scan(pool, "4h", lambda sym, interval, limit=None: k, sleep=0, allow_short=True)
        self.assertEqual([f["symbol"] for f in found], ["AAA"])
        self.assertEqual(found[0]["direction"], "SHORT")

    def test_a_pinned_coin_is_checked_even_when_not_in_the_pool_at_all(self):
        # QNT and MOVR each had a real, rule-qualifying breakout that was never scanned because
        # neither was in the pool that run -- a pinned coin must be checked regardless of the pool.
        closes = uptrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4
        k = rows(closes, t0=t0)
        found = M.scan([], "4h", lambda sym, interval, limit=None: k, sleep=0, pinned=["MOVR"])
        self.assertEqual([f["symbol"] for f in found], ["MOVR"])

    def test_a_pinned_coin_still_respects_skip_symbols(self):
        closes = uptrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4
        k = rows(closes, t0=t0)
        found = M.scan([], "4h", lambda sym, interval, limit=None: k, skip_symbols={"MOVR"}, sleep=0, pinned=["MOVR"])
        self.assertEqual(found, [])

    def test_pinned_coins_are_not_double_checked_by_the_random_draw(self):
        closes = uptrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4
        k = rows(closes, t0=t0)
        calls = []

        def fetch(sym, interval, limit=None):
            calls.append(sym)
            return k
        pool = [{"symbol": "MOVR", "name": "Moonriver"}]
        found = M.scan(pool, "4h", fetch, sleep=0, pinned=["MOVR"], max_new=5, attempts=40)
        self.assertEqual(calls, ["MOVR"])          # checked once, via the pinned path, not again by the pool scan
        self.assertEqual(found[0]["name"], "Moonriver")   # name still resolved from the pool entry

    def test_pinned_coins_do_not_exceed_max_new(self):
        closes = uptrend_then_break()
        t0 = int(time.time() * 1000) - (len(closes) - 1) * H4
        k = rows(closes, t0=t0)
        found = M.scan([], "4h", lambda sym, interval, limit=None: k, sleep=0, pinned=["AAA", "BBB", "CCC"], max_new=2)
        self.assertEqual(len(found), 2)


class PriceTextTests(unittest.TestCase):
    def test_tiny_prices_keep_distinguishing_digits(self):
        self.assertEqual(M.price_text(81704.3), "$81,704")
        self.assertEqual(M.price_text(2.6499), "$2.65")
        self.assertEqual(M.price_text(0.0901), "$0.0901")
        entry, stop, target = 0.0000063, 0.0000062, 0.0000065
        self.assertEqual(len({M.price_text(entry), M.price_text(stop), M.price_text(target)}), 3)
        self.assertEqual(M.price_text(None), "n/a")


class StatsAndNotificationsTest(unittest.TestCase):
    def test_stats_summarizes_wins_losses_and_average_net(self):
        rows_ = [{"result": "win", "entry": 100, "exit_price": 101.5, "coin": "A", "tf": "4h", "opened_at": "o1", "resolved_at": "r1"},
                 {"result": "loss", "entry": 100, "exit_price": 99.0, "coin": "B", "tf": "4h", "opened_at": "o2", "resolved_at": "r2"}]
        s = M.stats(rows_)
        self.assertEqual((s["wins"], s["losses"], s["win_rate"]), (1, 1, 50.0))
        self.assertAlmostEqual(s["avg_net"], ((1.5 - 0.2) + (-1.0 - 0.2)) / 2)

    def test_notification_events_describe_the_trailing_stop_not_a_fixed_target(self):
        pos = {"coin": "A", "tf": "4h", "entry": 100, "stop": 96, "risk_pct": 4.0, "opened_at": "2026-09-19T13:00:00", "kind": "trend"}
        rows_ = [{"result": "win", "entry": 100, "exit_price": 101.5, "coin": "A", "tf": "4h", "opened_at": "o1", "resolved_at": "r1"}]
        ev = M.notification_events([pos], rows_)
        self.assertEqual(ev[0]["type"], "signal")
        self.assertIn("trailing stop", ev[0]["body"])
        self.assertIn("no fixed target", ev[0]["body"])
        self.assertEqual(ev[0]["portion_key"], "screener")
        self.assertEqual({e["type"] for e in ev[1:]}, {"win"})
        self.assertEqual(len({e["id"] for e in ev}), 2)


if __name__ == "__main__":
    unittest.main()
