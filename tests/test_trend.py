import datetime
import os
import sys
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


class TrendTrackerTest(unittest.TestCase):
    def _open(self, now, entry=100.0, atr=1.0):
        return {"open": {"4h:AAA": {"coin": "AAA", "name": "Aaa", "tf": "4h", "kind": "trend", "entry": entry, "stop": entry - 4 * atr,
                                    "stop0": entry - 4 * atr, "target1": None, "target2": None, "net1": None, "atr": atr,
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

    def test_cooldown_after_trend_loss_is_48h(self):
        now = datetime.datetime(2026, 9, 20, 12, 0)
        res = [{"coin": "AAA", "tf": "4h", "result": "loss", "resolved_at": (now - datetime.timedelta(hours=30)).isoformat()}]
        self.assertIn("4h:AAA", M.cooling(res, now))
        res[0]["resolved_at"] = (now - datetime.timedelta(hours=60)).isoformat()
        self.assertNotIn("4h:AAA", M.cooling(res, now))


if __name__ == "__main__":
    unittest.main()
