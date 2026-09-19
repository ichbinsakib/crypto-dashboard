"""EventIntelligenceEngine: turns stored observations into a cautious, evidence-listed assessment.

It never predicts a price. Outputs are one of BULLISH_PRESSURE, BEARISH_PRESSURE, NEUTRAL or
HIGH_VOLATILITY_UNCERTAINTY, always with a LOW/MEDIUM/HIGH confidence and the evidence behind it.
Confidence only rises when independent pieces of stored evidence agree; with a thin history it
stays LOW and says why.
"""
import statistics

from . import timeutil

HIGH_LEVELS = ("HIGH", "VERY_HIGH")
HORIZONS = ["5m", "15m", "30m", "1h", "4h", "24h"]


# ---------- clustering / event risk ----------

def event_risk(events, now, cfg):
    """Counts of high-impact scheduled events in the next 24h / 3d / 7d and an event_risk_score."""
    def upcoming(hours):
        end = now + timeutil.dt.timedelta(hours=hours)
        return [e for e in events if e.get("status") == "SCHEDULED" and e.get("impact_level") in HIGH_LEVELS
                and now <= timeutil.parse_iso(e["release_datetime"]) <= end]
    n24, n3d, n7d = len(upcoming(24)), len(upcoming(72)), len(upcoming(168))
    d = cfg["weights"]["density"]
    score = min(100, n24 * 25 + max(0, n3d - n24) * 10 + max(0, n7d - n3d) * 4)
    dense = n24 >= d["events_24h_high"] or n3d >= d["events_3d_high"] or n7d >= d["events_7d_high"]
    return {"events_next_24h": n24, "events_next_3d": n3d, "events_next_7d": n7d,
            "event_risk_score": score, "high_event_density": dense,
            "label": "High Event Density" if dense else ("Elevated" if score >= 25 else "Normal")}


# ---------- historical statistics (sample sizes always shown) ----------

def reaction_stats(rows, horizon, min_sample):
    """rows: event_market_reactions dicts. Returns None if the sample is too small to say anything."""
    vals = [r.get(f"return_{horizon}") for r in rows if r.get(f"return_{horizon}") is not None]
    n = len(vals)
    if n < min_sample:
        return {"n": n, "sufficient": False, "note": f"Sample too small (n={n}, need {min_sample}) - no statistic shown."}
    return {"n": n, "sufficient": True, "median": round(statistics.median(vals), 3),
            "mean": round(statistics.fmean(vals), 3),
            "pct_positive": round(100 * sum(1 for v in vals if v > 0) / n, 1),
            "worst": round(min(vals), 3), "best": round(max(vals), 3)}


def family_history(events, reactions, family, asset, min_sample, surprise_dir=None):
    """Stats for released events of one family (optionally only those with an ABOVE/BELOW surprise)."""
    ids = {e["id"] for e in events if e.get("family") == family and e.get("status") == "RELEASED"
           and (surprise_dir is None or e.get("surprise_direction") == surprise_dir)}
    rows = [r for r in reactions if r["event_id"] in ids and r.get("asset") == asset]
    return {h: reaction_stats(rows, h, min_sample) for h in ("15m", "1h", "4h")} | {"events": len(ids)}


# ---------- assessment ----------

def _hours_to(event, now):
    return (timeutil.parse_iso(event["release_datetime"]) - now).total_seconds() / 3600


def assess(event, now, cfg, fedwatch=None, reaction=None):
    """-> dict(label, confidence, evidence[list], observed{}, assessment str, phase).

    `observed` holds facts only; `assessment` is the system's reading of them.
    """
    fam, level = event.get("family"), event.get("impact_level")
    released = event.get("status") == "RELEASED"
    observed = {"event": event["event_name"], "release_utc": event["release_datetime"],
                "forecast": event.get("forecast"), "actual": event.get("actual"),
                "previous": event.get("previous"), "surprise": event.get("surprise"),
                "surprise_classification": event.get("surprise_classification")}
    ev = []

    if not released:
        h = _hours_to(event, now)
        observed["hours_to_release"] = round(h, 1)
        ev.append(f"Impact level {level} ({fam}).")
        if event.get("forecast") is None:
            ev.append("No consensus forecast on file - a surprise cannot be measured in advance.")
        else:
            ev.append(f"Forecast on file: {event['forecast']} (source: {event.get('forecast_source') or 'unknown'}).")
        if fedwatch and fam in ("FOMC", "CPI", "NFP", "PCE"):
            ev.append(f"FedWatch (as of {fedwatch['snapshot_datetime']}): hold {fedwatch.get('hold_probability')}%, "
                      f"cut {fedwatch.get('cut_probability')}%, hike {fedwatch.get('hike_probability')}%.")
        if level in HIGH_LEVELS and 0 <= h <= 24:
            return {"phase": "pre", "label": "HIGH_VOLATILITY_UNCERTAINTY", "confidence": "MEDIUM",
                    "evidence": ev + [f"High-impact release in {h:.1f}h: markets often move sharply around these, in either direction."],
                    "observed": observed,
                    "assessment": "Volatility risk is elevated around the release. The direction is not predictable from what is known now."}
        return {"phase": "pre", "label": "NEUTRAL", "confidence": "LOW", "evidence": ev, "observed": observed,
                "assessment": "No basis for a directional view before the release."}

    sd, cls = event.get("surprise_direction"), event.get("surprise_classification")
    fc = event.get("forecast")
    ev.append(f"Actual {event.get('actual')} vs forecast {'n/a' if fc is None else fc}"
              + (f" -> surprise {event['surprise']:+g} ({cls}, {sd})." if event.get("surprise") is not None else "."))
    if event.get("previous") is not None:
        ev.append(f"Previous reading: {event['previous']}" + (f" (revised by {event['revision']})" if event.get("revision") else "") + ".")
    if cls in ("NO_FORECAST", "PENDING", None):
        return {"phase": "post", "label": "NEUTRAL", "confidence": "LOW",
                "evidence": ev + ["No measurable surprise (missing forecast or result), so no directional reading is made."],
                "observed": observed, "assessment": "Result recorded; surprise cannot be assessed without a forecast."}
    if cls == "INLINE":
        return {"phase": "post", "label": "NEUTRAL", "confidence": "MEDIUM", "evidence": ev,
                "observed": observed, "assessment": "Released in line with the forecast; little new information."}

    rd = cfg["weights"]["risk_direction"].get(fam)
    if rd is None:
        return {"phase": "post", "label": "HIGH_VOLATILITY_UNCERTAINTY", "confidence": "LOW",
                "evidence": ev + [f"No configured risk direction for {fam}."], "observed": observed,
                "assessment": "A notable surprise, but the system has no rule for which way it leans."}
    sign = (1 if sd == "ABOVE" else -1) * rd
    label = "BULLISH_PRESSURE" if sign > 0 else "BEARISH_PRESSURE"
    points = 1 if cls == "MODERATE" else 2
    ev.append(f"{cls.title()} {'upside' if sd == 'ABOVE' else 'downside'} surprise; configured reading for {fam}: "
              f"{'higher' if rd < 0 else 'lower'} prints tend to tighten financial conditions." if rd < 0 else
              f"{cls.title()} {'upside' if sd == 'ABOVE' else 'downside'} surprise; configured reading for {fam}: "
              f"higher prints tend to ease financial conditions.")
    if reaction and reaction.get("return_30m") is not None:
        r30 = reaction["return_30m"]
        agrees = (r30 > 0) == (sign > 0) and abs(r30) >= 0.2
        ev.append(f"Stored market move: {r30:+.2f}% at 30m ({'agrees with' if agrees else 'does not confirm'} this reading).")
        points += 1 if agrees else -1
    if fedwatch and fedwatch.get("_shift_pp") is not None:
        ev.append(f"FedWatch cut probability moved {fedwatch['_shift_pp']:+.1f}pp since the previous snapshot.")
    conf = "HIGH" if points >= 3 else "MEDIUM" if points >= 2 else "LOW"
    return {"phase": "post", "label": label, "confidence": conf, "evidence": ev, "observed": observed,
            "assessment": ("Potential upside pressure" if sign > 0 else "Potential downside pressure")
            + " on risk assets. This is a reading of the data, not a forecast."}


def scenario_cards(event, history, cfg, asset="BTCUSDT"):
    """Pre-event 'what if' cards with conditional wording and historical evidence (or an honest gap)."""
    fam = event.get("family")
    rd = cfg["weights"]["risk_direction"].get(fam)
    ms = cfg["weights"]["min_sample"]
    cards = []
    for title, direction, lean in (("Above forecast", "ABOVE", None), ("In line", "INLINE", "NEUTRAL"),
                                   ("Below forecast", "BELOW", None)):
        if lean is None:
            if rd is None:
                reading = "No configured reading for this event type."
            else:
                up = (direction == "ABOVE") == (rd > 0)
                reading = ("Could add upside pressure on risk assets." if up
                           else "Could add downside pressure on risk assets.")
        else:
            reading = "Likely limited new information; volatility may fade."
        h = (history.get(direction) or {}).get("1h") if history else None
        if h and h.get("sufficient"):
            hist = (f"Past {fam} releases with this outcome: median 1h {asset} move {h['median']:+.2f}%, "
                    f"{h['pct_positive']}% up (n={h['n']}).")
        else:
            n = h["n"] if h else 0
            hist = f"Historical reaction not shown: sample too small (n={n}, need {ms})."
        cards.append({"title": title, "reading": reading, "history": hist})
    return cards


def what_happened(event, reactions):
    """Plain post-event summary built only from stored fields."""
    parts = [f"{event['event_name']} ({event.get('reference_period') or 'n/a'}) was released."]
    if event.get("actual") is not None:
        parts.append(f"Actual: {event['actual']}; forecast: {event.get('forecast') if event.get('forecast') is not None else 'not on file'}; "
                     f"previous: {event.get('previous') if event.get('previous') is not None else 'n/a'}.")
        if event.get("surprise_classification") not in (None, "PENDING"):
            parts.append(f"Surprise: {event['surprise_classification']}"
                         + (f" ({event['surprise']:+g})." if event.get("surprise") is not None else "."))
    for r in reactions or []:
        moves = [f"{h} {r['return_' + h]:+.2f}%" for h in HORIZONS if r.get("return_" + h) is not None]
        if moves:
            parts.append(f"{r['asset']} after release: " + ", ".join(moves) +
                         (f"; max favorable {r['max_favorable_excursion']:+.2f}% / max adverse {r['max_adverse_excursion']:+.2f}%"
                          if r.get("max_favorable_excursion") is not None else "") + ".")
    return " ".join(parts)
