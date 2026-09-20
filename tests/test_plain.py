import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plain  # noqa: E402


class PlainTests(unittest.TestCase):
    def test_visible_text_is_rewritten(self):
        h = '<div>Key Resistance (30d high): $81,265</div><span>Accumulation | Markup | Distribution | Markdown</span>'
        out = plain.simplify(h)
        self.assertIn("Ceiling (30-day high): $81,265", out)
        self.assertIn("Buying increasing | Rising | Selling increasing | Falling", out)

    def test_tooltips_and_attributes_keep_the_technical_wording(self):
        h = '<span class="info-tip" data-tip="Accumulation = basing near lows; resistance and support">i</span><b title="Distribution">x</b>'
        self.assertEqual(plain.simplify(h), h)

    def test_numbers_and_markup_are_untouched(self):
        h = '<td class="pos">$80,335</td><td data-label="Wyckoff">+4.9%</td>'
        self.assertEqual(plain.simplify(h), h)

    def test_zone_labels_keep_their_emoji(self):
        self.assertIn("\U0001F7E2 BUYING INCREASING", plain.simplify("<span>\U0001F7E2 ACCUMULATION ZONE</span>"))

    def test_entity_phrase(self):
        self.assertIn("Crowd mood (Fear &amp; Greed)", plain.simplify("<td>Retail Mania (Fear &amp; Greed)</td>"))

    def test_empty(self):
        self.assertEqual(plain.simplify(""), "")
        self.assertEqual(plain.simplify(None), "")


if __name__ == "__main__":
    unittest.main()
