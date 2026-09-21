"""Overview redesign: grouped alerts, one status card, what-to-watch cards, simple coin cards, plain-English text."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dashboard as D  # noqa: E402
import market_status as MS  # noqa: E402


def coin(key, name, price, res, sup, **kw):
    c = {"key": key, "name": name, "emoji": "B", "price": price, "high_24h": price * 1.01, "low_24h": price * 0.99, "pct_24h": 2.0,
         "pct_7d": 4.0, "pct_30d": 9.0, "sma50": price * 0.95, "sma200": price * 0.85, "support_30d": sup, "resistance_30d": res,
         "mark_price": price, "index_price": price, "funding_rate": 0.0001, "oi_change_pct": 1.0, "oi_now": 1000.0, "stale": [],
         "fng_value": 50, "fng_class": "Neutral", "derivs_source": "OKX", "oi_source": "OKX (approx.)"}
    c.update(kw)
    return c


def build():
    coins = [coin("BTC", "Bitcoin", 80000.0, 80500.0, 70000.0), coin("ETH", "Ethereum", 2500.0, 2510.0, 2000.0)]
    alerts = [{"id": "a", "coin": "BTC", "condition": "above", "target": 78424.62, "label": "BTC breaks 30-day resistance", "triggered": True, "current_price": 80000.0, "dist_pct": 2.0, "status": "triggered"},
              {"id": "b", "coin": "BTC", "condition": "above", "target": 83000.0, "label": "BTC above $83k (Crypto Dada: breakout, $90k in view)", "triggered": True, "current_price": 83500.0, "dist_pct": 0.5, "status": "triggered"}]
    status = MS.assess(coins, {}, {}, None)
    _html, portions, _ = D.render(coins, 50, "Neutral", "2026-09-20 02:00:00", False, alerts_results=alerts, market_status=status)
    return portions


class OverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = build()

    def test_one_narrow_band_with_status_then_alerts_then_watch(self):
        h = self.p["_meta"]["html"]
        self.assertEqual(h.count('class="ov-band"'), 1)                   # one band, not three stacked sections
        self.assertLess(h.index("ov-status"), h.index("ov-alerts"))
        self.assertLess(h.index("ov-alerts"), h.index("ov-watch"))
        self.assertEqual(h.count('class="ov-row'), 3)
        self.assertNotIn("alert-box", h)

    def test_alerts_use_short_plain_wording(self):
        h = self.p["_meta"]["html"]
        self.assertIn("Breakout", h)
        self.assertIn("Above its 30-day ceiling", h)                       # kept as the chip's hover/long-press text
        self.assertIn("Above $83,000", h)
        self.assertNotIn("resistance", h.lower())

    def test_watch_cards_cover_btc_eth_and_signals_and_link_to_tabs(self):
        h = self.p["_meta"]["html"]
        self.assertIn('data-goto="bigcoins" data-sub="bc-btc"', h)
        self.assertIn('data-goto="bigcoins" data-sub="bc-eth"', h)
        self.assertIn('data-goto="screener"', h)

    def test_market_tab_has_a_simple_card_and_details_for_both_coins(self):
        h = self.p["bigcoins"]["html"]
        self.assertEqual(h.count('class="coin-simple'), 2)
        self.assertEqual(h.count("coin-details"), 2)
        self.assertIn("Bitcoin", h)

    def test_signals_page_says_which_signal_types_are_on_and_which_were_switched_off(self):
        import re
        h = self.p["screener"]["html"]
        text = re.sub(r"\s+", " ", " ".join(re.findall(r">([^<>]+)<", h)))
        self.assertIn("Only one signal type is running now", text)
        self.assertIn("Trend breakout", text)
        self.assertIn("Dip-buy signals and the 15-minute / 1-hour momentum signals were switched off", text)
        self.assertIn("stays listed until it finishes", text)

    def test_signals_has_one_short_plain_guide_not_a_glossary(self):
        import re
        h = self.p["screener"]["html"]
        self.assertEqual(h.count("How to read a signal"), 1)
        self.assertNotIn("What the labels mean", h)                       # the old two-column glossary is gone
        self.assertNotIn("What the score labels mean", h)
        self.assertNotIn("MOMENTUM BREAKOUT", h[h.index("How to read a signal"):h.index("How to read a signal") + 2500])
        guide = h[h.index("How to read a signal"):]
        guide = guide[:guide.index("</details>")]
        self.assertEqual(guide.count("<li>"), 5)                           # five short points
        text = " ".join(re.findall(r">([^<>]+)<", guide))
        for needle in ("TREND BREAKOUT", "Entry", "Stop", "trailing", "Trailing Stop", "no target price", "Follow"):
            self.assertIn(needle, text, needle)
        self.assertLess(len(text.split()), 230)                           # short enough to read in one go

    def test_no_atr_jargon_on_screen_and_trailing_stop_is_a_binance_percentage(self):
        import re
        h = self.p["screener"]["html"]
        self.assertNotRegex(h, r"ATRs?")                                # not in the text, the legend or any tooltip
        self.assertNotRegex(self.p["bigcoins"]["html"], r"ATRs?")
        with open(os.path.join(os.path.dirname(__file__), "..", "static", "scalping.js"), encoding="utf-8") as f:
            js = f.read()
        js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        js = re.sub(r"(?m)^\s*//.*$", "", js)
        self.assertNotRegex(js, r"ATR")                                 # the scalping page never shows the word either

    def test_trend_row_shows_the_trailing_stop_as_a_binance_percentage(self):
        import re
        coins = [coin("BTC", "Bitcoin", 80000.0, 80500.0, 70000.0), coin("ETH", "Ethereum", 2500.0, 2510.0, 2000.0)]
        mom = {"open": {"4h:ALGO": {"tf": "4h", "kind": "trend", "coin": "ALGO", "name": "Algorand", "entry": 0.1126, "stop": 0.0936, "stop0": 0.0936, "target1": None,
                                    "target2": None, "risk_pct": 16.9, "net1": None, "net2": None, "opened_at": "2026-09-20T22:03:00", "why": []},
                         "4h:AVAX": {"tf": "4h", "kind": "trend", "coin": "AVAX", "name": "Avalanche", "entry": 11.28, "stop": 8.73, "stop0": 8.73, "target1": None,
                                     "target2": None, "risk_pct": 22.6, "net1": None, "net2": None, "opened_at": "2026-09-20T22:07:00", "why": []}}, "resolved": []}
        _h, portions, _ = D.render(coins, 50, "Neutral", "2026-09-20 02:00:00", False, momentum_state=mom)
        h = portions["screener"]["html"]
        visible = re.sub(r"\s+", " ", " ".join(re.findall(r">([^<>]+)<", h)))
        self.assertIn("Trailing stop 16.9%", visible)
        self.assertIn("On Binance: trailing delta 16.9%", visible)
        self.assertIn("over the 20% max: use a fixed stop", visible)             # AVAX at 22.6% cannot be a native trailing stop
        self.assertIn("Typical hold ~4 days", visible)
        self.assertNotRegex(h, r"ATRs?")

    def test_bitcoin_and_ethereum_tabs_get_an_interactive_chart_host(self):
        h = self.p["bigcoins"]["html"]
        self.assertIn('class="coin-chart" data-binance="BTCUSDT"', h)
        self.assertIn('class="coin-chart" data-binance="ETHUSDT"', h)
        self.assertEqual(h.count('class="coin-chart"'), 2)

    def test_tab_names(self):
        self.assertIn("Signals", self.p["screener"]["title"])
        self.assertEqual(self.p["bigcoins"]["title"], "\U0001FA99 Market")

    def test_visible_jargon_is_replaced_but_tooltips_keep_the_technical_terms(self):
        import re
        for key in ("bigcoins", "screener"):
            h = self.p[key]["html"]
            visible = " ".join(re.findall(r">([^<>]+)<", h))
            for term in ("Key Resistance", "Key Support", "CYCLE MAP", "SIGNAL TABLE", "Wyckoff structure"):
                self.assertNotIn(term, visible, f"{term} still visible in {key}")
        tips = " ".join(re.findall(r'data-tip="([^"]*)"', self.p["bigcoins"]["html"]))
        self.assertIn("Accumulation", tips)                              # the technical wording still exists, inside the tooltip


if __name__ == "__main__":
    unittest.main()
