"""Derivatives fallbacks. No network. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import derivatives as D  # noqa: E402


class FakeGet:
    def __init__(self, routes):
        self.routes = routes

    def __call__(self, url, timeout=15):
        for frag, val in self.routes.items():
            if frag in url:
                if isinstance(val, Exception):
                    raise val
                return val
        raise OSError("no route " + url)


class DerivativesTests(unittest.TestCase):
    def setUp(self):
        self.saved = D._get

    def tearDown(self):
        D._get = self.saved

    def test_aster_premium_shape(self):
        D._get = FakeGet({"premiumIndex": {"markPrice": "81400.1", "indexPrice": "81440.2", "lastFundingRate": "0.0001"}})
        p = D.aster_premium("BTCUSDT")
        self.assertEqual(sorted(p), ["indexPrice", "lastFundingRate", "markPrice"])
        D._get = FakeGet({"premiumIndex": {"symbol": "X"}})
        with self.assertRaises(ValueError):
            D.aster_premium("XUSDT")

    def test_okx_premium_combines_three_calls(self):
        D._get = FakeGet({"mark-price": {"data": [{"markPx": "81389.2"}]}, "index-tickers": {"data": [{"idxPx": "81423.1"}]},
                          "funding-rate": {"data": [{"fundingRate": "0.0001"}]}})
        self.assertEqual(D.okx_premium("BTC"), {"markPrice": "81389.2", "indexPrice": "81423.1", "lastFundingRate": "0.0001"})

    def test_okx_oi_removes_the_price_move(self):
        hist = [[str(i * 3600000), str(100.0 + i), "1"] for i in range(30)]                # USD OI grows 100 -> 129
        D._get = FakeGet({"public/open-interest": {"data": [{"oiCcy": "30900"}]}, "rubik": {"data": list(reversed(hist))}})
        r = D.okx_oi("BTC", pct_24h=0.0)
        self.assertEqual(r["oi_now"], 30900.0)
        self.assertAlmostEqual(r["oi_change_pct"], (129 / 106 - 1) * 100, places=3)          # last vs 24 samples earlier
        r2 = D.okx_oi("BTC", pct_24h=10.0)
        self.assertLess(r2["oi_change_pct"], r["oi_change_pct"])                             # part of the rise was just price

    def test_okx_oi_short_history_raises(self):
        D._get = FakeGet({"public/open-interest": {"data": [{"oiCcy": "1"}]}, "rubik": {"data": [["1", "1", "1"]] * 3}})
        with self.assertRaises(ValueError):
            D.okx_oi("BTC")


if __name__ == "__main__":
    unittest.main()
