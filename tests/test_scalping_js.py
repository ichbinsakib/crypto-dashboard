"""SCALPING dashboard maths (performance stats, filters, live P&L, status words, data status), run with node; skipped if node is missing."""
import json
import os
import shutil
import subprocess
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "scalping.js")


def node(expr, setup=""):
    code = f"const S = require({json.dumps(JS)}); {setup} console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


ROWS = """const rows = [
 {id:'1',coin:'SOL',direction:'LONG',state:'TP2_HIT',exit_reason:'tp2',actual_entry:100,exit_time:'2026-09-20T10:00:00Z',created_at:'2026-09-20T09:00:00Z',pnl_pct:2.0,r_multiple:2.0,duration_min:30,timeframe:'5m',htf:'15m',regime:'TRENDING UP',setup_type:'breakout'},
 {id:'2',coin:'SOL',direction:'LONG',state:'STOP_LOSS',exit_reason:'stop',actual_entry:100,exit_time:'2026-09-20T11:00:00Z',created_at:'2026-09-20T10:30:00Z',pnl_pct:-1.0,r_multiple:-1.0,duration_min:20,timeframe:'5m',htf:'15m',regime:'SIDEWAYS',setup_type:'pullback'},
 {id:'3',coin:'XRP',direction:'SHORT',state:'STOP_LOSS',exit_reason:'stop',actual_entry:2,exit_time:'2026-09-20T12:00:00Z',created_at:'2026-09-20T11:30:00Z',pnl_pct:-2.0,r_multiple:-1.5,duration_min:10,timeframe:'5m',htf:'15m',regime:'TRENDING DOWN',setup_type:'breakout'},
 {id:'4',coin:'LINK',direction:'LONG',state:'EXPIRED',exit_reason:'not_entered',actual_entry:null,exit_time:'2026-09-20T13:00:00Z',created_at:'2026-09-20T12:30:00Z',pnl_pct:null,r_multiple:null,duration_min:30,timeframe:'5m',htf:'15m',regime:'SIDEWAYS',setup_type:'breakout'},
 {id:'5',coin:'SOL',direction:'LONG',state:'TP1_HIT',exit_reason:'tp1_then_breakeven',actual_entry:100,exit_time:'2026-09-20T14:00:00Z',created_at:'2026-09-20T13:30:00Z',pnl_pct:0.5,r_multiple:0.5,duration_min:40,timeframe:'5m',htf:'15m',regime:'TRENDING UP',setup_type:'breakout'},
];"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ScalpingJsTests(unittest.TestCase):
    def test_performance_stats(self):
        s = node("S.perfStats(rows)", ROWS)
        self.assertEqual((s["total"], s["triggered"], s["completed"], s["wins"], s["losses"]), (5, 4, 4, 2, 2))
        self.assertAlmostEqual(s["winRate"], 50.0)
        self.assertAlmostEqual(s["totalPnl"], -0.5)
        self.assertAlmostEqual(s["avgProfit"], 1.25)
        self.assertAlmostEqual(s["avgLoss"], -1.5)
        self.assertAlmostEqual(s["profitFactor"], 2.5 / 3.0)
        self.assertAlmostEqual(s["avgR"], (2.0 - 1.0 - 1.5 + 0.5) / 4)
        self.assertAlmostEqual(s["avgDuration"], 25.0)
        # cumulative: +2, +1, -1, -0.5 -> peak 2, trough -1 => max drawdown 3
        self.assertAlmostEqual(s["maxDrawdown"], 3.0)

    def test_expired_and_invalidated_signals_count_as_setups_but_not_trades(self):
        s = node("S.perfStats([rows[3]])", ROWS)
        self.assertEqual((s["total"], s["triggered"], s["completed"]), (1, 0, 0))
        self.assertIsNone(s["winRate"])
        self.assertIsNone(s["totalPnl"])

    def test_empty_stats_do_not_invent_numbers(self):
        s = node("S.perfStats([])")
        self.assertEqual(s["total"], 0)
        for k in ("winRate", "avgR", "avgProfit", "avgLoss", "totalPnl", "profitFactor", "maxDrawdown", "avgDuration"):
            self.assertIsNone(s[k], k)

    def test_profit_factor_with_no_losses_is_infinite_not_a_crash(self):
        self.assertIsNone(node("S.perfStats([rows[0]]).profitFactor === Infinity ? null : 'finite'", ROWS))

    def test_filters(self):
        ids = lambda f: sorted(node(f"S.applyFilters(rows, {json.dumps(f)}).map(r => r.id)", ROWS))
        self.assertEqual(ids({"coin": "SOL"}), ["1", "2", "5"])
        self.assertEqual(ids({"side": "SHORT"}), ["3"])
        self.assertEqual(ids({"regime": "SIDEWAYS"}), ["2", "4"])
        self.assertEqual(ids({"type": "pullback"}), ["2"])
        self.assertEqual(ids({"tf": "5m/15m", "coin": "LINK"}), ["4"])
        self.assertEqual(ids({}), ["1", "2", "3", "4", "5"])
        self.assertEqual(ids({"coin": "SOL", "regime": "TRENDING UP", "side": "LONG"}), ["1", "5"])

    def test_sorting(self):
        self.assertEqual(node("S.sortRows(rows, 'pnl', -1).map(r => r.id)", ROWS), ["1", "5", "2", "3", "4"])     # missing P&L goes last
        self.assertEqual(node("S.sortRows(rows, 'coin', 1).map(r => r.id)", ROWS)[0], "4")

    def test_live_pnl_long_short_and_partial(self):
        cfg = "const cfg = {partial_tp1_pct: 50, fee_pct: 0.2};"
        self.assertAlmostEqual(node("S.openPnl({direction:'LONG',actual_entry:100}, 101, cfg)", cfg), 0.8)
        self.assertAlmostEqual(node("S.openPnl({direction:'SHORT',actual_entry:100}, 99, cfg)", cfg), 0.8)
        self.assertAlmostEqual(node("S.openPnl({direction:'LONG',actual_entry:100,tp1_time:'x',tp1:101.5}, 102, cfg)", cfg), 0.5 * 1.5 + 0.5 * 2.0 - 0.2)
        self.assertIsNone(node("S.openPnl({direction:'LONG',actual_entry:null}, 101, cfg)", cfg))

    def test_trade_status_words(self):
        base = "const b = {direction:'LONG',entry_low:100,entry_high:100.2,stop:99,tp1:101.5,tp2:103,actual_entry:null,tp1_time:null};"
        self.assertEqual(node("S.tradeStatus(b, 100.1)", base), "IN ENTRY ZONE")
        self.assertEqual(node("S.tradeStatus(b, 101)", base), "WAITING FOR ENTRY")
        act = base + "const a = Object.assign({}, b, {actual_entry:100.1});"
        self.assertEqual(node("S.tradeStatus(a, 100.5)", act), "ACTIVE")
        self.assertEqual(node("S.tradeStatus(a, 101.3)", act), "TP1 APPROACHING")
        self.assertEqual(node("S.tradeStatus(a, 99.2)", act), "NEAR STOP")
        self.assertEqual(node("S.tradeStatus(Object.assign({}, a, {tp1_time:'x'}), 101.6)", act), "TP1 HIT")
        self.assertEqual(node("S.tradeStatus(Object.assign({}, a, {manual_close_requested:true}), 100.5)", act), "CLOSE REQUESTED")
        short = "const s = {direction:'SHORT',entry_low:99.8,entry_high:100,stop:101,tp1:98.5,tp2:97,actual_entry:99.9,tp1_time:null};"
        self.assertEqual(node("S.tradeStatus(s, 98.8)", short), "TP1 APPROACHING")

    def test_data_status_rules(self):
        self.assertEqual(node("S.dataStatus('LIVE', 2, true, true)"), "LIVE")
        self.assertEqual(node("S.dataStatus('LIVE', 20, true, true)"), "DELAYED")
        self.assertEqual(node("S.dataStatus('LIVE', 45, true, true)"), "STALE")
        self.assertEqual(node("S.dataStatus('STALE', 2, true, true)"), "STALE")
        self.assertEqual(node("S.dataStatus('LIVE', 2, false, true)"), "DELAYED")
        self.assertEqual(node("S.dataStatus('LIVE', 2, false, false)"), "DISCONNECTED")
        self.assertEqual(node("S.dataStatus('DISCONNECTED', 2, true, true)"), "DISCONNECTED")

    def test_session_vwap(self):
        k = "const T=Date.UTC(2026,8,20,0,0,0); const k=[[T,1,11,9,10,100],[T+300000,1,21,19,20,300],[T+600000,1,31,29,30,100]];"
        # typical prices 10, 20, 30 weighted 100, 300, 100 -> (1000+6000+3000)/500 = 20
        self.assertAlmostEqual(node("S.sessionVwap(k)", k), 20.0)
        self.assertIsNone(node("S.sessionVwap(k.slice(0,2))", k))            # too little of the day yet: n/a, not a guess
        self.assertIsNone(node("S.sessionVwap([])"))
        # candles from before UTC midnight are not part of today's VWAP
        old = "const T=Date.UTC(2026,8,20,0,0,0); const k=[[T-300000,1,101,99,100,1000],[T,1,11,9,10,100],[T+300000,1,11,9,10,100],[T+600000,1,11,9,10,100]];"
        self.assertAlmostEqual(node("S.sessionVwap(k)", old), 10.0)

    def test_price_formatting_and_result_labels(self):
        self.assertEqual(node("S.fmtPrice(185.2049)"), "185.20")
        self.assertEqual(node("S.fmtPrice(25.2)"), "25.200")
        self.assertEqual(node("S.fmtPrice(2.91234)"), "2.9123")
        self.assertEqual(node("S.fmtPrice(null)"), "n/a")
        self.assertEqual(node("rows.map(r => S.resultLabel(r))", ROWS), ["TP2", "SL", "SL", "EXPIRED", "TP1"])


if __name__ == "__main__":
    unittest.main()
