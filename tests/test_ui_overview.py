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

    def test_status_card_comes_before_the_grouped_alerts_then_watch_cards(self):
        h = self.p["_meta"]["html"]
        self.assertLess(h.index("ms-card"), h.index("alert-box"))
        self.assertLess(h.index("alert-box"), h.index("watch-strip"))
        self.assertEqual(h.count("alert-box-title"), 1)                 # one box, not a wall of banners

    def test_alerts_use_short_plain_wording(self):
        h = self.p["_meta"]["html"]
        self.assertIn("Breakout", h)
        self.assertIn("Above its 30-day ceiling", h)
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
