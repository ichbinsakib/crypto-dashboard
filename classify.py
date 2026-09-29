"""Plain-English (label, sentiment) classifiers for individual market metrics, plus the cycle-stage
and heat-score heuristics derived from them. Pure functions, no dependency on the rest of the app --
part of shrinking dashboard.py into focused modules (see formatting.py for the first increment)."""


def classify_price_structure(pct_24h, pct_7d):
    if pct_7d is None:
        return "Unknown", "neutral"
    if pct_7d >= 20 and (pct_24h or 0) >= 5:
        return "Parabolic (blow-off risk)", "bearish"
    if pct_7d >= 8:
        return "Uptrend", "bullish"
    if pct_7d <= -8:
        return "Downtrend", "bearish"
    return "Range / Consolidation", "neutral"


def classify_funding(rate):
    if rate is None:
        return "N/A", "neutral"
    pct = rate * 100
    if pct >= 0.03:
        return f"{pct:.4f}% - overheated longs", "bearish"
    if pct <= -0.01:
        return f"{pct:.4f}% - shorts paying (squeeze risk)", "bullish"
    return f"{pct:.4f}% - healthy/neutral", "neutral"


def classify_oi(oi_change_pct, price_change_pct):
    if oi_change_pct is None or price_change_pct is None:
        return "N/A", "neutral"
    if price_change_pct > 1 and oi_change_pct < 1:
        return f"OI {oi_change_pct:+.1f}% - spot-led rally", "bullish"
    if price_change_pct > 1 and oi_change_pct >= 3:
        return f"OI {oi_change_pct:+.1f}% - leverage buildup", "bearish"
    if price_change_pct < -1 and oi_change_pct < -1:
        return f"OI {oi_change_pct:+.1f}% - long flush", "neutral"
    if price_change_pct < -1 and oi_change_pct >= 2:
        return f"OI {oi_change_pct:+.1f}% - short buildup", "neutral"
    return f"OI {oi_change_pct:+.1f}% - flat", "neutral"


def classify_premium(mark, index):
    if mark is None or index is None or index == 0:
        return "N/A", "neutral"
    bps = (mark - index) / index * 10000
    if bps > 30:
        return f"{bps:.1f} bps - elevated bullish basis", "bearish"
    if bps < -10:
        return f"{bps:.1f} bps - backwardation (bearish)", "bearish"
    if bps > 5:
        return f"{bps:.1f} bps - healthy bullish basis", "bullish"
    return f"{bps:.1f} bps - flat", "neutral"


def classify_fng(value, classification):
    if value is None:
        return "N/A", "neutral"
    v = int(value)
    if v >= 75:
        return f"{v} - {classification} (euphoria risk)", "bearish"
    if v <= 25:
        return f"{v} - {classification} (contrarian accumulation zone)", "bullish"
    return f"{v} - {classification}", "neutral"


def classify_liquidation_risk(funding_pct, oi_change_pct):
    if funding_pct is None or oi_change_pct is None:
        return "N/A (model estimate)", "neutral"
    crowded_long = funding_pct >= 0.03 and oi_change_pct >= 3
    crowded_short = funding_pct <= -0.02 and oi_change_pct >= 3
    if crowded_long:
        return "Elevated - crowded longs (model estimate)", "bearish"
    if crowded_short:
        return "Elevated - crowded shorts (model estimate)", "bullish"
    return "Low/Moderate (model estimate)", "neutral"


def cycle_stage(price, sma50, sma200, pct_30d):
    if price is None or sma200 is None:
        return "Unknown"
    dist_pct = (price - sma200) / sma200 * 100
    p30 = pct_30d or 0
    if dist_pct > 40 and p30 > 15:
        return "Distribution"
    if dist_pct > 5 and p30 > 5:
        return "Markup"
    if dist_pct < -15 and p30 < -10:
        return "Markdown"
    return "Accumulation"


def heat_score(pct_30d, dist_from_sma200_pct, funding_pct, fng_value):
    parts = []
    if pct_30d is not None:
        parts.append(max(0, min(10, (pct_30d + 20) / 4)))
    if dist_from_sma200_pct is not None:
        parts.append(max(0, min(10, (dist_from_sma200_pct + 20) / 6)))
    if funding_pct is not None:
        parts.append(max(0, min(10, (funding_pct + 0.03) * 100)))
    if fng_value is not None:
        parts.append(fng_value / 10)
    if not parts:
        return None
    return round(sum(parts) / len(parts), 1)
