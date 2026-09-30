# Kairo Live Dashboard

A crypto market dashboard that regenerates itself automatically (GitHub Actions, ~every 10 minutes) and publishes to
Supabase, which a small login-gated shell on GitHub Pages reads from — free-tier data only, no paid APIs, no server
to maintain. Row-level security in Supabase decides which sections each signed-in user can see; some sections are
admin-only regardless of what's granted.

**Live URL:** https://ichbinsakib.github.io/crypto-dashboard/

## What it shows

- **BTC/ETH:** price, 24h/7d/30d change, SMA50/200, 30-day support/resistance, funding rate, open interest trend,
  futures mark/index premium. Binance's public spot/futures data is the primary source (fast, no rate limit issues);
  CoinGecko fills in only what Binance can't provide, and a stale-data banner shows exactly which figures fell back
  to a cached value on a given run.
- **Signals tab — Trend Breakout:** the one live signal-generation engine (`momentum.py`). Scans a rotating pool of
  top-market-cap coins for a 4-hour breakout above a 200-candle average, rides it with a trailing stop (no fixed
  target). Dip-buy signals and an earlier 15-minute/1-hour momentum rule were both retired for losing money in
  back-tests; their code and history are gone, not just switched off. An admin can pin specific coins in the
  **Watchlist** panel so they're checked every run regardless of the pool's random rotation — added after two real,
  rule-qualifying breakouts (QNT, MOVR) were confirmed missed purely because neither was ever scanned.
- **Performance tab:** the Trend Breakout engine's own win/loss record (daily/weekly/monthly), plus a Return % and
  a hypothetical "$50 bet on every call" figure to make the percentage concrete. Educational transparency, not a
  real account — see the info tooltip for the exact math (simple addition of each trade's own net %, not compounding).
- **🚀 Big Movers (admin, inside Market Events):** the biggest 24h gainers/losers across all liquid Binance USDT
  pairs (volume-floored to cut noise), not filtered to a market-cap list. Raw price action, not a signal — the card
  says so.
- **🎓 SCALPING (admin only):** a separate, faster engine (`scalping/`) watching SOL/LINK/XRP/ONDO on a 15m-trend /
  5m-entry basis with a 7-check setup score, full signal lifecycle (SETUP → ACTIVE → TP1/TP2/STOP/EXPIRED), and an
  escalating per-coin circuit breaker after a losing streak. Judged on its own record, separately from Trend Breakout.
- **Price alerts** you define in `data/alerts_config.json`.
- **Market Events (admin only):** see its own section below.

Rows that need paid data (MVRV Z-Score, NUPL, exchange flows, ETF flows, CME FedWatch probabilities) are explicitly
marked **Unavailable** rather than faked or estimated.

## How it runs

`.github/workflows/deploy.yml` runs `dashboard.py` on a schedule (best-effort every ~10 minutes — GitHub Actions
doesn't support finer-grained cron), which fetches fresh data, runs the Trend Breakout and scalping engines, renders
every tab's HTML, and publishes it all to Supabase (`publish_portions`). The GitHub Pages site is just the login
shell + client-side renderer (`static/app.js` and friends) reading from Supabase; nothing is regenerated client-side.
A local run without Supabase credentials configured falls back to writing `site/index.html` directly, for development.

## Editing alerts

With a Supabase backend configured (the deployed app), alerts live in the `price_alerts` table, not a file — an
admin signs in and clicks **Alerts** in the header to add, edit, enable/disable or delete one; changes apply on the
next scheduled run (`migrations/006_price_alerts.sql`, `admin_upsert_price_alert` / `admin_delete_price_alert`).

Running `dashboard.py` standalone (no `KAIRO_*` credentials) instead reads/writes `data/alerts_config.json` — each entry:

```json
{"id": "unique-id", "coin": "BTC", "condition": "above", "price": 85000, "label": "BTC above $85,000", "enabled": true}
```

Edit it directly (GitHub's web editor works fine) and trigger **Actions → Update Kairo Dashboard → Run workflow**,
or wait for the next scheduled run.

If you have this repo cloned locally, `python add_alert.py` opens a small desktop GUI for the same thing.

## Running locally

```
python dashboard.py
```

Without `KAIRO_*` Supabase credentials configured, this writes to `site/index.html` and reads/writes state and
alerts in `data/`, for local development. With credentials set, it publishes to Supabase like the scheduled job does.

## Education only

Not financial advice, not a signal service. Every engine here is judged openly on its own historical record (wins,
losses, and total P&L, including the failures) rather than presented as a track record to follow.

## Market Events (admin only)

An extra **Market Events** tab, visible only to admins (enforced by row-level security in Supabase, not just hidden
in the page; it cannot be granted to ordinary users). It is independent of the trading signals and changes none of them.

- **Sources:** BLS release schedule and Federal Reserve FOMC calendar (official pages, identifying User-Agent, refreshed at most every 12-24h), BLS public API for released CPI / jobs numbers, Binance 1-minute candles for BTC/ETH reactions, free RSS crypto headlines (CoinDesk, Cointelegraph). **CME FedWatch has no permitted automated access, so probabilities are never scraped or estimated** - an admin can type in a snapshot; it is shown with its source and age.
- **Not invented:** consensus forecasts are not available from official sources, so surprises show `NO_FORECAST` until an admin enters one (audit-logged). Assessments are labelled Bullish/Bearish pressure, Neutral or High volatility with a confidence level and the evidence; they are readings of stored data, never price predictions. Historical statistics are hidden below 5 samples.
- **Freshness:** every source shows LIVE / RECENT / STALE / UNAVAILABLE / ERROR with its retrieval time; failures back off exponentially and stale data is never shown as current.
- **Config:** impact rules, surprise thresholds and notification toggles have defaults in `events/config.py` and can be edited by an admin in the tab (stored in `event_config`). Optional env: `FRED_API_KEY`, `BLS_API_KEY`, `EVENTS_USER_AGENT`, `EVENTS_REACTION_ASSETS`.
- **Code:** `events/` (parsers, providers, classification, engine, reactions, movers, movers_radar, service), `static/events.js` (UI), `migrations/003_market_events.sql`.

## Tests

```
python -m unittest discover -s tests -v
```

`backtest/` holds standalone historical-replay scripts (`run.py`/`hold.py` for the trend engine, `fetch_scalp.py`/
`scalp_run.py` for the scalping engine) used to validate a rule change against real history before shipping it —
not part of the live app, and not run automatically.
