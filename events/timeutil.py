"""UTC storage / US-Eastern display with correct DST.

Implemented from the statutory US rule (2nd Sunday of March 02:00 -> 1st Sunday of November 02:00)
instead of zoneinfo, so it works on Windows without the tzdata package.
"""
import datetime as dt

UTC = dt.timezone.utc


def _nth_sunday(year, month, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)      # first Sunday
    return d + dt.timedelta(weeks=n - 1)


def dst_bounds_local(year):
    """(start, end) as naive local wall-clock datetimes; both switch at 02:00 local time."""
    return (dt.datetime.combine(_nth_sunday(year, 3, 2), dt.time(2)),
            dt.datetime.combine(_nth_sunday(year, 11, 1), dt.time(2)))


def et_offset_for_local(local):
    """UTC offset in hours (-4 or -5) for a naive Eastern wall-clock time."""
    start, end = dst_bounds_local(local.year)
    return -4 if start <= local < end else -5


def et_to_utc(local):
    """Naive Eastern wall-clock datetime -> aware UTC datetime."""
    return (local - dt.timedelta(hours=et_offset_for_local(local))).replace(tzinfo=UTC)


def utc_to_et(utc):
    """UTC datetime -> (naive Eastern wall-clock datetime, 'EDT' | 'EST')."""
    u = utc.astimezone(UTC).replace(tzinfo=None) if utc.tzinfo else utc
    start, end = dst_bounds_local(u.year)
    start_utc = start + dt.timedelta(hours=5)          # 02:00 EST
    end_utc = end + dt.timedelta(hours=4)              # 02:00 EDT
    if start_utc <= u < end_utc:
        return u - dt.timedelta(hours=4), "EDT"
    return u - dt.timedelta(hours=5), "EST"


def fmt_et(utc):
    local, abbr = utc_to_et(utc)
    return local.strftime("%a %b %d, %I:%M %p ") + abbr


def parse_iso(s):
    if s is None:
        return None
    d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def now_utc():
    return dt.datetime.now(UTC)
