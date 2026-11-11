"""Walk-forward view: the same trades as regime_run.py, but per calendar quarter, to see whether any edge is
stable over time or comes from one lucky stretch. Original docstring: Does gating trend entries on BTC's own regime (BTC above/below its 200-candle 4h EMA) help?
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


import datetime
def quarter(ts):
    d = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"

def table(label, H):
    qs = sorted({quarter(h[0]) for h in H})
    print(label)
    pos = 0
    for q in qs:
        g = [h[1] for h in H if quarter(h[0]) == q]
        avg = sum(g) / len(g); pos += avg > 0
        print(f"   {q}  n={len(g):4d}  win={sum(1 for x in g if x > 0)/len(g)*100:5.1f}%  avg={avg:+7.3f}%")
    print(f"   quarters with positive avg: {pos} of {len(qs)}")

for d in ("LONG", "SHORT"):
    H = simulate(d)
    table(f"{d} (all entries)", H)
    if d == "LONG":
        table("LONG only when BTC above EMA200", [h for h in H if h[2]])
