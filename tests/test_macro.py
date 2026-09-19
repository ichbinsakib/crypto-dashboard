"""Tests for cross-market rows and the macro regime. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import macro  # noqa: E402


def mk(sym, pct=None, abs_=None, price=1.0, unit="index", group="Macro"):
    return {"symbol": sym, "group": group, "price": price, "change_pct": pct, "change_abs": abs_, "unit": unit, "note": None}


class RegimeTests(unittest.TestCase):
    def test_risk_on(self):
        rows = [mk("DXY", -0.5), mk("US10Y", None, -0.06), mk("NDX", 1.0), mk("STABLE.C.D", -1.0), mk("TOTAL", 3.0)]
        r = macro.macro_regime(rows)
        self.assertEqual((r["label"], r["score"]), ("RISK-ON", 5))
        self.assertEqual(macro.spot_factor(r)[0], 2)

    def test_risk_off(self):
        rows = [mk("DXY", 0.6), mk("US10Y", None, 0.08), mk("NDX", -1.2), mk("STABLE.C.D", 1.0), mk("TOTAL", -3.0)]
        r = macro.macro_regime(rows)
        self.assertEqual((r["label"], r["score"]), ("RISK-OFF", -5))
        self.assertEqual(macro.spot_factor(r)[0], -2)

    def test_mixed_and_flat(self):
        r = macro.macro_regime([mk("DXY", 0.0), mk("US10Y", None, 0.0), mk("NDX", 0.1), mk("TOTAL", 0.5)])
        self.assertEqual((r["label"], macro.spot_factor(r)[0]), ("MIXED", 0))

    def test_missing_data_is_not_guessed(self):
        r = macro.macro_regime([mk("DXY", -0.5)])
        self.assertEqual(r["label"], "NOT ENOUGH DATA")
        self.assertEqual(macro.spot_factor(r)[0], 0)
        self.assertIn("DXY", [f["symbol"] for f in r["factors"]])
        self.assertIn("NDX", r["missing"])
        self.assertEqual(macro.spot_factor(None)[0], 0)


class TotalsTests(unittest.TestCase):
    def cg(self):
        def coin(sym, cap, chg):
            return {"symbol": sym, "market_cap": cap, "market_cap_change_24h": chg}
        markets = [coin("btc", 1000, 40), coin("eth", 300, 15), coin("usdt", 200, 0)] + [coin(f"a{i}", 50, 1) for i in range(10)]
        return {"global": {"total_market_cap": {"usd": 1900}}, "markets": markets,
                "stables": [coin("usdt", 200, 0), coin("usdc", 100, 0)]}

    def test_totals_are_consistent(self):
        t = macro.crypto_totals(self.cg())
        self.assertAlmostEqual(t["TOTAL"]["price"], 2000)                       # global (1900) lags per-coin sum (2000)
        self.assertAlmostEqual(t["TOTAL3"]["price"], 700)                       # total - BTC - ETH
        self.assertAlmostEqual(t["BTC.D"]["price"], 50.0)
        self.assertAlmostEqual(t["STABLE.C.D"]["price"], 15.0)
        self.assertGreater(t["TOTAL"]["change_pct"], 0)
        self.assertLess(t["USDT.D"]["change_abs"], 0)                           # market grew, USDT did not -> share falls

    def test_rows_and_html_escape(self):
        data = {"yahoo": {"DXY": {"price": 100, "prev": 99, "change_abs": 1, "change_pct": 1.0}}, "binance": {}, "crypto": None, "unrate": 4.1}
        rows = macro.build_rows(data)
        self.assertEqual([r["symbol"] for r in rows], ["DXY", "UNRATE"])
        html = macro.watchlist_html({"rows": rows, "regime": macro.macro_regime(rows), "errors": {"<b>x": "E"}, "fetched_at": "t"})
        self.assertIn("&lt;b&gt;x", html)
        self.assertNotIn("<b>x", html)
        self.assertIn("unavailable", macro.watchlist_html(None))


if __name__ == "__main__":
    unittest.main()
