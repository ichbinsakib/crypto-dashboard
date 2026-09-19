"""Plain-English layer for Market Events: importance tiers, "why should I care", possible scenarios, asset sensitivity,
post-event interpretation, the event-risk meter and the top-of-page summary.

Everything here is derived from stored data. Scenarios are *possible reactions, never predictions*; anything that is not
known says so ("Data unavailable") instead of being filled in. Written for an engineer with no finance background."""
import datetime as dt

from . import timeutil

TIERS = {
    "VERY_HIGH": ("major", "Major impact", "\U0001F534"),
    "HIGH": ("high", "High impact", "\U0001F7E0"),
    "MEDIUM": ("moderate", "Moderate impact", "\U0001F7E1"),
    "LOW": ("low", "Low impact", "⚪"),
}
SENS = {3: ("High", "\U0001F534"), 2: ("Medium", "\U0001F7E0"), 1: ("Low/Medium", "\U0001F7E1"), 0: ("Low", "⚪")}
ASSETS = ["USD", "Stocks", "Gold", "Crypto", "Oil"]

CATEGORIES = {"FOMC": "central_banks", "CPI": "inflation", "PPI": "inflation", "PCE": "inflation", "IMPORT_PRICES": "inflation",
              "NFP": "employment", "JOLTS": "employment", "ECI": "employment", "PRODUCTIVITY": "employment",
              "UNEMPLOYMENT": "employment", "GDP": "growth"}
CATEGORY_LABELS = {"central_banks": "Central banks", "inflation": "Inflation", "employment": "Employment", "growth": "Growth (GDP)",
                   "other": "Other"}

_SCEN_NOTE = "Possible reactions, not predictions - markets often do something unexpected."

KB = {
    "FOMC": {
        "title": "Fed interest-rate decision",
        "what": "The US Federal Reserve (the central bank) decides whether to raise, cut or keep its main interest rate.",
        "why": "Interest rates set the price of borrowing money for the whole economy. A surprise can quickly move the US dollar, stocks, bonds, gold and crypto.",
        "care": "This is the single biggest scheduled event. Prices often swing hard in the minutes after the 2:00 PM ET decision and again during the press conference.",
        "sens": [3, 3, 3, 2, 1],
        "watch": ["The rate decision itself (compare it with what was expected)", "The written statement released with it",
                  "The Fed Chair's press conference (tone matters as much as the number)"],
        "scenarios": [("Rates higher than expected", "The dollar may strengthen; risk assets such as stocks and crypto may come under pressure."),
                      ("Rates lower than expected", "The dollar may weaken; risk assets may react positively."),
                      ("Decision matches expectations", "The first reaction may be smaller, but the Chair's comments can still move markets.")],
        "interp": {"ABOVE": "The Fed set rates higher than markets expected.", "BELOW": "The Fed set rates lower than markets expected.",
                   "INLINE": "The decision matched what markets expected."},
    },
    "NFP": {
        "title": "US jobs report",
        "what": "The monthly count of new jobs created in the US, plus the unemployment rate.",
        "why": "It shows how healthy the economy is. Strong hiring can make the Fed keep rates high; weak hiring can raise recession worries or rate-cut hopes.",
        "care": "It is released at 8:30 AM ET and is one of the most volatile data releases of the month.",
        "sens": [3, 2, 2, 2, 1],
        "watch": ["Number of jobs added versus the forecast", "The unemployment rate", "Revisions to the previous months"],
        "scenarios": [("Many more jobs than expected", "A hot economy: the Fed may stay tough, so the dollar may firm while risk assets could wobble."),
                      ("Far fewer jobs than expected", "Signals a slowdown: rate-cut hopes may rise, but so may recession worries - the reaction can go either way."),
                      ("About as expected", "A smaller reaction; details such as wages and revisions may drive the move.")],
        "interp": {"ABOVE": "More jobs were added than analysts expected.", "BELOW": "Fewer jobs were added than analysts expected.",
                   "INLINE": "Job growth matched what analysts expected."},
    },
    "CPI": {
        "title": "Inflation report (CPI)",
        "what": "Consumer Price Index: how fast the prices people pay for everyday goods and services are rising.",
        "why": "The Fed's main job is keeping inflation near 2%. Hotter inflation makes rate cuts less likely; cooler inflation makes them more likely.",
        "care": "It is one of the most market-moving releases, at 8:30 AM ET. Big moves can happen within seconds.",
        "sens": [3, 3, 3, 2, 1],
        "watch": ["The headline monthly change versus the forecast", "The 'core' number (without food and energy)", "The previous month, which can be revised"],
        "scenarios": [("Higher than expected (hotter)", "Markets may fear rates stay high for longer: the dollar may strengthen and risk assets may face pressure."),
                      ("Lower than expected (cooler)", "Rate-cut hopes may rise: the dollar may weaken and risk assets may react positively."),
                      ("As expected", "A smaller first reaction; attention shifts to the details and the next Fed comments.")],
        "interp": {"ABOVE": "Prices rose faster than analysts expected (hotter inflation).",
                   "BELOW": "Prices rose more slowly than analysts expected (cooler inflation).",
                   "INLINE": "Inflation matched what analysts expected."},
    },
    "PPI": {
        "title": "Wholesale price report (PPI)",
        "what": "Producer Price Index: how fast prices are rising for businesses (before they reach shoppers).",
        "why": "It hints at where consumer inflation may go next, so it feeds into expectations about Fed rates.",
        "care": "Usually a smaller mover than CPI, but a big surprise can still shake markets.",
        "sens": [2, 2, 2, 1, 1],
        "watch": ["The monthly change versus the forecast"],
        "scenarios": [("Higher than expected", "Adds to inflation worries: the dollar may firm and risk assets may soften."),
                      ("Lower than expected", "Eases inflation worries: rate-cut hopes may rise."),
                      ("As expected", "Little reaction likely.")],
        "interp": {"ABOVE": "Business prices rose faster than expected.", "BELOW": "Business prices rose more slowly than expected.",
                   "INLINE": "Business prices matched expectations."},
    },
    "PCE": {
        "title": "Fed's preferred inflation gauge (PCE)",
        "what": "Personal Consumption Expenditures price index: another inflation measure, and the one the Fed officially targets.",
        "why": "Because the Fed targets it directly, it strongly shapes rate expectations.",
        "care": "Often already partly known from CPI, so surprises are usually smaller.",
        "sens": [3, 2, 2, 2, 1],
        "watch": ["The 'core' PCE number versus the forecast"],
        "scenarios": [("Higher than expected", "Rate-cut hopes may fade; risk assets may face pressure."),
                      ("Lower than expected", "Rate-cut hopes may grow; risk assets may react positively."),
                      ("As expected", "Little reaction likely.")],
        "interp": {"ABOVE": "The Fed's preferred inflation gauge came in higher than expected.",
                   "BELOW": "The Fed's preferred inflation gauge came in lower than expected.", "INLINE": "It matched expectations."},
    },
    "JOLTS": {
        "title": "Job openings report (JOLTS)",
        "what": "How many job openings US employers have.",
        "why": "A cooling job market can make the Fed more comfortable cutting rates.",
        "care": "A medium mover; it matters more when other data is unclear.",
        "sens": [1, 1, 1, 1, 0],
        "watch": ["Openings versus the previous month"],
        "scenarios": [("More openings than expected", "A strong job market: rate-cut hopes may fade slightly."),
                      ("Fewer openings than expected", "A cooling job market: rate-cut hopes may rise slightly.")],
        "interp": {"ABOVE": "More job openings than expected.", "BELOW": "Fewer job openings than expected.", "INLINE": "As expected."},
    },
    "ECI": {
        "title": "Employer labor-cost report (ECI)",
        "what": "How much it costs employers to pay their workers, including benefits.",
        "why": "Rising labor costs can keep inflation high, which the Fed watches closely.",
        "care": "Released quarterly; a medium mover.",
        "sens": [2, 1, 1, 1, 0],
        "watch": ["The quarterly change versus the forecast"],
        "scenarios": [("Higher than expected", "Adds to inflation worries."), ("Lower than expected", "Eases inflation worries.")],
        "interp": {"ABOVE": "Labor costs rose faster than expected.", "BELOW": "Labor costs rose more slowly than expected.", "INLINE": "As expected."},
    },
    "PRODUCTIVITY": {
        "title": "Worker productivity report",
        "what": "How much each hour of work produces.",
        "why": "Higher productivity can hold inflation down without hurting growth.",
        "care": "A minor-to-medium mover.",
        "sens": [1, 1, 1, 1, 0],
        "watch": ["Productivity and unit labor costs"],
        "scenarios": [],
        "interp": {"ABOVE": "Productivity was higher than expected.", "BELOW": "Productivity was lower than expected.", "INLINE": "As expected."},
    },
    "IMPORT_PRICES": {
        "title": "Import & export prices",
        "what": "How prices of goods the US buys from and sells to other countries are changing.",
        "why": "Imported price changes can feed into consumer inflation.",
        "care": "A minor-to-medium mover.",
        "sens": [1, 1, 1, 0, 1],
        "watch": ["Monthly change in import prices"],
        "scenarios": [],
        "interp": {"ABOVE": "Import prices rose faster than expected.", "BELOW": "Import prices rose more slowly than expected.", "INLINE": "As expected."},
    },
}
SHORT = {'FOMC': 'The Fed decides whether to raise, cut or hold interest rates.', 'NFP': 'How many jobs the US added last month - a health check on the economy.', 'CPI': 'How fast everyday prices are rising - key to Fed rate expectations.', 'PPI': 'Business-level price changes; a hint of where inflation is heading.', 'PCE': "The Fed's favourite inflation measure.", 'JOLTS': 'How many job openings US employers have.', 'ECI': 'How much employers pay for labor.', 'PRODUCTIVITY': 'How much work output each hour produces.', 'IMPORT_PRICES': 'Price changes of goods the US imports and exports.'}

GENERIC = {
    "title": None,
    "what": "A routine US government data release.",
    "why": "It adds detail to the economic picture but rarely changes what traders think the Fed will do.",
    "care": "Not usually a market mover. Safe to skip.",
    "sens": [0, 0, 0, 0, 0], "watch": [], "scenarios": [], "interp": {},
}

GLOSSARY = {
    "CPI": "Consumer Price Index. A measure of how much the prices of everyday goods and services are changing.",
    "PPI": "Producer Price Index. A measure of how much prices are changing for businesses (before they reach shoppers).",
    "GDP": "Gross Domestic Product. The total value of everything a country produces; the main measure of economic growth.",
    "FOMC": "Federal Open Market Committee. The group at the US Federal Reserve that votes on interest rates.",
    "PMI": "Purchasing Managers' Index. A survey of businesses: above 50 means expansion, below 50 means shrinking.",
    "NFP": "Non-Farm Payrolls. The monthly count of new US jobs (the main part of the jobs report).",
    "PCE": "Personal Consumption Expenditures. An inflation measure that the Fed officially targets.",
    "Jobless Claims": "How many people applied for unemployment benefits that week; a quick read on the job market.",
    "Fed Funds Rate": "The main interest rate the US Federal Reserve sets; it influences all other borrowing costs.",
    "Yield": "The return you earn on a bond. When bond prices fall, yields rise (and the reverse).",
    "Inflation": "How fast prices are rising. The Fed aims for about 2% a year.",
    "Interest Rate": "The price of borrowing money. Higher rates make loans and mortgages costlier and usually cool the economy.",
    "Volatility": "How much and how fast a price moves. High volatility means bigger, faster swings.",
    "Risk assets": "Investments that tend to rise when investors feel confident, such as stocks and crypto.",
    "Consensus": "The average forecast of analysts before a data release.",
    "bp": "Basis point. One hundredth of a percentage point (25 bp = 0.25%).",
}


def kb_for(family):
    return KB.get(family) or GENERIC


def tier(level):
    key, label, emoji = TIERS.get(level, TIERS["LOW"])
    return {"key": key, "label": label, "emoji": emoji}


def category_of(family):
    return CATEGORIES.get(family, "other")


def sensitivity(family):
    vals = kb_for(family)["sens"]
    return [{"asset": a, "level": v, "label": SENS[v][0], "emoji": SENS[v][1]} for a, v in zip(ASSETS, vals)]


def plain_title(event):
    return kb_for(event.get("family"))["title"] or event["event_name"]


def _et(iso):
    return timeutil.utc_to_et(timeutil.parse_iso(iso))[0]


def when_words(iso, now):
    """'today at 8:30 AM ET', 'tomorrow at 2:00 PM ET', 'on Wednesday at 2:00 PM ET', 'on Oct 14 at 8:30 AM ET'."""
    local = _et(iso)
    today = timeutil.utc_to_et(now)[0].date()
    t = local.strftime("%I:%M %p").lstrip("0")
    days = (local.date() - today).days
    if days == 0:
        return f"today at {t} ET"
    if days == 1:
        return f"tomorrow at {t} ET"
    if 1 < days < 7:
        return f"on {local.strftime('%A')} at {t} ET"
    return f"on {local.strftime('%b')} {local.day} at {t} ET"


def hours_until(iso, now):
    return (timeutil.parse_iso(iso) - now).total_seconds() / 3600


def _fmt(v):
    return "Data unavailable" if v is None else f"{v:g}"


def result_lines(event):
    """(result_line, interpretation) for a released event, from stored numbers only."""
    fam = event.get("family")
    kb = kb_for(fam)
    a, f, p = event.get("actual"), event.get("forecast"), event.get("previous")
    if a is None:
        if fam in ("CPI", "NFP"):
            return "The result has not been recorded yet.", None
        return "The numbers for this release are not collected automatically here; see the official release for the result.", None
    cls, dirn = event.get("surprise_classification"), event.get("surprise_direction")
    if f is None or cls in (None, "PENDING", "NO_FORECAST"):
        return (f"Result: {a:g}" + (f" (previous {p:g})" if p is not None else "") + ". No forecast was recorded for this release, "
                "so we can't say whether it beat or missed expectations.", None)
    word = {"ABOVE": "higher", "BELOW": "lower", "INLINE": "in line"}.get(dirn, "in line")
    size = {"MODERATE": "somewhat ", "LARGE": "much "}.get(cls, "")
    line = f"Result: {a:g} versus {f:g} expected - " + (f"{size}{word} than expected." if dirn != "INLINE" else "in line with expectations.")
    interp = kb["interp"].get(dirn or "INLINE")
    return line, interp


def scenario_rows(event):
    kb = kb_for(event.get("family"))
    return [{"scenario": s, "reaction": r} for s, r in kb["scenarios"]]


def market_line(reactions):
    """One plain sentence about the stored BTC/ETH move after a release (or None)."""
    parts = []
    for r in reactions or []:
        moves = [(h, r.get("return_" + h)) for h in ("30m", "1h", "24h")]
        moves = [(h, v) for h, v in moves if v is not None]
        if moves:
            parts.append(f"{r['asset'].replace('USDT', '')}: " + ", ".join(f"{v:+.1f}% after {h}" for h, v in moves))
    if not parts:
        return None
    return "Recorded market move - " + "; ".join(parts) + ". One event is an example, not a pattern."


def enrich(event, now, reactions=None):
    """Adds the plain-language fields the UI shows at levels 1 and 2 (numbers stay in the event for level 3)."""
    fam = event.get("family")
    kb = kb_for(fam)
    t = tier(event.get("impact_level"))
    out = {"tier": t, "category": category_of(fam), "category_label": CATEGORY_LABELS[category_of(fam)],
           "plain_title": plain_title(event), "what": kb["what"], "why": kb["why"], "care": kb["care"],
           "sensitivity": sensitivity(fam), "watch": kb["watch"], "one_liner": SHORT.get(fam, "A routine data release; rarely moves markets.")}
    released = event.get("status") == "RELEASED"
    if released:
        line, interp = result_lines(event)
        out["result_line"], out["interpretation"] = line, interp
        out["market_line"] = market_line(reactions)
    elif t["key"] in ("major", "high", "moderate"):
        out["scenarios"] = scenario_rows(event)
        out["scenario_note"] = _SCEN_NOTE
    return out


# ---------------- risk meter + summary ----------------

_POINTS = {"VERY_HIGH": 4.0, "HIGH": 2.0, "MEDIUM": 0.5, "LOW": 0.0}
_METER = [(6.0, "very_high", "VERY HIGH", "\U0001F534"), (3.5, "high", "HIGH", "\U0001F7E0"), (1.5, "moderate", "MODERATE", "\U0001F7E1"),
          (0.0, "low", "LOW", "\U0001F7E2")]


def _upcoming(events, now, days=7):
    out = []
    for e in events:
        if e.get("status") != "SCHEDULED":
            continue
        h = hours_until(e["release_datetime"], now)
        if -6 <= h <= days * 24:
            out.append((h, e))
    return sorted(out, key=lambda x: x[0])


def risk_meter(events, now):
    """Event-risk level from the number and importance of scheduled events: full weight inside 48h, 40% for days 3-7.
    It measures how much volatility to expect, not which way prices will go."""
    score, drivers = 0.0, []
    for h, e in _upcoming(events, now):
        w = 1.0 if h <= 48 else 0.4
        score += _POINTS.get(e.get("impact_level"), 0) * w
        if e.get("impact_level") in ("VERY_HIGH", "HIGH"):
            drivers.append({"title": plain_title(e), "when": when_words(e["release_datetime"], now), "hours": round(h, 1),
                            "tier": tier(e["impact_level"]), "id": e["id"], "within_48h": h <= 48})
    for thr, key, label, emoji in _METER:
        if score >= thr:
            break
    near = [d for d in drivers if d["within_48h"]]
    if key == "low":
        why = "No major or high-impact events are scheduled in the next 7 days."
    elif near:
        why = f"{len(near)} important event{'s' if len(near) != 1 else ''} scheduled within the next 48 hours."
    else:
        why = "Important events are scheduled later this week, none in the next 48 hours."
    return {"key": key, "label": label, "emoji": emoji, "score": round(score, 1), "why": why, "drivers": drivers[:6],
            "scale": [m[2] for m in reversed(_METER)]}


def _themes(drivers_events):
    cats = {}
    for e in drivers_events:
        cats.setdefault(category_of(e["family"]), []).append(plain_title(e))
    for cat, titles in cats.items():
        if len(titles) >= 2 and cat != "other":
            names = " and ".join(t.split(" (")[0] for t in titles[:3])
            return (f"Several upcoming events ({names}) all measure the same thing - "
                    f"{'inflation' if cat == 'inflation' else 'the job market' if cat == 'employment' else 'central-bank policy'} - "
                    f"so together they tell one story.")
    return None


def _recent(events, now):
    """Sentence about released major/high events in the last 7 days, only where a surprise could be measured."""
    rows = []
    for e in events:
        if e.get("status") != "RELEASED" or e.get("impact_level") not in ("VERY_HIGH", "HIGH"):
            continue
        if not (0 <= -hours_until(e["release_datetime"], now) <= 168):
            continue
        rows.append(e)
    if not rows:
        return None
    fed = next((e for e in rows if e.get("family") == "FOMC" and (e.get("details") or {}).get("decision")), None)
    if fed:
        rows = [e for e in rows if e is not fed]
        head = f"Fed decision ({_et(fed['release_datetime']).strftime('%b')} {_et(fed['release_datetime']).day}): {fed['details']['decision']}"
        if not rows:
            return head
    else:
        head = None
    measured = [e for e in rows if e.get("surprise_classification") in ("MODERATE", "LARGE")]
    if not measured:
        names = ", ".join(plain_title(e) for e in rows[:2])
        tail = f"Already released this week: {names}. No forecast was on file, so we can't say if they beat or missed expectations."
        return f"{head} {tail}" if head else tail
    parts = []
    for e in measured[:2]:
        word = {"ABOVE": "higher", "BELOW": "lower"}.get(e.get("surprise_direction"), "different")
        parts.append(f"{plain_title(e)} came in {word} than expected")
    return (head + " " if head else "") + "Recent results: " + "; ".join(parts) + "."


def summary(events, now, meetings=None):
    """The 'Market Event Summary' card: level, one-paragraph headline, what it means, what to watch, one-line takeaway."""
    meter = risk_meter(events, now)
    up = _upcoming(events, now)
    def weight(e):
        base = e.get("impact_score") or {"VERY_HIGH": 9, "HIGH": 7}.get(e.get("impact_level"), 0)
        return base + (1 if e.get("family") == "FOMC" else 0)
    ranked = [(h, e) for h, e in up if e.get("impact_level") in ("VERY_HIGH", "HIGH")]
    top = max(ranked, key=lambda x: (weight(x[1]), -x[0]), default=None)       # biggest first, earlier wins a tie
    important = [e for h, e in ranked]
    today_et = timeutil.utc_to_et(now)[0].date()
    todays = [e for e in important if _et(e["release_datetime"]).date() == today_et]
    out = {"level": meter["key"], "label": meter["label"], "emoji": meter["emoji"], "why": meter["why"], "drivers": meter["drivers"],
           "scale": meter["scale"], "score": meter["score"]}
    if top:
        h, e = top
        kb = kb_for(e["family"])
        others = [x for x in important if x["id"] != e["id"]]
        head = f"The biggest event coming up is the {plain_title(e)} {when_words(e['release_datetime'], now)}."
        if others:
            head += f" {len(others)} other important event{'s' if len(others) != 1 else ''} follow{'' if len(others) != 1 else 's'} within the week."
        out["headline"] = head
        out["what_it_means"] = kb["why"]
        out["watch"] = list(kb["watch"])[:4]
        when = when_words(e["release_datetime"], now)
        if meter["key"] in ("very_high", "high"):
            out["takeaway"] = (f"Expect higher-than-normal volatility around the {plain_title(e)} ({when}). "
                               "It is safer not to open new leveraged trades right before it.")
        else:
            out["takeaway"] = f"One important event is coming ({when}); expect a possible short burst of movement around it."
    else:
        nxt = next((e for e in sorted(events, key=lambda x: x["release_datetime"])
                    if e.get("status") == "SCHEDULED" and e.get("impact_level") in ("VERY_HIGH", "HIGH")
                    and hours_until(e["release_datetime"], now) > 0), None)
        out["headline"] = "Quiet stretch: no major scheduled events in the next 7 days."
        if nxt:
            days = int(hours_until(nxt["release_datetime"], now) // 24)
            out["headline"] += f" The next big one is the {plain_title(nxt)} {when_words(nxt['release_datetime'], now)} (in about {days} days)."
        out["what_it_means"] = "With no big scheduled news, price moves are more likely to come from other things such as headlines, money flows or technical levels."
        out["watch"] = ["Nothing major on the calendar - check back before the next important release."]
        out["takeaway"] = "Event risk is low right now."
    out["today"] = ("Today: " + "; ".join(f"{plain_title(e)} at {_et(e['release_datetime']).strftime('%I:%M %p').lstrip('0')} ET"
                                        for e in todays[:3]) + ".") if todays else None
    out["theme"] = _themes(important) if len(important) > 1 else None
    out["recent"] = _recent(events, now)
    out["environment"] = {"low": "quiet", "moderate": "moderately busy", "high": "busy", "very_high": "very busy"}[meter["key"]]
    return out


# ---------------- FOMC ----------------

def _rate_text(lo, hi):
    return "Data unavailable" if lo is None or hi is None else f"{lo:.2f}% - {hi:.2f}%"


def decision_text(m):
    """Plain sentence about a decided meeting from stored rate fields."""
    if m.get("rate_upper") is None or m.get("prev_rate_upper") is None:
        return None
    bp = m.get("change_bps")
    if bp is None:
        bp = round((m["rate_upper"] - m["prev_rate_upper"]) * 100)
    rng = _rate_text(m["rate_lower"], m["rate_upper"])
    if bp > 0:
        return f"Raised rates by {bp:g} bp to {rng}."
    if bp < 0:
        return f"Cut rates by {abs(bp):g} bp to {rng}."
    return f"Held rates at {rng}."


def _expected(fedwatch, meeting):
    if not fedwatch or str(fedwatch.get("meeting_date")) != str(meeting.get("end_date")):
        return None
    opts = [("Cut", fedwatch.get("cut_probability")), ("Hold", fedwatch.get("hold_probability")), ("Hike", fedwatch.get("hike_probability"))]
    opts = [(n, p) for n, p in opts if p is not None]
    if not opts:
        return None
    n, p = max(opts, key=lambda x: x[1])
    return {"outcome": n, "probability": p, "as_of": fedwatch.get("snapshot_datetime"), "source": fedwatch.get("source")}


def fomc_panel(meetings, events_by_id, reactions_by_event, fedwatch, current_range, now):
    """Special presentation for the next and the most recent Fed meeting."""
    ms = sorted(meetings or [], key=lambda m: m["decision_datetime"])
    nxt = next((m for m in ms if timeutil.parse_iso(m["decision_datetime"]) > now), None)
    past = [m for m in ms if timeutil.parse_iso(m["decision_datetime"]) <= now]
    last = past[-1] if past else None
    kb = KB["FOMC"]
    panel = {"why_title": "Why FOMC matters",
             "why": ("The Federal Reserve controls US monetary policy. Changes in interest rates affect borrowing costs, the US dollar, "
                     "stocks, bonds, gold and other markets."),
             "current_range": _rate_text(*current_range) if current_range else "Data unavailable", "next": None, "last": None}
    if nxt:
        d = timeutil.parse_iso(nxt["decision_datetime"])
        ev = events_by_id.get(nxt["id"], {})
        minutes_est = (d + dt.timedelta(days=21))
        panel["next"] = {
            "id": nxt["id"], "dates": f"{nxt['start_date']} to {nxt['end_date']}", "decision_time": timeutil.fmt_et(d),
            "when": when_words(nxt["decision_datetime"], now), "hours": round(hours_until(nxt["decision_datetime"], now), 1),
            # The Fed's page only links the press conference after it happens, so an upcoming meeting never proves there is none.
            "press_conference": True,
            "press_note": "The Fed Chair normally holds a press conference about 30 minutes after the decision.",
            "projections": bool(nxt.get("has_projections")),
            "projections_note": "New economic projections (the 'dot plot') are published at this meeting." if nxt.get("has_projections") else None,
            "previous_rate": _rate_text(nxt.get("prev_rate_lower") or (current_range[0] if current_range else None),
                                        nxt.get("prev_rate_upper") or (current_range[1] if current_range else None)),
            "expected": _expected(fedwatch, nxt), "actual": "Not announced yet",
            "minutes": f"Minutes are usually published about 3 weeks later (around {minutes_est.astimezone(timeutil.UTC).strftime('%b %d')}); date not yet confirmed.",
            "statement_url": nxt.get("statement_url"), "impact": ev.get("impact_level", "VERY_HIGH"),
        }
    if last:
        ev = events_by_id.get(last["id"], {})
        res = decision_text(last)
        panel["last"] = {
            "id": last["id"], "date": str(last["end_date"]), "decision_time": timeutil.fmt_et(timeutil.parse_iso(last["decision_datetime"])),
            "decision": res or "Data unavailable (rate change not recorded yet).",
            "previous_rate": _rate_text(last.get("prev_rate_lower"), last.get("prev_rate_upper")),
            "actual_rate": _rate_text(last.get("rate_lower"), last.get("rate_upper")),
            "minutes_url": last.get("minutes_url"), "statement_url": last.get("statement_url"),
            "market": market_line(reactions_by_event.get(last["id"])),
        }
    return panel
