"""Pure HTML parsers for the official BLS release schedule and the Federal Reserve FOMC calendar.

They never fabricate: anything that doesn't parse cleanly is skipped and reported in `problems`.
"""
import datetime as dt
import re
from html import unescape

from . import timeutil

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]


def _clean(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_time(text):
    m = re.search(r"(\d{1,2}):(\d{2})\s*([AP]M)", text or "", re.I)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if not (1 <= h <= 12 and 0 <= mi < 60):
        return None
    return dt.time(h % 12 + (12 if ap == "PM" else 0), mi)


def parse_bls_schedule(html, year, month):
    """-> (events, problems). One dict per release: name, reference_period, release_datetime (UTC), source_url."""
    events, problems = [], []
    if "release-calendar" not in html:
        return [], ["no release-calendar table found (page layout changed?)"]
    for cell in re.finditer(r"<td([^>]*)>(.*?)</td>", html, re.S):
        attrs, body = cell.group(1), cell.group(2)
        idm = re.search(r'id="d(\d{2})(\d{2})"', attrs)
        if not idm or "other-month" in attrs:
            continue
        mm, dd = int(idm.group(1)), int(idm.group(2))
        if mm != month or "holiday" in attrs:
            continue
        for p in re.finditer(r"<p>\s*<strong>(.*?)</strong>(.*?)</p>", body, re.S):
            name = _clean(p.group(1))
            rest = [_clean(x) for x in re.split(r"<br\s*/?>", p.group(2)) if _clean(x)]
            if not name:
                continue
            t = parse_time(rest[-1]) if rest else None
            if t is None:
                problems.append(f"{year}-{mm:02d}-{dd:02d} {name}: no release time")
                continue
            try:
                local = dt.datetime.combine(dt.date(year, mm, dd), t)
            except ValueError:
                problems.append(f"bad date {year}-{mm}-{dd}")
                continue
            events.append({"name": name, "reference_period": rest[0] if len(rest) > 1 else None,
                           "release_datetime": timeutil.et_to_utc(local),
                           "source_url": f"https://www.bls.gov/schedule/{year}/{month:02d}_sched.htm"})
    return events, problems


def parse_fomc_calendar(html, years=None):
    """-> (meetings, problems). The decision statement is released 14:00 ET on the last meeting day."""
    meetings, problems = [], []
    panels = list(re.finditer(r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>', html))
    for i, pm in enumerate(panels):
        year = int(pm.group(1))
        if years and year not in years:
            continue
        seg = html[pm.end(): panels[i + 1].start() if i + 1 < len(panels) else len(html)]
        for row in re.split(r'<div class="[^"]*\bfomc-meeting\b[^"]*\brow\b[^"]*"|<div class="row fomc-meeting', seg)[1:]:
            mo = re.search(r"fomc-meeting__month[^>]*>\s*<strong>([A-Za-z/]+)</strong>", row)
            da = re.search(r"fomc-meeting__date[^>]*>\s*([^<]+)<", row)
            if not mo or not da:
                continue
            try:
                # A label like "Apr/May" means the meeting crosses months; the decision is in the last one.
                label = mo.group(1).split("/")[-1].lower()
                month = next(i for i, n in enumerate(_MONTHS, 1) if n.startswith(label[:3]))
                dm = re.match(r"\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?(\*?)", da.group(1))
                start_d, end_d = int(dm.group(1)), int(dm.group(2) or dm.group(1))
                start_month = month - 1 if (dm.group(2) and end_d < start_d) else month
                start = dt.date(year, start_month if start_month >= 1 else 12, start_d)
                end = dt.date(year, month, end_d)
            except (ValueError, AttributeError, StopIteration):
                problems.append(f"{year}: unparsable meeting row {mo.group(1)} {da.group(1)!r}")
                continue
            stmt = re.search(r'href="(/newsevents/pressreleases/monetary\d{8}a\.htm)"', row)
            minutes = re.search(r'href="(/monetarypolicy/fomcminutes\d{8}\.htm)"', row)
            meetings.append({
                "id": f"fomc-{end.isoformat()}", "start_date": start, "end_date": end,
                "decision_datetime": timeutil.et_to_utc(dt.datetime.combine(end, dt.time(14, 0))),
                "has_projections": dm.group(3) == "*", "press_conference": "Press Conference" in row,
                "statement_url": "https://www.federalreserve.gov" + stmt.group(1) if stmt else None,
                "minutes_url": "https://www.federalreserve.gov" + minutes.group(1) if minutes else None,
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"})
    return meetings, problems


def parse_fredgraph_csv(text):
    """FRED fredgraph.csv -> [(date, float)], skipping the '.' missing-value marker."""
    out = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            out.append((dt.date.fromisoformat(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return out
