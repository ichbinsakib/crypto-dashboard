"""Plain-English classifiers and cycle/heat heuristics, extracted from dashboard.py.
Previously only exercised indirectly through render()/btc_dashboard tests; direct coverage now."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import classify as C  # noqa: E402


class ClassifyPriceStructureTests(unittest.TestCase):
    def test_none_is_unknown(self):
        self.assertEqual(C.classify_price_structure(1.0, None), ("Unknown", "neutral"))

    def test_parabolic_needs_both_a_hot_week_and_a_hot_day(self):
        self.assertEqual(C.classify_price_structure(5.0, 20.0)[1], "bearish")
        self.assertEqual(C.classify_price_structure(1.0, 20.0)[1], "bullish")   # just a strong uptrend, not parabolic

    def test_uptrend_downtrend_range(self):
        self.assertEqual(C.classify_price_structure(0, 10.0), ("Uptrend", "bullish"))
        self.assertEqual(C.classify_price_structure(0, -10.0), ("Downtrend", "bearish"))
        self.assertEqual(C.classify_price_structure(0, 0.0), ("Range / Consolidation", "neutral"))


class ClassifyFundingTests(unittest.TestCase):
    def test_none_is_na(self):
        self.assertEqual(C.classify_funding(None), ("N/A", "neutral"))

    def test_overheated_squeeze_and_neutral(self):
        self.assertEqual(C.classify_funding(0.0004)[1], "bearish")
        self.assertEqual(C.classify_funding(-0.0002)[1], "bullish")
        self.assertEqual(C.classify_funding(0.0001)[1], "neutral")


class ClassifyOiTests(unittest.TestCase):
    def test_missing_data_is_na(self):
        self.assertEqual(C.classify_oi(None, 1.0), ("N/A", "neutral"))

    def test_spot_led_rally_vs_leverage_buildup(self):
        self.assertEqual(C.classify_oi(0.5, 2.0)[1], "bullish")
        self.assertEqual(C.classify_oi(4.0, 2.0)[1], "bearish")

    def test_long_flush_and_short_buildup_are_neutral_reads(self):
        self.assertEqual(C.classify_oi(-2.0, -2.0)[1], "neutral")
        self.assertEqual(C.classify_oi(3.0, -2.0)[1], "neutral")


class ClassifyPremiumTests(unittest.TestCase):
    def test_missing_or_zero_index_is_na(self):
        self.assertEqual(C.classify_premium(None, 100.0), ("N/A", "neutral"))
        self.assertEqual(C.classify_premium(100.0, 0), ("N/A", "neutral"))

    def test_elevated_backwardation_healthy_and_flat(self):
        self.assertEqual(C.classify_premium(103.1, 100.0)[1], "bearish")   # 31 bps
        self.assertEqual(C.classify_premium(98.8, 100.0)[1], "bearish")    # -12 bps
        self.assertEqual(C.classify_premium(100.06, 100.0)[1], "bullish")  # 6 bps
        self.assertEqual(C.classify_premium(100.02, 100.0)[1], "neutral")  # 2 bps


class ClassifyFngTests(unittest.TestCase):
    def test_none_is_na(self):
        self.assertEqual(C.classify_fng(None, "Neutral"), ("N/A", "neutral"))

    def test_extremes_are_contrarian_signals(self):
        self.assertEqual(C.classify_fng(80, "Extreme Greed")[1], "bearish")
        self.assertEqual(C.classify_fng(20, "Extreme Fear")[1], "bullish")
        self.assertEqual(C.classify_fng(50, "Neutral")[1], "neutral")


class ClassifyLiquidationRiskTests(unittest.TestCase):
    def test_missing_data_is_na(self):
        self.assertEqual(C.classify_liquidation_risk(None, 1.0), ("N/A (model estimate)", "neutral"))

    def test_crowded_long_and_short(self):
        self.assertEqual(C.classify_liquidation_risk(0.04, 4.0)[1], "bearish")
        self.assertEqual(C.classify_liquidation_risk(-0.03, 4.0)[1], "bullish")
        self.assertEqual(C.classify_liquidation_risk(0.01, 1.0)[1], "neutral")


class CycleStageTests(unittest.TestCase):
    def test_missing_price_or_sma200_is_unknown(self):
        self.assertEqual(C.cycle_stage(None, 90, 100, 5), "Unknown")

    def test_distribution_markup_markdown_accumulation(self):
        self.assertEqual(C.cycle_stage(150, 95, 100, 20), "Distribution")   # 50% above sma200, hot month
        self.assertEqual(C.cycle_stage(110, 95, 100, 10), "Markup")
        self.assertEqual(C.cycle_stage(80, 95, 100, -15), "Markdown")
        self.assertEqual(C.cycle_stage(100, 95, 100, 0), "Accumulation")


class HeatScoreTests(unittest.TestCase):
    def test_no_inputs_gives_none(self):
        self.assertIsNone(C.heat_score(None, None, None, None))

    def test_averages_the_available_parts_and_clamps_to_0_10(self):
        # pct_30d=200 would clamp to 10, fng=100 -> 10: average of just these two is 10.0
        self.assertEqual(C.heat_score(200, None, None, 100), 10.0)
        self.assertEqual(C.heat_score(-200, None, None, 0), 0.0)


if __name__ == "__main__":
    unittest.main()
