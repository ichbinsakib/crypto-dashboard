"""Weekly cross-sectional momentum on liquid coins, long-only, with fees -- does picking recent winners beat simply holding BTC?

Rules (all decided at the daily close of the signal day, executed at the NEXT day's open -- no look-ahead):
  * universe  : top N coins by 30-day average dollar volume among everything listed at that time (delisted coins stay in)
  * score     : return over the last LOOKBACK days, skipping the most recent SKIP days (or return / volatility)
  * buy       : top K by score, equal weight, only if the score is positive
  * regime    : only invested while BTC closes above its REGIME-day average, otherwise 100% cash
  * rebalance : every REBAL days; cost = fee + slippage per side on every traded dollar
Benchmarks: BTC buy-and-hold, BTC only when above its regime average, and equal-weight top-K by volume under the same regime
(that last one shows what the momentum ranking adds on top of just 'hold liquid coins when BTC is healthy').
Run: python momentum_weekly.py   (reads backtest/data_daily, writes momentum_results.json)
"""
import json, math, os, sys, itertools, functools, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
DAY = 86400000
SIDE_COST = 0.0015  # 0.10% exchange fee + 0.05% slippage, per side


def load():
    series = {}
    for f in os.listdir(os.path.join(HERE, "data_daily")):
        if f.endswith(".json"):
            series[f[:-5]] = json.load(open(os.path.join(HERE, "data_daily", f)))
    t0 = min(rows[0][0] for rows in series.values()); t1 = max(rows[-1][0] for rows in series.values())
    n = int((t1 - t0) // DAY) + 1
    O, C, V = {}, {}, {}
    for c, rows in series.items():
        o, cl, v = [None] * n, [None] * n, [None] * n
        for r in rows:
            i = int((r[0] - t0) // DAY)
            o[i], cl[i], v[i] = r[1], r[4], r[5]
        O[c], C[c], V[c] = o, cl, v
    return t0, n, O, C, V


T0, N, O, C, V = load()
COINS = sorted(C)


def date_of(i):
    import time
    return time.strftime("%Y-%m-%d", time.gmtime((T0 + i * DAY) / 1000))


def index_of(datestr):
    import calendar, time
    return int((calendar.timegm(time.strptime(datestr, "%Y-%m-%d")) * 1000 - T0) // DAY)


# --- precomputed helpers -------------------------------------------------------------------------------------------
def sma_series(c, w):
    out, s, q = [None] * N, 0.0, []
    for i in range(N):
        x = c[i]
        if x is None:
            q.clear(); s = 0.0; continue
        q.append(x); s += x
        if len(q) > w: s -= q.pop(0)
        if len(q) == w: out[i] = s / w
    return out


_sma_cache = {}
def btc_sma(w):
    if w not in _sma_cache: _sma_cache[w] = sma_series(C["BTC"], w)
    return _sma_cache[w]


_vol30 = {c: None for c in COINS}
def avg_vol(c):
    if _vol30[c] is None:
        v = V[c]; out = [None] * N
        for i in range(29, N):
            w = [x for x in v[i - 29:i + 1] if x is not None]
            if len(w) >= 25: out[i] = sum(w) / len(w)
        _vol30[c] = out
    return _vol30[c]


@functools.lru_cache(maxsize=None)
def universe_c(t, top_n, min_vol=2e6):
    cand = []
    for c in COINS:
        a = avg_vol(c)[t]
        if a is not None and a >= min_vol and C[c][t] is not None and O[c][t + 1 if t + 1 < N else t] is not None:
            cand.append((a, c))
    cand.sort(reverse=True)
    return tuple(c for _, c in cand[:top_n])


def universe(t, top_n):
    return list(universe_c(t, top_n))


@functools.lru_cache(maxsize=None)
def score(c, t, lookback, skip, mode):
    a, b = t - skip, t - skip - lookback
    if b < 0: return None
    pa, pb = C[c][a], C[c][b]
    if pa is None or pb is None: return None
    r = pa / pb - 1
    if mode == "ret": return r
    seg = [C[c][i] for i in range(b, a + 1)]
    if any(x is None for x in seg): return None
    rets = [seg[i + 1] / seg[i] - 1 for i in range(len(seg) - 1)]
    sd = st.pstdev(rets) if len(rets) > 2 else 0
    return r / sd if sd > 0 else None


# --- simulator ---------------------------------------------------------------------------------------------------------
def simulate(pick, rebal, offset, start, end, regime=200, daily_regime_exit=False, cost=SIDE_COST):
    """pick(t) -> list of coins (equal weight) or [] for cash. Returns list of (day_index, equity)."""
    smab = btc_sma(regime)
    cash, units, last = 1.0, {}, {}
    eq = []
    for d in range(start + 1, end + 1):
        t = d - 1
        # coins that stopped trading: sell at last close
        for c in list(units):
            if C[c][d] is None and O[c][d] is None:
                cash += units.pop(c) * last[c]
        is_rebal = (t - start - offset) % rebal == 0 and t >= start + offset
        want_exit = False
        if daily_regime_exit and units:
            b = C["BTC"][t]; s = smab[t]
            want_exit = False if regime <= 1 else (b is None or s is None or b <= s)
        if is_rebal or want_exit:
            b = C["BTC"][t]; s = smab[t]
            risk_on = True if regime <= 1 else (b is not None and s is not None and b > s)   # regime<=1 = no filter (buy & hold)
            target = pick(t) if (risk_on and not want_exit) else []
            target = [c for c in target if O[c][d] is not None]
            px = lambda c: O[c][d] if O[c][d] is not None else last.get(c)
            equity = cash + sum(u * px(c) for c, u in units.items())
            w = 1.0 / len(target) if target else 0.0
            tv = {c: w * equity for c in target}
            traded = sum(abs(tv.get(c, 0.0) - units.get(c, 0.0) * px(c)) for c in set(tv) | set(units))
            fee = traded * cost
            scale = (equity - fee) / equity if equity > 0 else 0
            units = {c: tv[c] * scale / O[c][d] for c in target}
            cash = equity - fee - sum(tv[c] * scale for c in target)
        for c in units:
            if C[c][d] is not None: last[c] = C[c][d]
        eq.append((d, cash + sum(u * (C[c][d] if C[c][d] is not None else last[c]) for c, u in units.items())))
    return eq


def stats(eq):
    if len(eq) < 30: return None
    v = [1.0] + [e for _, e in eq]
    r = [v[i + 1] / v[i] - 1 for i in range(len(v) - 1)]
    yrs = len(r) / 365
    mu, sd = st.mean(r), st.pstdev(r)
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x); mdd = min(mdd, x / peak - 1)
    return {"total_%": round((v[-1] - 1) * 100, 1), "cagr_%": round((v[-1] ** (1 / yrs) - 1) * 100, 1) if v[-1] > 0 else -100,
            "vol_%": round(sd * math.sqrt(365) * 100, 1), "sharpe": round(mu / sd * math.sqrt(365), 2) if sd > 0 else 0,
            "maxdd_%": round(mdd * 100, 1), "days": len(r)}


def momentum_picker(top_n, lookback, skip, k, mode):
    def pick(t):
        sc = []
        for c in universe(t, top_n):
            s = score(c, t, lookback, skip, mode)
            if s is not None and s > 0: sc.append((s, c))
        sc.sort(reverse=True)
        return [c for _, c in sc[:k]]
    return pick


def volume_picker(top_n, k):
    return lambda t: universe(t, top_n)[:k]


def btc_picker(t):
    return ["BTC"]


def avg_over_offsets(pick, rebal, start, end, regime, daily_exit=False, cost=SIDE_COST):
    res = [stats(simulate(pick, rebal, off, start, end, regime, daily_exit, cost)) for off in range(0, rebal, max(1, rebal // 7))]
    res = [x for x in res if x]
    if not res: return None
    keys = ("total_%", "cagr_%", "vol_%", "sharpe", "maxdd_%")
    out = {k: round(st.mean(x[k] for x in res), 2) for k in keys}
    out["sharpe_min"] = min(x["sharpe"] for x in res); out["n_offsets"] = len(res)
    return out


if __name__ == "__main__":
    A, SPLIT, B = index_of("2020-06-01"), index_of("2023-06-30"), N - 2
    print("data: %s .. %s, %d coins" % (date_of(0), date_of(N - 1), len(COINS)))
    print("period %s..%s  | train %s..%s | test %s..%s\n" % (date_of(A), date_of(B), date_of(A), date_of(SPLIT), date_of(SPLIT), date_of(B)))
    periods = {"train": (A, SPLIT), "test": (SPLIT, B), "all": (A, B)}
    results = {"benchmarks": {}, "grid": []}

    # ---- benchmarks
    def bench(name, pick, regime=200, daily=False, rebal=7):
        row = {}
        for pn, (s, e) in periods.items():
            row[pn] = avg_over_offsets(pick, rebal, s, e, regime, daily)
        results["benchmarks"][name] = row
        print("%-34s" % name, " | ".join("%s: CAGR %6.1f%% Sh %5.2f DD %6.1f%%" % (pn, row[pn]["cagr_%"], row[pn]["sharpe"], row[pn]["maxdd_%"]) for pn in periods))
    bench("BTC buy & hold", btc_picker, regime=1)
    bench("BTC only above 200d avg", btc_picker, regime=200, daily=True, rebal=1)
    bench("Top-5 by volume, regime 200", volume_picker(20, 5))
    bench("Top-10 by volume, regime 200", volume_picker(20, 10))

    # ---- parameter grid on TRAIN, then look at TEST for every config (no cherry picking: print all)
    grid = list(itertools.product([20], [14, 28, 56, 90], [0, 7], [3, 5, 8], ["ret", "risk"], [100, 200]))
    print("\nGrid (%d configs): top_n lookback skip K mode regime -> train Sh | test Sh | test CAGR | test DD" % len(grid))
    for top_n, lb, sk, k, mode, rg in grid:
        pick = momentum_picker(top_n, lb, sk, k, mode)
        tr = avg_over_offsets(pick, 7, A, SPLIT, rg); te = avg_over_offsets(pick, 7, SPLIT, B, rg)
        if not tr or not te: continue
        results["grid"].append({"top_n": top_n, "lookback": lb, "skip": sk, "k": k, "mode": mode, "regime": rg, "train": tr, "test": te})
        print("N%-2d L%-3d S%-2d K%d %-4s R%-3d | %5.2f | %5.2f | %6.1f%% | %6.1f%%" % (top_n, lb, sk, k, mode, rg, tr["sharpe"], te["sharpe"], te["cagr_%"], te["maxdd_%"]), flush=True)
    json.dump(results, open(os.path.join(HERE, "momentum_results.json"), "w"), indent=1)
