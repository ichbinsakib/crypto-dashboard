"""Replay the live SCALPING setup-scoring (scalping/analysis.py) and lifecycle (scalping/lifecycle.py)
against 90 days of real 5m/15m history for the 4 scalping coins, to see at real historical scale
whether the 7-check Setup Score actually predicts win/loss. Reuses the production evaluate()/
advance() functions unchanged, so results reflect the exact same rules as the live engine."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scalping import analysis, lifecycle, config as scfg  # noqa: E402

COINS = ("SOL", "LINK", "XRP", "ONDO")
DATA = os.path.join(os.path.dirname(__file__), "scalp_data")
MIN_EXEC, MIN_HTF = 61, 61
EXEC_WINDOW, HTF_WINDOW = 300, 120


def load(coin, interval):
    with open(os.path.join(DATA, f"{coin}_{interval}.json")) as f:
        return json.load(f)


def from_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)


def backtest_coin(coin, cfg):
    exec5 = load(coin, "5m")
    htf15 = load(coin, "15m")
    n = len(exec5)
    base_ms = exec5[0][0]
    htf_i = 0
    out = []
    i = MIN_EXEC
    while i < n - 2:
        t_close = exec5[i][0] + 300_000
        while htf_i < len(htf15) and htf15[htf_i][0] + 900_000 <= t_close:
            htf_i += 1
        if htf_i < MIN_HTF:
            i += 1
            continue
        exec_win = exec5[max(0, i - EXEC_WINDOW):i + 1]
        exec_rows = exec_win + [exec_win[-1]]
        htf_win = htf15[max(0, htf_i - HTF_WINDOW):htf_i]
        htf_rows = htf_win + [htf_win[-1]]
        ev = analysis.evaluate(coin, htf_rows, exec_rows, cfg)
        if ev["status"] != "SETUP":
            i += 1
            continue
        sig = lifecycle.new_signal(coin, ev, ev["regime"], from_ms(t_close), cfg, exec5[i][0])
        future = exec5[i + 1:]
        if not future:
            break
        future_rows = future + [future[-1]]
        resolved = lifecycle.advance(sig, future_rows, from_ms(exec5[-1][0]), cfg)
        out.append((ev, resolved))
        if resolved.get("exit_time"):
            exit_ms = int(datetime.datetime.fromisoformat(resolved["exit_time"].replace("Z", "+00:00")).timestamp() * 1000)
            idx = max(i + 1, (exit_ms - base_ms) // 300_000)
            i = int(idx) + 1
        else:
            i += 1                                             # still open at the end of history: just move on
    return out


def main():
    cfg = scfg.effective({})
    all_results = []
    for coin in COINS:
        res = backtest_coin(coin, cfg)
        print(f"{coin}: {len(res)} setups generated")
        all_results.extend(res)
    with open(os.path.join(os.path.dirname(__file__), "scalp_results.json"), "w") as f:
        json.dump([{"checks": ev["checks"], "score": ev["score"], "quality": ev["quality"],
                    "coin": ev["symbol"], "direction": r["direction"], "state": r["state"],
                    "pnl_pct": r.get("pnl_pct"), "mfe_pct": r.get("mfe_pct"), "mae_pct": r.get("mae_pct"),
                    "entry_time": r.get("entry_time"), "exit_reason": r.get("exit_reason")}
                   for ev, r in all_results], f)
    print(f"\nTotal setups: {len(all_results)}")


if __name__ == "__main__":
    main()
