import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import metrics as M  # noqa: E402


def candle(close, high=None, low=None, vol=100.0, quote=None, taker_buy_quote=None):
    high = high if high is not None else close * 1.01
    low = low if low is not None else close * 0.99
    quote = quote if quote is not None else vol * close
    tb = taker_buy_quote if taker_buy_quote is not None else quote / 2
    return [0, close, high, low, close, vol, 0, quote, 0, 0, tb, 0]


class MetricsTest(unittest.TestCase):
    def test_volume_ratio(self):
        ks = [candle(100, vol=10) for _ in range(30)] + [candle(100, vol=30) for _ in range(3)]
        self.assertGreater(M.volume_ratio(ks, 30), 1.5)
        self.assertIsNone(M.volume_ratio(ks[:5], 30))

    def test_taker_delta(self):
        ks = [candle(100, quote=1000, taker_buy_quote=750) for _ in range(3)]
        self.assertAlmostEqual(M.taker_delta_usd(ks), 1500)
        self.assertIsNone(M.taker_delta_usd([[1, 2, 3, 4, 5, 6]] * 3))

    def test_depth_ratio(self):
        depth = {"bids": [["99.5", "10"], ["90", "500"]], "asks": [["100.5", "5"]]}
        self.assertAlmostEqual(M.depth_ratio(depth, 100), 995 / 502.5)
        self.assertIsNone(M.depth_ratio({"bids": [["99.5", "1"]], "asks": []}, 100))

    def test_score_and_regime(self):
        self.assertEqual(M.score_100(-1), 40)
        self.assertEqual(M.score_100(9), 100)
        self.assertEqual(M.regime_word("RISK-ON"), "BULLISH")
        self.assertEqual(M.regime_word(None), "N/A")

    def test_compute_and_display_never_invent(self):
        ks = [candle(100 + i * 0.1) for i in range(60)]
        m = M.compute("BTC", "15m", 30, 105.9, ks)
        self.assertIsNone(m["fut_vr"])
        self.assertIsNone(m["ldr"])
        rows = dict(M.display_rows(m, "BUY", "60/100", "15 Min", "2026-01-01 10:00 UTC", "$105.9"))
        self.assertEqual(rows["Futures VR"], "n/a")
        self.assertEqual(rows["Symbol"], "BTCUSDT")
        self.assertEqual(rows["Timeframe"], "15 Min")
        self.assertIn("Time", rows)
        self.assertIn("%", rows["Typical candle move"])


if __name__ == "__main__":
    unittest.main()
