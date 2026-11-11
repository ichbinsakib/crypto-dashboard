"""Evidence scorecard: conservative verdicts, and the result is always shown without the single best trade."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scorecard as S  # noqa: E402


def tr(pct, day, direction="LONG"):
    entry = 100.0
    exit_price = entry * (1 + pct / 100) if direction == "LONG" else entry * (1 - pct / 100)
    return {"entry": entry, "exit_price": exit_price, "direction": direction, "resolved_at": f"2026-10-{day:02d}T00:00:00"}


class ScorecardTests(unittest.TestCase):
    def test_no_trades(self):
        self.assertEqual(S.scorecard([])["verdict"]["level"], "none")

    def test_a_short_that_falls_is_a_win(self):
        sc = S.scorecard([tr(5, 1, "SHORT")], fee_pct=0.2)
        self.assertAlmostEqual(sc["avg"], 4.8)

    def test_few_trades_is_never_called_promising(self):
        sc = S.scorecard([tr(10, d) for d in range(1, 21)])
        self.assertEqual(sc["verdict"]["level"], "early")

    def test_enough_losing_trades_says_no_edge(self):
        rows = [tr(-1, 1 + i % 28) for i in range(120)]
        self.assertEqual(S.scorecard(rows)["verdict"]["level"], "bad")
        self.assertIn("Do not trade real money", S.scorecard(rows)["verdict"]["why"])

    def test_a_record_carried_by_one_trade_is_flagged(self):
        rows = [tr(-2, 1 + i % 28) for i in range(110)] + [tr(500, 20)]
        sc = S.scorecard(rows)
        self.assertGreater(sc["total"], 0)                   # positive overall...
        self.assertLess(sc["total_ex_best"], 0)              # ...but not without the best trade
        self.assertEqual(sc["verdict"]["title"], "RESULT RESTS ON ONE TRADE")

    def test_steady_positive_record_is_promising_not_proven(self):
        rows = [tr(3 if i % 2 else -1, 1 + i % 28) for i in range(120)]
        self.assertEqual(S.scorecard(rows)["verdict"]["level"], "promising")

    def test_streak_and_drawdown(self):
        rows = [tr(5, 1), tr(-3, 2), tr(-3, 3), tr(-3, 4), tr(5, 5)]
        sc = S.scorecard(rows, fee_pct=0.0)
        self.assertEqual(sc["worst_streak"], 3)
        self.assertAlmostEqual(sc["max_drawdown"], 9.0)

    def test_html_shows_the_verdict_and_the_without_best_figure(self):
        h = S.scorecard_html(S.scorecard([tr(-1, 1 + i % 28) for i in range(120)]), "Trend")
        self.assertIn("NO EDGE SO FAR", h)
        self.assertIn("Total without best trade", h)


if __name__ == "__main__":
    unittest.main()
