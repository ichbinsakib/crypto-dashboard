"""Chart editor maths and storage (Fibonacci, measure, long/short position, geometry, magnet, saving), run with node."""
import json
import os
import shutil
import subprocess
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "drawtools.js")
FAKE_STORAGE = """
const store = {};
global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
"""


def node(expr, setup=""):
    code = f"{FAKE_STORAGE} const D = require({json.dumps(JS)}); {setup} console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class DrawToolsTests(unittest.TestCase):
    def test_fibonacci_levels_run_from_the_end_point_back_to_the_start(self):
        lv = node("D.fibLevels(100, 200)")
        self.assertEqual([l["ratio"] for l in lv], [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1])
        self.assertAlmostEqual(lv[0]["price"], 200)
        self.assertAlmostEqual(lv[3]["price"], 150)
        self.assertAlmostEqual(lv[4]["price"], 200 - 100 * 0.618)
        self.assertAlmostEqual(lv[6]["price"], 100)
        down = node("D.fibLevels(200, 100)")
        self.assertAlmostEqual(down[3]["price"], 150)                       # a downswing retraces the other way

    def test_measure_reports_change_percent_bars_and_time(self):
        m = node("D.measure({t: 0, p: 100}, {t: 3600000 * 5, p: 105}, 3600000)")
        self.assertAlmostEqual(m["dp"], 5)
        self.assertAlmostEqual(m["pct"], 5.0)
        self.assertEqual(m["bars"], 5)
        self.assertEqual(node("D.spanText(90 * 60000)"), "1h 30m")
        self.assertEqual(node("D.spanText(50 * 3600000)"), "2d 2h")
        self.assertEqual(node("D.spanText(12 * 60000)"), "12m")
        self.assertIsNone(node("D.measure({t: 0, p: 0}, {t: 1, p: 1}, 1).pct"))

    def test_position_tool_risk_reward(self):
        long_ = node("D.positionStats(100, 98, 106)")
        self.assertEqual(long_["side"], "LONG")
        self.assertAlmostEqual(long_["rr"], 3.0)
        self.assertAlmostEqual(long_["riskPct"], 2.0)
        self.assertAlmostEqual(long_["rewardPct"], 6.0)
        short = node("D.positionStats(100, 102, 96)")
        self.assertEqual(short["side"], "SHORT")
        self.assertAlmostEqual(short["rr"], 2.0)
        self.assertIsNone(node("D.positionStats(100, 100, 105)")["rr"])           # no stop distance: no ratio, not infinity

    def test_geometry_and_magnet(self):
        self.assertAlmostEqual(node("D.distToSegment(5, 3, 0, 0, 10, 0)"), 3.0)
        self.assertAlmostEqual(node("D.distToSegment(-4, 3, 0, 0, 10, 0)"), 5.0)      # beyond the end: distance to the end point
        self.assertAlmostEqual(node("D.distToSegment(1, 1, 2, 2, 2, 2)"), 2 ** 0.5)   # zero-length segment
        self.assertEqual(node("D.nearestOHLC(101.4, [0, 100, 105, 99, 102])"), 102)   # open 100, high 105, low 99, close 102
        self.assertEqual(node("D.nearestOHLC(104, [0, 100, 105, 99, 102])"), 105)

    def test_freehand_strokes_are_thinned_but_keep_both_ends(self):
        pts = "Array.from({length: 100}, (_, i) => ({x: i, y: 0, t: i, p: 1}))"
        out = node(f"(function(){{ const s = D.simplify({pts}, 5); return [s.length, s[0].x, s[s.length-1].x]; }})()")
        self.assertLess(out[0], 30)
        self.assertEqual(out[1:], [0, 99])

    def test_drawings_are_saved_per_chart_and_survive_bad_data(self):
        setup = "D.saveDrawings('TOTAL', [{id: 'a', type: 'trend', pts: [{t: 1, p: 2}, {t: 3, p: 4}]}]);"
        self.assertEqual(node("D.loadDrawings('TOTAL').map(d => d.type)", setup), ["trend"])
        self.assertEqual(node("D.loadDrawings('ETHUSDT')", setup), [])                # another chart is separate
        junk = "localStorage.setItem('kairo.draw.v1.BAD', '{not json'); localStorage.setItem('kairo.draw.v1.MIX', JSON.stringify([{type:'trend'}, {id:'x', type:'text', pts:[{t:1,p:1}]}, null, 5]));"
        self.assertEqual(node("D.loadDrawings('BAD')", junk), [])                     # corrupted storage never throws
        self.assertEqual(node("D.loadDrawings('MIX').map(d => d.id)", junk), ["x"])     # entries without points are dropped
        cleared = setup + "D.saveDrawings('TOTAL', []);"
        self.assertEqual(node("D.loadDrawings('TOTAL')", cleared), [])
        self.assertEqual(node("Object.keys(store).length", cleared), 0)                # an empty list removes the key


if __name__ == "__main__":
    unittest.main()
