# Kairo Live Dashboard

A BTC/ETH market dashboard that regenerates itself automatically and publishes to GitHub Pages — free-tier data only, no paid APIs, no server to maintain.

**Live URL:** https://ichbinsakib.github.io/crypto-dashboard/

## What it shows

- Price, 24h/7d/30d change, 30-day support/resistance
- Funding rate, open interest trend, futures mark/index premium (Binance public API)
- Fear & Greed Index (Alternative.me), used as a retail-sentiment proxy
- A heuristic cycle-stage model (Accumulation / Markup / Distribution / Markdown) and a 1-10 "heat score", both derived from the numbers above — not a third-party analytics product
- **Spot Signal (educational):** a transparent, rule-based reading of whether current conditions resemble a historical spot accumulation or distribution zone. Combines proximity to key levels, Fear & Greed, cycle stage, price structure, extension from the 200-day average, and futures crowd positioning into a scored HOLD / ACCUMULATE / DISTRIBUTE-style label — every factor and its point contribution is shown, nothing is hidden. It is not backtested and not a trade instruction; see `compute_spot_signal()` in `dashboard.py` for the exact rules.
- **🔍 Screener tab:** runs the same rule-based model (minus the futures-crowd-positioning factor) across the top `SCREENER_SIZE` coins by market cap, ranks them best-to-worst, and highlights the coin currently closest to an accumulation zone and the one closest to a distribution zone. Not a recommendation to trade any coin listed — it's the same educational model applied at scale, and small/mid-caps carry far more risk than BTC/ETH. CoinGecko's free tier rate-limits per-coin chart calls hard, so a handful of coins may be missing from the ranking on any given run; that's expected, not a bug.
- Price alerts you define in `data/alerts_config.json`

Rows that need paid on-chain data (MVRV Z-Score, NUPL, exchange flows, ETF flows) are explicitly marked **Unavailable** rather than faked.

## How it runs

`.github/workflows/deploy.yml` runs `dashboard.py` on a schedule (best-effort every ~5 minutes — GitHub Actions doesn't support finer-grained cron), publishes `site/index.html` to GitHub Pages, and commits the updated `data/` folder back to the repo so state and alert history persist between runs.

## Editing alerts

Edit `data/alerts_config.json` directly (GitHub's web editor works fine) — each entry:

```json
{"id": "unique-id", "coin": "BTC", "condition": "above", "price": 85000, "label": "BTC above $85,000", "enabled": true}
```

Push the change (or edit via GitHub's UI, which commits for you) and it takes effect on the next scheduled run, or trigger **Actions → Update Kairo Dashboard → Run workflow** for an immediate refresh.

If you have this repo cloned locally, `python add_alert.py` opens a small desktop GUI for the same thing.

## Running locally

```
python dashboard.py
```

Writes to `site/index.html`, reading/writing state and alerts in `data/`.

## Education only

Not financial advice. The cycle model and heat score are Kairo's own heuristics, not guaranteed signals.

## Market Events (admin only)

An extra **Market Events** tab, visible only to admins (enforced by row-level security in Supabase, not just hidden in the page; it cannot be granted to ordinary users). It is independent of the trading signals and changes none of them.

- **Sources:** BLS release schedule and Federal Reserve FOMC calendar (official pages, identifying User-Agent, refreshed at most every 12-24h), BLS public API for released CPI / jobs numbers, Binance 1-minute candles for BTC/ETH reactions. **CME FedWatch has no permitted automated access, so probabilities are never scraped or estimated** - an admin can type in a snapshot; it is shown with its source and age.
- **Not invented:** consensus forecasts are not available from official sources, so surprises show `NO_FORECAST` until an admin enters one (audit-logged). Assessments are labelled Bullish/Bearish pressure, Neutral or High volatility with a confidence level and the evidence; they are readings of stored data, never price predictions. Historical statistics are hidden below 5 samples.
- **Freshness:** every source shows LIVE / RECENT / STALE / UNAVAILABLE / ERROR with its retrieval time; failures back off exponentially and stale data is never shown as current.
- **Config:** impact rules, surprise thresholds and notification toggles have defaults in `events/config.py` and can be edited by an admin in the tab (stored in `event_config`). Optional env: `FRED_API_KEY`, `BLS_API_KEY`, `EVENTS_USER_AGENT`, `EVENTS_REACTION_ASSETS`.
- **Code:** `events/` (parsers, providers, classification, engine, reactions, service), `static/events.js` (UI), `migrations/003_market_events.sql`.
- **Tests:** `python -m unittest discover -s tests -v`
