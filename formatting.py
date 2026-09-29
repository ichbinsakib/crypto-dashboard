"""Pure, dependency-free display-formatting helpers shared across dashboard.py's rendering code.
Split out as the first step of shrinking dashboard.py (a 3000+ line monolith) into focused modules --
these have no dependency on the rest of the app, so extracting them carries none of the risk that
moving anything touching render()'s shared closures would."""
import datetime
import math


def fmt_usd(v, decimals=2):
    if v is None:
        return "N/A"
    return f"${v:,.{decimals}f}"


def fmt_usd_adaptive(v):
    """Scales decimal places to the coin's price so sub-$1 coins (ADA, DOGE, meme coins)
    don't lose all precision under a fixed 2-decimal format."""
    if v is None:
        return "N/A"
    if v >= 1:
        return f"${v:,.2f}"
    if v >= 0.01:
        return f"${v:,.4f}"
    return f"${v:,.{min(10, 2 - math.floor(math.log10(abs(v))))}f}" if v > 0 else "$0.000000"


def fmt_net_fee_html(net_pct, example_notional=100):
    """Renders a target's profit net of the round-trip fee, plus a concrete dollar example on
    a stated notional, so the fee drag on thin short-timeframe targets is visible at a glance
    instead of something a reader has to calculate by hand."""
    if net_pct is None:
        return ""
    example_amount = net_pct / 100 * example_notional
    css_class = "pos" if net_pct > 0.02 else ("neg" if net_pct < -0.02 else "watch")
    pct_sign = "+" if net_pct >= 0 else ""
    amt_sign = "+" if example_amount >= 0 else "-"
    return (f'<span class="{css_class}">{pct_sign}{net_pct:.2f}% net '
            f'({amt_sign}${abs(example_amount):.2f} on ${example_notional})</span>')


def fmt_duration_hours(hours):
    """Humanizes a duration given in fractional hours, e.g. 0.75 -> "45m", 26.5 -> "1d 2h"."""
    total_minutes = round(hours * 60)
    if total_minutes < 60:
        return f"{max(total_minutes, 1)}m"
    total_hours, minutes = divmod(total_minutes, 60)
    if total_hours < 24:
        return f"{total_hours}h {minutes}m" if minutes else f"{total_hours}h"
    days, rem_hours = divmod(total_hours, 24)
    return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"


def fmt_time_ago(iso_ts, now=None):
    now = now or datetime.datetime.now()
    then = datetime.datetime.fromisoformat(iso_ts)
    hours = (now - then).total_seconds() / 3600
    return f"{fmt_duration_hours(hours)} ago"


def fmt_pct(v, decimals=2, sign=True):
    if v is None:
        return "N/A"
    s = "+" if (sign and v > 0) else ""
    return f"{s}{v:.{decimals}f}%"


def badge_html(status, text):
    icon = {"bullish": "↗", "bearish": "↘", "neutral": "–", "locked": "\U0001F512"}.get(status, "")
    return f'<span class="badge {status}">{icon} {text}</span>'


def ps_safe(s):
    return str(s).replace('"', "'").replace("`", "'")
