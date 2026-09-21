"""'Why the market moved': every rule, the honesty rules, and the daily log."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from events import movers as M  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 22, 14, 0, tzinfo=UTC)          # a Tuesday


def inputs(btc_pct=1.6, **kw):
    d = {"btc": {"pct_24h": btc_pct, "oi_change_pct": 0.5, "funding_rate": 0.0001, "at_30d_high": False}, "eth": {"pct_24h": 2.0}, "typical_move_pct": 1.1,
         "macro": {"TOTAL": {"change_pct": 2.0}}, "fng": {"value": 60, "label": "Greed"}}
    d.update(kw)
    return d


def event(name="US CPI", hours_ago=3, impact="VERY_HIGH", status="RELEASED", ret=None, **extra):
    when = NOW - dt.timedelta(hours=hours_ago)
    e = {"id": "e1", "event_name": name, "plain_title": name, "impact_level": impact, "status": status, "release_datetime": when.isoformat(),
         "actual": 3.1, "forecast": 3.0, "unit": "%", "reactions": [] if ret is None else [{"asset": "BTCUSDT", "return_1h": ret}]}
    e.update(extra)
    return e


class SizeTests(unittest.TestCase):
    def test_size_labels(self):
        self.assertEqual(M.size_of_move(0.3, 1.0)[1], "a small move")
        self.assertEqual(M.size_of_move(1.0, 1.0)[1], "a normal-sized move")
        self.assertEqual(M.size_of_move(1.6, 1.0)[1], "bigger than a normal day")
        self.assertEqual(M.size_of_move(-3.0, 1.0)[1], "an unusually large move")
        self.assertEqual(M.size_of_move(1.0, None), (None, None))

    def test_typical_move_ignores_the_forming_candle_and_needs_history(self):
        closes = [100 * (1.01 ** i) for i in range(40)] + [999]                 # the last value (today, forming) must not count
        self.assertAlmostEqual(M.typical_move_pct(closes), 1.0, places=6)
        self.assertIsNone(M.typical_move_pct([100, 101, 102]))


class DriverTests(unittest.TestCase):
    def keys(self, m, side="up"):
        return {f["key"] for f in m[side]}

    def test_a_rally_with_supportive_macro_lists_the_matching_reasons(self):
        macro = {"TOTAL": {"change_pct": 2.0}, "NDX": {"change_pct": 1.1}, "DXY": {"change_pct": -0.5}, "US10Y": {"change_abs": -0.06},
                 "STABLE.C.D": {"change_abs": -0.8}, "OTHERS": {"change_pct": 3.4}}
        m = M.explain(inputs(macro=macro), [], NOW)
        self.assertEqual(m["direction"], "UP")
        self.assertTrue({"stocks_NDX", "dollar", "yields", "stables", "alts_lead"} <= self.keys(m))
        self.assertIn("up 1.6%", m["headline"])
        self.assertIn("bigger than a normal day", m["headline"])
        self.assertTrue(all(f["strength"] in ("STRONG", "SOME", "WEAK") for f in m["up"]))
        weights = [f["weight"] for f in m["up"]]
        self.assertEqual(weights, sorted(weights, reverse=True))               # strongest first

    def test_opposing_signals_are_listed_as_what_held_it_back(self):
        macro = {"TOTAL": {"change_pct": 2.0}, "NDX": {"change_pct": -1.4}, "DXY": {"change_pct": 0.7}}
        m = M.explain(inputs(macro=macro), [], NOW)
        self.assertEqual(m["direction"], "UP")
        self.assertTrue({"stocks_NDX", "dollar"} <= self.keys(m, "down"))
        self.assertEqual(self.keys(m, "up") & {"stocks_NDX", "dollar"}, set())

    def test_a_fall_flips_the_reading(self):
        macro = {"NDX": {"change_pct": -1.2}, "STABLE.C.D": {"change_abs": 0.9}}
        m = M.explain(inputs(btc_pct=-2.4, macro=macro), [], NOW)
        self.assertEqual((m["direction"], m["emoji"]), ("DOWN", "\U0001F534"))
        self.assertTrue({"stocks_NDX", "stables"} <= self.keys(m, "down"))
        self.assertIn("down 2.4%", m["headline"])

    def test_small_moves_are_flat_and_do_not_pretend_to_have_a_cause(self):
        m = M.explain(inputs(btc_pct=0.2), [], NOW)
        self.assertEqual(m["direction"], "FLAT")
        self.assertIn("flat", m["headline"])
        self.assertIn("quiet", m["summary"])

    def test_no_driver_in_the_data_says_so_instead_of_inventing_one(self):
        m = M.explain(inputs(macro={"TOTAL": {"change_pct": 2.0}}), [], NOW)
        self.assertEqual(m["up"], [])
        self.assertIn("None of the signals", m["summary"])
        self.assertTrue(m["cant_see"])
        self.assertIn("not proven causes", m["disclaimer"])

    def test_missing_data_leaves_factors_out_and_missing_price_returns_nothing(self):
        self.assertIsNone(M.explain({"btc": {}}, [], NOW))
        self.assertIsNone(M.explain({}, [], NOW))
        m = M.explain(inputs(macro={}), [], NOW)
        self.assertEqual(m["up"] + m["down"], [])

    def test_leverage_readings(self):
        up_short_cover = M.explain(inputs(btc_pct=2.0, btc={"pct_24h": 2.0, "oi_change_pct": -4.0, "funding_rate": 0.0}), [], NOW)
        self.assertIn("short_cover", self.keys(up_short_cover))
        up_borrowed = M.explain(inputs(btc_pct=2.0, btc={"pct_24h": 2.0, "oi_change_pct": 5.0, "funding_rate": 0.0}), [], NOW)
        self.assertIn("lev_build_up", self.keys(up_borrowed, "down"))
        down_flush = M.explain(inputs(btc_pct=-3.0, btc={"pct_24h": -3.0, "oi_change_pct": -6.0, "funding_rate": 0.0}), [], NOW)
        self.assertIn("long_flush", self.keys(down_flush, "down"))
        crowded = M.explain(inputs(btc={"pct_24h": 1.6, "funding_rate": 0.0005}), [], NOW)
        self.assertIn("funding_hot", self.keys(crowded, "down"))

    def test_breakouts(self):
        m = M.explain(inputs(btc={"pct_24h": 1.6, "at_30d_high": True}), [], NOW)
        self.assertIn("breakout_up", self.keys(m))
        red = M.explain(inputs(btc={"pct_24h": -1.6, "at_30d_high": True}), [], NOW)
        self.assertNotIn("breakout_up", self.keys(red))                        # a high on a red day is not a breakout


class EventTests(unittest.TestCase):
    def test_a_data_release_with_a_clear_reaction_is_a_driver(self):
        m = M.explain(inputs(), [event(ret=0.8)], NOW)
        f = next(x for x in m["up"] if x["key"].startswith("event_"))
        self.assertEqual(f["strength"], "STRONG")
        self.assertIn("US CPI", f["title"])
        self.assertIn("+0.80% within 1h", f["evidence"])
        self.assertIn("3.1%", f["evidence"])

    def test_a_release_with_no_reaction_is_only_a_note(self):
        m = M.explain(inputs(), [event(ret=0.05)], NOW)
        self.assertFalse([x for x in m["up"] + m["down"] if x["key"].startswith("event_")])
        self.assertTrue(any("did not react much" in n for n in m["notes"]))

    def test_no_major_release_is_stated_plainly(self):
        m = M.explain(inputs(), [event(impact="LOW", ret=0.9), event(hours_ago=40, ret=0.9)], NOW)
        self.assertTrue(any("No major US data release" in n for n in m["notes"]))

    def test_upcoming_release_within_a_day_is_flagged(self):
        soon = event(name="FOMC decision", hours_ago=-5, status="SCHEDULED")
        m = M.explain(inputs(), [soon], NOW)
        self.assertTrue(any("Coming up within 24 hours: FOMC decision" in n for n in m["notes"]))

    def test_extreme_sentiment_and_weekend_notes(self):
        m = M.explain(inputs(fng={"value": 82, "label": "Extreme Greed"}), [], NOW)
        self.assertTrue(any("extreme" in n.lower() for n in m["notes"]))
        sat = dt.datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
        self.assertTrue(any("weekend" in n for n in M.explain(inputs(), [], sat)["notes"]))


class HistoryTests(unittest.TestCase):
    def test_one_row_per_day_today_is_overwritten_and_the_log_is_capped(self):
        m = M.explain(inputs(macro={"NDX": {"change_pct": 1.2}}), [], NOW)
        h = M.update_history([], m, NOW)
        self.assertEqual([r["date"] for r in h], ["2026-09-22"])
        m2 = M.explain(inputs(btc_pct=2.5), [], NOW + dt.timedelta(hours=3))
        h = M.update_history(h, m2, NOW + dt.timedelta(hours=3))
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["btc_pct"], 2.5)
        many = []
        for i in range(40):
            many = M.update_history(many, m, NOW - dt.timedelta(days=40 - i))
        self.assertEqual(len(many), 30)
        self.assertEqual(many, sorted(many, key=lambda r: r["date"]))


if __name__ == "__main__":
    unittest.main()
