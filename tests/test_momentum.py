"""Momentum tier: signal rules, tracker, cooldown, notifications, HTML. Run: python -m unittest discover -s tests"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import momentum as M  # noqa: E402

STEP = 900_000  # 15m in ms


def bars(n=96, start=100.0, slope=0.3, vol=100, t0=0):
    out, p = [], start
    for i in range(n):
        out.append([t0 + i * STEP, p, p + 0.5, p - 1.0, p + slope, vol])
        p += slope
    return out


def with_breakout(vol_last=200, jump=1.2):
    k = bars()
    last = float(k[-1][4])
    n = len(k)
    for j in range(3):                      # last three candles carry the volume
        k[-1 - j][5] = vol_last
    k.append([n * STEP, last, last + jump + 0.3, last - 0.5, last + jump, vol_last])
    return k


class SignalTests(unittest.TestCase):
    def test_breakout_qualifies(self):
        s = M.compute_momentum_signal(with_breakout(), 30)
        self.assertEqual(s["status"], "momentum", s["failed"])
        t = s["trade"]
        self.assertLess(t["stop"], t["entry"])
        self.assertGreater(t["target1"], t["entry"])
        self.assertGreater(t["target1NetPct"], M.MIN_NET_PCT)
        self.assertEqual(s["score"], 7)

    def test_each_rule_can_veto(self):
        no_volume = M.compute_momentum_signal(with_breakout(vol_last=100), 30)
        self.assertIn("volume", no_volume["failed"])
        k = with_breakout()
        k[-1][4] = float(k[-2][4]) - 0.2    # closes below the prior high: no breakout
        self.assertIn("breakout", M.compute_momentum_signal(k, 30)["failed"])
        chase = with_breakout(jump=6.0)      # broke out and already ran far past the level
        self.assertIn("fresh", M.compute_momentum_signal(chase, 30)["failed"])
        down = [[i * STEP, 200 - i * 0.3, 200.5 - i * 0.3, 199 - i * 0.3, 199.7 - i * 0.3, 100] for i in range(100)]
        self.assertIn("trend", M.compute_momentum_signal(down, 30)["failed"])

    def test_not_enough_data(self):
        self.assertIsNone(M.compute_momentum_signal(bars(20), 30))
        self.assertIsNone(M.compute_momentum_signal([], 30))


NOW = datetime.datetime(2026, 9, 19, 13, 0)


def sig(sym="AAA", tf="15m", price=100.0, atr=1.0):
    return {"symbol": sym, "name": sym, "tf": tf, "trade": {"entry": price, "stop": price - atr, "target1": price + 1.5 * atr,
                                                            "target2": price + 3 * atr, "target1NetPct": 1.3}}


def candle(t_dt, lo, hi, close):
    ms = t_dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000
    return [ms, close, hi, lo, close, 100]


class TrackerTests(unittest.TestCase):
    def open_one(self, **kw):
        state, opened, res = M.update_tracker({}, [sig(**kw)], lambda s, i: [], now=NOW, sleep=0)
        return state, opened

    def test_opens_once_and_dedupes(self):
        state, opened = self.open_one()
        self.assertEqual(len(opened), 1)
        state2, opened2, _ = M.update_tracker(state, [sig()], lambda s, i: [candle(NOW, 99.9, 100.2, 100.1)], now=NOW + datetime.timedelta(minutes=5), sleep=0)
        self.assertEqual(opened2, [])
        self.assertEqual(len(state2["open"]), 1)

    def test_win_uses_candles_since_open_not_just_price(self):
        state, _ = self.open_one()
        # a spike to the target between runs, and price back near entry now: still a win
        ks = [candle(NOW - datetime.timedelta(minutes=30), 90, 200, 100),      # before the call: ignored
              candle(NOW + datetime.timedelta(minutes=5), 99.5, 101.6, 100.4)]
        s2, _, resolved = M.update_tracker(state, [], lambda s, i: ks, now=NOW + datetime.timedelta(minutes=15), sleep=0)
        self.assertEqual([r["result"] for r in resolved], ["win"])
        self.assertEqual(s2["open"], {})

    def test_loss_and_conservative_same_candle(self):
        state, _ = self.open_one()
        ks = [candle(NOW + datetime.timedelta(minutes=5), 98.5, 101.8, 100)]   # touches both stop (99) and target (101.5)
        _, _, resolved = M.update_tracker(state, [], lambda s, i: ks, now=NOW + datetime.timedelta(minutes=15), sleep=0)
        self.assertEqual(resolved[0]["result"], "loss")

    def test_expiry_and_cooldown_blocks_resignal(self):
        state, _ = self.open_one()
        ks = [candle(NOW + datetime.timedelta(minutes=5), 99.5, 100.5, 100.2)]
        later = NOW + datetime.timedelta(hours=7)                               # 15m calls expire after 6h
        s2, _, resolved = M.update_tracker(state, [sig()], lambda s, i: ks, now=later, sleep=0)
        self.assertEqual(resolved[0]["result"], "expired")
        self.assertEqual(s2["open"], {})                                        # same coin not re-opened during cooldown
        self.assertIn("15m:AAA", M.cooling(s2["resolved"], later + datetime.timedelta(hours=1)))
        self.assertNotIn("15m:AAA", M.cooling(s2["resolved"], later + datetime.timedelta(hours=7)))

    def test_fetch_failure_keeps_position_open(self):
        state, _ = self.open_one()

        def boom(s, i):
            raise RuntimeError("down")
        s2, _, resolved = M.update_tracker(state, [], boom, now=NOW + datetime.timedelta(minutes=10), sleep=0)
        self.assertEqual(len(s2["open"]), 1)
        self.assertEqual(resolved, [])


class PriceTextTests(unittest.TestCase):
    def test_tiny_prices_keep_distinguishing_digits(self):
        self.assertEqual(M.price_text(81704.3), "$81,704")
        self.assertEqual(M.price_text(2.6499), "$2.65")
        self.assertEqual(M.price_text(0.0901), "$0.0901")
        entry, stop, target = 0.0000063, 0.0000062, 0.0000065
        self.assertEqual(len({M.price_text(entry), M.price_text(stop), M.price_text(target)}), 3)
        self.assertEqual(M.price_text(None), "n/a")


class ScanAndOutputTests(unittest.TestCase):
    def test_scan_skips_and_tolerates_missing_pairs(self):
        good = with_breakout()

        def fetch(sym, interval):
            if sym == "NOPE":
                raise ValueError("no pair")
            return good
        pool = [{"symbol": "AAA", "name": "A"}, {"symbol": "nope", "name": "N"}, {"symbol": "SKIP", "name": "S"}]
        found = M.scan(pool, "15m", fetch, skip_symbols={"SKIP"}, sleep=0)
        self.assertEqual([f["symbol"] for f in found], ["AAA"])
        self.assertEqual(found[0]["tf"], "15m")

    def test_stats_and_notifications(self):
        rows = [{"result": "win", "entry": 100, "exit_price": 101.5, "coin": "A", "tf": "15m", "opened_at": "o1", "resolved_at": "r1"},
                {"result": "loss", "entry": 100, "exit_price": 99.0, "coin": "B", "tf": "1h", "opened_at": "o2", "resolved_at": "r2"}]
        s = M.stats(rows)
        self.assertEqual((s["wins"], s["losses"], s["win_rate"]), (1, 1, 50.0))
        self.assertAlmostEqual(s["avg_net"], ((1.5 - 0.2) + (-1.0 - 0.2)) / 2)
        pos = {"coin": "A", "tf": "15m", "entry": 100, "stop": 99, "target1": 101.5, "opened_at": "2026-09-19T13:00:00"}
        ev = M.notification_events([pos], rows)
        self.assertEqual(ev[0]["type"], "signal")
        self.assertIn("experimental", ev[0]["title"])
        self.assertEqual(ev[0]["portion_key"], "screener")
        self.assertEqual({e["type"] for e in ev[1:]}, {"win", "loss"})
        self.assertEqual(len({e["id"] for e in ev}), 3)

    def test_panel_html_states_and_escaping(self):
        empty = M.panel_html({}, now=NOW)
        self.assertIn("EXPERIMENTAL", empty)
        self.assertIn("No coin has just broken", empty)
        self.assertIn("no proven edge", empty)
        st = {"open": {"15m:<b>X": {"coin": "<b>X", "tf": "15m", "entry": 1.0, "stop": 0.99, "target1": 1.015, "net1": 1.3,
                                   "opened_at": (NOW - datetime.timedelta(minutes=7)).isoformat()}}, "resolved": []}
        html = M.panel_html(st, now=NOW)
        self.assertIn("&lt;b&gt;X", html)
        self.assertNotIn("<b>X", html)
        self.assertIn("7m ago", html)


if __name__ == "__main__":
    unittest.main()
