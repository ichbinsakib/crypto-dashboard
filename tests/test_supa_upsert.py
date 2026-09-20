import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import supa  # noqa: E402


class UpsertShapeTests(unittest.TestCase):
    def test_rows_with_different_keys_are_sent_in_separate_uniform_batches(self):
        b = supa.Backend("http://x", "k", "e", "p")
        sent = []
        b._request = lambda method, path, body=None, headers=None, **kw: sent.append(body)
        b.upsert("economic_events", [{"id": "a", "x": 1}, {"id": "b", "x": 2, "forecast": "3.1"}, {"id": "c", "x": 3}], "id")
        self.assertEqual(len(sent), 2)
        for batch in sent:
            self.assertEqual(len({tuple(sorted(r)) for r in batch}), 1)     # every batch has one key shape
        self.assertEqual(sorted(r["id"] for batch in sent for r in batch), ["a", "b", "c"])      # nothing lost

    def test_empty_is_a_no_op(self):
        b = supa.Backend("http://x", "k", "e", "p")
        b._request = lambda *a, **k: self.fail("should not be called")
        b.upsert("t", [], "id")


if __name__ == "__main__":
    unittest.main()
