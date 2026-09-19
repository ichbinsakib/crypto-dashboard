"""Plain-language layer for Market Events. Run: python -m unittest discover -s tests"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from events import config, explain, providers, service, timeutil  # noqa: E402

UTC = dt.timezone.utc
CFG = config.effective()


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


def ev(id_, name, family, level, when, status="SCHEDULED", **kw):
    e = {"id": id_, "event_name": name, "family": family, "impact_level": level, "release_datetime": when.isoformat(), "status": status,
         "forecast": None, "actual": None, "previous": None}
    e.update(kw)
    return e


NOW = utc(2026, 9, 21, 12, 0)                      # Monday 8:00 AM ET (EDT)
CPI = lambda d=22, h=12, m=30: ev("cpi", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, d, h, m))   # noqa: E731
FOMC = lambda d=23: ev("fomc", "FOMC Meeting Decision", "FOMC", "VERY_HIGH", utc(2026, 9, d, 18, 0))          # noqa: E731
PPI = lambda: ev("ppi", "Producer Price Index", "PPI", "HIGH", utc(2026, 9, 24, 12, 30))                      # noqa: E731
TENURE = lambda: ev("ten", "Employee Tenure", "OTHER", "LOW", utc(2026, 9, 22, 14, 0))                         # noqa: E731


class TierAndWordsTests(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(explain.tier("VERY_HIGH")["label"], "Major impact")
        self.assertEqual(explain.tier("HIGH")["emoji"], "\U0001F7E0")
        self.assertEqual(explain.tier("MEDIUM")["key"], "moderate")
        self.assertEqual(explain.tier("LOW")["key"], "low")
        self.assertEqual(explain.tier("weird")["key"], "low")

    def test_when_words_uses_eastern_time_and_dst(self):
        self.assertEqual(explain.when_words(utc(2026, 9, 21, 12, 30).isoformat(), NOW), "today at 8:30 AM ET")
        self.assertEqual(explain.when_words(utc(2026, 9, 22, 12, 30).isoformat(), NOW), "tomorrow at 8:30 AM ET")
        self.assertEqual(explain.when_words(utc(2026, 9, 23, 18, 0).isoformat(), NOW), "on Wednesday at 2:00 PM ET")
        self.assertEqual(explain.when_words(utc(2026, 12, 4, 13, 30).isoformat(), NOW), "on Dec 4 at 8:30 AM ET")   # EST: 13:30 UTC = 8:30

    def test_categories_and_sensitivity(self):
        self.assertEqual(explain.category_of("CPI"), "inflation")
        self.assertEqual(explain.category_of("NFP"), "employment")
        self.assertEqual(explain.category_of("FOMC"), "central_banks")
        self.assertEqual(explain.category_of("SOMETHING"), "other")
        s = {x["asset"]: x["label"] for x in explain.sensitivity("FOMC")}
        self.assertEqual((s["USD"], s["Crypto"], s["Oil"]), ("High", "Medium", "Low/Medium"))
        self.assertTrue(all(x["label"] == "Low" for x in explain.sensitivity("OTHER")))


class RiskMeterTests(unittest.TestCase):
    def test_quiet(self):
        m = explain.risk_meter([TENURE()], NOW)
        self.assertEqual(m["key"], "low")
        self.assertIn("No major or high-impact events", m["why"])

    def test_one_major_within_48h_is_high(self):
        m = explain.risk_meter([CPI()], NOW)
        self.assertEqual((m["key"], m["label"]), ("high", "HIGH"))
        self.assertEqual(m["drivers"][0]["title"], "Inflation report (CPI)")

    def test_cluster_is_very_high(self):
        m = explain.risk_meter([CPI(), FOMC(22), PPI()], NOW)
        self.assertEqual(m["key"], "very_high")
        self.assertIn("2 important events", m["why"])            # CPI + FOMC inside 48h (PPI is later)

    def test_far_major_is_only_moderate(self):
        far = ev("nfp", "Employment Situation", "NFP", "VERY_HIGH", utc(2026, 9, 26, 12, 30))
        m = explain.risk_meter([far], NOW)
        self.assertEqual(m["key"], "moderate")
        self.assertIn("none in the next 48 hours", m["why"])

    def test_released_and_past_events_do_not_count(self):
        done = ev("old", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, 14, 12, 30), status="RELEASED")
        self.assertEqual(explain.risk_meter([done], NOW)["key"], "low")


class SummaryTests(unittest.TestCase):
    def test_headline_and_takeaway_for_fomc(self):
        s = explain.summary([FOMC(), CPI()], NOW)
        self.assertEqual(s["level"], "high")                                   # CPI inside 48h, FOMC just outside it
        self.assertEqual(explain.summary([FOMC(22), CPI()], NOW)["level"], "very_high")
        self.assertIn("Fed interest-rate decision", s["headline"])
        self.assertIn("on Wednesday at 2:00 PM ET", s["headline"])              # FOMC outranks CPI even though CPI comes first
        self.assertIn("1 other important event", s["headline"])
        self.assertIn("volatility", s["takeaway"])
        self.assertIn("leveraged", s["takeaway"])
        self.assertTrue(any("statement" in w for w in s["watch"]))
        self.assertNotIn("prediction", s["takeaway"].lower())

    def test_today_line(self):
        s = explain.summary([CPI(21, 12, 30), FOMC()], NOW)
        self.assertIn("Today: Inflation report (CPI) at 8:30 AM ET", s["today"])
        self.assertIsNone(explain.summary([FOMC()], NOW)["today"])

    def test_quiet_stretch_names_next_big_event(self):
        later = ev("nfp", "Employment Situation", "NFP", "VERY_HIGH", utc(2026, 10, 2, 12, 30))
        s = explain.summary([TENURE(), later], NOW)
        self.assertEqual(s["level"], "low")
        self.assertIn("Quiet stretch", s["headline"])
        self.assertIn("US jobs report", s["headline"])
        self.assertIn("Event risk is low", s["takeaway"])

    def test_theme_when_events_measure_the_same_thing(self):
        s = explain.summary([CPI(), PPI()], NOW)
        self.assertIn("inflation", s["theme"])
        self.assertIsNone(explain.summary([CPI()], NOW)["theme"])

    def test_press_conference_kept_for_upcoming_meetings(self):
        # The Fed's page only links the press conference after it happens, so "no link yet" must not remove it.
        s = explain.summary([FOMC()], NOW, meetings=[{"id": "fomc", "press_conference": False}])
        self.assertTrue(any("press conference" in w.lower() for w in s["watch"]))

    def test_recent_results_only_when_a_surprise_was_measured(self):
        hot = ev("c0", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, 17, 12, 30), status="RELEASED", actual=0.6, forecast=0.3,
                 surprise_classification="LARGE", surprise_direction="ABOVE")
        s = explain.summary([hot, TENURE()], NOW)
        self.assertIn("came in higher than expected", s["recent"])
        nofc = ev("c1", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, 17, 12, 30), status="RELEASED", actual=0.6,
                  surprise_classification="NO_FORECAST")
        self.assertIn("no forecast was on file", explain.summary([nofc], NOW)["recent"].lower())
        self.assertIsNone(explain.summary([TENURE()], NOW)["recent"])
        fed = ev("f0", "FOMC Meeting Decision", "FOMC", "VERY_HIGH", utc(2026, 9, 17, 18, 0), status="RELEASED",
                 details={"decision": "Raised rates by 25 bp to 4.50% - 4.75%."})
        self.assertEqual(explain.summary([fed], NOW)["recent"], "Fed decision (Sep 17): Raised rates by 25 bp to 4.50% - 4.75%.")


class InterpretationTests(unittest.TestCase):
    def test_hot_cpi(self):
        e = ev("c", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, 11, 12, 30), status="RELEASED", actual=0.6, forecast=0.3,
               previous=0.2, surprise_classification="LARGE", surprise_direction="ABOVE")
        line, interp = explain.result_lines(e)
        self.assertIn("0.6 versus 0.3 expected", line)
        self.assertIn("much higher than expected", line)
        self.assertIn("hotter inflation", interp)

    def test_missing_forecast_is_not_pretended(self):
        e = ev("c", "Consumer Price Index", "CPI", "VERY_HIGH", utc(2026, 9, 11, 12, 30), status="RELEASED", actual=0.4, previous=0.1,
               surprise_classification="NO_FORECAST")
        line, interp = explain.result_lines(e)
        self.assertIn("No forecast was recorded", line)
        self.assertIsNone(interp)
        self.assertEqual(explain.result_lines(ev("x", "n", "CPI", "LOW", NOW, status="RELEASED"))[0], "The result has not been recorded yet.")
        self.assertIn("not collected automatically", explain.result_lines(ev("x", "n", "PPI", "HIGH", NOW, status="RELEASED"))[0])

    def test_scenarios_are_labelled_possible(self):
        d = explain.enrich(CPI(), NOW)
        self.assertEqual(len(d["scenarios"]), 3)
        self.assertIn("not predictions", d["scenario_note"])
        for sc in d["scenarios"]:
            self.assertNotIn("will rise", sc["reaction"].lower())
            self.assertNotIn("will fall", sc["reaction"].lower())
        self.assertNotIn("scenarios", explain.enrich(TENURE(), NOW))                 # low-impact: none

    def test_glossary_covers_requested_terms(self):
        for t in ("CPI", "PPI", "GDP", "FOMC", "PMI", "NFP", "PCE", "Jobless Claims", "Fed Funds Rate", "Yield", "Inflation", "Interest Rate"):
            self.assertIn(t, explain.GLOSSARY)
            self.assertLess(len(explain.GLOSSARY[t]), 140)                            # one plain sentence


class FomcTests(unittest.TestCase):
    def meeting(self, id_, end, decision, **kw):
        m = {"id": id_, "start_date": end - dt.timedelta(days=1), "end_date": end, "decision_datetime": decision.isoformat(),
             "has_projections": True, "press_conference": True, "statement_url": None, "minutes_url": None,
             "rate_lower": None, "rate_upper": None, "prev_rate_lower": None, "prev_rate_upper": None, "change_bps": None}
        m.update(kw)
        return m

    def test_decision_text(self):
        self.assertEqual(explain.decision_text({"rate_lower": 4.5, "rate_upper": 4.75, "prev_rate_lower": 4.25, "prev_rate_upper": 4.5}),
                         "Raised rates by 25 bp to 4.50% - 4.75%.")
        self.assertIn("Cut rates by 50 bp", explain.decision_text({"rate_lower": 4.0, "rate_upper": 4.25, "prev_rate_lower": 4.5, "prev_rate_upper": 4.75}))
        self.assertIn("Held rates", explain.decision_text({"rate_lower": 4.25, "rate_upper": 4.5, "prev_rate_lower": 4.25, "prev_rate_upper": 4.5}))
        self.assertIsNone(explain.decision_text({"rate_upper": None, "prev_rate_upper": 4.5}))

    def test_panel_next_and_last(self):
        nxt = self.meeting("fomc-2026-10-28", dt.date(2026, 10, 28), utc(2026, 10, 28, 18, 0), prev_rate_lower=4.5, prev_rate_upper=4.75)
        last = self.meeting("fomc-2026-09-16", dt.date(2026, 9, 16), utc(2026, 9, 16, 18, 0), rate_lower=4.5, rate_upper=4.75,
                            prev_rate_lower=4.25, prev_rate_upper=4.5, change_bps=25, minutes_url="https://example.test/min")
        fw = {"meeting_date": "2026-10-28", "cut_probability": 10, "hold_probability": 80, "hike_probability": 10,
              "snapshot_datetime": "2026-09-20T10:00:00+00:00", "source": "manual entry (admin) from CME FedWatch"}
        p = explain.fomc_panel([nxt, last], {}, {}, fw, (4.5, 4.75), NOW)
        self.assertEqual(p["next"]["expected"]["outcome"], "Hold")
        self.assertEqual(p["next"]["previous_rate"], "4.50% - 4.75%")
        self.assertEqual(p["next"]["actual"], "Not announced yet")
        self.assertIn("normally holds a press conference", p["next"]["press_note"])
        self.assertEqual(p["last"]["decision"], "Raised rates by 25 bp to 4.50% - 4.75%.")
        self.assertEqual(p["last"]["minutes_url"], "https://example.test/min")
        self.assertIn("Federal Reserve controls US monetary policy", p["why"])

    def test_panel_without_data_says_unavailable(self):
        nxt = self.meeting("m", dt.date(2026, 10, 28), utc(2026, 10, 28, 18, 0))
        p = explain.fomc_panel([nxt], {}, {}, None, None, NOW)
        self.assertEqual(p["current_range"], "Data unavailable")
        self.assertEqual(p["next"]["previous_rate"], "Data unavailable")
        self.assertIsNone(p["next"]["expected"])
        self.assertIsNone(p["last"])


class ServiceFedRateTests(unittest.TestCase):
    """FOMC end to end with fake sources: rates around a decision, released status, plain result, payload shape."""
    MEETING = {"id": "fomc-2026-09-16", "start_date": dt.date(2026, 9, 15), "end_date": dt.date(2026, 9, 16),
               "decision_datetime": utc(2026, 9, 16, 18, 0), "has_projections": True, "press_conference": True,
               "statement_url": None, "minutes_url": None, "source_url": "u"}
    NEXT = {"id": "fomc-2026-10-28", "start_date": dt.date(2026, 10, 27), "end_date": dt.date(2026, 10, 28),
            "decision_datetime": utc(2026, 10, 28, 18, 0), "has_projections": False, "press_conference": True,
            "statement_url": None, "minutes_url": None, "source_url": "u"}

    def rates(self, through=dt.date(2026, 9, 19)):
        days, lo, up = [], [], []
        d = dt.date(2026, 9, 1)
        while d <= through:
            hiked = d >= dt.date(2026, 9, 17)
            lo.append((d, 4.50 if hiked else 4.25))
            up.append((d, 4.75 if hiked else 4.50))
            d += dt.timedelta(days=1)
        return lo, up

    def run_svc(self, store, now, **kw):
        import test_events as te
        return service.run(store, now, bls=te.FakeBLS([]), fed=te.FakeFed([self.MEETING, self.NEXT], rates=self.rates(**kw)), prices=te.FakePrices())

    def test_decided_meeting_and_payload(self):
        st = service.MemoryStore()
        st.tables["fedwatch_snapshots"] = [{"meeting_date": "2026-09-16", "snapshot_datetime": "2026-09-15T10:00:00+00:00", "cut_probability": 3,
                                            "hold_probability": 5, "hike_probability": 92, "source": "manual entry (admin) from CME FedWatch"}]
        now = utc(2026, 9, 19, 12, 0)
        p = self.run_svc(st, now)
        fomc_ev = next(e for e in p["events"] if e["id"] == "fomc-2026-09-16")
        self.assertEqual(fomc_ev["status"], "RELEASED")
        self.assertEqual(fomc_ev["result_line"], "Raised rates by 25 bp to 4.50% - 4.75%.")
        self.assertIn("matched what markets expected", fomc_ev["interpretation"])
        self.assertEqual(p["fomc"]["last"]["decision"], "Raised rates by 25 bp to 4.50% - 4.75%.")
        self.assertEqual(p["fomc"]["next"]["previous_rate"], "4.50% - 4.75%")
        self.assertEqual(p["fomc"]["current_range"], "4.50% - 4.75%")
        self.assertEqual(fomc_ev["details"]["prev_range"], "4.25% - 4.50%")
        upcoming = next(e for e in p["events"] if e["id"] == "fomc-2026-10-28")
        self.assertEqual(upcoming["tier"]["label"], "Major impact")
        self.assertEqual(len(upcoming["scenarios"]), 3)
        for key in ("summary", "glossary", "categories", "not_tracked", "sources"):
            self.assertIn(key, p)
        self.assertIn("central_banks", [c["key"] for c in p["categories"]])
        self.assertEqual(p["sources"]["fed_rates"]["data_status"], "LIVE")

    def test_rates_lag_is_reported_not_guessed(self):
        st = service.MemoryStore()
        now = utc(2026, 9, 16, 20, 0)                                       # 2h after the decision; FRED has nothing after the 16th yet
        p = self.run_svc(st, now, through=dt.date(2026, 9, 16))
        e = next(e for e in p["events"] if e["id"] == "fomc-2026-09-16")
        self.assertEqual(e["status"], "RELEASED")
        self.assertIn("data unavailable", e["result_line"])
        self.assertEqual(p["fomc"]["last"]["decision"], "Data unavailable (rate change not recorded yet).")

    def test_rate_source_failure_keeps_going(self):
        import test_events as te
        st = service.MemoryStore()
        p = service.run(st, NOW, bls=te.FakeBLS([]), fed=te.FakeFed([self.NEXT]), prices=te.FakePrices())        # no rates (raises)
        self.assertIn(p["sources"]["fed_rates"]["data_status"], ("UNAVAILABLE", "ERROR"))
        self.assertIn("fed_rates", p["data_problems"])
        self.assertEqual(p["fomc"]["current_range"], "Data unavailable")


if __name__ == "__main__":
    unittest.main()
