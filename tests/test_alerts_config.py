"""Alerts config: Supabase-backed (price_alerts table) when a backend is given, local
data/alerts_config.json otherwise -- same None-means-seed-defaults contract either way."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dashboard as D  # noqa: E402


class FakeBackend:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.seeded = None

    def select(self, table):
        assert table == "price_alerts"
        return self.rows

    def seed_price_alerts(self, rows):
        self.seeded = rows


class LoadAlertsConfigTests(unittest.TestCase):
    def test_no_backend_and_no_local_file_returns_none(self):
        missing_path = "/tmp/does-not-exist-alerts.json"
        orig = D.ALERTS_CONFIG_PATH
        D.ALERTS_CONFIG_PATH = missing_path
        try:
            self.assertIsNone(D.load_alerts_config())
        finally:
            D.ALERTS_CONFIG_PATH = orig

    def test_empty_supabase_table_means_seed_defaults(self):
        self.assertIsNone(D.load_alerts_config(FakeBackend(rows=[])))

    def test_supabase_rows_are_shaped_into_the_same_alerts_dict(self):
        backend = FakeBackend(rows=[{"id": "btc-above-90k", "coin": "BTC", "condition": "above",
                                     "price": 90000.0, "label": "BTC above $90k", "enabled": True}])
        cfg = D.load_alerts_config(backend)
        self.assertEqual(cfg, {"alerts": [{"id": "btc-above-90k", "coin": "BTC", "condition": "above",
                                           "price": 90000.0, "label": "BTC above $90k", "enabled": True}]})

    def test_supabase_read_failure_returns_an_empty_list_not_none(self):
        class BoomBackend:
            def select(self, table):
                raise RuntimeError("down")
        cfg = D.load_alerts_config(BoomBackend())
        self.assertEqual(cfg, {"alerts": []})       # empty, not None -- None would trigger reseeding


class SaveAlertsConfigTests(unittest.TestCase):
    def test_seeding_with_a_backend_calls_seed_price_alerts_not_the_local_file(self):
        backend = FakeBackend()
        config = {"alerts": [{"id": "btc-resistance-break", "coin": "BTC", "condition": "above",
                              "price": 85000.0, "label": "BTC breaks 30-day resistance", "enabled": True}]}
        D.save_alerts_config(config, backend)
        self.assertEqual(backend.seeded, [{"id": "btc-resistance-break", "coin": "BTC", "condition": "above",
                                           "price": 85000.0, "label": "BTC breaks 30-day resistance", "enabled": True}])


if __name__ == "__main__":
    unittest.main()
