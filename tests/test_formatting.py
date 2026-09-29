"""Pure display-formatting helpers, extracted from dashboard.py. No network, no state."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import formatting as F  # noqa: E402


class FormattingTests(unittest.TestCase):
    def test_fmt_usd(self):
        self.assertEqual(F.fmt_usd(1234.5), "$1,234.50")
        self.assertEqual(F.fmt_usd(None), "N/A")

    def test_fmt_usd_adaptive_scales_decimals_for_sub_dollar_coins(self):
        self.assertEqual(F.fmt_usd_adaptive(81704.3), "$81,704.30")
        self.assertEqual(F.fmt_usd_adaptive(0.0901), "$0.0901")
        self.assertEqual(F.fmt_usd_adaptive(None), "N/A")

    def test_fmt_net_fee_html_shows_a_dollar_example_and_colors_the_sign(self):
        h = F.fmt_net_fee_html(1.5)
        self.assertIn("+1.50% net", h)
        self.assertIn("+$1.50 on $100", h)
        self.assertIn('class="pos"', h)
        self.assertEqual(F.fmt_net_fee_html(None), "")

    def test_fmt_duration_hours_humanizes(self):
        self.assertEqual(F.fmt_duration_hours(0.75), "45m")
        self.assertEqual(F.fmt_duration_hours(26.5), "1d 2h")

    def test_fmt_pct(self):
        self.assertEqual(F.fmt_pct(2.5), "+2.50%")
        self.assertEqual(F.fmt_pct(-1.2), "-1.20%")
        self.assertEqual(F.fmt_pct(None), "N/A")

    def test_badge_html_picks_an_icon_by_status(self):
        self.assertIn("↗", F.badge_html("bullish", "Up"))
        self.assertIn("bearish", F.badge_html("bearish", "Down"))

    def test_ps_safe_strips_quotes_for_powershell(self):
        self.assertEqual(F.ps_safe('He said "hi" `n'), "He said 'hi' 'n")


if __name__ == "__main__":
    unittest.main()
