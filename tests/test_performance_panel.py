"""Performance tab: dip-buy and the retired 15m/1h momentum rule are both switched off for good,
so their history is dropped entirely -- only the live 4h Trend Breakout engine's record is shown."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dashboard as D  # noqa: E402

NOW = "2026-09-29 12:00:00"


def ago(**kw):
    return (datetime.datetime.now() - datetime.timedelta(**kw)).isoformat()


def coin(key, name, price):
    return {"key": key, "name": name, "emoji": "B", "price": price, "high_24h": price * 1.01, "low_24h": price * 0.99,
            "pct_24h": 2.0, "pct_7d": 4.0, "pct_30d": 9.0, "sma50": price * 0.95, "sma200": price * 0.85,
            "support_30d": price * 0.9, "resistance_30d": price * 1.1, "mark_price": price, "index_price": price,
            "funding_rate": 0.0001, "oi_change_pct": 1.0, "oi_now": 1000.0, "stale": [],
            "fng_value": 50, "fng_class": "Neutral", "derivs_source": "OKX", "oi_source": "OKX (approx.)"}


def build():
    coins = [coin("BTC", "Bitcoin", 80000.0), coin("ETH", "Ethereum", 2500.0)]
    dip_state = {"open": {}, "resolved": [
        {"coin": "SOL", "name": "Solana", "tf": "15m", "entry": 100.0, "stop": 98.0, "target1": 102.0,
         "exit_price": 102.0, "result": "win", "opened_at": "2026-09-19T10:00:00", "resolved_at": "2026-09-19T12:00:00"},
    ]}
    mom_state = {
        "open": {"4h:AVAX": {"coin": "AVAX", "name": "Avalanche", "tf": "4h", "kind": "trend", "entry": 11.0, "stop": 9.0,
                             "target1": None, "opened_at": "2026-09-28T00:00:00"}},
        "resolved": [
            {"coin": "QNT", "name": "Qnt", "tf": "4h", "entry": 80.0, "stop": 75.0, "target1": None,
             "exit_price": 200.0, "result": "win", "opened_at": "2026-09-24T16:00:00", "resolved_at": "2026-09-28T09:00:00"},
            {"coin": "DOGE", "name": "Dogecoin", "tf": "15m", "entry": 0.1, "stop": 0.098, "target1": 0.102,
             "exit_price": 0.098, "result": "loss", "opened_at": "2026-09-19T17:00:00", "resolved_at": "2026-09-19T18:00:00"},
        ],
    }
    _html, portions, _ = D.render(coins, 50, "Neutral", NOW, False, pnl_state=dip_state, momentum_state=mom_state)
    return portions["performance"]["html"]


class PerformancePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = build()

    def test_dip_buy_is_gone(self):
        self.assertNotIn("Dip buy", self.h)
        self.assertNotIn("SOL", self.h)                 # the dip-buy resolved row itself

    def test_retired_15m_1h_momentum_is_gone(self):
        self.assertNotIn("Momentum (experimental)", self.h)
        self.assertNotIn("DOGE", self.h)                 # the old 15m momentum resolved row

    def test_trend_breakout_history_is_shown(self):
        self.assertIn("Trend Breakout", self.h)
        self.assertIn("QNT", self.h)
        self.assertIn("AVAX", self.h)                    # the open trend position

    def test_title_no_longer_says_all_signals(self):
        self.assertNotIn("all signals", self.h)


def build_returns():
    coins = [coin("BTC", "Bitcoin", 80000.0), coin("ETH", "Ethereum", 2500.0)]
    mom_state = {"open": {}, "resolved": [
        # within the last day: +5% and -2% raw moves
        {"coin": "AAA", "name": "Aaa", "tf": "4h", "entry": 100.0, "stop": 90.0, "target1": None, "exit_price": 105.0, "result": "win", "opened_at": ago(hours=20), "resolved_at": ago(hours=10)},
        {"coin": "BBB", "name": "Bbb", "tf": "4h", "entry": 100.0, "stop": 90.0, "target1": None, "exit_price": 98.0, "result": "loss", "opened_at": ago(hours=15), "resolved_at": ago(hours=5)},
        # 3 days ago: outside Daily, inside Weekly/Monthly
        {"coin": "CCC", "name": "Ccc", "tf": "4h", "entry": 100.0, "stop": 90.0, "target1": None, "exit_price": 108.0, "result": "win", "opened_at": ago(days=4), "resolved_at": ago(days=3)},
    ]}
    _html, portions, _ = D.render(coins, 50, "Neutral", NOW, False, momentum_state=mom_state)
    return portions["performance"]["html"]


class ReturnAndInvestmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = build_returns()

    def test_daily_return_is_the_simple_sum_of_that_days_trades_after_fees(self):
        # (105/100-1)*100-0.2 + (98/100-1)*100-0.2 = 4.8 + (-2.2) = +2.60%
        self.assertIn("Return: +2.60%", self.h)

    def test_weekly_return_includes_the_3_day_old_trade_too(self):
        # +4.8 -2.2 + (108/100-1)*100-0.2 = +2.6 + 7.8 = +10.40%
        self.assertIn("Return: +10.40%", self.h)

    def test_dollar_investment_matches_the_return_percent(self):
        # +2.60% of $50 = +$1.30, final value $51.30
        self.assertIn("$51.30", self.h)
        self.assertIn("+1.30", self.h)



def build_all_losing():
    coins = [coin("BTC", "Bitcoin", 80000.0), coin("ETH", "Ethereum", 2500.0)]
    mom_state = {"open": {}, "resolved": [
        {"coin": "AAA", "name": "Aaa", "tf": "4h", "entry": 100.0, "stop": 90.0, "target1": None, "exit_price": 94.0, "result": "loss", "opened_at": ago(hours=20), "resolved_at": ago(hours=10)},
    ]}
    _html, portions, _ = D.render(coins, 50, "Neutral", NOW, False, momentum_state=mom_state)
    return portions["performance"]["html"]


class NegativeReturnTests(unittest.TestCase):
    def test_a_losing_day_shows_a_negative_return_and_a_final_value_below_50(self):
        h = build_all_losing()
        # (94/100-1)*100-0.2 = -6.20%
        self.assertIn("Return: -6.20%", h)
        self.assertIn("$46.90", h)                        # 50 - 3.10
        self.assertIn("-3.10", h)


if __name__ == "__main__":
    unittest.main()
