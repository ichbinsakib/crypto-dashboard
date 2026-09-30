"""Backtest the mirrored SHORT trend rule against the real LONG rule, using the actual production
compute_trend_signal() unchanged, over the same 2-year 4h history as backtest/hold.py -- a
60/40 train/test split, exactly like every other backtest in this project.

Result (recorded here since this script is not run automatically): LONG holds up in both halves
(train +2.10% avg, test +0.48% avg -- consistent with hold.py). SHORT does not: train -1.52% avg,
test +0.32% avg, net -757% over all 2 years. A straight sign-flip of the long rule is not a valid
short-side strategy; do not enable allow_short in production off the back of this script alone."""
import sys
import time

sys.path.insert(0, "..")
import run as R  # noqa: E402
import momentum as M  # noqa: E402


def simulate(data, direction):
    H = []
    s = 1 if direction == "LONG" else -1
    for sym, rows_ in data.items():
        n = len(rows_)
        atrs_full = M._atr_series(rows_)   # computed once per coin, not re-derived every candle
        i = M.TREND_EMA + 30
        while i < n - 2:
            window = rows_[:i + 2]
            sig = M.compute_trend_signal(window, 55, now_ms=window[-1][0] + 10 * 60000, direction=direction)
            if not sig or sig["status"] != "momentum":
                i += 1
                continue
            entry_ts = window[-1][0]
            entry = sig["price"]
            stop = entry - s * M.TREND_STOP_ATR * sig["atr"]
            best = entry
            j = i + 1
            out = None
            while j < n:
                r = rows_[j]
                o, hi, lo = float(r[1]), float(r[2]), float(r[3])
                adv_x, fav_x = (lo, hi) if s > 0 else (hi, lo)
                if (adv_x - stop) * s <= 0:
                    out = stop if (o - stop) * s > 0 else o
                    break
                best = max(best, fav_x) if s > 0 else min(best, fav_x)
                a = atrs_full[j]
                stop = max(stop, best - s * M.TREND_STOP_ATR * a) if s > 0 else min(stop, best - s * M.TREND_STOP_ATR * a)
                j += 1
            if out is None:
                break
            net = (out - entry) / entry * 100 * s - M.FEE_PCT
            H.append((entry_ts, net))
            i = j + 1
    return H


if __name__ == "__main__":
    t_start = time.time()
    data = R.load(4)
    allts = sorted(r[0] for rows in data.values() for r in rows[:1] + rows[-1:])
    t0, t1 = min(allts), max(allts)
    cut = t0 + 0.6 * (t1 - t0)
    for direction in ("LONG", "SHORT"):
        H = simulate(data, direction)
        for label, g in (("TRAIN", [(ts, x) for ts, x in H if ts < cut]),
                         ("TEST", [(ts, x) for ts, x in H if ts >= cut]), ("ALL", H)):
            if not g:
                print(direction, label, "n=0")
                continue
            win_rate = sum(1 for _, x in g if x > 0) / len(g) * 100
            avg, tot = sum(x for _, x in g) / len(g), sum(x for _, x in g)
            print(f"{direction} {label:6s} n={len(g):4d} win={win_rate:5.1f}% avg={avg:+.3f}% total={tot:+.1f}%")
    print("elapsed", time.time() - t_start)
