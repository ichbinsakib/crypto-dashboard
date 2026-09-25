"""Recent crypto news headlines from free, keyless RSS feeds (CoinDesk, Cointelegraph).

This is raw, unedited headline text only -- no sentiment analysis, no interpretation, no scoring. The app has no reliable
way to judge whether a headline is bullish or bearish, so it doesn't try; it just shows what was published and when,
so a human can weigh it themselves. A feed that fails is silently skipped, never faked."""
import datetime as dt
import re
import urllib.request
from xml.etree import ElementTree

UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}
FEEDS = [("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
         ("Cointelegraph", "https://cointelegraph.com/rss")]
MAX_PER_FEED = 8
MAX_TOTAL = 12
MAX_AGE_HOURS = 30


def _get(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _parse_date(s):
    """RFC-822 date (RSS pubDate), tolerant of the usual variants; None if it can't be read."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    return None


def parse_feed(xml_bytes, source):
    """RSS <item> elements -> [{title, link, source, published}], skipping anything unparseable."""
    out = []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = _parse_date(item.findtext("pubDate"))
        if title:
            out.append({"title": re.sub(r"\s+", " ", title), "link": link, "source": source, "published": pub})
        if len(out) >= MAX_PER_FEED:
            break
    return out


def fetch_all(now=None, get=None):
    """-> [{title, link, source, published_iso, age_min}], newest first, capped, only from the last MAX_AGE_HOURS.
    Never raises: a feed that fails or times out is simply left out."""
    now = now or dt.datetime.now(dt.timezone.utc)
    get = get or _get
    items = []
    for name, url in FEEDS:
        try:
            items += parse_feed(get(url), name)
        except Exception:  # noqa: BLE001 - one dead feed must not take the others down
            continue
    items = [x for x in items if x["published"] and (now - x["published"]) <= dt.timedelta(hours=MAX_AGE_HOURS)]
    items.sort(key=lambda x: x["published"], reverse=True)
    out = []
    for x in items[:MAX_TOTAL]:
        age = (now - x["published"]).total_seconds() / 60
        out.append({"title": x["title"], "link": x["link"], "source": x["source"],
                     "published_iso": x["published"].strftime("%Y-%m-%dT%H:%M:%SZ"), "age_min": round(age)})
    return out
