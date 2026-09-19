"""Market Events tests. Run: python -m unittest discover -s tests -v   (no network, no extra packages)."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from events import classify, config, engine, parsers, providers, reactions, service, timeutil  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
UTC = dt.timezone.utc
CFG = config.effective()


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def utc(*a):
    return dt.datetime(*a, tzinfo=UTC)


class TimezoneTests(unittest.TestCase):
    def test_winter_is_est(self):
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 1, 28, 14, 0)), utc(2026, 1, 28, 19, 0))

    def test_summer_is_edt(self):
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 9, 11, 8, 30)), utc(2026, 9, 11, 12, 30))

    def test_dst_boundaries_2026(self):
        # 2026: DST starts Sun Mar 8, ends Sun Nov 1.
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 3, 6, 8, 30)), utc(2026, 3, 6, 13, 30))   # Fri, EST
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 3, 9, 8, 30)), utc(2026, 3, 9, 12, 30))   # Mon, EDT
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 10, 30, 8, 30)), utc(2026, 10, 30, 12, 30))
        self.assertEqual(timeutil.et_to_utc(dt.datetime(2026, 11, 2, 8, 30)), utc(2026, 11, 2, 13, 30))

    def test_roundtrip_and_abbreviation(self):
        local, abbr = timeutil.utc_to_et(utc(2026, 7, 2, 12, 30))
        self.assertEqual((local, abbr), (dt.datetime(2026, 7, 2, 8, 30), "EDT"))
        local, abbr = timeutil.utc_to_et(utc(2026, 12, 4, 13, 30))
        self.assertEqual((local, abbr), (dt.datetime(2026, 12, 4, 8, 30), "EST"))

    def test_switch_instant(self):
        # 2026-03-08 07:00 UTC is 02:00 EST -> clocks jump to 03:00 EDT.
        self.assertEqual(timeutil.utc_to_et(utc(2026, 3, 8, 6, 59))[1], "EST")
        self.assertEqual(timeutil.utc_to_et(utc(2026, 3, 8, 7, 0))[1], "EDT")


class ParserTests(unittest.TestCase):
    def test_bls_schedule(self):
        ev, problems = parsers.parse_bls_schedule(read("bls_2026_09.html"), 2026, 9)
        self.assertEqual(problems, [])
        names = {e["name"] for e in ev}
        self.assertIn("Consumer Price Index", names)
        self.assertIn("Employment Situation", names)
        self.assertNotIn("Labor Day", names)                         # holiday cell is not a release
        cpi = next(e for e in ev if e["name"] == "Consumer Price Index")
        self.assertEqual(cpi["release_datetime"], utc(2026, 9, 11, 12, 30))   # 08:30 EDT
        self.assertEqual(cpi["reference_period"], "August 2026")
        jolts = next(e for e in ev if e["name"].startswith("Job Openings"))
        self.assertEqual(jolts["release_datetime"], utc(2026, 9, 1, 14, 0))   # 10:00 EDT

    def test_bls_layout_change_is_reported_not_guessed(self):
        ev, problems = parsers.parse_bls_schedule("<html><body>nothing here</body></html>", 2026, 9)
        self.assertEqual(ev, [])
        self.assertTrue(problems)

    def test_bls_malformed_cell_skipped(self):
        html = ('<table class="release-calendar"><tr><td id="d0910"><p class="day">10</p>'
                '<p><strong>Producer Price Index<br></strong>August 2026<br>soon</p></td></tr></table>')
        ev, problems = parsers.parse_bls_schedule(html, 2026, 9)
        self.assertEqual(ev, [])
        self.assertEqual(len(problems), 1)

    def test_fomc_calendar(self):
        meetings, problems = parsers.parse_fomc_calendar(read("fomc_calendars.html"))
        self.assertEqual(problems, [])
        m = {x["id"]: x for x in meetings}
        jan = m["fomc-2026-01-28"]
        self.assertEqual(jan["decision_datetime"], utc(2026, 1, 28, 19, 0))
        self.assertFalse(jan["has_projections"])
        mar = m["fomc-2026-03-18"]
        self.assertTrue(mar["has_projections"])                      # the * marks a Summary of Economic Projections
        self.assertEqual(mar["decision_datetime"], utc(2026, 3, 18, 18, 0))   # EDT already
        self.assertIn("monetary20260318a", mar["statement_url"])

    def test_fomc_month_crossing_meeting(self):
        meetings, _ = parsers.parse_fomc_calendar(read("fomc_calendars.html"), years={2023})
        first = min(meetings, key=lambda x: x["end_date"])
        self.assertEqual((first["start_date"], first["end_date"]), (dt.date(2023, 1, 31), dt.date(2023, 2, 1)))

    def test_fredgraph(self):
        rows = parsers.parse_fredgraph_csv("DATE,DFEDTARU\n2026-01-01,4.5\n2026-01-02,.\n2026-01-03,4.25\n")
        self.assertEqual(rows, [(dt.date(2026, 1, 1), 4.5), (dt.date(2026, 1, 3), 4.25)])


class ClassificationTests(unittest.TestCase):
    def test_impact_rules(self):
        self.assertEqual(classify.classify_impact("Consumer Price Index", CFG)[:2], ("CPI", "VERY_HIGH"))
        self.assertEqual(classify.classify_impact("FOMC Meeting Decision", CFG)[:2], ("FOMC", "VERY_HIGH"))
        self.assertEqual(classify.classify_impact("Employee Tenure", CFG)[:2], ("OTHER", "LOW"))

    def test_impact_is_configurable(self):
        cfg = config.effective({"impact": {"rules": [{"match": "tenure", "family": "X", "level": "HIGH", "score": 8}]}})
        self.assertEqual(classify.classify_impact("Employee Tenure", cfg), ("X", "HIGH", 8))

    def test_surprise_levels(self):
        self.assertEqual(classify.surprise(0.3, 0.3, "CPI", CFG)["classification"], "INLINE")
        s = classify.surprise(0.4, 0.3, "CPI", CFG)
        self.assertEqual((s["classification"], s["direction"]), ("MODERATE", "ABOVE"))
        s = classify.surprise(0.0, 0.3, "CPI", CFG)
        self.assertEqual((s["classification"], s["direction"], s["value"]), ("LARGE", "BELOW", -0.3))

    def test_surprise_per_family_scale(self):
        self.assertEqual(classify.surprise(150, 120, "NFP", CFG)["classification"], "MODERATE")   # 30k miss
        self.assertEqual(classify.surprise(0.4, 0.3, "CPI", CFG)["classification"], "MODERATE")

    def test_missing_forecast_or_actual(self):
        self.assertEqual(classify.surprise(0.3, None, "CPI", CFG)["classification"], "NO_FORECAST")
        self.assertEqual(classify.surprise(None, 0.3, "CPI", CFG)["classification"], "PENDING")
        self.assertIsNone(classify.surprise(0.3, None, "CPI", CFG)["value"])

    def test_revision(self):
        self.assertEqual(classify.revision(0.3, 0.2), 0.1)
        self.assertIsNone(classify.revision(0.3, 0.3))
        self.assertIsNone(classify.revision(None, 0.3))


class HeadlineTests(unittest.TestCase):
    def test_cpi_and_nfp(self):
        series = {"CUSR0000SA0": {(2026, 5): 100.0, (2026, 6): 100.3, (2026, 7): 100.8},
                  "CES0000000001": {(2026, 5): 1000.0, (2026, 6): 1100.0, (2026, 7): 1150.0}}
        self.assertEqual(providers.headline_values(series, "CPI", 2026, 7), (0.5, 0.3))
        self.assertEqual(providers.headline_values(series, "NFP", 2026, 7), (50.0, 100.0))
        self.assertEqual(providers.headline_values(series, "CPI", 2026, 8), (None, None))   # not published yet


class EngineTests(unittest.TestCase):
    NOW = utc(2026, 9, 10, 12, 0)

    def ev(self, **kw):
        base = {"id": "e1", "event_name": "Consumer Price Index", "family": "CPI", "impact_level": "VERY_HIGH",
                "status": "SCHEDULED", "release_datetime": "2026-09-11T08:30:00+00:00", "forecast": None,
                "actual": None, "previous": None}
        base.update(kw)
        return base

    def test_pre_event_high_impact_is_volatility_not_direction(self):
        a = engine.assess(self.ev(), self.NOW, CFG)
        self.assertEqual(a["label"], "HIGH_VOLATILITY_UNCERTAINTY")
        self.assertNotIn("will", a["assessment"].lower().split("rise")[0] if "rise" in a["assessment"].lower() else "")
        self.assertTrue(any("No consensus forecast" in x for x in a["evidence"]))

    def test_far_event_neutral_low(self):
        a = engine.assess(self.ev(release_datetime="2026-09-20T12:30:00+00:00"), self.NOW, CFG)
        self.assertEqual((a["label"], a["confidence"]), ("NEUTRAL", "LOW"))

    def test_hot_cpi_is_bearish_pressure(self):
        e = self.ev(status="RELEASED", actual=0.6, forecast=0.3, surprise=0.3, surprise_classification="LARGE",
                    surprise_direction="ABOVE")
        a = engine.assess(e, self.NOW, CFG)
        self.assertEqual(a["label"], "BEARISH_PRESSURE")
        self.assertEqual(a["confidence"], "MEDIUM")                    # no market confirmation stored yet
        self.assertIn("Potential downside pressure", a["assessment"])

    def test_confirming_reaction_raises_confidence_contradicting_lowers(self):
        e = self.ev(status="RELEASED", actual=0.6, forecast=0.3, surprise=0.3, surprise_classification="LARGE",
                    surprise_direction="ABOVE")
        self.assertEqual(engine.assess(e, self.NOW, CFG, reaction={"return_30m": -0.8})["confidence"], "HIGH")
        self.assertEqual(engine.assess(e, self.NOW, CFG, reaction={"return_30m": 0.8})["confidence"], "LOW")

    def test_soft_unemployment_direction_flips(self):
        e = self.ev(family="UNEMPLOYMENT", status="RELEASED", actual=4.6, forecast=4.3, surprise=0.3,
                    surprise_classification="LARGE", surprise_direction="ABOVE")
        self.assertEqual(engine.assess(e, self.NOW, CFG)["label"], "BULLISH_PRESSURE")

    def test_missing_forecast_gives_no_direction(self):
        e = self.ev(status="RELEASED", actual=0.6, surprise_classification="NO_FORECAST")
        a = engine.assess(e, self.NOW, CFG)
        self.assertEqual((a["label"], a["confidence"]), ("NEUTRAL", "LOW"))

    def test_inline_is_neutral(self):
        e = self.ev(status="RELEASED", actual=0.3, forecast=0.3, surprise=0.0, surprise_classification="INLINE")
        self.assertEqual(engine.assess(e, self.NOW, CFG)["label"], "NEUTRAL")

    def test_clustering(self):
        stamps = ("2026-09-10T13:00", "2026-09-10T14:00", "2026-09-10T20:00", "2026-09-12T12:30", "2026-09-14T12:30")
        evs = [self.ev(id=str(i), release_datetime=t + ":00+00:00") for i, t in enumerate(stamps)]
        r = engine.event_risk(evs, self.NOW, CFG)
        self.assertEqual(r["events_next_24h"], 3)
        self.assertTrue(r["high_event_density"])
        self.assertEqual(r["label"], "High Event Density")
        self.assertFalse(engine.event_risk(evs[:1], self.NOW, CFG)["high_event_density"])

    def test_stats_refuse_small_samples(self):
        rows = [{"return_1h": v} for v in (0.5, -0.2, 0.1)]
        s = engine.reaction_stats(rows, "1h", 5)
        self.assertFalse(s["sufficient"])
        self.assertNotIn("median", s)
        self.assertIn("n=3", s["note"])

    def test_stats_with_enough_data(self):
        rows = [{"return_1h": v} for v in (1, 2, 3, -1, -2, 4)]
        s = engine.reaction_stats(rows, "1h", 5)
        self.assertTrue(s["sufficient"])
        self.assertEqual((s["n"], s["median"], s["pct_positive"]), (6, 1.5, 66.7))

    def test_scenarios_state_insufficient_sample(self):
        cards = engine.scenario_cards(self.ev(), {"ABOVE": {"1h": {"n": 2, "sufficient": False}}}, CFG)
        self.assertEqual([c["title"] for c in cards], ["Above forecast", "In line", "Below forecast"])
        self.assertIn("sample too small", cards[0]["history"])
        for c in cards:
            self.assertNotIn("will rise", c["reading"].lower())
            self.assertNotIn("will fall", c["reading"].lower())


class ReactionTests(unittest.TestCase):
    def candles(self, release, minutes, start_price=100.0, drift=0.01):
        out, p = [], start_price
        for i in range(-65, minutes):
            t = release + i * 60_000
            p2 = p * (1 + drift / 100)
            out.append({"t": t, "high": max(p, p2) * 1.0005, "low": min(p, p2) * 0.9995, "close": p2})
            p = p2
        return out

    def test_horizons_and_excursions(self):
        rel = 1_800_000_000_000
        c = self.candles(rel, 1500)
        r = reactions.compute_reaction(c, rel, rel + 1500 * 60_000)
        self.assertTrue(r["complete"])
        self.assertGreater(r["return_24h"], r["return_1h"] > 0 and r["return_1h"])
        self.assertGreater(r["max_favorable_excursion"], 0)
        self.assertLess(r["max_adverse_excursion"], 0.1)
        self.assertIsNotNone(r["volatility_change"])

    def test_future_horizons_stay_empty(self):
        rel = 1_800_000_000_000
        c = self.candles(rel, 20)
        r = reactions.compute_reaction(c, rel, rel + 20 * 60_000)
        self.assertIsNotNone(r["return_15m"])
        self.assertIsNone(r["return_30m"])
        self.assertFalse(r["complete"])
        self.assertIsNone(r["volatility_change"])            # 60m window not elapsed


class FakeBLS(providers.BLSProvider):
    def __init__(self, items=None, series=None, fail=False):
        self.items, self.series, self.fail, self.calls = items or [], series or {}, fail, 0

    def fetch_events(self, months):
        self.calls += 1
        if self.fail:
            raise providers.ProviderError("BLS down")
        return list(self.items), []

    def fetch_series(self, a, b):
        if self.fail:
            raise providers.ProviderError("BLS API down")
        return self.series


class FakeFed(providers.FederalReserveProvider):
    def __init__(self, meetings=None, fail=False):
        self.meetings, self.fail = meetings or [], fail

    def fetch_meetings(self, years):
        if self.fail:
            raise providers.ProviderError("Fed down")
        return list(self.meetings), []


class FakePrices(providers.MarketPriceProvider):
    def __init__(self, candles=None, fail=False):
        self.candles, self.fail = candles or [], fail

    def klines_1m(self, symbol, s, e):
        if self.fail:
            raise providers.ProviderError("prices down")
        return self.candles


def cpi_item(day=11):
    return {"name": "Consumer Price Index", "reference_period": "August 2026",
            "release_datetime": utc(2026, 9, day, 12, 30), "source_url": "u"}


class ServiceTests(unittest.TestCase):
    NOW = utc(2026, 9, 10, 12, 0)

    def run_svc(self, store, now=None, **kw):
        kw.setdefault("bls", FakeBLS([cpi_item()]))
        kw.setdefault("fed", FakeFed())
        kw.setdefault("prices", FakePrices())
        return service.run(store, now or self.NOW, **kw)

    def test_schedule_stored_with_classification(self):
        st = service.MemoryStore()
        p = self.run_svc(st)
        e = p["events"][0]
        self.assertEqual((e["family"], e["impact_level"], e["status"]), ("CPI", "VERY_HIGH", "SCHEDULED"))
        self.assertEqual(e["release_et"], "Fri Sep 11, 08:30 AM EDT")
        self.assertEqual(p["sources"]["bls_schedule"]["data_status"], "LIVE")

    def test_duplicate_events_collapse(self):
        st = service.MemoryStore()
        self.run_svc(st, bls=FakeBLS([cpi_item(), cpi_item()]))
        self.run_svc(st, now=self.NOW + dt.timedelta(days=1), bls=FakeBLS([cpi_item()]))
        self.assertEqual(len(st.tables["economic_events"]), 1)

    def test_rescan_keeps_admin_forecast(self):
        st = service.MemoryStore()
        self.run_svc(st)
        st.tables["economic_events"][0]["forecast"] = 0.3
        st.tables["economic_events"][0]["forecast_source"] = "manual (admin)"
        self.run_svc(st, now=self.NOW + dt.timedelta(days=1), bls=FakeBLS([cpi_item()]))
        self.assertEqual(st.tables["economic_events"][0]["forecast"], 0.3)

    def test_api_failure_marks_unavailable_and_backs_off(self):
        st = service.MemoryStore()
        bls = FakeBLS(fail=True)
        p = self.run_svc(st, bls=bls)
        self.assertEqual(p["sources"]["bls_schedule"]["data_status"], "UNAVAILABLE")
        self.assertEqual(p["events"], [])
        calls = bls.calls
        self.run_svc(st, now=self.NOW + dt.timedelta(minutes=5), bls=bls)      # inside backoff window
        self.assertEqual(bls.calls, calls)
        self.run_svc(st, now=self.NOW + dt.timedelta(minutes=30), bls=bls)     # backoff elapsed
        self.assertEqual(bls.calls, calls + 1)

    def test_failure_after_success_never_shows_live(self):
        st = service.MemoryStore()
        self.run_svc(st)
        later = self.NOW + dt.timedelta(hours=13)
        p = self.run_svc(st, now=later, bls=FakeBLS(fail=True))
        self.assertEqual(p["sources"]["bls_schedule"]["data_status"], "ERROR")
        self.assertEqual(p["events"][0]["family"], "CPI")                        # previous data kept, but flagged
        p = self.run_svc(st, now=self.NOW + dt.timedelta(days=3), bls=FakeBLS(fail=True))
        self.assertEqual(p["sources"]["bls_schedule"]["data_status"], "STALE")

    def test_actual_release_revision_and_surprise(self):
        st = service.MemoryStore()
        self.run_svc(st)
        row = st.tables["economic_events"][0]
        row.update(forecast=0.3, previous=0.2)
        series = {"CUSR0000SA0": {(2026, 6): 100.0, (2026, 7): 100.3, (2026, 8): 100.9},
                  "CUSR0000SA0L1E": {(2026, 7): 100.0, (2026, 8): 100.3}}
        after = utc(2026, 9, 11, 13, 0)
        p = self.run_svc(st, now=after, bls=FakeBLS([cpi_item()], series))
        e = p["events"][0]
        self.assertEqual((e["status"], e["actual"], e["previous"]), ("RELEASED", 0.6, 0.3))
        self.assertEqual(e["revision"], 0.1)                                       # previous was revised 0.2 -> 0.3
        self.assertEqual((e["surprise_classification"], e["surprise_direction"]), ("LARGE", "ABOVE"))
        self.assertEqual(e["assessment"]["label"], "BEARISH_PRESSURE")
        self.assertIn("Actual: 0.6", e["what_happened"])

    def test_actual_not_published_yet_stays_scheduled(self):
        st = service.MemoryStore()
        self.run_svc(st)
        after = utc(2026, 9, 11, 12, 45)
        p = self.run_svc(st, now=after, bls=FakeBLS([cpi_item()], {"CUSR0000SA0": {(2026, 7): 100.0}}))
        self.assertEqual(p["events"][0]["status"], "SCHEDULED")
        self.assertIsNone(p["events"][0].get("actual"))

    def test_missing_forecast_release(self):
        st = service.MemoryStore()
        self.run_svc(st)
        series = {"CUSR0000SA0": {(2026, 7): 100.0, (2026, 8): 100.5}}
        p = self.run_svc(st, now=utc(2026, 9, 11, 13, 0), bls=FakeBLS([cpi_item()], series))
        e = p["events"][0]
        self.assertEqual(e["surprise_classification"], "NO_FORECAST")
        self.assertEqual(e["assessment"]["label"], "NEUTRAL")

    def test_outside_hours_release_time_kept(self):
        st = service.MemoryStore()
        item = {"name": "Employer Costs", "reference_period": "June 2026", "release_datetime": utc(2026, 9, 9, 3, 0),
                "source_url": "u"}
        p = self.run_svc(st, bls=FakeBLS([item]))
        self.assertEqual(p["events"][0]["release_et"], "Tue Sep 08, 11:00 PM EDT")     # local date differs from UTC date

    def test_reactions_computed_after_release(self):
        st = service.MemoryStore()
        self.run_svc(st)
        rel_ms = int(utc(2026, 9, 11, 12, 30).timestamp() * 1000)
        c = ReactionTests().candles(rel_ms, 400)
        series = {"CUSR0000SA0": {(2026, 7): 100.0, (2026, 8): 100.5}}
        p = self.run_svc(st, now=utc(2026, 9, 11, 19, 30), bls=FakeBLS([cpi_item()], series), prices=FakePrices(c))
        rows = st.tables["event_market_reactions"]
        self.assertEqual({r["asset"] for r in rows}, {"BTCUSDT", "ETHUSDT"})
        self.assertIsNotNone(rows[0]["return_4h"])
        self.assertIn("after release", p["events"][0]["what_happened"])

    def test_price_failure_does_not_break_run(self):
        st = service.MemoryStore()
        self.run_svc(st)
        series = {"CUSR0000SA0": {(2026, 7): 100.0, (2026, 8): 100.5}}
        p = self.run_svc(st, now=utc(2026, 9, 11, 13, 0), bls=FakeBLS([cpi_item()], series), prices=FakePrices(fail=True))
        self.assertEqual(p["events"][0]["status"], "RELEASED")
        self.assertIn(p["sources"]["reactions"]["data_status"], ("ERROR", "STALE", "UNAVAILABLE"))

    def test_fedwatch_is_never_invented(self):
        st = service.MemoryStore()
        p = self.run_svc(st, fed=FakeFed([{
            "id": "fomc-2026-09-16", "start_date": dt.date(2026, 9, 15), "end_date": dt.date(2026, 9, 16),
            "decision_datetime": utc(2026, 9, 16, 18, 0), "has_projections": True, "press_conference": True,
            "statement_url": None, "minutes_url": None, "source_url": "u"}]))
        self.assertIsNone(p["fedwatch"])
        self.assertEqual(p["sources"]["fedwatch"]["data_status"], "UNAVAILABLE")

    def test_manual_fedwatch_snapshot_shown_with_source_and_shift(self):
        st = service.MemoryStore()
        meeting = {"id": "fomc-2026-09-16", "start_date": dt.date(2026, 9, 15), "end_date": dt.date(2026, 9, 16),
                   "decision_datetime": utc(2026, 9, 16, 18, 0), "has_projections": True, "press_conference": True,
                   "statement_url": None, "minutes_url": None, "source_url": "u"}
        st.tables["fedwatch_snapshots"] = [
            {"meeting_date": "2026-09-16", "snapshot_datetime": "2026-09-09T12:00:00+00:00", "cut_probability": 60,
             "hold_probability": 40, "hike_probability": 0, "source": "manual entry (admin) from CME FedWatch"},
            {"meeting_date": "2026-09-16", "snapshot_datetime": "2026-09-10T11:00:00+00:00", "cut_probability": 45,
             "hold_probability": 55, "hike_probability": 0, "source": "manual entry (admin) from CME FedWatch"}]
        p = self.run_svc(st, fed=FakeFed([meeting]))
        fw = p["fedwatch"]
        self.assertEqual((fw["cut_probability"], fw["_shift_pp"], fw["data_status"]), (45, -15, "LIVE"))
        cfg = config.effective()
        notes = service.notifications(p, cfg, self.NOW, set())
        self.assertTrue(any(n["type"] == "fedwatch_shift" for n in notes))

    def test_notifications_toggles_and_dedupe(self):
        st = service.MemoryStore()
        now = utc(2026, 9, 11, 11, 45)
        p = self.run_svc(st, now=now, bls=FakeBLS([cpi_item()]))
        cfg = config.effective()
        notes = service.notifications(p, cfg, now, set())
        self.assertTrue(any(n["type"] == "event_upcoming" for n in notes))
        self.assertTrue(all(n["portion_key"] == "events" for n in notes))
        self.assertEqual(service.notifications(p, cfg, now, {n["id"] for n in notes}), [])
        off = config.effective({"notifications": {"upcoming_high_impact": False}})
        self.assertFalse(any(n["type"] == "event_upcoming" for n in service.notifications(p, off, now, set())))


class MigrationTests(unittest.TestCase):
    def test_migration_files_exist_and_lock_tables(self):
        d = os.path.join(os.path.dirname(FIX), "..", "migrations")
        sql = "".join(open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d)) if f.endswith(".sql"))
        for t in ("economic_events", "event_market_reactions", "fedwatch_snapshots"):
            self.assertIn(f"create table public.{t}", sql)
            self.assertIn(f"alter table public.{t} enable row level security", sql)
        self.assertIn("public.is_admin()", sql)


if __name__ == "__main__":
    unittest.main()


class KnowledgeTests(unittest.TestCase):
    def test_bullish_reading_is_capped_and_cautioned(self):
        from events import knowledge
        e = {"id": "u", "event_name": "Unemployment", "family": "UNEMPLOYMENT", "impact_level": "HIGH", "status": "RELEASED",
             "release_datetime": "2026-09-04T12:30:00+00:00", "actual": 4.6, "forecast": 4.3, "surprise": 0.3,
             "surprise_classification": "LARGE", "surprise_direction": "ABOVE"}
        a = engine.assess(e, utc(2026, 9, 5), CFG, reaction={"return_30m": 0.9})
        self.assertEqual(a["label"], "BULLISH_PRESSURE")
        self.assertEqual(a["confidence"], "MEDIUM")
        self.assertTrue(any("propping up" in x for x in a["evidence"]))
        self.assertIn("propping_up", knowledge.CONCEPTS)

    def test_support_check(self):
        from events import knowledge
        c = [{"t": i, "high": 101, "low": 100 if i % 5 == 0 else 100.5, "close": 100.7, "volume": 10 if i < 30 else 3} for i in range(60)]
        r = knowledge.support_check(c)
        self.assertTrue(r["volume_fading"] and r["low_retests"] >= 3)
        self.assertIsNone(knowledge.support_check(c[:10]))


class ViewpointTests(unittest.TestCase):
    def test_viewpoint_is_labelled_opinion_and_scoped(self):
        from events import knowledge
        self.assertTrue(any("opinion, not fact" in x for x in knowledge.viewpoint_for("CPI")))
        self.assertEqual(knowledge.viewpoint_for("JOLTS"), [])
        v = knowledge.VIEWPOINTS["yields_demand_for_us_debt"]
        self.assertTrue(v["source"].startswith("https://x.com/") and v["date"])


class NewsContextTests(unittest.TestCase):
    def test_news_is_labelled_and_expires(self):
        from events import knowledge
        lines = knowledge.viewpoint_for("FOMC", utc(2026, 9, 20))
        self.assertTrue(any("reported by Reuters" in x and "not verified" in x for x in lines))
        self.assertTrue(any("Crypto Dada" in x for x in lines))
        late = knowledge.viewpoint_for("FOMC", utc(2026, 11, 20))
        self.assertFalse(any("Reuters" in x for x in late))          # 30-day validity passed
        self.assertEqual(knowledge.context_items(utc(2026, 9, 20), "JOLTS"), [])
