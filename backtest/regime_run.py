"""Does gating trend entries on BTC's own regime (BTC above/below its 200-candle 4h EMA) help?
Same 2-year 4h history, production compute_trend_signal, 60/40 train/test split."""
import sys, bisect
sys.path.insert(0, "..")
import run as R
import momentum as M

data = R.load(4)
btc = data["BTC"]
b_ts = [r[0] for r in btc]
b_close = [float(r[4]) for r in btc]
k = 2 / (M.TREND_EMA + 1); e = b_close[0]; b_ema = []
for x in b_close:
    e = x * k + e * (1 - k); b_ema.append(e)

def btc_up(ts):
    i = bisect.bisect_right(b_ts, ts) - 1
    return i >= 0 and b_close[i] > b_ema[i]

allts = sorted(r[0] for rows in data.values() for r in rows[:1] + rows[-1:])
t0, t1 = min(allts), max(allts); cut = t0 + 0.6 * (t1 - t0)

def simulate(direction):
    s = 1 if direction == "LONG" else -1; H = []
    for sym, rows_ in data.items():
        n = len(rows_); atrs = M._atr_series(rows_); i = M.TREND_EMA + 30
        while i < n - 2:
            window = rows_[:i + 2]
            sig = M.compute_trend_signal(window, 55, now_ms=window[-1][0] + 600000, direction=direction)
            if not sig or sig["status"] != "momentum":
                i += 1; continue
            ts = window[-1][0]; entry = sig["price"]
            stop = entry - s * M.TREND_STOP_ATR * sig["atr"]; best = entry; j = i + 1; out = None
            while j < n:
                r = rows_[j]; o, hi, lo = float(r[1]), float(r[2]), float(r[3])
                adv, fav = (lo, hi) if s > 0 else (hi, lo)
                if (adv - stop) * s <= 0:
                    out = stop if (o - stop) * s > 0 else o; break
                best = max(best, fav) if s > 0 else min(best, fav)
                stop = max(stop, best - s * M.TREND_STOP_ATR * atrs[j]) if s > 0 else min(stop, best - s * M.TREND_STOP_ATR * atrs[j])
                j += 1
            if out is None: break
            H.append((ts, (out - entry) / entry * 100 * s - M.FEE_PCT, btc_up(ts))); i = j + 1
    return H

def rep(label, g):
    if not g: print(f"{label:34s} n=0"); return
    print(f"{label:34s} n={len(g):4d} win={sum(1 for x in g if x[1]>0)/len(g)*100:5.1f}% avg={sum(x[1] for x in g)/len(g):+.3f}% total={sum(x[1] for x in g):+8.1f}%")

for d in ("LONG", "SHORT"):
    H = simulate(d)
    for label, sel in (("all", lambda h: True), ("BTC up (above EMA200)", lambda h: h[2]), ("BTC down (below EMA200)", lambda h: not h[2])):
        g = [h for h in H if sel(h)]
        rep(f"{d} {label} TRAIN", [h for h in g if h[0] < cut]); rep(f"{d} {label} TEST", [h for h in g if h[0] >= cut])
