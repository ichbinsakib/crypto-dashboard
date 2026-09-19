"""Wyckoff distribution detector on synthetic schematics. Run: python -m unittest discover -s tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from brain import wyckoff as W  # noqa: E402


def k(o, h, l, c, v=100):
    return [0, o, h, l, c, v]


def advance(n=50, start=100.0, step=2.0):
    out, p = [], start
    for _ in range(n):
        out.append(k(p, p + step + 1, p - 1, p + step, 100))
        p += step
    return out


def climax_and_reaction():
    c = advance()                                            # 100 -> 200
    c.append(k(200, 215, 199, 205, 400))                     # buying climax: new high on heavy volume
    for lo in (195, 188, 180, 172, 170):                     # automatic reaction sets the floor at 170
        c.append(k(lo + 6, lo + 8, lo - 1 if lo > 170 else 170, lo + 2, 150))
    return c


def range_bars(n=20):
    out = []
    for i in range(n):
        base = 178 + (i % 5) * 6                             # oscillate 178..202 inside the box
        out.append(k(base, base + 3, base - 3, base + 1, 90))
    out.append(k(205, 209, 203, 207, 80))                    # secondary test of the highs on lower volume
    out.append(k(204, 210, 202, 206, 80))
    return out


class WyckoffTests(unittest.TestCase):
    def test_range_after_climax(self):
        d = W.detect_distribution(climax_and_reaction() + range_bars())
        self.assertEqual(d["stage"], "range", d)
        self.assertEqual(d["levels"]["bc_high"], 215)
        self.assertEqual(d["levels"]["range_low"], 170)
        self.assertTrue(any("Climactic volume" in e for e in d["evidence"]))
        self.assertTrue(any("secondary tests" in e for e in d["evidence"]))
        self.assertEqual(d["score"], -1)

    def test_upthrust_after_distribution(self):
        c = climax_and_reaction() + range_bars() + [k(208, 220, 205, 211, 320), k(210, 212, 204, 206, 120)]
        d = W.detect_distribution(c)
        self.assertEqual(d["stage"], "utad", d)
        self.assertTrue(any("bull trap" in e for e in d["evidence"]))
        self.assertEqual(d["score"], -2)

    def test_sign_of_weakness_then_markdown(self):
        base = climax_and_reaction() + range_bars()
        sow = base + [k(200, 201, 160, 164, 350), k(164, 166, 155, 158, 260)]
        d = W.detect_distribution(sow)
        self.assertEqual(d["stage"], "sow", d)
        self.assertTrue(any("heavy volume" in e for e in d["evidence"]))
        later = sow + [k(158 - i, 159 - i, 150 - i, 152 - i, 200) for i in range(15)]
        self.assertEqual(W.detect_distribution(later)["stage"], "markdown")

    def test_last_point_of_supply(self):
        base = climax_and_reaction() + range_bars()
        c = base + [k(200, 201, 160, 164, 350), k(164, 168, 160, 166, 120), k(166, 170, 163, 168, 90)]
        d = W.detect_distribution(c)
        self.assertEqual(d["stage"], "lpsy", d)

    def test_no_structure_cases(self):
        self.assertEqual(W.detect_distribution(advance(80))["stage"], "none")           # pure uptrend, no climax/reaction
        flat = [k(100, 101, 99, 100, 100) for _ in range(80)]
        self.assertEqual(W.detect_distribution(flat)["stage"], "none")                  # no prior advance
        self.assertEqual(W.detect_distribution(advance(10))["stage"], "none")           # too short

    def test_breakout_above_is_not_distribution(self):
        c = climax_and_reaction() + range_bars() + [k(210 + 4 * i, 214 + 4 * i, 208 + 4 * i, 213 + 4 * i, 200) for i in range(14)]
        self.assertEqual(W.detect_distribution(c)["stage"], "none")

    def test_spot_factor_points_and_weight(self):
        rng = W.detect_distribution(climax_and_reaction() + range_bars())
        self.assertEqual(W.spot_factor(rng)[0], -1)
        self.assertEqual(W.spot_factor(rng, weight=0)[0], 0)
        self.assertEqual(W.spot_factor({"stage": "none", "score": 0, "evidence": [], "confidence": "LOW"})[0], 0)
        self.assertEqual(W.spot_factor(None)[0], 0)
        low_late = {"stage": "sow", "score": -2, "evidence": ["x"], "confidence": "LOW"}
        self.assertEqual(W.spot_factor(low_late)[0], -1)                                # thin evidence: mild lean only
        self.assertEqual(W.spot_factor({"stage": "sow", "score": -2, "evidence": ["x"], "confidence": "HIGH"})[0], -2)
        self.assertEqual(W.spot_factor({"stage": "markdown", "score": 0, "evidence": ["x"], "confidence": "HIGH"})[0], 0)

    def test_schematic_documented(self):
        self.assertEqual([p["phase"] for p in W.SCHEMATIC], list("ABCDE"))


if __name__ == "__main__":
    unittest.main()


class BreakoutInvalidationTests(unittest.TestCase):
    def test_close_above_climax_high_cancels_the_read(self):
        c = climax_and_reaction() + range_bars() + [k(208, 220, 205, 211, 320), k(211, 224, 210, 222, 300)]
        self.assertEqual(W.detect_distribution(c)["stage"], "none")             # UT then a close above 215 = breakout, not a trap

    def test_reading_text(self):
        d = W.detect_distribution(climax_and_reaction() + range_bars())
        txt = W.spot_factor(d)[1]
        self.assertIn("Phase A/B", txt)
        self.assertIn("215", txt)
