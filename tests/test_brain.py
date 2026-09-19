"""Tests for the course 'brain' (patterns + checklist). Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from brain import course, patterns as P  # noqa: E402


def k(o, h, l, c, v=100):
    return [0, o, h, l, c, v]


def flat(n, price=100.0):
    return [k(price, price + 0.5, price - 0.5, price) for _ in range(n)]


class PatternTests(unittest.TestCase):
    def test_bullish_fvg_detected_and_unfilled(self):
        c = flat(30) + [k(100, 101, 99.8, 100.8), k(101, 106, 100.9, 105.5), k(105.5, 107, 104, 106.5)]
        gaps = [g for g in P.fair_value_gaps(c) if g["type"] == "bull"]
        self.assertTrue(gaps)
        self.assertEqual((gaps[0]["low"], gaps[0]["high"]), (101, 104))     # high of candle 1 .. low of candle 3
        self.assertFalse(gaps[0]["filled"])

    def test_fvg_filled_when_price_returns(self):
        c = flat(30) + [k(100, 101, 99.8, 100.8), k(101, 106, 100.9, 105.5), k(105.5, 107, 104, 106.5), k(106, 106, 100, 101)]
        self.assertTrue([g for g in P.fair_value_gaps(c) if g["type"] == "bull"][0]["filled"])

    def test_fvg_retest_zone(self):
        c = flat(30) + [k(100, 101, 99.8, 100.8), k(101, 106, 100.9, 105.5), k(105.5, 107, 104, 106.5), k(106, 106.2, 103.5, 103.8)]
        self.assertTrue(P.fvg_retest(c)["in_zone"])

    def test_uptrend_structure_and_ema_bias(self):
        c = []
        for i in range(120):
            base = 100 + i * 0.5 + (2 if i % 8 < 4 else 0)          # rising with pullbacks
            c.append(k(base, base + 1, base - 1, base + 0.2))
        self.assertEqual(P.structure(c)["trend"], "up")
        self.assertEqual(P.ema_bias(c)["bias"], "bull")

    def test_downtrend_is_bear(self):
        c = [k(200 - i * 0.5, 201 - i * 0.5, 199 - i * 0.5, 199.8 - i * 0.5) for i in range(120)]
        self.assertEqual(P.ema_bias(c)["bias"], "bear")

    def test_parabolic_and_volume_spike(self):
        c = flat(40) + [k(100 + i * 3, 101 + i * 3, 99 + i * 3, 102 + i * 3, 100) for i in range(12)]
        c[-1][5] = 1000
        self.assertTrue(P.parabolic(c)["parabolic"])
        self.assertTrue(P.volume_spike(c)["spike"])
        self.assertFalse(P.parabolic(flat(40))["parabolic"])

    def test_fib_golden_zone(self):
        c = flat(5, 100)
        c += [k(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(20)]          # up-leg 100 -> ~121
        c += [k(120, 120, 107, 108)]                                               # pullback to ~0.5 retracement
        f = P.fib_position(c)
        self.assertTrue(f["valid"] and f["golden_zone"], f)

    def test_position_size_rule(self):
        r = P.position_size(1000, 1.0, 100, 95)
        self.assertAlmostEqual(r["risk_amount"], 10)
        self.assertAlmostEqual(r["units"] * 5, 10)                                # losing 5 per unit at the stop => 10 total
        self.assertIsNone(P.position_size(1000, 1, 100, 100))


class CourseTests(unittest.TestCase):
    def test_curriculum_loaded(self):
        self.assertGreaterEqual(len(course.CURRICULUM), 18)
        self.assertTrue(course.module("Fair Value"))
        self.assertTrue(course.module("Leverage")[0]["points"])

    def test_checklist_flags_bad_plans(self):
        bad = course.pre_trade_checklist(entry=100, stop=None, leverage=20, hours_to_next_high_event=3, trend="down")
        failed = {c["rule"] for c in bad if not c["ok"]}
        self.assertIn("Stop loss defined before entry", failed)
        self.assertIn("Leverage at or below 5x", failed)
        self.assertIn("No fresh leverage right before major news", failed)
        self.assertIn("Prefer trading with the trend", failed)

    def test_checklist_passes_good_plan(self):
        good = course.pre_trade_checklist(entry=100, stop=98, targets=[103, 106], account=1000, leverage=1,
                                          hours_to_next_high_event=72, trend="up")
        self.assertTrue(all(c["ok"] for c in good), good)

    def test_backtest_notes_present(self):
        self.assertTrue(any("do not gate" in n for n in course.BACKTEST_NOTES))


if __name__ == "__main__":
    unittest.main()
