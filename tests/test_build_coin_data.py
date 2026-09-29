"""build_coin_data's price fallback: when CoinGecko is down, prefer this run's own live futures
index price over a possibly-hours-old cached spot price. No network: every fetch is monkeypatched."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dashboard as D  # noqa: E402

COIN = {"key": "BTC", "name": "Bitcoin", "cg_id": "bitcoin", "symbol": "BTCUSDT", "emoji": "₿"}
PREV = {"price": 70000.0, "high_24h": 71000.0, "low_24h": 69000.0, "pct_24h": 1.0, "pct_7d": 2.0, "pct_30d": 3.0,
        "mark_price": 70050.0, "index_price": 70060.0, "funding_rate": 0.0001, "sma50": 1, "sma200": 1,
        "support_30d": 1, "resistance_30d": 1, "oi_change_pct": 1, "oi_now": 1}


def _no_chart():
    raise RuntimeError("chart down")


def _no_oi(symbol):
    raise RuntimeError("oi down")


class BuildCoinDataPriceFallbackTests(unittest.TestCase):
    def setUp(self):
        self._orig_premium = D.fetch_binance_premium
        self._orig_chart = D.fetch_market_chart
        self._orig_oi = D.fetch_binance_oi_hist
        self._orig_aster = D.deriv_mod.aster_premium
        self._orig_okx = D.deriv_mod.okx_premium
        self._orig_okx_oi = D.deriv_mod.okx_oi
        D.fetch_market_chart = lambda cg_id: _no_chart()
        D.fetch_binance_oi_hist = lambda symbol: _no_oi(symbol)
        D.deriv_mod.okx_oi = lambda key, pct: None

    def tearDown(self):
        D.fetch_binance_premium = self._orig_premium
        D.fetch_market_chart = self._orig_chart
        D.fetch_binance_oi_hist = self._orig_oi
        D.deriv_mod.aster_premium = self._orig_aster
        D.deriv_mod.okx_premium = self._orig_okx
        D.deriv_mod.okx_oi = self._orig_okx_oi

    def test_coingecko_down_but_futures_up_uses_the_live_index_price_not_a_stale_cache(self):
        D.fetch_binance_premium = lambda symbol: {"markPrice": "70200.5", "indexPrice": "70210.25", "lastFundingRate": "0.0001"}
        out = D.build_coin_data(COIN, {}, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70210.25)
        self.assertNotIn("price", out["stale"])
        self.assertIn("24h range / % change", out["stale"])
        # figures CoinGecko alone provides still fall back to the cache, unchanged
        self.assertEqual(out["high_24h"], PREV["high_24h"])
        self.assertEqual(out["pct_24h"], PREV["pct_24h"])

    def test_coingecko_and_all_futures_sources_down_falls_back_to_the_cached_price(self):
        D.fetch_binance_premium = lambda symbol: (_ for _ in ()).throw(RuntimeError("binance down"))
        D.deriv_mod.aster_premium = lambda symbol: (_ for _ in ()).throw(RuntimeError("aster down"))
        D.deriv_mod.okx_premium = lambda key: (_ for _ in ()).throw(RuntimeError("okx down"))
        out = D.build_coin_data(COIN, {}, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], PREV["price"])
        self.assertIn("price", out["stale"])

    def test_coingecko_success_is_used_regardless_of_futures_state(self):
        D.fetch_binance_premium = lambda symbol: {"markPrice": "70200.5", "indexPrice": "70210.25", "lastFundingRate": "0.0001"}
        markets = {"bitcoin": {"current_price": 70555.0, "high_24h": 71500.0, "low_24h": 69500.0,
                               "price_change_percentage_24h_in_currency": 1.5,
                               "price_change_percentage_7d_in_currency": 2.5,
                               "price_change_percentage_30d_in_currency": 3.5}}
        out = D.build_coin_data(COIN, markets, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70555.0)
        self.assertNotIn("price", out["stale"])
        self.assertNotIn("24h range / % change", out["stale"])


if __name__ == "__main__":
    unittest.main()
