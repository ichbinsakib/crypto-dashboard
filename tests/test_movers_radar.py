"""Big Movers radar: pure sort/filter of a Binance ticker list or a CoinGecko-style pool, no
network, no signal claims."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from events import movers_radar as R  # noqa: E402


def coin(symbol, pct24, pct1h=1.0, pct7d=10.0, price=1.0):
    return {"symbol": symbol, "name": symbol.title(), "current_price": price,
            "price_change_percentage_1h_in_currency": pct1h,
            "price_change_percentage_24h_in_currency": pct24,
            "price_change_percentage_7d_in_currency": pct7d}


def ticker(symbol, pct24, price=1.0, quote_volume=10_000_000):
    return {"symbol": symbol, "lastPrice": str(price), "priceChangePercent": str(pct24), "quoteVolume": str(quote_volume)}


class TopMoversTests(unittest.TestCase):
    def test_empty_pool_gives_empty_lists_not_an_error(self):
        out = R.top_movers([])
        self.assertEqual(out["gainers"], [])
        self.assertEqual(out["losers"], [])

    def test_none_pool_is_tolerated(self):
        out = R.top_movers(None)
        self.assertEqual(out["gainers"], [])

    def test_gainers_are_sorted_biggest_first(self):
        pool = [coin("a", 5.0), coin("b", 54.0), coin("c", 12.0)]
        out = R.top_movers(pool)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["B", "C", "A"])

    def test_losers_are_sorted_worst_first_and_exclude_gainers(self):
        pool = [coin("a", -5.0), coin("b", 54.0), coin("c", -22.0)]
        out = R.top_movers(pool)
        self.assertEqual([r["symbol"] for r in out["losers"]], ["C", "A"])
        self.assertNotIn("B", [r["symbol"] for r in out["losers"]])

    def test_a_flat_or_all_green_pool_yields_no_losers(self):
        pool = [coin("a", 1.0), coin("b", 2.0)]
        out = R.top_movers(pool)
        self.assertEqual(out["losers"], [])

    def test_coins_with_no_24h_pct_are_skipped_not_guessed(self):
        pool = [coin("a", 5.0), {"symbol": "b", "name": "B", "current_price": 1.0}]
        out = R.top_movers(pool)
        self.assertEqual(len(out["gainers"]), 1)

    def test_result_is_capped_at_top_n(self):
        pool = [coin(str(i), float(i)) for i in range(1, 30)]
        out = R.top_movers(pool, top_n=5)
        self.assertEqual(len(out["gainers"]), 5)

    def test_disclaimer_warns_against_chasing_an_already_extended_move(self):
        out = R.top_movers([coin("a", 5.0)])
        self.assertIn("chasing", out["disclaimer"].lower())

    def test_symbol_is_uppercased_and_pct24_is_rounded(self):
        pool = [coin("qnt", 54.0612)]
        out = R.top_movers(pool)
        self.assertEqual(out["gainers"][0]["symbol"], "QNT")
        self.assertEqual(out["gainers"][0]["pct_24h"], 54.1)


class TopMoversBinanceTests(unittest.TestCase):
    def test_only_usdt_pairs_are_considered(self):
        tickers = [ticker("QNTUSDT", 54.0), ticker("QNTBTC", 90.0), ticker("QNTETH", 90.0)]
        out = R.top_movers_binance(tickers)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["QNT"])

    def test_stablecoins_and_fiat_pairs_are_excluded(self):
        tickers = [ticker("QNTUSDT", 5.0), ticker("USDCUSDT", 0.01), ticker("EURUSDT", 0.2), ticker("BUSDUSDT", 0.0)]
        out = R.top_movers_binance(tickers)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["QNT"])

    def test_leveraged_tokens_are_excluded(self):
        tickers = [ticker("QNTUSDT", 5.0), ticker("BTCUPUSDT", 40.0), ticker("BTCDOWNUSDT", -40.0), ticker("ETHBULLUSDT", 30.0)]
        out = R.top_movers_binance(tickers)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["QNT"])

    def test_illiquid_pairs_below_the_volume_floor_are_excluded(self):
        tickers = [ticker("QNTUSDT", 5.0, quote_volume=10_000_000), ticker("DUSTUSDT", 900.0, quote_volume=1000)]
        out = R.top_movers_binance(tickers)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["QNT"])

    def test_gainers_and_losers_sort_correctly(self):
        tickers = [ticker("AAAUSDT", 5.0), ticker("BBBUSDT", 54.0), ticker("CCCUSDT", -22.0)]
        out = R.top_movers_binance(tickers, top_n=2)
        self.assertEqual([r["symbol"] for r in out["gainers"]], ["BBB", "AAA"])
        self.assertEqual([r["symbol"] for r in out["losers"]], ["CCC"])

    def test_pct_1h_and_pct_7d_are_not_available_from_binance(self):
        out = R.top_movers_binance([ticker("QNTUSDT", 54.0)])
        self.assertIsNone(out["gainers"][0]["pct_1h"])
        self.assertIsNone(out["gainers"][0]["pct_7d"])

    def test_empty_or_missing_ticker_list_is_tolerated(self):
        self.assertEqual(R.top_movers_binance([]), R.top_movers_binance(None))
        self.assertEqual(R.top_movers_binance(None)["gainers"], [])


class LiquidPoolTests(unittest.TestCase):
    def test_sorted_by_volume_descending_and_shaped_like_the_coingecko_pool_cache(self):
        tickers = [ticker("AAAUSDT", 1.0, quote_volume=5_000_000), ticker("BBBUSDT", 1.0, quote_volume=50_000_000),
                   ticker("CCCUSDT", 1.0, quote_volume=20_000_000)]
        pool = R.liquid_pool(tickers, limit=10)
        self.assertEqual([p["symbol"] for p in pool], ["bbb", "ccc", "aaa"])
        self.assertEqual(pool[0], {"id": None, "symbol": "bbb", "name": "BBB"})

    def test_stablecoins_fiat_and_leveraged_tokens_are_excluded(self):
        tickers = [ticker("AAAUSDT", 1.0), ticker("USDCUSDT", 1.0), ticker("EURUSDT", 1.0), ticker("BTCUPUSDT", 1.0)]
        pool = R.liquid_pool(tickers, limit=10)
        self.assertEqual([p["symbol"] for p in pool], ["aaa"])

    def test_result_is_capped_at_limit(self):
        tickers = [ticker(f"C{i}USDT", 1.0, quote_volume=float(i)) for i in range(20)]
        pool = R.liquid_pool(tickers, limit=5)
        self.assertEqual(len(pool), 5)

    def test_empty_or_missing_tickers_gives_an_empty_pool(self):
        self.assertEqual(R.liquid_pool([], 10), [])
        self.assertEqual(R.liquid_pool(None, 10), [])


class BuildReportTests(unittest.TestCase):
    def test_binance_is_used_when_it_has_data(self):
        report = R.build_report(binance_tickers=[ticker("QNTUSDT", 54.0)], coingecko_pool=[coin("ltc", 1.0)])
        self.assertEqual([r["symbol"] for r in report["gainers"]], ["QNT"])

    def test_falls_back_to_coingecko_when_binance_is_unavailable(self):
        report = R.build_report(binance_tickers=None, coingecko_pool=[coin("ltc", 5.0)])
        self.assertEqual([r["symbol"] for r in report["gainers"]], ["LTC"])

    def test_falls_back_to_coingecko_when_binance_yields_no_rows(self):
        report = R.build_report(binance_tickers=[ticker("USDCUSDT", 0.01)], coingecko_pool=[coin("ltc", 5.0)])
        self.assertEqual([r["symbol"] for r in report["gainers"]], ["LTC"])

    def test_both_unavailable_gives_an_empty_report_not_an_error(self):
        report = R.build_report(binance_tickers=None, coingecko_pool=None)
        self.assertEqual(report["gainers"], [])
        self.assertEqual(report["losers"], [])


if __name__ == "__main__":
    unittest.main()
