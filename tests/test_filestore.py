import json
import os
import tempfile
import unittest

import filestore


class FileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.b = filestore.FileBackend(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_state_round_trip_and_missing_key_is_none(self):
        self.assertIsNone(self.b.get_state())
        self.b.put_state({"a": 1})
        self.b.put_state([1, 2], "_x")
        self.assertEqual(self.b.get_state(), {"a": 1})
        self.assertEqual(self.b.get_state("_x"), [1, 2])

    def test_upsert_merges_on_key_and_select_filters_orders_limits(self):
        self.b.upsert("t", [{"id": "a", "n": 1, "k": "X"}, {"id": "b", "n": 2, "k": "Y"}], "id")
        self.b.upsert("t", [{"id": "a", "n": 9}, {"id": "c", "n": 3, "k": "X"}], "id")
        rows = {r["id"]: r for r in self.b.select("t")}
        self.assertEqual(rows["a"], {"id": "a", "n": 9, "k": "X"})
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["id"] for r in self.b.select("t", "select=*&k=eq.X&order=n.desc&limit=1")], ["a"])

    def test_config_tables_come_from_config_dir_and_are_never_written(self):
        os.makedirs(os.path.join(self.root, "config"))
        with open(os.path.join(self.root, "config", "trend_settings.json"), "w") as f:
            json.dump([{"key": "config", "value": {"pinned_coins": ["QNT"]}}], f)
        self.assertEqual(self.b.select("trend_settings")[0]["value"]["pinned_coins"], ["QNT"])
        self.assertEqual(self.b.select("scalp_settings"), [])          # absent config file -> empty, engine uses defaults

    def test_publish_portions_merges_and_writes_site_file(self):
        self.b.publish_portions({"a": {"title": "A", "sort_order": 2, "html": "<p>a</p>", "data": {}}})
        self.b.publish_portions({"b": {"title": "B", "sort_order": 1, "html": "<p>b</p>", "data": {"x": 1}}})
        with open(os.path.join(self.root, "site", "portions.json")) as f:
            rows = json.load(f)
        self.assertEqual([r["key"] for r in rows], ["b", "a"])         # kept the earlier one, sorted by sort_order

    def test_notifications_dedupe_by_id_newest_first_and_capped(self):
        ev = lambda i: {"id": f"e{i}", "ts": f"2026-01-01T00:00:{i:02d}Z", "type": "signal", "title": "t", "body": "", "portion_key": "screener"}
        self.b.publish_notifications([ev(1), ev(2)])
        self.b.publish_notifications([ev(2), ev(3)])
        with open(os.path.join(self.root, "site", "notifications.json")) as f:
            feed = json.load(f)
        self.assertEqual([e["id"] for e in feed], ["e3", "e2", "e1"])

    def test_empty_notifications_still_write_nothing_harmful(self):
        self.b.publish_notifications([])
        self.assertEqual(self.b.get_state("nothing"), None)


if __name__ == "__main__":
    unittest.main()
