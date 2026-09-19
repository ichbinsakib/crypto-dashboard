"""Aster DEX context for the scanner. No network. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aster as A  # noqa: E402

PREM = [{"symbol": "XRPUSDT", "markPrice": "1.4400", "indexPrice": "1.4380", "lastFundingRate": "0.0001"},
        {"symbol": "HOTUSDT", "markPrice": "1.0", "indexPrice": "1.0", "lastFundingRate": "0.0009"},
        {"symbol": "BTCUSD", "markPrice": "1", "indexPrice": "1", "lastFundingRate": "0"},          # not a USDT perpetual
        {"symbol": "BADUSDT", "markPrice": "x", "indexPrice": "1", "lastFundingRate": "0"}]           # malformed row is skipped
TICK = [{"symbol": "XRPUSDT", "quoteVolume": "1500000", "priceChangePercent": "8.1"}]


class AsterTests(unittest.TestCase):
    def setUp(self):
        A.SNAPSHOT = A.parse_snapshot(PREM, TICK)

    def test_parse(self):
        self.assertEqual(sorted(A.SNAPSHOT), ["HOT", "XRP"])
        x = A.SNAPSHOT["XRP"]
        self.assertAlmostEqual(x["funding_pct"], 0.01)
        self.assertAlmostEqual(x["basis_bps"], (1.44 - 1.438) / 1.438 * 1e4, places=3)
        self.assertEqual(x["quote_volume"], 1500000.0)

    def test_lookup_flags(self):
        self.assertIsNone(A.lookup("NOPE", 1.0))
        ok = A.lookup("XRP", 1.4390)
        self.assertEqual(ok["flags"], [])
        hot = A.lookup("HOT", 1.0)
        self.assertEqual(hot["flags"], ["crowded longs"])
        gap = A.lookup("XRP", 1.20)                                   # Binance price far from Aster mark
        self.assertIn("price mismatch between venues", gap["flags"])
        self.assertGreater(gap["price_gap_pct"], 2)

    def test_card_html(self):
        self.assertEqual(A.card_html(None), "")
        html = A.card_html(A.lookup("HOT", 1.0))
        self.assertIn("Aster perpetual", html)
        self.assertIn("Caution: crowded longs", html)
        self.assertIn("does not change the score", html)
        self.assertNotIn("Caution", A.card_html(A.lookup("XRP", 1.439)))

    def test_refresh_failure_leaves_empty_snapshot(self):
        saved = A._get
        A._get = lambda path, timeout=15: (_ for _ in ()).throw(OSError("down"))
        try:
            self.assertEqual(A.refresh(), {})
        finally:
            A._get = saved


if __name__ == "__main__":
    unittest.main()
