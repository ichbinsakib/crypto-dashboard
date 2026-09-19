"""Crypto Dada course curriculum as data (condensed from the course notes the Teka agent uses), plus the rules
the app enforces or shows. `BACKTEST_NOTES` records what testing found so nobody wires an unproven rule into signals."""

CURRICULUM = [
  {
    "module": "Vol 1 — Money: Demand & Supply",
    "points": [
      "All price movement reduces to demand vs supply of money flowing into/out of an asset.",
      "Understand market cap vs price, circulating vs total vs max supply, inflationary vs deflationary tokenomics, and how new supply (unlocks, emissions, mining) pressures price.",
      "Liquidity drives markets: when money (stablecoin inflows, fiat on-ramps, global liquidity) enters crypto, prices rise; when it exits, everything bleeds regardless of \"good charts.\""
    ]
  },
  {
    "module": "Vol 2 — Fundamentals: How to Decipher",
    "points": [
      "Evaluate a project before its chart: team, use case, tokenomics, vesting/unlock schedule, backers/VCs, community, competitors, narrative fit.",
      "Red flags: anonymous teams with heavy insider allocation, low float / high FDV, copy-paste whitepapers, paid shill campaigns."
    ]
  },
  {
    "module": "Vol 2.1 — Fundamental & On-chain Data Analysis",
    "points": [
      "On-chain metrics: active addresses, exchange inflow/outflow (inflow = potential sell pressure, outflow = accumulation), whale wallet movements, stablecoin supply, MVRV, realized price, funding rates, open interest.",
      "Cross-check fundamentals with on-chain reality: is the \"adoption\" story visible on-chain or only in marketing?"
    ]
  },
  {
    "module": "Vol 2.2 — Fundamental Analysis: Cycles, Types, Methods",
    "points": [
      "Market cycles: accumulation → markup → distribution → markdown; Bitcoin halving cycle context; alt-season rotation (BTC → ETH → large caps → mid/low caps → memes).",
      "Match analysis method to the trade horizon: long-term investing leans on fundamentals + cycles; short-term trading leans on technicals + liquidity."
    ]
  },
  {
    "module": "Live Session — Order Book, On-chain Data, Chart Drawing, Wallets",
    "points": [
      "Order book reading: bid/ask walls, spoofing awareness, depth as short-term S/R.",
      "Wallet hygiene: custodial vs non-custodial, seed phrase safety, hardware wallets for holdings, exchange only for active trading capital."
    ]
  },
  {
    "module": "Vol 3 — Crypto Calendar, Screener & Earnings",
    "points": [
      "Use economic calendars (FOMC, CPI, rate decisions) and crypto calendars (unlocks, mainnet launches, ETF dates) — volatility clusters around events; avoid opening leveraged positions right before major news.",
      "Screeners: filter coins by volume spikes, % change, market-cap tier to build a watchlist instead of chasing Twitter calls."
    ]
  },
  {
    "module": "Vol 4 — Fair Value Gap (FVG)",
    "points": [
      "FVG = 3-candle imbalance where candle 1's high/low doesn't overlap candle 3, leaving an unfilled gap in the middle candle.",
      "Price tends to return to fill FVGs — treat them as magnets and entry zones: bullish FVG below price = potential long entry on retest; bearish FVG above = potential short/take-profit zone.",
      "Higher-timeframe FVGs carry more weight; confluence with S/R or Fibonacci strengthens the setup."
    ]
  },
  {
    "module": "Vol 5 — Leverage / Futures Trading (A-Z)",
    "points": [
      "Mechanics: long/short, isolated vs cross margin, leverage multiplier, liquidation price, funding rates, mark vs last price.",
      "Course rules: low leverage for beginners (2–5x max), ALWAYS set a stop loss before entry, position size so that a stopped-out trade costs only 1–2% of the account, never add margin to save a losing trade emotionally.",
      "Liquidation is capital destruction — risk is defined by position size + stop distance, not by leverage number alone."
    ]
  },
  {
    "module": "Vol 5.1 — Investing vs Trading + 2 Strategies",
    "points": [
      "Separate portfolios and mindsets: investing = fundamentals-driven, cycle-based, DCA accumulation in bear markets, selling into euphoria; trading = shorter horizon, technical, strict invalidation.",
      "Never let a losing trade \"become an investment.\""
    ]
  },
  {
    "module": "Vol 5.2 — Spot Trading, Investing & Profit Taking",
    "points": [
      "Profit-taking plans: laddered selling at predefined targets (e.g., sell in tranches at Fib extensions / prior highs), keep a moonbag if thesis intact, convert profits to stables — unrealized profit is not profit."
    ]
  },
  {
    "module": "Vol 7.1 — Patterns: How to Draw, Conditions & Trade Setup",
    "points": [
      "A pattern is only tradable with: (1) correct drawing across multiple touches, (2) context (trend, volume), (3) a defined trigger (breakout/retest), (4) target (measured move), (5) invalidation (stop).",
      "Triangles, wedges, head & shoulders, double tops/bottoms — always wait for confirmation (candle close beyond level, ideally with volume), don't front-run."
    ]
  },
  {
    "module": "Vol 7.2 — Support & Resistance, Momentum & EMA Cross",
    "points": [
      "Draw S/R as zones, not lines, from swing highs/lows and high-volume areas; flipped levels (support→resistance and vice versa) are key retest entries.",
      "EMA framework: 20/50/100/200 EMAs; golden cross / death cross; price above rising 200 EMA = bull bias, below = bear bias; EMAs act as dynamic S/R in trends."
    ]
  },
  {
    "module": "Vol 7.3 — Volume Profile",
    "points": [
      "Volume profile shows traded volume by price level: POC (point of control), high-volume nodes (acceptance / S-R), low-volume nodes (price moves fast through them).",
      "Use HVNs as targets/reaction zones and LVNs as breakout corridors."
    ]
  },
  {
    "module": "Vol 7.4 — Highs & Lows, Channels, Bull & Bear Flags",
    "points": [
      "Trend structure: higher highs + higher lows = uptrend; lower highs + lower lows = downtrend; a break of structure signals possible reversal.",
      "Channels: trade bounces within, breakout with volume for continuation.",
      "Flags: sharp impulse (pole) + counter-trend consolidation (flag) → continuation; target ≈ pole length projected from breakout."
    ]
  },
  {
    "module": "Vol 7.5 — Parabolic Curve & God Candle",
    "points": [
      "Parabolic advances (steepening curve, each base shorter) end violently — never short a parabola early, never FOMO-buy the final vertical leg; take profits in tranches as the curve steepens.",
      "\"God candles\" (massive single candles) usually mark exhaustion or news shocks — wait for the next candles to confirm direction."
    ]
  },
  {
    "module": "Vol 7.6 — DCA in Futures: Fibonacci & Liquidity",
    "points": [
      "Planned (not emotional) DCA entries: pre-split the entry across Fib retracement levels (0.5, 0.618, 0.786) and liquidity zones (below equal lows / above equal highs where stop hunts occur), with one hard invalidation stop for the whole position.",
      "Liquidity concept: price seeks resting liquidity (clusters of stops); sweeps of obvious highs/lows before reversal are normal — plan entries after the sweep, not before."
    ]
  },
  {
    "module": "Vol 7.7 — Megaphone Pattern",
    "points": [
      "Broadening structure (higher highs + lower lows, diverging trendlines) = volatility expansion / indecision.",
      "Trade the boundaries with confirmation; targets at opposite trendline; invalidation just beyond the swept extreme. Fakeouts are common — size down."
    ]
  },
  {
    "module": "Vol 8.1 — Harmonics: Three Drive Pattern",
    "points": [
      "Three symmetrical, consecutive drives to a high/low, each ending at Fib extensions (typically 1.272/1.618 of the prior pullback), pullbacks retracing ~0.618–0.786.",
      "Completion of drive 3 = reversal zone: enter counter-trend with stop beyond the pattern extreme, targets at retracements of the whole structure."
    ]
  },
  {
    "module": "Vol 9.1 — Fibonacci Strategy: Sequence, Retracement & Extensions",
    "points": [
      "Draw retracements swing-low→swing-high (uptrend) for pullback entries: 0.382 shallow, 0.5–0.618 golden zone, 0.786 deep.",
      "Extensions (1.272, 1.618, 2.618) for profit targets beyond prior highs. Fib levels work best in confluence with S/R, FVGs, and EMAs — a Fib level alone is not a trade."
    ]
  },
  {
    "module": "Vol 10.1 — Pump & Dump Cycles: New, Low-cap & Memecoins",
    "points": [
      "Anatomy: insider accumulation → ignition pump → social-media hype → distribution to retail → dump. Recognize which phase you're seeing.",
      "Rules for memecoins/new listings: only money you can lose entirely, take initial capital out fast (play with house money), watch holder distribution and LP locks, assume every low-cap can go to zero, never marry a memecoin."
    ]
  }
]
