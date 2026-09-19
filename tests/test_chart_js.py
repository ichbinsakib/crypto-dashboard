"""Chart helper maths, run with node (skipped when node is not installed). Run: python -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import unittest

JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "chart.js")


def run(expr):
    code = f"const C = require({json.dumps(JS)}); console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ChartMathTests(unittest.TestCase):
    def test_ema_matches_definition(self):
        r = run("C.ema([1,2,3,4,5,6], 3)")
        self.assertEqual(r[:2], [None, None])
        self.assertAlmostEqual(r[2], 2.0)                          # SMA seed
        self.assertAlmostEqual(r[3], 3.0)                          # 4*0.5 + 2*0.5
        self.assertAlmostEqual(r[5], 5.0)
        self.assertEqual(run("C.ema([1,2], 5)"), [None, None])       # not enough data -> nothing invented

    def test_nice_ticks_cover_range_with_round_steps(self):
        t = run("C.niceTicks(93.3, 251.7, 7)")
        self.assertTrue(all(93.3 <= v <= 251.7 for v in t))
        self.assertGreaterEqual(len(t), 4)
        steps = {round(b - a, 6) for a, b in zip(t, t[1:])}
        self.assertEqual(len(steps), 1)
        self.assertIn(list(steps)[0], (20.0, 25.0, 50.0, 10.0))
        self.assertEqual(run("C.niceTicks(5, 5, 6)"), [5])

    def test_decimals_follow_the_price_scale(self):
        self.assertEqual(run("C.decimalsFor(0.0003)"), 6)           # SOL/BTC style (ticks every 0.00005)
        self.assertLessEqual(run("C.decimalsFor(160)"), 1)          # dollar prices
        self.assertGreaterEqual(run("C.decimalsFor(0.9)"), 2)       # yields

    def test_range_slicing(self):
        self.assertEqual(run("C.sliceRange([1,2,3,4,5], 'MAX')"), [1, 2, 3, 4, 5])
        self.assertEqual(len(run("C.sliceRange(Array.from({length:400},(_, i)=>i), '1Y')")), 260)
        self.assertEqual(len(run("C.sliceRange(Array.from({length:400},(_, i)=>i), '3M')")), 65)

    def test_number_format(self):
        self.assertEqual(run("C.fmt(111.406, 2)"), "111.41")
        self.assertEqual(run("C.fmt(81234.5, 0)"), "81,235")


if __name__ == "__main__":
    unittest.main()
