"""build_coin_data's source priority for BTC/ETH: Binance (ticker + daily klines) is primary,
CoinGecko is a fallback for whichever piece Binance fails to provide, and the futures index price
/ cached values are the last resort. No network: every fetch is monkeypatched."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dashboard as D  # noqa: E402

COIN = {"key": "BTC", "name": "Bitcoin", "cg_id": "bitcoin", "symbol": "BTCUSDT", "emoji": "₿"}
PREV = {"price": 70000.0, "high_24h": 71000.0, "low_24h": 69000.0, "pct_24h": 1.0, "pct_7d": 2.0, "pct_30d": 3.0,
        "mark_price": 70050.0, "index_price": 70060.0, "funding_rate": 0.0001, "sma50": 1, "sma200": 1,
        "support_30d": 1, "resistance_30d": 1, "oi_change_pct": 1, "oi_now": 1}
TICK = {"lastPrice": "70123.45", "highPrice": "71000.0", "lowPrice": "69000.0", "priceChangePercent": "1.75"}
MARKETS = {"bitcoin": {"current_price": 70555.0, "high_24h": 71500.0, "low_24h": 69500.0,
                       "price_change_percentage_24h_in_currency": 1.5,
                       "price_change_percentage_7d_in_currency": 2.5,
                       "price_change_percentage_30d_in_currency": 3.5}}


def daily_closes(n=210, start=60000.0, step=50.0):
    """[openTime, open, high, low, close, volume]-shaped rows, close ramping linearly."""
    return [[i, start + i * step, start + i * step + 10, start + i * step - 10, start + i * step, 100.0] for i in range(n)]


def _raise(*a, **k):
    raise RuntimeError("down")


class BuildCoinDataPriceFallbackTests(unittest.TestCase):
    def setUp(self):
        self._orig = {"premium": D.fetch_binance_premium, "chart": D.fetch_market_chart, "oi": D.fetch_binance_oi_hist,
                       "ticker": D.fetch_binance_ticker24hr, "ohlc": D.fetch_binance_ohlc,
                       "aster": D.deriv_mod.aster_premium, "okx": D.deriv_mod.okx_premium, "okx_oi": D.deriv_mod.okx_oi}
        D.fetch_market_chart = lambda cg_id: _raise()
        D.fetch_binance_oi_hist = lambda symbol: _raise()
        D.deriv_mod.okx_oi = lambda key, pct: None
        D.fetch_binance_premium = lambda symbol: {"markPrice": "70200.5", "indexPrice": "70210.25", "lastFundingRate": "0.0001"}

    def tearDown(self):
        D.fetch_binance_premium = self._orig["premium"]
        D.fetch_market_chart = self._orig["chart"]
        D.fetch_binance_oi_hist = self._orig["oi"]
        D.fetch_binance_ticker24hr = self._orig["ticker"]
        D.fetch_binance_ohlc = self._orig["ohlc"]
        D.deriv_mod.aster_premium = self._orig["aster"]
        D.deriv_mod.okx_premium = self._orig["okx"]
        D.deriv_mod.okx_oi = self._orig["okx_oi"]

    def test_binance_ticker_and_daily_klines_are_used_when_both_are_up(self):
        D.fetch_binance_ticker24hr = lambda pair: TICK
        D.fetch_binance_ohlc = lambda key, interval, limit=100: daily_closes()
        out = D.build_coin_data(COIN, {}, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70123.45)
        self.assertEqual(out["high_24h"], 71000.0)
        self.assertEqual(out["pct_24h"], 1.75)
        self.assertNotIn("price", out["stale"])
        self.assertNotIn("24h range / % change", out["stale"])
        self.assertNotIn("moving averages / range", out["stale"])
        closes = [r[4] for r in daily_closes()]
        self.assertAlmostEqual(out["pct_7d"], (closes[-1] / closes[-8] - 1) * 100)
        self.assertAlmostEqual(out["pct_30d"], (closes[-1] / closes[-31] - 1) * 100)
        self.assertAlmostEqual(out["sma50"], sum(closes[-50:]) / 50)
        self.assertEqual(out["support_30d"], min(closes[-30:]))
        self.assertEqual(out["resistance_30d"], max(closes[-30:]))

    def test_binance_ticker_down_falls_back_to_coingecko_price_but_keeps_binance_history(self):
        D.fetch_binance_ticker24hr = lambda pair: _raise()
        D.fetch_binance_ohlc = lambda key, interval, limit=100: daily_closes()
        out = D.build_coin_data(COIN, MARKETS, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70555.0)          # from CoinGecko
        self.assertNotIn("price", out["stale"])
        closes = [r[4] for r in daily_closes()]
        self.assertAlmostEqual(out["pct_7d"], (closes[-1] / closes[-8] - 1) * 100)   # from Binance, not CoinGecko's 2.5

    def test_binance_daily_klines_down_falls_back_to_coingecko_chart_for_history(self):
        D.fetch_binance_ticker24hr = lambda pair: TICK
        D.fetch_binance_ohlc = lambda key, interval, limit=100: _raise()
        D.fetch_market_chart = lambda cg_id: [60000.0 + i * 10 for i in range(210)]
        out = D.build_coin_data(COIN, MARKETS, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70123.45)          # from Binance ticker
        self.assertEqual(out["pct_7d"], 2.5)              # from CoinGecko markets (Binance daily unavailable)
        self.assertNotIn("moving averages / range", out["stale"])

    def test_both_price_sources_down_falls_back_to_the_live_futures_index_price(self):
        D.fetch_binance_ticker24hr = lambda pair: _raise()
        D.fetch_binance_ohlc = lambda key, interval, limit=100: _raise()
        out = D.build_coin_data(COIN, {}, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], 70210.25)
        self.assertNotIn("price", out["stale"])
        self.assertIn("24h range / % change", out["stale"])
        self.assertIn("moving averages / range", out["stale"])

    def test_everything_down_falls_back_to_the_cached_price(self):
        D.fetch_binance_premium = lambda symbol: _raise()
        D.deriv_mod.aster_premium = lambda symbol: _raise()
        D.deriv_mod.okx_premium = lambda key: _raise()
        D.fetch_binance_ticker24hr = lambda pair: _raise()
        D.fetch_binance_ohlc = lambda key, interval, limit=100: _raise()
        out = D.build_coin_data(COIN, {}, 50, "Neutral", {"BTC": PREV})
        self.assertEqual(out["price"], PREV["price"])
        self.assertIn("price", out["stale"])


if __name__ == "__main__":
    unittest.main()
