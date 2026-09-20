"""SCALPING: config, server payload, and the browser analysis maths (run with node; skipped if node is missing)."""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scalping import config, service  # noqa: E402

JS = os.path.join(ROOT, "static", "scalping.js")


def node(expr, setup=""):
    code = f"const S = require({json.dumps(JS)}); const P = {json.dumps(config.PARAMS)}; {setup} console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


# 5m candles helper (JS): [openTime, o, h, l, c, v]
MK = ("const T0 = Date.UTC(2026,8,20,0,0,0); "
      "function mk(closes, vol) { return closes.map((c,i)=>[T0+i*300000, c, c*1.002, c*0.998, c, vol && vol[i] != null ? vol[i] : 100]); } ")


class ConfigTests(unittest.TestCase):
    def test_only_the_four_requested_coins(self):
        self.assertEqual([c["symbol"] for c in config.COINS], ["SOL", "LINK", "XRP", "ONDO"])

    def test_payload_survives_missing_data_sources(self):
        class Boom:
            SNAPSHOT = {"SOL": {"funding_pct": 0.01, "mark": 150.0}}

            @staticmethod
            def okx_oi(sym):
                raise RuntimeError("down")
        p = service.build_payload(Boom, Boom)
        self.assertEqual(len(p["coins"]), 4)
        sol = p["coins"][0]
        self.assertEqual(sol["funding_pct"], 0.01)
        self.assertIsNone(sol["oi_change_pct"])                 # unavailable stays None, never invented
        self.assertIsNone(p["coins"][1]["funding_pct"])
        self.assertEqual(service.build_payload()["coins"][0]["funding_pct"], None)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class AnalysisTests(unittest.TestCase):
    def test_too_little_data_is_reported_not_guessed(self):
        r = node("S.analyze(mk([1,2,3]), null, {}, P)", MK)
        self.assertFalse(r["ok"])

    def test_uptrend_with_volume_is_watch_long_with_levels_net_of_fees(self):
        setup = MK + "const closes = Array.from({length: 200}, (_, i) => 100 + i*0.25 + (i%2)*0.6); " \
                     "const vol = closes.map((c,i)=> i >= 196 ? 400 : 100); "
        r = node("S.analyze(mk(closes, vol), {bids: [[99.9, 500]], asks: [[100.1, 100]]}, {funding_pct: 0.005}, P)", setup)
        self.assertTrue(r["ok"])
        self.assertEqual(r["verdict"], "WATCH LONG", r["checks"])
        L = r["levels"]
        self.assertLess(L["stop"], L["entry"])
        self.assertGreater(L["t2"], L["t1"])
        self.assertAlmostEqual(L["net1"], P_ATR_T1 * r["atrPct"] - config.FEE_PCT, places=6)

    def test_downtrend_is_avoid(self):
        setup = MK + "const closes = Array.from({length: 200}, (_, i) => 200 - i*0.4 + (i%2)*0.5); "
        r = node("S.analyze(mk(closes), null, {}, P)", setup)
        self.assertEqual(r["verdict"], "AVOID")

    def test_crowded_funding_blocks_watch_long(self):
        setup = MK + "const closes = Array.from({length: 200}, (_, i) => 100 + i*0.25 + (i%2)*0.6); " \
                     "const vol = closes.map((c,i)=> i >= 196 ? 400 : 100); "
        r = node("S.analyze(mk(closes, vol), {bids: [[99.9, 500]], asks: [[100.1, 100]]}, {funding_pct: 0.2}, P)", setup)
        self.assertNotEqual(r["verdict"], "WATCH LONG")

    def test_tiny_moves_fail_the_fee_check(self):
        setup = MK + "const closes = Array.from({length: 200}, (_, i) => 100 + i*0.0005); "                      "const tiny = closes.map((c,i)=>[T0+i*300000, c, c*1.0002, c*0.9998, c, 100]); "
        r = node("S.analyze(tiny, null, {}, P)", setup)
        cost = [c for c in r["checks"] if c["key"] == "cost"][0]
        self.assertEqual(cost["state"], "fail")
        self.assertNotEqual(r["verdict"], "WATCH LONG")

    def test_depth_ratio(self):
        self.assertAlmostEqual(node("S.depthRatio({bids:[[99.5,10]], asks:[[100.5,5]]}, 100, 1)"), 995 / 502.5)
        self.assertIsNone(node("S.depthRatio(null, 100, 1)"))


P_ATR_T1 = config.PARAMS["atr_t1"]


if __name__ == "__main__":
    unittest.main()
