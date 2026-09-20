import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import market_status as MS  # noqa: E402


def coin(key, price=100, sma50=95, sma200=90, p24=1.0, p7=3.0, p30=8.0, res=130, hi=None, lo=None):
    return {"key": key, "price": price, "sma50": sma50, "sma200": sma200, "pct_24h": p24, "pct_7d": p7, "pct_30d": p30,
            "resistance_30d": res, "support_30d": 80, "high_24h": hi or price * 1.01, "low_24h": lo or price * 0.99}


def klines(range_pct=2.0, vol=100.0, n=40, last_vol=100.0):
    rows = [[i, 100, 100 + range_pct / 2, 100 - range_pct / 2, 100, vol] for i in range(n)]
    rows[-2][5] = last_vol
    return rows


class StatusTests(unittest.TestCase):
    def st(self, btc, eth, kl=None, wy=None, total=None):
        return MS.assess([btc, eth], kl or {"BTC": klines(), "ETH": klines()}, wy or {}, total)

    def test_bullish_trend(self):
        r = self.st(coin("BTC"), coin("ETH"))
        self.assertEqual(r["state"], "BULLISH TREND")
        self.assertTrue(r["line"].startswith("\U0001F7E2 MARKET STATUS: BULLISH TREND — "))

    def test_bearish_trend(self):
        r = self.st(coin("BTC", price=80, p7=-4, p30=-10), coin("ETH", price=80, p7=-5, p30=-12))
        self.assertEqual(r["state"], "BEARISH TREND")

    def test_breakout_at_30_day_high_on_green_day(self):
        r = self.st(coin("BTC", price=130, res=130, p24=2.0), coin("ETH"))
        self.assertEqual(r["state"], "BREAKOUT")

    def test_high_volatility_beats_everything(self):
        big = coin("BTC", price=100, hi=106, lo=98)               # 8% 24h range vs 2% normal
        r = self.st(big, coin("ETH"))
        self.assertEqual(r["state"], "HIGH VOLATILITY")

    def test_distribution_needs_topping_pattern_near_the_highs(self):
        wy = {"BTC": {"stage": "utad", "confidence": "MEDIUM"}}
        r = self.st(coin("BTC", price=125, res=130, p24=-0.5), coin("ETH"), wy=wy)
        self.assertEqual(r["state"], "DISTRIBUTION")
        far = self.st(coin("BTC", price=100, res=130, p24=-0.5), coin("ETH"), wy=wy)      # 23% below the high: not distribution
        self.assertNotEqual(far["state"], "DISTRIBUTION")
        low_conf = {"BTC": {"stage": "utad", "confidence": "LOW"}}
        self.assertNotEqual(self.st(coin("BTC", price=125, res=130, p24=-0.5), coin("ETH"), wy=low_conf)["state"], "DISTRIBUTION")

    def test_sideways_vs_scalping(self):
        flat = dict(price=100, sma50=101, sma200=99, p24=0.2, p7=1.0, p30=2.0)                # mixed votes, tiny moves
        self.assertEqual(self.st(coin("BTC", **flat), coin("ETH", **flat))["state"], "SIDEWAYS")
        busy = {"BTC": klines(vol=100, last_vol=200), "ETH": klines()}                        # volume 2x normal
        self.assertEqual(self.st(coin("BTC", **flat), coin("ETH", **flat), kl=busy)["state"], "SCALPING CONDITIONS")

    def test_btc_and_eth_disagreeing_is_no_clear_signal(self):
        r = self.st(coin("BTC"), coin("ETH", price=80, p7=-5, p30=-10))
        self.assertEqual(r["state"], "NO CLEAR SIGNAL")

    def test_missing_data_never_crashes_and_never_guesses(self):
        self.assertEqual(MS.assess([], {}, {}, None)["state"], "NO CLEAR SIGNAL")
        self.assertEqual(MS.assess([{"key": "BTC", "price": None}], None, None, None)["state"], "NO CLEAR SIGNAL")

    def test_wider_market_caution_note(self):
        r = self.st(coin("BTC"), coin("ETH"), total=-3.5)
        self.assertIn("wider market is down", r["text"])

    def test_html_is_one_line_with_reasons_in_tip(self):
        r = self.st(coin("BTC"), coin("ETH"))
        h = MS.line_html(r, lambda s: s.replace("&", "&amp;").replace('"', "&quot;"))
        self.assertIn('class="market-status ms-bullish"', h)
        self.assertIn("data-tip=", h)
        self.assertEqual(h.count("MARKET STATUS"), 1)


class EntryVerdictTests(unittest.TestCase):
    def st(self, btc, eth, **kw):
        return MS.assess([btc, eth], {"BTC": klines(), "ETH": klines()}, kw.get("wy", {}), kw.get("total"))

    def test_bullish_mid_range_is_a_good_time(self):
        r = self.st(coin("BTC", price=100, res=130), coin("ETH"))
        self.assertEqual((r["state"], r["entry"]), ("BULLISH TREND", "GOOD"))
        self.assertIn("Entry: ✅ GOOD TIME", r["line"])

    def test_bullish_but_right_under_the_high_says_wait_for_a_dip(self):
        r = self.st(coin("BTC", price=127, res=130, p24=-0.3), coin("ETH"))          # 97% of the high, red day: not a breakout
        self.assertEqual((r["state"], r["entry"]), ("BULLISH TREND", "WAIT"))

    def test_bullish_with_a_falling_wider_market_waits(self):
        self.assertEqual(self.st(coin("BTC"), coin("ETH"), total=-3.0)["entry"], "WAIT")

    def test_breakout_is_not_a_chase_entry(self):
        self.assertEqual(self.st(coin("BTC", price=130, res=130, p24=2.0), coin("ETH"))["entry"], "WAIT")

    def test_bearish_distribution_and_volatile_are_bad_times(self):
        self.assertEqual(self.st(coin("BTC", price=80, p7=-4, p30=-10), coin("ETH", price=80, p7=-5, p30=-12))["entry"], "BAD")
        wy = {"BTC": {"stage": "utad", "confidence": "MEDIUM"}}
        self.assertEqual(self.st(coin("BTC", price=125, res=130, p24=-0.5), coin("ETH"), wy=wy)["entry"], "BAD")
        self.assertEqual(self.st(coin("BTC", price=100, hi=106, lo=98), coin("ETH"))["entry"], "BAD")

    def test_no_data_never_says_good(self):
        self.assertEqual(MS.assess([], {}, {}, None)["entry"], "WAIT")

    def test_every_state_has_an_entry_verdict_and_line_stays_one_line(self):
        for r in (self.st(coin("BTC"), coin("ETH")), self.st(coin("BTC"), coin("ETH", price=80, p7=-5, p30=-10))):
            self.assertIn(r["entry"], ("GOOD", "WAIT", "BAD"))
            self.assertNotIn(chr(10), r["line"])


if __name__ == "__main__":
    unittest.main()
