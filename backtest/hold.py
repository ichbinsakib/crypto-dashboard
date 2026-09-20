"""Holding-time distribution of the 4h trend rule (N=55, 4 ATR trail, above 200 avg) on all history."""
import statistics as st, run as R
data = R.load(4); H = []
for sym, rows in data.items():
    c = [r[4] for r in rows]; a = R.atr(rows); e = R.ema(c, 200); n = len(rows); i = 256
    while i < n - 2:
        if not (c[i] > max(r[2] for r in rows[i-55:i]) and c[i] > e[i]): i += 1; continue
        entry = rows[i+1][1]; hh = entry; stop = entry - 4 * a[i]; j = i + 1; out = None
        while j < n:
            r = rows[j]
            if r[3] <= stop: out = min(stop, r[1]); break
            hh = max(hh, r[2]); stop = max(stop, hh - 4 * a[j]); j += 1
        if out is None: break
        H.append(((j - i) * 4, (out / entry - 1) * 100 - R.FEE)); i = j + 1
h = sorted(x[0] for x in H); q = lambda p: h[int(p * (len(h) - 1))]
print("trades", len(H), "hours: p25 %d median %d p75 %d p90 %d" % (q(.25), q(.5), q(.75), q(.9)))
w = sorted(x[0] for x in H if x[1] > 0); l = sorted(x[0] for x in H if x[1] <= 0)
print("winners median %d h (n=%d), losers median %d h (n=%d)" % (st.median(w), len(w), st.median(l), len(l)))
print("avg net %.2f%% win %.0f%%" % (st.mean(x[1] for x in H), 100 * len(w) / len(H)))
