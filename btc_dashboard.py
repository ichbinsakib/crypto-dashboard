"""BITCOIN LIVE DASHBOARD (Big Coins > BTC tab): price action, market read, cycle score gauge, 10-signal table,
derivatives snapshot, cycle map, takeaways and an on-chain strip - laid out like a trader's one-screen dashboard.

Every number comes from a real source (CoinGecko, Binance, CoinMetrics community, Alternative.me) or the app's own models.
Anything without a permitted free source (ETF flows) says "Data unavailable" instead of being invented."""
import datetime
import json
import math
import urllib.request
from html import escape as _e

CM = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
UA = {"User-Agent": "Mozilla/5.0 (KairoDashboard)"}


# ---------------- on-chain data (CoinMetrics community API, free) ----------------

def _cm(metrics, start, page=10000):
    url = f"{CM}?assets=btc&metrics={metrics}&frequency=1d&start_time={start}&page_size={page}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read())["data"]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def fetch_onchain(prev=None, now=None):
    """-> dict(mvrv, nupl, mvrv_z, exch_in, exch_out, net_flow, as_of, preliminary) with None for anything unavailable.
    The all-history market-cap deviation (for the Z-score) is cached for 24h so a 5-minute job stays light."""
    now = now or _now()
    prev = prev or {}
    out = {"mvrv": None, "nupl": None, "mvrv_z": None, "exch_in": None, "exch_out": None, "net_flow": None, "as_of": None,
           "preliminary": False, "mcap_std": prev.get("mcap_std"), "std_at": prev.get("std_at"), "error": None}
    try:
        stale = not out["mcap_std"] or not out["std_at"] or (now - datetime.datetime.fromisoformat(out["std_at"])).total_seconds() > 86400
        if stale:
            rows = _cm("CapMrktCurUSD", "2011-01-01")
            vals = [float(r["CapMrktCurUSD"]) for r in rows if r.get("CapMrktCurUSD")]
            if len(vals) > 1000:
                mean = sum(vals) / len(vals)
                out["mcap_std"] = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
                out["std_at"] = now.isoformat()
        start = (now - datetime.timedelta(days=4)).strftime("%Y-%m-%d")
        rows = _cm("CapMVRVCur,CapMrktCurUSD", start, 20)
        last = [r for r in rows if r.get("CapMVRVCur") and r.get("CapMrktCurUSD")][-1]
        mvrv, mcap = float(last["CapMVRVCur"]), float(last["CapMrktCurUSD"])
        out["mvrv"], out["as_of"] = mvrv, last["time"][:10]
        if mvrv > 0:
            realized = mcap / mvrv
            out["nupl"] = (mcap - realized) / mcap
            if out["mcap_std"]:
                out["mvrv_z"] = (mcap - realized) / out["mcap_std"]
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
    try:
        rows = _cm("FlowInExUSD,FlowOutExUSD", (now - datetime.timedelta(days=4)).strftime("%Y-%m-%d"), 20)
        row = [r for r in rows if r.get("FlowInExUSD") and r.get("FlowOutExUSD")][-1]
        out["exch_in"], out["exch_out"] = float(row["FlowInExUSD"]), float(row["FlowOutExUSD"])
        out["net_flow"] = out["exch_in"] - out["exch_out"]
        out["flow_date"] = row["time"][:10]
        out["preliminary"] = "flash" in (row.get("FlowInExUSD-status", "") + row.get("FlowOutExUSD-status", ""))
    except Exception as e:  # noqa: BLE001
        out["error"] = out["error"] or type(e).__name__
    return out


# ---------------- small formatters / classifiers ----------------

def usd(v, d=0):
    return "Data unavailable" if v is None else f"${v:,.{d}f}"


def compact_usd(v):
    if v is None:
        return "Data unavailable"
    s = "-" if v < 0 else ""
    v = abs(v)
    return f"{s}${v / 1e9:.2f}B" if v >= 1e9 else f"{s}${v / 1e6:.0f}M"


def chip(status):
    label, cls = {"bullish": ("▲ BULLISH", "up"), "bearish": ("▼ BEARISH", "down"), "neutral": ("— NEUTRAL", "mid")}.get(status, ("N/A", "na"))
    return f'<span class="bd-chip bd-{cls}">{label}</span>'


def nupl_read(n):
    if n is None:
        return "Data unavailable", "na"
    zone = ("Capitulation", "bullish") if n < 0 else ("Hope / Fear", "bullish") if n < 0.25 else ("Optimism / Anxiety", "neutral") if n < 0.5 \
        else ("Belief / Denial", "neutral") if n < 0.75 else ("Euphoria", "bearish")
    return f"{zone[0]} ({n:.3f})", zone[1]


def mvrv_read(z):
    if z is None:
        return "Data unavailable", "na"
    if z < 1:
        return f"Fair to cheap ({z:.2f})", "bullish"
    if z < 5:
        return f"Moderate ({z:.2f})", "neutral"
    return f"Overheated ({z:.2f})", "bearish"


def flow_read(net):
    if net is None:
        return "Data unavailable", "na"
    if net <= -100e6:
        return f"Net outflow {compact_usd(net)} (coins leaving exchanges)", "bullish"
    if net >= 100e6:
        return f"Net inflow {compact_usd(net)} (coins heading to exchanges)", "bearish"
    return f"Roughly balanced ({compact_usd(net)})", "neutral"


# ---------------- graphics ----------------

def sparkline(klines):
    """24h hourly-close sparkline as inline SVG."""
    try:
        cl = [float(k[4]) for k in klines[-25:]]
    except Exception:  # noqa: BLE001
        cl = []
    if len(cl) < 5:
        return '<div class="bd-sub">Chart unavailable</div>'
    lo, hi = min(cl), max(cl)
    span = (hi - lo) or 1
    w, h, padx, pady = 300, 96, 34, 8
    pts = [(padx + i * (w - padx - 4) / (len(cl) - 1), pady + (1 - (v - lo) / span) * (h - 2 * pady)) for i, v in enumerate(cl)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    up = cl[-1] >= cl[0]
    col = "#22c55e" if up else "#ef4444"
    grid = "".join(f'<line x1="{padx}" x2="{w - 4}" y1="{pady + i * (h - 2 * pady) / 3:.1f}" y2="{pady + i * (h - 2 * pady) / 3:.1f}" class="bd-grid"/>' for i in range(4))
    labels = "".join(f'<text x="2" y="{pady + i * (h - 2 * pady) / 3 + 3:.1f}" class="bd-axis">{(hi - i * span / 3) / 1000:.1f}K</text>' for i in range(4))
    return (f'<svg viewBox="0 0 {w} {h + 14}" class="bd-spark" role="img" aria-label="BTC price, last 24 hours">{grid}{labels}'
            f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2"/>'
            f'<text x="{padx}" y="{h + 11}" class="bd-axis">24h ago</text><text x="{w / 2 + 6}" y="{h + 11}" class="bd-axis">12h ago</text>'
            f'<text x="{w - 26}" y="{h + 11}" class="bd-axis">Now</text></svg>')


def _pt(cx, cy, r, ang):
    a = math.radians(ang)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def gauge(score):
    """Semicircle gauge, 10 (left, accumulation) to 1 (right, markdown risk)."""
    cx, cy, r = 150, 138, 100

    def ang(s):
        return 180 - (10 - s) / 9 * 180

    def arc(s_from, s_to, col):
        x1, y1 = _pt(cx, cy, r, ang(s_from) + 0.0)
        x2, y2 = _pt(cx, cy, r, ang(s_to))
        return f'<path d="M {x1:.1f} {y1:.1f} A {r} {r} 0 0 1 {x2:.1f} {y2:.1f}" stroke="{col}" stroke-width="16" fill="none"/>'
    arcs = arc(10, 8, "#22c55e") + arc(8, 5, "#eab308") + arc(5, 3, "#f97316") + arc(3, 1, "#ef4444")
    ticks = "".join(f'<text x="{_pt(cx, cy, r + 22, ang(s))[0]:.1f}" y="{_pt(cx, cy, r + 22, ang(s))[1] + 4:.1f}" text-anchor="middle" class="bd-tick">{s}</text>' for s in range(10, 0, -1))
    nx, ny = _pt(cx, cy, 78, ang(score))
    return (f'<svg viewBox="0 0 300 168" class="bd-gauge" role="img" aria-label="Market cycle score {score} out of 10">{arcs}{ticks}'
            f'<line x1="{cx}" y1="{cy}" x2="{nx:.1f}" y2="{ny:.1f}" stroke="#eab308" stroke-width="4" stroke-linecap="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="9" fill="#0b120e" stroke="#9ca3af" stroke-width="3"/></svg>')


# ---------------- content ----------------

def structure(c, label, status):
    """Price-structure label for this dashboard: the app's 7-day rule alone called a coin sitting at its 30-day high above both
    long averages 'Range / Consolidation'. Use the moving-average stack too so it agrees with the market read."""
    if "Parabolic" in (label or ""):
        return label, status
    p, s50, s200 = c.get("price"), c.get("sma50"), c.get("sma200")
    if p and s50 and s200:
        if p > s50 > s200:
            return "Uptrend (above the 50- and 200-day averages)", "bullish"
        if p < s50 < s200:
            return "Downtrend (below the 50- and 200-day averages)", "bearish"
        return "Range / Consolidation (mixed averages)", "neutral"
    return label, status


def cycle_score(spot_score):
    """1-10, higher = closer to the accumulation end. Derived from the app's own spot model (range about -9..+9)."""
    return max(1, min(10, round(5.5 + (spot_score or 0) / 2)))


def headline(stage, struct, wy):
    base = {"Accumulation": ("NOT A CYCLE TOP YET", "BUILDING A BASE"),
            "Markup": ("UPTREND INTACT", "TREND IS UP"),
            "Distribution": ("TOP RISK IS RISING", "STRETCHED AFTER A BIG RUN"),
            "Markdown": ("DOWNTREND: STAY CAUTIOUS", "PRICE IS BELOW ITS LONG-TERM TREND")}.get(stage, ("READING THE MARKET", "NOT ENOUGH DATA"))
    title, sub = base
    if wy and wy.get("stage") in ("range", "utad", "sow", "lpsy") and stage in ("Markup", "Accumulation"):
        sub = "WATCH THE OVERHEAD RANGE (POSSIBLE DISTRIBUTION)"
    elif struct and "Parabolic" in struct:
        sub = "PARABOLIC MOVE: BLOW-OFF RISK"
    return title, sub


def _pct(v):
    return "n/a" if v is None else f"{v:+.1f}%"


def market_paragraph(x):
    c = x["c"]
    p = c.get("price")
    bits = [f"Bitcoin is at {usd(p)}, {_pct(c.get('pct_24h'))} on the day and {_pct(c.get('pct_7d'))} over 7 days."]
    sup, res = c.get("support_30d"), c.get("resistance_30d")
    if p and sup and res and res > sup:
        pos = (p - sup) / (res - sup) * 100
        bits.append(f"That is {pos:.0f}% of the way up its 30-day range ({usd(sup)} to {usd(res)}).")
    if x["funding"][0] != "N/A":
        bits.append(f"Futures funding is {x['funding'][0]}.")
    oc = x.get("onchain") or {}
    if oc.get("mvrv_z") is not None:
        bits.append(f"On-chain valuation reads {mvrv_read(oc['mvrv_z'])[0].lower()} and holder profit is {nupl_read(oc.get('nupl'))[0].lower()}.")
    if oc.get("net_flow") is not None:
        bits.append(f"Exchanges saw {flow_read(oc['net_flow'])[0].lower()}.")
    if x["fng"][0] != "N/A":
        bits.append(f"Crowd sentiment: {x['fng'][0]}.")
    return " ".join(bits)


def simple_read(x):
    c, st = x["c"], x["stage"]
    p, sup, res = c.get("price"), c.get("support_30d"), c.get("resistance_30d")
    if p and res and p >= res * 0.98:
        return f"Bitcoin is pressing against its 30-day high near {usd(res)}."
    if p and sup and p <= sup * 1.03:
        return f"Bitcoin is sitting on its 30-day low near {usd(sup)}."
    return f"Bitcoin is in the middle of its 30-day range ({st.lower()} phase)."


def takeaways(x):
    c, oc = x["c"], x.get("onchain") or {}
    out = []
    p, sup, res = c.get("price"), c.get("support_30d"), c.get("resistance_30d")
    if res and sup:
        out.append(f"{usd(res)} is the 30-day high to beat and {usd(sup)} is the 30-day floor; a daily close beyond either would change the picture.")
    d = []
    if x["funding"][0] != "N/A":
        d.append(f"funding is {x['funding'][0]}")
    if x["oi"][0] != "N/A":
        d.append(f"open interest is {x['oi'][0]}")
    if x["premium"][0] != "N/A":
        d.append(f"futures premium is {x['premium'][0]}")
    if d:
        out.append("Derivatives: " + "; ".join(d) + ".")
    o = []
    if oc.get("mvrv_z") is not None:
        o.append(f"valuation (MVRV Z-score) is {oc['mvrv_z']:.2f}")
    if oc.get("nupl") is not None:
        o.append(f"NUPL is {oc['nupl']:.3f}")
    if oc.get("net_flow") is not None:
        o.append(f"exchange net flow is {compact_usd(oc['net_flow'])}")
    if o:
        out.append("On-chain: " + ", ".join(o) + ".")
    wy = x.get("wyckoff")
    if wy and wy.get("stage") != "none":
        out.append(f"Chart structure shows a possible Wyckoff distribution pattern ({wy['stage']}, {wy['confidence'].lower()} confidence); treat breakouts above the range with care.")
    elif x.get("macro"):
        out.append(f"Cross-market backdrop reads {x['macro']['label'].title()} (dollar, yields, stocks, stablecoins).")
    return out[:4]


def alert_state(x):
    """green / yellow / red per the three published alert rules."""
    funding_hot = x["funding"][1] == "bearish"
    oi_hot = "leverage buildup" in x["oi"][0]
    parabolic = "Parabolic" in x["price_struct"][0]
    nupl = (x.get("onchain") or {}).get("nupl") or 0
    if parabolic and funding_hot and oi_hot:
        return "red"
    if parabolic or funding_hot or oi_hot or x["fng"][1] == "bearish" or nupl > 0.5:
        return "yellow"
    return "green"


def _deriv(x, which, reading, status):
    """Derivatives reading with its exchange source, or an honest 'unavailable' when only a stale copy exists."""
    c = x["c"]
    stale = c.get("stale") or []
    key = "funding rate / futures premium" if which in ("funding", "premium") else "open interest"
    if key in stale:
        return "Data unavailable (live feed blocked; last known value is stale)", "na"
    src = c.get("derivs_source") if which in ("funding", "premium") else c.get("oi_source")
    return (f"{reading} [{src}]" if src and reading != "N/A" else reading), status


def signal_rows(x):
    oc = x.get("onchain") or {}
    nl, ns = nupl_read(oc.get("nupl"))
    zl, zs = mvrv_read(oc.get("mvrv_z"))
    fl, fs = flow_read(oc.get("net_flow"))
    if oc.get("preliminary") and oc.get("net_flow") is not None:
        fl += " (preliminary)"
    fund = _deriv(x, "funding", x["funding"][0], x["funding"][1])
    oi = _deriv(x, "oi", x["oi"][0], x["oi"][1])
    prem = _deriv(x, "premium", x["premium"][0], x["premium"][1])
    liq = ("Data unavailable (needs funding and open interest)", "na") if "na" in (fund[1], oi[1]) else (x["liq"][0], x["liq"][1])
    rows = [
        ("Price Structure", "Blow-off move / vertical trend", "Parabolic breakout", x["price_struct"][0], x["price_struct"][1]),
        ("ETF Flows", "Sustained spot demand", "Large outflows", "Data unavailable (no free ETF-flow feed)", "na"),
        ("Funding Rates", "Overheated longs", "Strong positive spike", fund[0], fund[1]),
        ("Open Interest (OI)", "Leverage buildup", "OI exploding higher", oi[0], oi[1]),
        ("Futures Premium", "Excessive bullish basis", "Premium sharply elevated", prem[0], prem[1]),
        ("MVRV Z-Score", "Valuation overheating", "High top-zone valuation", zl, zs),
        ("NUPL", "Euphoria", "Euphoric zone", nl, ns),
        ("Retail Mania (Fear & Greed)", "Euphoric crowd behavior", "FOMO mania everywhere", x["fng"][0], x["fng"][1]),
        ("Exchange Inflows / Outflows", "Coins moving to / from exchanges", "Heavy inflows / balance rise", fl, fs),
        ("Liquidation Risk", "Crowded leverage", "One-sided crowded setup", liq[0], liq[1]),
    ]
    out = []
    for i, (name, watch, warn, read, st) in enumerate(rows, 1):
        col = {"bullish": "bd-g", "bearish": "bd-r", "neutral": "bd-y"}.get(st, "bd-n")
        out.append(f'<tr><td>{i}</td><td>{_e(name)}</td><td class="bd-dim">{_e(watch)}</td><td class="bd-dim">{_e(warn)}</td>'
                   f'<td class="{col}">{_e(read)}</td><td>{chip(st)}</td></tr>')
    return "".join(out)


def build(x):
    """x: {c, stage, spot, price_struct, funding, oi, premium, fng, liq, wyckoff, macro, hourly, onchain, generated}."""
    c = x["c"]
    x = dict(x, price_struct=structure(c, *x["price_struct"]))
    score = cycle_score((x.get("spot") or {}).get("score"))
    title, sub = headline(x["stage"], x["price_struct"][0], x.get("wyckoff"))
    oc = x.get("onchain") or {}
    p = c.get("price")
    hi24 = lo24 = None
    try:
        cl = [(float(k[2]), float(k[3])) for k in x["hourly"][-24:]]
        hi24, lo24 = max(a for a, _ in cl), min(b for _, b in cl)
    except Exception:  # noqa: BLE001
        pass
    rng = f"{usd(lo24)} - {usd(hi24)}" if hi24 else "Data unavailable"
    struct_status = x["price_struct"][1]
    struct_col = {"bullish": "bd-g", "bearish": "bd-r"}.get(struct_status, "bd-y")
    stages = ["Accumulation", "Markup", "Distribution", "Markdown"]
    cyc = "".join(f'<div class="bd-cyc{" bd-here" if s == x["stage"] else ""}"><span>{s}</span>'
                  + ('<b>&#9650; WE ARE HERE</b>' if s == x["stage"] else "") + '</div>' + ('<i>&#8594;</i>' if k < 3 else "")
                  for k, s in enumerate(stages))
    st_pill = {"Accumulation": ("STABLE", "up"), "Markup": ("HEALTHY", "up"), "Distribution": ("CAUTION", "mid"), "Markdown": ("WEAK", "down")}.get(x["stage"], ("N/A", "na"))
    alert = alert_state(x)
    oi_amt = f"{c['oi_now'] / 1000:.1f}k BTC" if c.get("oi_now") else "Data unavailable"
    fund_txt = x["funding"][0] if x["funding"][0] != "N/A" else "Data unavailable"
    take = "".join(f"<li>{_e(t)}</li>" for t in takeaways(x)) or "<li>Not enough data for takeaways.</li>"
    zl, zs = mvrv_read(oc.get("mvrv_z"))
    nl, ns = nupl_read(oc.get("nupl"))
    fl, fs = flow_read(oc.get("net_flow"))
    z_txt = f"{oc['mvrv_z']:.2f}" if oc.get("mvrv_z") is not None else "Data unavailable"
    n_txt = f"{oc['nupl']:.3f}" if oc.get("nupl") is not None else "Data unavailable"
    net_txt = compact_usd(oc.get("net_flow"))
    inout = f"In {compact_usd(oc.get('exch_in'))} / Out {compact_usd(oc.get('exch_out'))}" if oc.get("exch_in") is not None else "Data unavailable"
    rules = [("green", "GREEN (Healthy):", "No parabolic price. Derivatives calm. On-chain not euphoric."),
             ("yellow", "YELLOW (Caution):", "Demand fragile, leverage building or crowd getting greedy."),
             ("red", "RED (Top zone):", "Parabolic price + overheated funding + exploding open interest.")]
    rules_html = "".join(f'<div class="bd-rule{" bd-on" if k == alert else ""}"><b class="bd-{ {"green": "g", "yellow": "y", "red": "r"}[k] }">{t}</b> {d}'
                         f'{" <em>&larr; right now</em>" if k == alert else ""}</div>' for k, t, d in rules)
    return f"""
<div class="bd">
  <div class="bd-title"><span class="bd-coin">&#8383;</span><h2><span>BITCOIN</span> <em>LIVE</em> <strong>DASHBOARD</strong></h2></div>
  <div class="bd-date">{_e(x.get("generated", ""))} &nbsp;|&nbsp; Live snapshot, refreshed about every 5 minutes</div>

  <div class="bd-grid3">
    <section class="bd-card"><h3>&#128200; PRICE ACTION</h3>
      <div class="bd-price">BTC Price: <b>{usd(p)}</b></div>
      <div class="bd-sub">24h Range: {rng}</div>
      {sparkline(x["hourly"])}
      <div class="bd-kv"><span>&#8599; Structure:</span><b class="{struct_col}">{_e(x["price_struct"][0])}</b></div>
      <div class="bd-kv"><span>&#8853; Key Support (30d low):</span><b class="bd-g">{usd(c.get("support_30d"))}</b></div>
      <div class="bd-kv"><span>&#8854; Key Resistance (30d high):</span><b class="bd-r">{usd(c.get("resistance_30d"))}</b></div>
      <div class="bd-simple"><span>Simple Read:</span> <b>{_e(simple_read(x))}</b></div>
    </section>
    <section class="bd-card bd-gold"><h3 class="bd-goldh">&#9888; CURRENT MARKET READ</h3>
      <div class="bd-big">{_e(title)}</div>
      <div class="bd-subhead">{_e(sub)}</div>
      <p class="bd-para">{_e(market_paragraph(x))}</p>
    </section>
    <section class="bd-card"><h3>&#8635; MARKET CYCLE SCORE</h3>
      {gauge(score)}
      <div class="bd-score"><b>{score}</b>/10</div>
      <div class="bd-stages"><span class="bd-g">Accumulation</span> | <span class="bd-y">Markup</span> | <span class="bd-o">Distribution</span> | <span class="bd-r">Markdown</span></div>
      <div class="bd-stagebox"><div class="bd-sub">Cycle stage: <b>{_e(x["stage"])}</b><br>Score is this app's own model (10 = accumulation end, 1 = markdown risk).</div>
        <span class="bd-chip bd-{st_pill[1]}">{st_pill[0]}</span></div>
    </section>
  </div>

  <section class="bd-card bd-wide"><h3>&#9776; SIGNAL TABLE (CORE OF DASHBOARD)</h3>
    <div class="bd-scroll"><table class="bd-table"><thead><tr><th>#</th><th>Signal</th><th>What to Watch</th><th>Top Warning Level</th><th>Current Read</th><th>Status</th></tr></thead>
    <tbody>{signal_rows(x)}</tbody></table></div>
  </section>

  <div class="bd-grid3">
    <section class="bd-card"><h3>ETF / DERIVATIVES SNAPSHOT</h3>
      <div class="bd-tiles">
        <div class="bd-tile"><small>ETF FLOWS</small><b class="bd-n">Data unavailable</b><em>no free feed</em></div>
        <div class="bd-tile"><small>FUNDING</small><b class="bd-y">{_e(fund_txt.split(" - ")[0])}</b><em>Binance</em></div>
        <div class="bd-tile"><small>OPEN INTEREST</small><b>{oi_amt}</b><em>{_e(x["oi"][0])}</em></div>
      </div>
      <h3 style="margin-top:14px">TOP ALERT RULES</h3>{rules_html}
    </section>
    <section class="bd-card"><h3>&#128506; CYCLE MAP</h3><div class="bd-cycrow">{cyc}</div>
      <div class="bd-sub" style="margin-top:12px">Where the app's model places Bitcoin in the four-phase cycle: {_e(x["stage"])}.</div>
    </section>
    <section class="bd-card"><h3>&#10003; KEY TAKEAWAYS</h3><ul class="bd-take">{take}</ul></section>
  </div>

  <div class="bd-strip">
    <div><small>MVRV Z-SCORE</small><b class="bd-{ {"bullish": "g", "bearish": "r", "neutral": "y"}.get(zs, "n") }">{z_txt}</b></div>
    <div><small>NUPL</small><b class="bd-{ {"bullish": "g", "bearish": "r", "neutral": "y"}.get(ns, "n") }">{n_txt}</b></div>
    <div><small>EXCHANGE NET FLOW (24h)</small><b class="bd-{ {"bullish": "g", "bearish": "r", "neutral": "y"}.get(fs, "n") }">{net_txt}</b></div>
    <div><small>IN / OUT TOTALS</small><b class="bd-n" style="font-size:12px">{inout}</b></div>
  </div>
  <div class="bd-foot">Sources: CoinGecko, Binance, CoinMetrics community (on-chain, {_e(oc.get("as_of") or "n/a")}{", exchange flows preliminary" if oc.get("preliminary") else ""}), Alternative.me. Model outputs are estimates. Education only, not financial advice.</div>
</div>
"""
