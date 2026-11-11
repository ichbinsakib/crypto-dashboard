"""Evidence scorecard for a signal engine's closed trades: is there any reason to trust it with real money yet?

Pure functions. The verdict is deliberately conservative -- the live record so far has been dominated by a single
trade (+148% on QNT; without it the engine was deeply negative), so the card always shows the result WITHOUT the
best trade, plus the worst losing streak, rather than just a headline win rate."""

MIN_TRADES = 100          # below this a record says almost nothing, whatever the win rate


def trade_net(r, fee_pct):
    """Net % of one closed trade after the round-trip fee; SHORT profits when price falls."""
    s = 1 if r.get("direction", "LONG") == "LONG" else -1
    return (r["exit_price"] / r["entry"] - 1) * 100 * s - fee_pct


def scorecard(rows, fee_pct=0.2):
    """-> dict of headline numbers + a verdict {level, title, why}. `rows` are resolved trades with exit_price."""
    done = sorted((r for r in rows if r.get("exit_price") and r.get("entry")), key=lambda r: r["resolved_at"])
    nets = [trade_net(r, fee_pct) for r in done]
    n = len(nets)
    if not n:
        return {"n": 0, "verdict": {"level": "none", "title": "NO TRADES YET", "why": "Nothing has closed, so there is no record to judge."}}
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    total = sum(nets)
    total_ex_best = total - max(nets)
    streak = worst = 0
    for x in nets:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    peak = equity = dd = 0.0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    out = {"n": n, "wins": len(wins), "win_rate": len(wins) / n * 100, "avg": total / n, "total": total,
           "total_ex_best": total_ex_best, "best": max(nets), "worst": min(nets), "worst_streak": worst, "max_drawdown": dd,
           "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) else None}
    if n < MIN_TRADES:
        v = {"level": "early", "title": "NOT ENOUGH EVIDENCE",
             "why": f"{n} closed trades; at least {MIN_TRADES} are needed before a win rate or average means much."}
    elif total / n <= 0:
        v = {"level": "bad", "title": "NO EDGE SO FAR",
             "why": "Trades lose money on average after fees. Do not trade real money from these signals."}
    elif total_ex_best <= 0:
        v = {"level": "bad", "title": "RESULT RESTS ON ONE TRADE",
             "why": "Remove the single best trade and the record is not positive. That is luck, not a method."}
    else:
        v = {"level": "promising", "title": "PROMISING, KEEP PAPER-TRADING",
             "why": "Positive after fees even without the best trade. Keep watching it before risking real money."}
    out["verdict"] = v
    return out


def scorecard_html(sc, label, esc=lambda s: s):
    v = sc["verdict"]
    color = {"bad": "var(--red)", "promising": "var(--green)"}.get(v["level"], "var(--muted)")
    head = (f'<div class="card-title">&#128269; EVIDENCE CHECK &mdash; {esc(label)}</div>'
            f'<div style="font-size:18px;font-weight:800;color:{color};margin:4px 0;">{esc(v["title"])}</div>'
            f'<div class="sub">{esc(v["why"])}</div>')
    if not sc["n"]:
        return f'<div class="cycle-map" style="margin-bottom:10px;">{head}</div>'
    pf = f'{sc["profit_factor"]:.2f}' if sc["profit_factor"] is not None else "n/a"
    cells = [("Closed trades", f'{sc["n"]}'), ("Win rate", f'{sc["win_rate"]:.0f}%'), ("Average / trade", f'{sc["avg"]:+.2f}%'),
             ("Total", f'{sc["total"]:+.0f}%'), ("Total without best trade", f'{sc["total_ex_best"]:+.0f}%'),
             ("Worst losing streak", f'{sc["worst_streak"]}'), ("Deepest drawdown", f'-{sc["max_drawdown"]:.0f}%'),
             ("Profit factor", pf)]
    grid = "".join(f'<div><div class="sub">{esc(k)}</div><b>{esc(val)}</b></div>' for k, val in cells)
    note = ('<div class="sub" style="margin-top:6px;">Each trade is its own net % after fees, added together; not an account balance. '
            'Past results do not predict future ones.</div>')
    return (f'<div class="cycle-map" style="margin-bottom:10px;">{head}'
            f'<div class="top-grid" style="grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px;">{grid}</div>{note}</div>')
