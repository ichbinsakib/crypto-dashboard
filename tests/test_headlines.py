"""Headline feed: parsing, staleness filtering, capping, and never raising on a bad feed."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from events import headlines as H  # noqa: E402

NOW = dt.datetime(2026, 9, 25, 12, 0, tzinfo=dt.timezone.utc)


def rss(items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{p}</pubDate></item>" for t, l, p in items)
    return f'<?xml version="1.0"?><rss><channel>{body}</channel></rss>'.encode()


class ParseTests(unittest.TestCase):
    def test_parses_items_and_normalises_whitespace(self):
        xml = rss([("Bitcoin   hits\n new high", "https://x.com/a", "Fri, 25 Sep 2026 10:00:00 GMT")])
        out = H.parse_feed(xml, "TestFeed")
        self.assertEqual(out[0]["title"], "Bitcoin hits new high")
        self.assertEqual(out[0]["source"], "TestFeed")
        self.assertEqual(out[0]["published"], dt.datetime(2026, 9, 25, 10, 0, tzinfo=dt.timezone.utc))

    def test_malformed_xml_returns_empty_not_a_crash(self):
        self.assertEqual(H.parse_feed(b"not xml at all", "X"), [])

    def test_caps_items_per_feed(self):
        xml = rss([(f"Title {i}", "", "Fri, 25 Sep 2026 10:00:00 GMT") for i in range(20)])
        self.assertEqual(len(H.parse_feed(xml, "X")), H.MAX_PER_FEED)

    def test_items_without_a_title_are_skipped(self):
        xml = rss([("", "https://x.com/a", "Fri, 25 Sep 2026 10:00:00 GMT")])
        self.assertEqual(H.parse_feed(xml, "X"), [])


class FetchAllTests(unittest.TestCase):
    def fake_get(self, feeds):
        def get(url):
            for name, u in H.FEEDS:
                if u == url:
                    return feeds.get(name, rss([]))
            raise AssertionError("unexpected url " + url)
        return get

    def test_merges_sorts_and_reports_age(self):
        feeds = {"CoinDesk": rss([("Old CD", "u1", "Fri, 25 Sep 2026 06:00:00 GMT")]),
                 "Cointelegraph": rss([("New CT", "u2", "Fri, 25 Sep 2026 11:30:00 GMT")])}
        out = H.fetch_all(now=NOW, get=self.fake_get(feeds))
        self.assertEqual([x["title"] for x in out], ["New CT", "Old CD"])
        self.assertEqual(out[0]["age_min"], 30)
        self.assertEqual(out[1]["age_min"], 360)

    def test_stale_items_beyond_the_age_window_are_dropped(self):
        feeds = {"CoinDesk": rss([("Ancient", "u", "Wed, 23 Sep 2026 00:00:00 GMT")]), "Cointelegraph": rss([])}
        self.assertEqual(H.fetch_all(now=NOW, get=self.fake_get(feeds)), [])

    def test_one_dead_feed_does_not_stop_the_other(self):
        def get(url):
            if "coindesk" in url:
                raise TimeoutError("dead")
            return rss([("Alive", "u", "Fri, 25 Sep 2026 11:00:00 GMT")])
        out = H.fetch_all(now=NOW, get=get)
        self.assertEqual([x["title"] for x in out], ["Alive"])

    def test_both_feeds_dead_returns_empty_never_raises(self):
        def get(url):
            raise ConnectionError("down")
        self.assertEqual(H.fetch_all(now=NOW, get=get), [])

    def test_items_without_a_parseable_date_are_dropped_not_guessed(self):
        feeds = {"CoinDesk": rss([("No date", "u", "")]), "Cointelegraph": rss([])}
        self.assertEqual(H.fetch_all(now=NOW, get=self.fake_get(feeds)), [])

    def test_result_is_capped_at_max_total(self):
        items = [(f"T{i}", "u", "Fri, 25 Sep 2026 11:00:00 GMT") for i in range(H.MAX_PER_FEED)]
        feeds = {"CoinDesk": rss(items), "Cointelegraph": rss(items)}
        out = H.fetch_all(now=NOW, get=self.fake_get(feeds))
        self.assertEqual(len(out), H.MAX_TOTAL)


if __name__ == "__main__":
    unittest.main()
