"""Scheduled refresh for Market Events.

`run(store)` is called from the dashboard job every few minutes but each source only hits the
network when its own interval has elapsed (config.REFRESH_MINUTES), with exponential backoff after
failures. Every source keeps a status row (LIVE/RECENT/STALE/UNAVAILABLE/ERROR) so stale data is
never shown as current. Failure of any part is contained: it is logged, recorded and the run goes on.
Nothing here touches the trading-signal code.
"""
import datetime as dt
import logging
import re

from . import classify, config, engine, providers, reactions, timeutil

log = logging.getLogger("kairo.events")
UTC = timeutil.UTC


# ---------------- store implementations ----------------

class MemoryStore:
    """Dict-backed store with the same two methods as supa.Backend (tests / offline preview)."""

    def __init__(self, keys=None):
        self.tables, self.keys = {}, keys or {}

    def select(self, table, query=""):
        return [dict(r) for r in self.tables.get(table, [])]

    def upsert(self, table, rows, on_conflict):
        cols = on_conflict.split(",")
        cur = self.tables.setdefault(table, [])
        for row in rows:
            for i, ex in enumerate(cur):
                if all(ex.get(c) == row.get(c) for c in cols):
                    ex.update(row)
                    break
            else:
                cur.append(dict(row))


def _iso(d):
    return d.astimezone(UTC).isoformat() if isinstance(d, dt.datetime) else d


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------- status / scheduling ----------------

def _due(status, source, now, force=False):
    if force:
        return True
    st = status.get(source) or {}
    nr = timeutil.parse_iso(st.get("next_retry")) if st.get("next_retry") else None
    if nr:
        return now >= nr                                 # after a failure only the backoff timer decides
    la = timeutil.parse_iso(st.get("last_attempt")) if st.get("last_attempt") else None
    return not la or (now - la) >= dt.timedelta(minutes=config.REFRESH_MINUTES.get(source, 60))


def _record(store, status, source, now, ok, message=None):
    st = status.get(source) or {"source": source, "consecutive_failures": 0}
    st["last_attempt"] = _iso(now)
    if ok:
        st.update(consecutive_failures=0, next_retry=None, retrieved_at=_iso(now), last_updated=_iso(now),
                  data_status="LIVE", message=message)
    else:
        n = st.get("consecutive_failures", 0) + 1
        wait = min(config.BACKOFF["max_minutes"], config.BACKOFF["base_minutes"] * 2 ** (n - 1))
        st.update(consecutive_failures=n, next_retry=_iso(now + dt.timedelta(minutes=wait)),
                  message=(message or "failed")[:300],
                  data_status="UNAVAILABLE" if not st.get("retrieved_at") else "ERROR")
    status[source] = st
    store.upsert("provider_status", [st], "source")


def freshness(st, now):
    """LIVE / RECENT / STALE / UNAVAILABLE / ERROR for display; a failing source is never 'LIVE'."""
    if not st or not st.get("retrieved_at"):
        return "UNAVAILABLE"
    if st.get("consecutive_failures", 0) > 0:
        return "ERROR" if (now - timeutil.parse_iso(st["retrieved_at"])) < dt.timedelta(minutes=config.FRESHNESS["recent_minutes"]) else "STALE"
    age = now - timeutil.parse_iso(st["retrieved_at"])
    if age <= dt.timedelta(minutes=max(config.FRESHNESS["live_minutes"], config.REFRESH_MINUTES.get(st["source"], 0) * 1.5)):
        return "LIVE"
    return "RECENT" if age <= dt.timedelta(minutes=config.FRESHNESS["recent_minutes"]) else "STALE"


# ---------------- building event rows ----------------

def event_row(base, cfg, existing=None, now=None):
    """Merge a freshly scraped schedule item into the stored row, keeping forecast/actual/notes intact."""
    fam, level, score = classify.classify_impact(base["event_name"], cfg)
    row = {
        "id": base["id"], "event_name": base["event_name"], "event_type": fam, "family": fam,
        "source": base["source"], "release_datetime": _iso(base["release_datetime"]),
        "reference_period": base.get("reference_period"), "impact_level": level, "impact_score": score,
        "source_url": base.get("source_url"), "retrieved_at": _iso(now), "last_updated": _iso(now),
        "data_status": "LIVE", "updated_at": _iso(now),
    }
    if existing:
        for k in ("forecast", "forecast_source", "actual", "previous", "revision", "surprise",
                  "surprise_classification", "status", "details", "post_event_assessment", "market_reaction"):
            if existing.get(k) is not None:
                row[k] = existing[k]
    else:
        row["status"] = "SCHEDULED"
    return row


def bls_events(items):
    out = []
    for it in items:
        d = timeutil.utc_to_et(it["release_datetime"])[0].date().isoformat()
        out.append({"id": f"bls-{d}-{_slug(it['name'])}", "event_name": it["name"], "source": "BLS",
                    "release_datetime": it["release_datetime"], "reference_period": it["reference_period"],
                    "source_url": it["source_url"]})
    return out


def fomc_events(meetings):
    return [{"id": m["id"], "event_name": "FOMC Meeting Decision", "source": "Federal Reserve",
             "release_datetime": m["decision_datetime"],
             "reference_period": f"{m['start_date']:%b %d} - {m['end_date']:%b %d, %Y}".replace(" 0", " "),
             "source_url": m["source_url"]} for m in meetings]


def _months(now, back, ahead):
    y, m = now.year, now.month
    out = []
    for k in range(-back, ahead + 1):
        mm = m - 1 + k
        out.append((y + mm // 12, mm % 12 + 1))
    return out


# ---------------- refresh steps ----------------

def refresh_calendars(store, status, cfg, now, bls, fed, force):
    rows = {r["id"]: r for r in store.select("economic_events")}
    if _due(status, "bls_schedule", now, force):
        try:
            items, problems = bls.fetch_events(_months(now, config.CALENDAR_MONTHS_BACK, config.CALENDAR_MONTHS_AHEAD))
            evs = bls_events(items)
            seen = set()
            out = []
            for e in evs:                                   # de-duplicate: same id twice in one scrape
                if e["id"] in seen:
                    continue
                seen.add(e["id"])
                out.append(event_row(e, cfg, rows.get(e["id"]), now))
            store.upsert("economic_events", out, "id")
            for r in out:
                rows[r["id"]] = r
            _record(store, status, "bls_schedule", now, True, f"{len(out)} events" + (f"; {len(problems)} skipped" if problems else ""))
            log.info("bls schedule: %d events, %d skipped", len(out), len(problems))
        except providers.ProviderError as e:
            log.warning("bls schedule failed: %s", e)
            _record(store, status, "bls_schedule", now, False, str(e))
    if _due(status, "fed_calendar", now, force):
        try:
            meetings, problems = fed.fetch_meetings({now.year - 1, now.year, now.year + 1})
            store.upsert("fomc_meetings", [{
                "id": m["id"], "start_date": m["start_date"].isoformat(), "end_date": m["end_date"].isoformat(),
                "decision_datetime": _iso(m["decision_datetime"]), "has_projections": m["has_projections"],
                "press_conference": m["press_conference"], "statement_url": m["statement_url"],
                "minutes_url": m["minutes_url"], "source_url": m["source_url"], "retrieved_at": _iso(now),
                "updated_at": _iso(now)} for m in meetings], "id")
            out = [event_row(e, cfg, rows.get(e["id"]), now) for e in fomc_events(meetings)]
            store.upsert("economic_events", out, "id")
            for r in out:
                rows[r["id"]] = r
            _record(store, status, "fed_calendar", now, True, f"{len(meetings)} meetings")
        except providers.ProviderError as e:
            log.warning("fed calendar failed: %s", e)
            _record(store, status, "fed_calendar", now, False, str(e))
    return rows


def refresh_actuals(store, status, cfg, now, bls, rows, force):
    """For releases whose time has passed: fetch the official headline number and compute the surprise."""
    pending = [r for r in rows.values() if r.get("source") == "BLS" and r["status"] == "SCHEDULED"
               and timeutil.parse_iso(r["release_datetime"]) <= now]
    if not pending:
        return []
    if not _due(status, "bls_actuals", now, force):
        return []
    changed = []
    try:
        series = bls.fetch_series(now.year - 2, now.year)
    except providers.ProviderError as e:
        log.warning("bls actuals failed: %s", e)
        _record(store, status, "bls_actuals", now, False, str(e))
        return []
    for r in pending:
        fam = r["family"]
        rel = timeutil.parse_iso(r["release_datetime"])
        ref = _reference_month(r.get("reference_period"))
        if fam in ("CPI", "NFP") and ref:
            actual, prev = providers.headline_values(series, fam, *ref)
            if actual is None:
                if now - rel > dt.timedelta(hours=12):
                    r["data_status"] = "STALE"
                continue                                    # not published yet; try again next cycle
            details = dict(r.get("details") or {})
            if fam == "CPI":
                core, _ = providers.headline_values(series, "CORE_CPI", *ref)
                details["core_cpi_mom"] = core
            else:
                ur, _ = providers.headline_values(series, "UNEMPLOYMENT", *ref)
                details["unemployment_rate"] = ur
            s = classify.surprise(actual, r.get("forecast"), fam, cfg)
            rev = classify.revision(prev, r.get("previous"))
            r.update(actual=actual, previous=prev if prev is not None else r.get("previous"), revision=rev,
                     surprise=s["value"], surprise_classification=s["classification"], details=details,
                     status="RELEASED", last_updated=_iso(now), retrieved_at=_iso(now), data_status="LIVE",
                     updated_at=_iso(now))
            r["surprise_direction"] = s["direction"]
        elif now - rel > dt.timedelta(hours=1):
            # Released, but this system doesn't collect that headline number automatically.
            r.update(status="RELEASED", surprise_classification="NO_FORECAST" if r.get("forecast") is None else "PENDING",
                     last_updated=_iso(now), updated_at=_iso(now))
        else:
            continue
        changed.append(r)
    for r in changed:
        db_row = {k: v for k, v in r.items() if k != "surprise_direction"}
        db_row["details"] = dict(db_row.get("details") or {}, surprise_direction=r.get("surprise_direction"))
        store.upsert("economic_events", [db_row], "id")
    _record(store, status, "bls_actuals", now, True, f"{len(changed)} updated")
    return changed


def _reference_month(text):
    m = re.match(r"([A-Za-z]+)\s+(\d{4})$", text or "")
    if not m:
        return None
    for i, n in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1):
        if m.group(1).lower().startswith(n):
            return int(m.group(2)), i
    return None


def refresh_reactions(store, status, cfg, now, prices, rows, force):
    if not _due(status, "reactions", now, force):
        return
    existing = {(r["event_id"], r["asset"]): r for r in store.select("event_market_reactions")}
    now_ms = int(now.timestamp() * 1000)
    todo = []
    for r in rows.values():
        if r["status"] != "RELEASED" or r["impact_level"] not in ("MEDIUM", "HIGH", "VERY_HIGH"):
            continue
        rel = timeutil.parse_iso(r["release_datetime"])
        if now - rel > dt.timedelta(days=config.REACTION_BACKFILL_DAYS) or now < rel:
            continue
        for asset in config.REACTION_ASSETS:
            if not (existing.get((r["id"], asset)) or {}).get("complete"):
                todo.append((r, rel, asset))
    todo.sort(key=lambda t: t[1], reverse=True)              # newest first; older history backfills over later runs
    ok = True
    for r, rel, asset in todo[:12]:
        try:
            end = min(now, rel + dt.timedelta(hours=24, minutes=2))
            candles = prices.klines_1m(asset, rel - dt.timedelta(minutes=65), end)
            if not candles:
                continue
            row = reactions.compute_reaction(candles, int(rel.timestamp() * 1000), now_ms)
            row.update(event_id=r["id"], asset=asset, computed_at=_iso(now))
            store.upsert("event_market_reactions", [row], "event_id,asset")
        except providers.ProviderError as e:
            ok = False
            log.warning("reaction %s %s failed: %s", r["id"], asset, e)
    _record(store, status, "reactions", now, ok, None if ok else "price source failed")


# ---------------- public entry points ----------------

def run(store, now=None, bls=None, fed=None, prices=None, force=False):
    """Refresh everything that is due, then return the section payload for the admin dashboard."""
    now = now or timeutil.now_utc()
    bls, fed, prices = bls or providers.BLSProvider(), fed or providers.FederalReserveProvider(), prices or providers.BinanceMirrorPrices()
    cfg = config.effective({r["key"]: r["value"] for r in store.select("event_config")})
    status = {r["source"]: r for r in store.select("provider_status")}
    rows = refresh_calendars(store, status, cfg, now, bls, fed, force)
    refresh_actuals(store, status, cfg, now, bls, rows, force)
    refresh_reactions(store, status, cfg, now, prices, rows, force)
    return build_payload(store, cfg, status, now)


def build_payload(store, cfg, status, now):
    events = sorted(store.select("economic_events"), key=lambda e: e["release_datetime"])
    react = store.select("event_market_reactions")
    snaps = store.select("fedwatch_snapshots")
    meetings = store.select("fomc_meetings")
    fw = providers.ManualFedWatchProvider(snaps)
    by_event = {}
    for r in react:
        by_event.setdefault(r["event_id"], []).append(r)

    next_meeting = next((m for m in sorted(meetings, key=lambda m: m["decision_datetime"])
                         if timeutil.parse_iso(m["decision_datetime"]) >= now), None)
    fedwatch = None
    if next_meeting:
        md = next_meeting["end_date"]
        latest, prev = fw.latest(md), fw.previous(md)
        if latest:
            age_h = (now - timeutil.parse_iso(latest["snapshot_datetime"])).total_seconds() / 3600
            fedwatch = dict(latest, meeting_date=str(md), age_hours=round(age_h, 1),
                            data_status="LIVE" if age_h <= 24 else "RECENT" if age_h <= 24 * 7 else "STALE")
            if prev and prev.get("cut_probability") is not None and latest.get("cut_probability") is not None:
                fedwatch["_shift_pp"] = round(latest["cut_probability"] - prev["cut_probability"], 1)
    out_events = []
    for e in events:
        ev = dict(e)
        det = ev.get("details") or {}
        ev["surprise_direction"] = det.get("surprise_direction")
        ev["release_et"] = timeutil.fmt_et(timeutil.parse_iso(ev["release_datetime"]))
        ev["assessment"] = engine.assess(ev, now, cfg, fedwatch if ev["family"] in ("FOMC", "CPI", "NFP", "PCE") else None,
                                         next((r for r in by_event.get(ev["id"], []) if r["asset"] == "BTCUSDT"), None))
        ev["reactions"] = by_event.get(ev["id"], [])
        if ev["status"] == "RELEASED":
            ev["what_happened"] = engine.what_happened(ev, ev["reactions"])
        elif timeutil.parse_iso(ev["release_datetime"]) > now and ev["impact_level"] in engine.HIGH_LEVELS:
            hist = {d: engine.family_history(events, react, ev["family"], "BTCUSDT", cfg["weights"]["min_sample"], d)
                    for d in ("ABOVE", "INLINE", "BELOW")}
            ev["scenarios"] = engine.scenario_cards(ev, hist, cfg)
        out_events.append(ev)
    risk = engine.event_risk(out_events, now, cfg)
    ms = cfg["weights"]["min_sample"]
    history = {fam: engine.family_history(events, react, fam, config.REACTION_ASSETS[0], ms)
               for fam in {e["family"] for e in events if e["status"] == "RELEASED"}}
    lo, hi = now - dt.timedelta(days=config.PAYLOAD_DAYS_BACK), now + dt.timedelta(days=config.PAYLOAD_DAYS_AHEAD)
    out_events = [e for e in out_events if lo <= timeutil.parse_iso(e["release_datetime"]) <= hi]
    sources = {}
    for name in ("bls_schedule", "fed_calendar", "bls_actuals", "reactions"):
        st = status.get(name) or {"source": name}
        sources[name] = {"data_status": freshness(st, now), "retrieved_at": st.get("retrieved_at"),
                         "last_attempt": st.get("last_attempt"), "message": st.get("message")}
    sources["fedwatch"] = {"data_status": fedwatch["data_status"] if fedwatch else "UNAVAILABLE",
                           "retrieved_at": fedwatch["snapshot_datetime"] if fedwatch else None,
                           "message": None if fedwatch else "No automated FedWatch feed is permitted; an admin can enter a snapshot."}
    return {"generated_at": _iso(now), "events": out_events, "history": history,
            "meetings": [m for m in meetings if timeutil.parse_iso(m["decision_datetime"]) >= lo], "fedwatch": fedwatch,
            "risk": risk, "sources": sources, "config": {k: cfg[k] for k in ("impact", "thresholds", "notifications")},
            "reaction_assets": config.REACTION_ASSETS}


def notifications(payload, cfg, now, already):
    """Feed events (per-type toggles from config). `already` = ids that were sent before; ids are deterministic."""
    n = cfg["notifications"]
    out = []

    def add(id_, type_, title, body):
        if id_ not in already:
            out.append({"id": id_, "ts": _iso(now), "type": type_, "title": title, "body": body, "portion_key": "events"})
    lead = dt.timedelta(minutes=n["upcoming_lead_minutes"])
    for e in payload["events"]:
        rel = timeutil.parse_iso(e["release_datetime"])
        hi = e["impact_level"] in engine.HIGH_LEVELS
        if n["upcoming_high_impact"] and hi and e["status"] == "SCHEDULED" and now <= rel <= now + lead:
            add(f"ev-up-{e['id']}", "event_upcoming", f"Upcoming: {e['event_name']}",
                f"{e['impact_level']} impact, releases {e['release_et']}.")
        if e["status"] == "RELEASED" and now - rel < dt.timedelta(hours=6):
            if n["actual_released"] and e.get("actual") is not None and hi:
                add(f"ev-rel-{e['id']}", "event_released", f"Released: {e['event_name']}",
                    f"Actual {e['actual']} (forecast {e['forecast'] if e.get('forecast') is not None else 'n/a'}).")
            if n["large_surprise"] and e.get("surprise_classification") == "LARGE":
                add(f"ev-surp-{e['id']}", "event_surprise", f"Large surprise: {e['event_name']}",
                    f"Actual {e['actual']} vs forecast {e['forecast']} ({e['surprise']:+g}).")
    r = payload["risk"]
    if n["high_event_density"] and r["high_event_density"]:
        add(f"ev-dens-{now:%Y%m%d}", "event_density", "High Event Density",
            f"{r['events_next_24h']} high-impact events in 24h, {r['events_next_7d']} in 7 days.")
    fw = payload.get("fedwatch")
    if n["fedwatch_shift"] and fw and fw.get("_shift_pp") is not None and abs(fw["_shift_pp"]) >= n["fedwatch_shift_pp"]:
        add(f"ev-fw-{fw.get('id', fw['snapshot_datetime'])}", "fedwatch_shift", "FedWatch shift",
            f"Cut probability moved {fw['_shift_pp']:+.1f}pp for the {fw['meeting_date']} meeting.")
    if n["data_unavailable"]:
        for name, s in payload["sources"].items():
            if name != "fedwatch" and s["data_status"] in ("STALE", "ERROR", "UNAVAILABLE"):
                add(f"ev-src-{name}-{now:%Y%m%d}", "event_data", f"Events data {s['data_status'].lower()}: {name}",
                    s.get("message") or "Source not updating.")
    return out
