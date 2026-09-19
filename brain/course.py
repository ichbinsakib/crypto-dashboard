"""What the app has learned from the Crypto Dada course: the curriculum (curriculum_data.py), the hard rules,
and a pre-trade checklist that grades any idea against them. Educational - not financial advice."""
from .curriculum_data import CURRICULUM

# Course risk rules (Vol 5). Numbers are the course's, kept in one place.
RULES = {
    "risk_per_trade_pct": (1.0, 2.0),      # a stopped-out trade should cost only 1-2% of the account
    "max_beginner_leverage": 5,            # 2-5x for beginners
    "stop_required": True,                 # always set a stop before entry
    "never_add_margin_to_loser": True,
    "avoid_leverage_before_news_hours": 24,  # Vol 3: volatility clusters around FOMC/CPI/unlocks
    "take_profit_in_tranches": True,       # Vol 5.2 / 7.5
}

# Findings from testing course concepts on ~40 coins of Binance history (chronological train/test split,
# ATR stop/target geometry, 0.2% round-trip fees). Kept so unproven ideas are not wired into signals.
BACKTEST_NOTES = [
    "Trading WITH the trend is consistently less bad than against it: EMA-bear and lower-highs/lower-lows states were the "
    "worst bucket for long entries on both 15m and 1h, in both the train and test periods (about -0.2% to -0.35% net per trade).",
    "No single course feature (EMA bias, market structure, bullish FVG retest, Fibonacci golden zone, volume spike, "
    "parabolic filter) or combination produced a positive net result that held out of sample after fees. Confidence intervals "
    "included zero, and 15m results flipped sign between train and test.",
    "Cross-market backdrop (dollar, 10Y yield, Nasdaq daily moves vs BTC next-day and 3-day returns, 3 years of data, "
    "chronological split): risk-on and risk-off days were not distinguishable from all days, and the direction flipped between "
    "the train and test halves. It is included in the BTC/ETH spot score at the owner's request (macro.MACRO_WEIGHT) but unproven.",
    "Therefore these features are shown as context and checklist items only; they do not gate or score the app's signals. "
    "Revisit with more history (months, not weeks) before changing any signal rule.",
]


def pre_trade_checklist(entry, stop, targets=None, account=None, leverage=None, hours_to_next_high_event=None,
                        trend=None, parabolic=False):
    """Grade a trade idea against the course rules. Returns [{'rule', 'ok', 'note'}]. Never says 'buy'."""
    out = []
    ok_stop = stop is not None and entry is not None and stop != entry
    out.append({"rule": "Stop loss defined before entry", "ok": bool(ok_stop),
                "note": "Stop is the invalidation level." if ok_stop else "No valid stop: the course says do not enter."})
    if ok_stop and account:
        risk = abs(entry - stop) / entry * (leverage or 1) * 100
        lo, hi = RULES["risk_per_trade_pct"]
        out.append({"rule": "Risk 1-2% of the account per trade", "ok": risk <= hi,
                    "note": f"Putting the whole account in at this stop distance risks {risk:.1f}% of it; size the position so a stop-out costs at most {hi:.0f}%."})
    if leverage is not None:
        out.append({"rule": f"Leverage at or below {RULES['max_beginner_leverage']}x", "ok": leverage <= RULES["max_beginner_leverage"],
                    "note": f"Leverage {leverage}x. Liquidation is capital destruction; risk comes from size plus stop distance."})
    if targets and ok_stop:
        rr = (targets[0] - entry) / (entry - stop) if entry > stop else None
        if rr is not None:
            out.append({"rule": "Reward at least ~1.5x the risk", "ok": rr >= 1.5, "note": f"First target is {rr:.2f}R."})
        if len(targets) > 1:
            out.append({"rule": "Take profit in tranches", "ok": True, "note": f"{len(targets)} targets planned."})
    if hours_to_next_high_event is not None:
        near = hours_to_next_high_event <= RULES["avoid_leverage_before_news_hours"]
        out.append({"rule": "No fresh leverage right before major news", "ok": not near,
                    "note": (f"High-impact event in {hours_to_next_high_event:.0f}h - volatility clusters around it." if near
                             else "No high-impact event in the next 24h.")})
    if trend:
        out.append({"rule": "Prefer trading with the trend", "ok": trend != "down",
                    "note": "Tests show long entries into a downtrend were the worst bucket." if trend == "down" else f"Trend: {trend}."})
    if parabolic:
        out.append({"rule": "Never chase a parabolic final leg", "ok": False, "note": "Price is extended; take profits, do not FOMO-buy."})
    return out


def module(name_part):
    """Look up curriculum modules by part of the title, e.g. module('Fair Value')."""
    return [m for m in CURRICULUM if name_part.lower() in m["module"].lower()]
