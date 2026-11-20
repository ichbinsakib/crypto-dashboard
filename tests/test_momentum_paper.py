import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import momentum_paper as M


def series(n, start=100.0, step=0.0):
    return [start * (1 + step) ** i for i in range(n)]


def mk(btc_step, alt_steps, n=130, qv=5e6):
    d = {"BTC": {"close": series(n, 100, btc_step), "qv": [qv * 10] * n}}
    for name, s in alt_steps.items():
        d[name] = {"close": series(n, 10, s), "qv": [qv] * n}
    return d


class Regime(unittest.TestCase):
    def test_needs_history_and_trend(self):
        self.assertFalse(M.regime_on(series(50, 100, 0.01)))
        self.assertTrue(M.regime_on(series(130, 100, 0.01)))
        self.assertFalse(M.regime_on(series(130, 100, -0.01)))


class Pick(unittest.TestCase):
    def test_picks_strongest_positive_and_skips_losers(self):
        alts = {"AAA": 0.02, "BBB": 0.01, "CCC": -0.02, "DDD": 0.005}
        # add noise so volatility is non-zero
        d = mk(0.003, alts)
        for k, v in d.items():
            v["close"] = [x * (1 + (0.002 if i % 2 else -0.002)) for i, x in enumerate(v["close"])]
        got = M.pick_momentum(d)
        self.assertNotIn("CCC", got)
        self.assertEqual(got[0], "AAA")

    def test_illiquid_coins_excluded(self):
        d = mk(0.003, {"AAA": 0.02})
        d["AAA"]["qv"] = [1e5] * 130
        d["AAA"]["close"] = [x * (1 + (0.002 if i % 2 else -0.002)) for i, x in enumerate(d["AAA"]["close"])]
        self.assertNotIn("AAA", M.pick_momentum(d))


class Rebalance(unittest.TestCase):
    def test_fee_is_charged_and_equity_conserved_minus_fee(self):
        p = M.new_portfolio()
        M.rebalance(p, ["AAA", "BBB"], {"AAA": 10.0, "BBB": 20.0}, "2026-01-05")
        v = M.value(p, {"AAA": 10.0, "BBB": 20.0})
        self.assertAlmostEqual(v, M.START_CASH * (1 - M.SIDE_COST), places=4)       # all cash -> fully invested costs one side
        self.assertEqual(len(p["trades"]), 2)
        self.assertLess(p["cash"], 1e-6)                                            # no hidden leverage

    def test_unchanged_target_trades_almost_nothing(self):
        p = M.new_portfolio()
        px = {"AAA": 10.0}
        M.rebalance(p, ["AAA"], px, "d1")
        before = M.value(p, px)
        M.rebalance(p, ["AAA"], px, "d2")
        self.assertAlmostEqual(M.value(p, px), before, places=6)

    def test_go_to_cash(self):
        p = M.new_portfolio()
        M.rebalance(p, ["AAA"], {"AAA": 10.0}, "d1")
        M.rebalance(p, [], {"AAA": 10.0}, "d2")
        self.assertEqual(p["units"], {})
        self.assertAlmostEqual(p["cash"], M.START_CASH * (1 - M.SIDE_COST) ** 2, places=3)


class Step(unittest.TestCase):
    def fresh(self):
        return {"version": 1, "started": "2026-01-05", "portfolios": {n: M.new_portfolio() for n in ("momentum", "btc_regime", "btc_hold")}}

    def test_monday_buys_when_regime_on_and_once_per_day(self):
        d = mk(0.003, {"AAA": 0.02, "BBB": 0.01})
        for v in d.values():
            v["close"] = [x * (1 + (0.002 if i % 2 else -0.002)) for i, x in enumerate(v["close"])]
        px = {c: v["close"][-1] for c, v in d.items()}
        s = self.fresh()
        M.step(s, d, px, px, "2026-01-05", True)
        self.assertTrue(s["regime_on"])
        self.assertTrue(s["portfolios"]["momentum"]["units"])
        self.assertIn("BTC", s["portfolios"]["btc_regime"]["units"])
        self.assertIn("BTC", s["portfolios"]["btc_hold"]["units"])
        n = len(s["portfolios"]["momentum"]["trades"])
        M.step(s, d, px, px, "2026-01-05", True)                                     # same day again: no new trades
        self.assertEqual(len(s["portfolios"]["momentum"]["trades"]), n)
        self.assertEqual(len(s["portfolios"]["momentum"]["equity"]), 1)

    def test_regime_off_means_cash_but_btc_hold_stays(self):
        d = mk(-0.003, {"AAA": 0.02})
        px = {c: v["close"][-1] for c, v in d.items()}
        s = self.fresh()
        M.step(s, d, px, px, "2026-01-05", True)
        self.assertFalse(s["regime_on"])
        self.assertEqual(s["portfolios"]["momentum"]["units"], {})
        self.assertEqual(s["portfolios"]["btc_regime"]["units"], {})
        self.assertIn("BTC", s["portfolios"]["btc_hold"]["units"])

    def test_losing_regime_midweek_sells_everything(self):
        up = mk(0.003, {"AAA": 0.02})
        for v in up.values():
            v["close"] = [x * (1 + (0.002 if i % 2 else -0.002)) for i, x in enumerate(v["close"])]
        px = {c: v["close"][-1] for c, v in up.items()}
        s = self.fresh()
        M.step(s, up, px, px, "2026-01-05", True)
        down = mk(-0.01, {"AAA": 0.02})
        px2 = {c: v["close"][-1] for c, v in down.items()}
        M.step(s, down, px2, px2, "2026-01-06", False)                               # Tuesday, BTC fell under its average
        self.assertEqual(s["portfolios"]["momentum"]["units"], {})
        self.assertEqual(s["portfolios"]["btc_regime"]["units"], {})

    def test_summary_shape(self):
        s = self.fresh()
        px = {"BTC": 100.0}
        for p in s["portfolios"].values():
            p["equity"] = [["d1", 10000.0], ["d2", 11000.0], ["d3", 9900.0]]
        out = M.summary(s, px)
        self.assertEqual(out["portfolios"]["momentum"]["return_pct"], -1.0)
        self.assertEqual(out["portfolios"]["momentum"]["max_drawdown_pct"], -10.0)


if __name__ == "__main__":
    unittest.main()
