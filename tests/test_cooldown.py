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


if __name__ == "__main__":
    unittest.main()
