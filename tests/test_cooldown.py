"""Cooldown after a loss must also silence the 'New signal' alert. Run: python -m unittest discover -s tests"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dashboard as d  # noqa: E402


class CooldownTests(unittest.TestCase):
    def test_recent_loss_cools_down_and_old_one_does_not(self):
        now = datetime.datetime(2026, 9, 19, 13, 0)
        resolved = [
            {"tf": "15m", "coin": "JST", "result": "loss", "resolved_at": (now - datetime.timedelta(minutes=10)).isoformat()},
            {"tf": "15m", "coin": "OLD", "result": "loss", "resolved_at": (now - datetime.timedelta(hours=8)).isoformat()},
            {"tf": "1h", "coin": "WIN", "result": "win", "resolved_at": now.isoformat()},
        ]
        cool = d.cooldown_keys(resolved, now)
        self.assertIn("15m:JST", cool)
        self.assertNotIn("15m:OLD", cool)          # 15m cooldown is 6h and has passed
        self.assertNotIn("1h:WIN", cool)           # wins never cool down

    def test_strong_buy_skips_cooling_coin(self):
        res = {"15m": [{"symbol": "JST", "score": 5, "label": "x", "price": 1, "trade": None},
                       {"symbol": "XRP", "score": 5, "label": "x", "price": 1, "trade": None}]}
        found = d.find_strong_buys([], {}, [], res, {"15m:JST": object()})
        self.assertEqual([f["symbol"] for f in found], ["XRP"])
        self.assertEqual(len(d.find_strong_buys([], {}, [], res)), 2)


class OncePerCallTests(unittest.TestCase):
    def test_flicker_of_a_tracked_call_does_not_alert_again(self):
        new = [{"dedupe_key": "scanner-1h:WLFI", "symbol": "WLFI"}, {"dedupe_key": "scanner-15m:LTC", "symbol": "LTC"},
               {"dedupe_key": "daily:BTC", "symbol": "BTC"}]
        kept = d.drop_already_tracked(new, {"1h:WLFI"})
        self.assertEqual([k["dedupe_key"] for k in kept], ["scanner-15m:LTC", "daily:BTC"])

    def test_first_alert_for_a_call_still_goes_out(self):
        new = [{"dedupe_key": "scanner-1h:WLFI", "symbol": "WLFI"}]
        self.assertEqual(d.drop_already_tracked(new, set()), new)                    # not tracked before this run -> alert
        self.assertEqual(d.drop_already_tracked(new, {"15m:WLFI"}), new)            # a different timeframe is a different call


if __name__ == "__main__":
    unittest.main()
