"""Backtest the scalping engine's SHORT side (already built into scalping/analysis.py, just gated
behind allow_short) against the same 90 days of real 5m/15m history as scalp_run.py, using the
actual production evaluate()/lifecycle.advance() with allow_short=True.

Result (recorded here since this script is not run automatically): LONG (n=52, already reflecting
the momentum+volume gate) is close to flat -- train avg -0.03%, test avg +0.03%, total +0.42%.
SHORT (n=22) is negative in BOTH halves -- train avg -0.33%, test avg -0.12%, total -4.77% -- a
cleaner and worse result than the trend engine's mirrored short (which at least flipped sign
between halves). Every coin's SHORT breakdown is flat-to-negative. Do not read this as a reason to
enable allow_short in production off the back of this script alone."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scalp_run as SR  # noqa: E402
from scalping import config as scfg  # noqa: E402


if __name__ == "__main__":
    cfg = scfg.effective({"allow_short": True})
    all_results = []
    for coin in SR.COINS:
        res = SR.backtest_coin(coin, cfg)
        print(f"{coin}: {len(res)} setups")
        all_results.extend(res)
    out = [{"checks": ev["checks"], "score": ev["score"], "quality": ev["quality"], "coin": ev["symbol"],
            "direction": r["direction"], "state": r["state"], "pnl_pct": r.get("pnl_pct"), "mfe_pct": r.get("mfe_pct"),
            "mae_pct": r.get("mae_pct"), "entry_time": r.get("entry_time"), "exit_reason": r.get("exit_reason")}
           for ev, r in all_results]
    with open(os.path.join(os.path.dirname(__file__), "scalp_results_short.json"), "w") as f:
        json.dump(out, f)
    print(f"\nTotal setups: {len(out)}")
