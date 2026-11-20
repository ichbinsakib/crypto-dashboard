"""Stress-test the best weekly-momentum candidates: daily regime exit, higher costs, rebalance spacing, year by year."""
import json, os, statistics as st
import momentum_weekly as M
A, SPLIT, B = M.index_of("2020-06-01"), M.index_of("2023-06-30"), M.N - 2
CANDS = {"L14 K5 risk R100": (14, 0, 5, "risk", 100), "L28 K5 risk R100": (28, 0, 5, "risk", 100), "L14 K3 ret R100": (14, 0, 3, "ret", 100), "L14 K8 risk R100": (14, 0, 8, "risk", 100)}
def row(label, pick, rebal=7, regime=100, daily=False, cost=M.SIDE_COST):
    out = []
    for nm, (s, e) in (("train", (A, SPLIT)), ("test", (SPLIT, B))):
        r = M.avg_over_offsets(pick, rebal, s, e, regime, daily, cost)
        out.append("%s Sh %5.2f CAGR %6.1f%% DD %6.1f%%" % (nm, r["sharpe"], r["cagr_%"], r["maxdd_%"]))
    print("%-46s %s" % (label, " | ".join(out)), flush=True)
for name, (lb, sk, k, mode, rg) in CANDS.items():
    pick = M.momentum_picker(20, lb, sk, k, mode)
    print("==", name)
    row("base (weekly, cost 0.15%/side)", pick, regime=rg)
    row("daily regime exit", pick, regime=rg, daily=True)
    row("cost 0.30%/side (stress)", pick, regime=rg, cost=0.003)
    row("rebalance every 3 days", pick, rebal=3, regime=rg)
    row("rebalance every 14 days", pick, rebal=14, regime=rg)
    row("daily exit + cost 0.30%", pick, regime=rg, daily=True, cost=0.003)
print("\n== year by year (base L14 K5 risk R100, daily exit) vs BTC buy&hold vs BTC>100d")
pick = M.momentum_picker(20, 14, 0, 5, "risk")
import calendar, time
for yr in range(2020, 2027):
    s = max(A, M.index_of("%d-01-01" % yr)); e = min(B, M.index_of("%d-12-31" % yr))
    if e - s < 60: continue
    a = M.stats(M.simulate(pick, 7, 0, s, e, 100, True)); b = M.stats(M.simulate(M.btc_picker, 1, 0, s, e, 1)); c = M.stats(M.simulate(M.btc_picker, 1, 0, s, e, 100, True))
    print(yr, "momentum %+7.1f%% DD %6.1f%% | BTC hold %+7.1f%% DD %6.1f%% | BTC>100d %+7.1f%% DD %6.1f%%" % (a["total_%"], a["maxdd_%"], b["total_%"], b["maxdd_%"], c["total_%"], c["maxdd_%"]))
