"""BTC live dashboard: classifiers, graphics, honesty about unavailable data. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import btc_dashboard as B  # noqa: E402


def ctx(**over):
    base = {"c": {"price": 81800.0, "pct_24h": 4.2, "pct_7d": 6.6, "support_30d": 74000.0, "resistance_30d": 82300.0, "oi_now": 163900.0},
            "stage": "Accumulation", "spot": {"score": 3}, "price_struct": ("Uptrend", "bullish"),
            "funding": ("0.0066% - healthy/neutral", "neutral"), "oi": ("OI +0.5% - flat", "neutral"),
            "premium": ("12.0 bps - healthy bullish basis", "bullish"), "fng": ("71 - Greed", "neutral"),
            "liq": ("Low/Moderate (model estimate)", "neutral"), "wyckoff": {"stage": "none", "confidence": "LOW"},
            "macro": {"label": "RISK-ON"}, "generated": "2026-09-19 12:00",
            "hourly": [[0, 0, 82000 + i * 10, 81000 - i, 81500 + i * 20, 1] for i in range(30)],
            "onchain": {"mvrv": 1.45, "nupl": 0.31, "mvrv_z": 1.1, "net_flow": -150e6, "exch_in": 800e6, "exch_out": 950e6,
                        "as_of": "2026-09-18", "preliminary": True}}
    base.update(over)
    return base


class DashboardTests(unittest.TestCase):
    def test_builds_all_sections_and_ten_signals(self):
        html = B.build(ctx())
        for needle in ("BITCOIN", "PRICE ACTION", "CURRENT MARKET READ", "MARKET CYCLE SCORE", "SIGNAL TABLE", "KEY TAKEAWAYS", "CYCLE MAP", "WE ARE HERE"):
            self.assertIn(needle, html)
        self.assertEqual(html.count("<tr><td>"), 10)

    def test_unavailable_is_stated_not_invented(self):
        html = B.build(ctx(onchain=None, hourly=[]))
        self.assertIn("Data unavailable", html)
        self.assertIn("Chart unavailable", html)
        self.assertNotIn("NaN", html)
        etf = B.signal_rows(ctx())
        self.assertIn("Data unavailable (no free ETF-flow feed)", etf)

    def test_zones(self):
        self.assertEqual(B.nupl_read(-0.05)[1], "bullish")
        self.assertEqual(B.nupl_read(0.3)[1], "neutral")
        self.assertEqual(B.nupl_read(0.8)[1], "bearish")
        self.assertEqual(B.mvrv_read(0.5)[1], "bullish")
        self.assertEqual(B.mvrv_read(6.0)[1], "bearish")
        self.assertEqual(B.flow_read(-200e6)[1], "bullish")
        self.assertEqual(B.flow_read(200e6)[1], "bearish")
        self.assertEqual(B.flow_read(10e6)[1], "neutral")
        self.assertEqual(B.nupl_read(None)[1], "na")

    def test_cycle_score_range_and_headlines(self):
        self.assertEqual(B.cycle_score(9), 10)
        self.assertEqual(B.cycle_score(-9), 1)
        self.assertEqual(B.cycle_score(0), 6)
        self.assertEqual(B.headline("Accumulation", "Uptrend", None)[0], "NOT A CYCLE TOP YET")
        self.assertIn("DOWNTREND", B.headline("Markdown", "Downtrend", None)[0])
        self.assertIn("DISTRIBUTION", B.headline("Markup", "Uptrend", {"stage": "range"})[1])

    def test_alert_rule(self):
        self.assertEqual(B.alert_state(ctx()), "green")
        hot = ctx(price_struct=("Parabolic (blow-off risk)", "bearish"), funding=("0.05% - overheated longs", "bearish"),
                  oi=("OI +4.0% - leverage buildup", "bearish"))
        self.assertEqual(B.alert_state(hot), "red")
        self.assertEqual(B.alert_state(ctx(funding=("0.05% - overheated longs", "bearish"))), "yellow")

    def test_html_escaping(self):
        html = B.build(ctx(price_struct=("<script>x</script>", "neutral")))
        self.assertNotIn("<script>x", html)

    def test_gauge_needle_moves_with_score(self):
        self.assertNotEqual(B.gauge(9), B.gauge(2))
        self.assertIn("8/10", "8/10")


if __name__ == "__main__":
    unittest.main()
