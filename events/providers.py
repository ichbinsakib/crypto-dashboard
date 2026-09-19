"""Data providers behind small interfaces, so a source can be swapped without touching the engine.

Every provider raises ProviderError on failure (network, HTTP, malformed data) and never returns
made-up values. Only official/permitted sources are accessed, with an identifying User-Agent and
conservative request spacing (see config.REFRESH_MINUTES).
"""
import datetime as dt
import json
import urllib.error
import urllib.request

from . import config, parsers, timeutil


class ProviderError(Exception):
    pass


def http_get(url, headers=None, timeout=None, retries=2):
    h = {"User-Agent": config.USER_AGENT, "Accept": "*/*"}
    h.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout or config.HTTP_TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:
                break                                   # 403/404 won't improve on retry
        except Exception as e:                          # noqa: BLE001 - network errors of any kind
            last = type(e).__name__
        if attempt < retries:
            import time
            time.sleep(1.5 * (attempt + 1))
    raise ProviderError(f"GET {url.split('?')[0]} failed: {last}")


# ---------------- interfaces ----------------

class EconomicCalendarProvider:
    name = "calendar"

    def fetch_events(self, months):                     # months: [(year, month)]
        raise NotImplementedError


class BLSProvider(EconomicCalendarProvider):
    """Official BLS release schedule (one page per month) + BLS public data API for actual values."""
    name = "bls_schedule"

    def fetch_events(self, months):
        out, problems = [], []
        for y, m in months:
            html = http_get(f"https://www.bls.gov/schedule/{y}/{m:02d}_sched.htm")
            ev, pr = parsers.parse_bls_schedule(html, y, m)
            out += ev
            problems += pr
        if not out:
            raise ProviderError("BLS schedule parsed to zero events" + (f": {problems[:2]}" if problems else ""))
        return out, problems

    # series id -> (family label, how to turn levels into the headline number)
    SERIES = {"CUSR0000SA0": "CPI", "CUSR0000SA0L1E": "CORE_CPI", "LNS14000000": "UNEMPLOYMENT", "CES0000000001": "NFP"}

    def fetch_series(self, year_from, year_to):
        """-> {series_id: {(year, month): value}} from the BLS public API (v1 needs no key)."""
        version = "v2" if config.BLS_API_KEY else "v1"
        body = {"seriesid": list(self.SERIES), "startyear": str(year_from), "endyear": str(year_to)}
        if config.BLS_API_KEY:
            body["registrationkey"] = config.BLS_API_KEY
        req = urllib.request.Request(f"https://api.bls.gov/publicAPI/{version}/timeseries/data/",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": config.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as r:
                payload = json.loads(r.read())
        except Exception as e:                          # noqa: BLE001
            raise ProviderError(f"BLS API failed: {type(e).__name__}") from None
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise ProviderError("BLS API: " + "; ".join(payload.get("message") or ["request not succeeded"])[:200])
        out = {}
        for s in payload.get("Results", {}).get("series", []):
            vals = {}
            for d in s.get("data", []):
                if d.get("period", "").startswith("M") and d["period"] != "M13":
                    try:
                        vals[(int(d["year"]), int(d["period"][1:]))] = float(d["value"])
                    except (ValueError, KeyError):
                        continue
            out[s["seriesID"]] = vals
        return out


def headline_values(series, family, ref_year, ref_month):
    """Headline figure for a release from index/level series, or (None, None) if not yet published.
    CPI/PPI-style: month-over-month % change. NFP: monthly change in thousands. Unemployment: the rate."""
    def prev_month(y, m):
        return (y - 1, 12) if m == 1 else (y, m - 1)
    key = {"CPI": "CUSR0000SA0", "CORE_CPI": "CUSR0000SA0L1E", "UNEMPLOYMENT": "LNS14000000", "NFP": "CES0000000001"}.get(family)
    vals = series.get(key) if key else None
    if not vals or (ref_year, ref_month) not in vals:
        return None, None
    cur = vals[(ref_year, ref_month)]
    py, pm = prev_month(ref_year, ref_month)
    if family in ("CPI", "CORE_CPI"):
        if (py, pm) not in vals:
            return None, None
        pp, ppp = prev_month(py, pm)
        actual = round((cur / vals[(py, pm)] - 1) * 100, 1)
        previous = round((vals[(py, pm)] / vals[(pp, ppp)] - 1) * 100, 1) if (pp, ppp) in vals else None
        return actual, previous
    if family == "NFP":
        if (py, pm) not in vals:
            return None, None
        pp, ppp = prev_month(py, pm)
        return round(cur - vals[(py, pm)], 1), (round(vals[(py, pm)] - vals[(pp, ppp)], 1) if (pp, ppp) in vals else None)
    return cur, vals.get((py, pm))                      # UNEMPLOYMENT: level itself


class FederalReserveProvider:
    name = "fed_calendar"

    def fetch_meetings(self, years):
        html = http_get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
        meetings, problems = parsers.parse_fomc_calendar(html, set(years))
        if not meetings:
            raise ProviderError("Fed calendar parsed to zero meetings" + (f": {problems[:2]}" if problems else ""))
        return meetings, problems

    def fetch_target_range(self):
        """Current fed funds target range from FRED (fredgraph.csv, no key needed) -> (lower, upper, as_of)."""
        try:
            lo = parsers.parse_fredgraph_csv(http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL"))
            up = parsers.parse_fredgraph_csv(http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU"))
        except ProviderError:
            return None
        if not lo or not up:
            return None
        return lo[-1][1], up[-1][1], up[-1][0]


class FedWatchProvider:
    """CME FedWatch has no permitted automated access from here, so probabilities are never scraped or
    invented. The default provider only relays snapshots an admin typed in from the CME site (or any
    licensed feed a future provider implements): it returns them with their source and timestamp."""
    name = "fedwatch"

    def latest(self, meeting_date):
        raise NotImplementedError


class ManualFedWatchProvider(FedWatchProvider):
    def __init__(self, snapshots):
        self.snapshots = snapshots                      # rows from fedwatch_snapshots

    def latest(self, meeting_date):
        rows = [s for s in self.snapshots if str(s["meeting_date"]) == str(meeting_date)]
        return max(rows, key=lambda s: s["snapshot_datetime"]) if rows else None

    def previous(self, meeting_date):
        rows = sorted((s for s in self.snapshots if str(s["meeting_date"]) == str(meeting_date)),
                      key=lambda s: s["snapshot_datetime"])
        return rows[-2] if len(rows) >= 2 else None


class MarketPriceProvider:
    name = "market_prices"

    def klines_1m(self, symbol, start_utc, end_utc):
        raise NotImplementedError


class BinanceMirrorPrices(MarketPriceProvider):
    """1-minute candles from Binance's public spot mirror (same host the dashboard already uses)."""
    BASE = "https://data-api.binance.vision/api/v3/klines"

    def klines_1m(self, symbol, start_utc, end_utc):
        out, cursor = [], int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)
        while cursor < end_ms:
            rows = json.loads(http_get(f"{self.BASE}?symbol={symbol}&interval=1m&startTime={cursor}&endTime={end_ms}&limit=1000"))
            if not rows:
                break
            out += [{"t": r[0], "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows]
            cursor = rows[-1][0] + 60_000
            if len(rows) < 1000:
                break
        return out
