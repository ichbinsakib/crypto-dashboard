"""Walk-forward-style backtest: pick params on the first 60% of history, judge on the last 40% (never tuned on)."""
import json, os, glob, statistics as st, itertools, sys
FEE = 0.3  # % round trip incl. slippage
D = os.path.join(os.path.dirname(__file__), "data")
def resample(rows, h):
    out = []
    for i in range(0, len(rows) - h + 1, h):
        g = rows[i:i + h]
        out.append([g[0][0], g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
    return out
def ema(v, n):
    k = 2 / (n + 1); o = []; e = v[0]
    for x in v: e = x * k + e * (1 - k); o.append(e)
    return o
def atr(rows, n=14):
    tr = [rows[0][2] - rows[0][3]] + [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i-1][4]), abs(rows[i][3] - rows[i-1][4])) for i in range(1, len(rows))]
    return ema(tr, n)
def rsi(c, n=14):
    g = l = 0; o = [50] * len(c)
    for i in range(1, len(c)):
        d = c[i] - c[i-1]; u, w = max(d, 0), max(-d, 0)
        if i <= n: g += u / n; l += w / n
        else: g = (g * (n-1) + u) / n; l = (l * (n-1) + w) / n
        if i >= n: o[i] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    return o
def trades(rows, mode, N, k, trend, cut, maxbars):
    """mode 'trend': donchian breakout, chandelier trailing exit. 'dip': RSI<N in uptrend, exit RSI>55 or stop k*ATR or timeout."""
    c = [r[4] for r in rows]; a = atr(rows); e = ema(c, trend) if trend else None; rs = rsi(c) if mode == "dip" else None
    out = []; i = max(N, trend or 0, 30) + 1; n = len(rows)
    while i < n - 2:
        if mode == "trend":
            sig = c[i] > max(r[2] for r in rows[i-N:i]) and (not trend or c[i] > e[i])
        else:
            sig = rs[i] < N and (not trend or c[i] > e[i])
        if not sig: i += 1; continue
        entry = rows[i+1][1]; hh = entry; stop = entry - k * a[i]; j = i + 1; exit_p = None
        while j < n:
            r = rows[j]
            if r[3] <= stop: exit_p = min(stop, r[1]); break
            hh = max(hh, r[2])
            if mode == "trend": stop = max(stop, hh - k * a[j])
            elif rs[j] > 55: exit_p = r[4]; break
            if j - i >= maxbars: exit_p = r[4]; break
            j += 1
        if exit_p is None: break
        out.append((rows[i+1][0], (exit_p / entry - 1) * 100 - FEE)); i = j + 1
    return out
def load(h):
    d = {}
    for f in glob.glob(D + "/*.json"):
        rows = json.load(open(f)); d[os.path.basename(f)[:-5]] = resample(rows, h) if h > 1 else rows
    return d
def summarize(t):
    if not t: return None
    r = [x[1] for x in t]; w = [x for x in r if x > 0]; ls = [-x for x in r if x <= 0]
    return dict(n=len(r), win=100 * len(w) / len(r), avg=st.mean(r), med=st.median(r), pf=(sum(w) / sum(ls)) if ls else 9.9, big=sum(1 for x in r if x >= 3) / len(r) * 100)
def evaluate(data, cut_ts, **kw):
    tr, te = [], []
    for sym, rows in data.items():
        for ts, p in trades(rows, cut=cut_ts, **kw):
            (tr if ts < cut_ts else te).append((ts, p))
    return summarize(tr), summarize(te)
if __name__ == "__main__":
    res = []
    for tfname, h in (("4h", 4), ("1d", 24)):
        data = load(h); allts = sorted(r[0] for rows in data.values() for r in rows[:1] + rows[-1:]); t0, t1 = min(allts), max(allts)
        cut = t0 + 0.6 * (t1 - t0)
        grid = []
        for N, k, tr_ in itertools.product((20, 40, 80), (2, 3, 4), (0, 200)):
            grid.append(("trend", N, k, tr_, 400))
        for N, k, tr_ in itertools.product((25, 30), (2, 3), (0, 100)):
            grid.append(("dip", N, k, tr_, 60))
        for mode, N, k, tr_, mb in grid:
            a, b = evaluate(data, cut, mode=mode, N=N, k=k, trend=tr_, maxbars=mb)
            if a and b: res.append((tfname, mode, N, k, tr_, a, b))
    json.dump(res, open(os.path.join(os.path.dirname(__file__), "results.json"), "w"))
    print("tf mode N k trend | TRAIN n win% avg% pf | TEST n win% avg% pf")
    for r in sorted(res, key=lambda x: -x[5]["avg"])[:12]:
        print(r[0], r[1], r[2], r[3], r[4], "|", "%d %.0f %.2f %.2f" % (r[5]["n"], r[5]["win"], r[5]["avg"], r[5]["pf"]), "|", "%d %.0f %.2f %.2f" % (r[6]["n"], r[6]["win"], r[6]["avg"], r[6]["pf"]))
    pos = sum(1 for r in res if r[6]["avg"] > 0); print("\nconfigs:", len(res), " positive on TEST:", pos)
    for m in ("trend", "dip"):
        s = [r for r in res if r[1] == m]; print(m, "median TEST avg %.2f%%, median TEST win %.0f%%" % (st.median(r[6]["avg"] for r in s), st.median(r[6]["win"] for r in s)))
    for tfname, h in (("4h", 4), ("1d", 24)):
        d = load(h); rets = [(rows[-1][4] / rows[0][1] - 1) * 100 for rows in d.values()]
        print("buy&hold", tfname, "avg over full 2y across coins: %.0f%%, median %.0f%%" % (st.mean(rets), st.median(rets)))
