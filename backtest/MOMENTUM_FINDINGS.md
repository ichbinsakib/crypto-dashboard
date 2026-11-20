# Weekly cross-sectional momentum backtest (2020-06 .. 2026-11, 75 coins incl. delisted, daily bars)
Rules: top-20 coins by 30d dollar volume, rank by 14-28d return (or return/vol), hold top K equal-weight long-only,
weekly rebalance at next open, 0.15%/side cost, cash when BTC is below its 100/200-day average. Train 2020-06..2023-06, test 2023-06..2026-11.

| Strategy (test period)        | Sharpe | CAGR | Max drawdown |
|-------------------------------|-------:|-----:|-------------:|
| BTC buy & hold                | 0.68   | 23%  | -53%         |
| BTC only above 200d average   | 0.72   | 22%  | -32%         |
| BTC only above 100d average   | 0.87   | 26%  | -37%         |
| Momentum L14 K5 (best-looking)| 1.01   | 55%  | -61%         |
| Average of all 96 momentum settings | 0.55 | 15% | -64%     |

* Train Sharpe 1.2-1.8 fell to ~0.55 out of sample on average (over-fit); only 22/96 settings beat BTC>200d in test.
* Momentum beat BTC in 2021 (+591%), 2025, 2026; lost to it in 2020, 2023, 2024. Edge is concentrated in one bull year.
* Excess return vs "BTC above 100d" is not statistically significant (t=1.5 test, 2.0 all; bootstrap CI includes 0).
* Drawdowns of -55% to -75% in every variant, even with the BTC filter, daily exits, or 14-day rebalancing.
Files: momentum_weekly.py (engine + grid), momentum_robust.py (stress tests), momentum_results.json, fetch_daily.py (data).
