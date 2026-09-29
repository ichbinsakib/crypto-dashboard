"""Big Movers radar: pure sort/filter of a CoinGecko-style pool, no network, no signal claims."""
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


if __name__ == "__main__":
    unittest.main()
