/* SCALPING dashboard (admin only). Shows what the server-side scalping engine decided; it does not analyse anything itself.
 *
 * The engine (scalping/ + scalping_job.py, run on a 5-minute schedule) owns every signal and its whole lifecycle. This page
 * renders that payload, refreshes prices live from Binance's public API, and lets the admin change settings or request a manual
 * close through admin-only database functions. Anything the engine could not compute is shown as n/a, never estimated.
 * Setup Score is a documented 0-10 rule score, not a probability. Analysis, not advice. */
(function () {
  'use strict';

  /* ---------------- pure helpers (exported for node tests) ---------------- */
  function fmtPrice(v) {
    if (v == null || isNaN(v)) return 'n/a';
    var d = v >= 100 ? 2 : v >= 10 ? 3 : v >= 1 ? 4 : 5;
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function mean(a) { return a.length ? a.reduce(function (s, x) { return s + x; }, 0) / a.length : null; }
  function sum(a) { return a.reduce(function (s, x) { return s + x; }, 0); }
  function isTrade(r) { return r.actual_entry != null && r.exit_time; }

  /* rows: signals (finished and open). filters: {coin, side, from, to, tf, regime, type} ('' = any). */
  function applyFilters(rows, f) {
    f = f || {};
    return rows.filter(function (r) {
      if (f.coin && r.coin !== f.coin) return false;
      if (f.side && r.direction !== f.side) return false;
      if (f.tf && (r.timeframe + '/' + r.htf) !== f.tf) return false;
      if (f.regime && r.regime !== f.regime) return false;
      if (f.type && r.setup_type !== f.type) return false;
      var t = Date.parse(r.created_at);
      if (f.from && t < Date.parse(f.from + 'T00:00:00')) return false;
      if (f.to && t > Date.parse(f.to + 'T23:59:59')) return false;
      return true;
    });
  }

  function perfStats(rows) {
    var trades = rows.filter(isTrade).sort(function (a, b) { return Date.parse(a.exit_time) - Date.parse(b.exit_time); });
    var wins = trades.filter(function (r) { return r.pnl_pct > 0; }), losses = trades.filter(function (r) { return r.pnl_pct <= 0; });
    var gw = sum(wins.map(function (r) { return r.pnl_pct; })), gl = -sum(losses.map(function (r) { return r.pnl_pct; }));
    var eq = 0, peak = 0, dd = 0;
    trades.forEach(function (r) { eq += r.pnl_pct; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); });
    return {
      total: rows.length, triggered: rows.filter(function (r) { return r.actual_entry != null; }).length, completed: trades.length,
      wins: wins.length, losses: losses.length, winRate: trades.length ? wins.length / trades.length * 100 : null,
      avgR: mean(trades.map(function (r) { return r.r_multiple; }).filter(function (x) { return x != null; })),
      avgProfit: mean(wins.map(function (r) { return r.pnl_pct; })), avgLoss: mean(losses.map(function (r) { return r.pnl_pct; })),
      totalPnl: trades.length ? sum(trades.map(function (r) { return r.pnl_pct; })) : null,
      profitFactor: gl > 0 ? gw / gl : (gw > 0 ? Infinity : null), maxDrawdown: trades.length ? dd : null,
      avgDuration: mean(trades.map(function (r) { return r.duration_min; }).filter(function (x) { return x != null; }))
    };
  }

  /* live P&L of an open trade in % after fees; a partial exit at target 1 is counted the same way the engine does */
  function openPnl(r, price, cfg) {
    if (r.actual_entry == null || price == null) return null;
    var s = r.direction === 'LONG' ? 1 : -1, e = r.actual_entry, g = (price - e) / e * 100 * s;
    if (r.tp1_time) { var frac = cfg.partial_tp1_pct / 100, g1 = (r.tp1 - e) / e * 100 * s; g = frac * g1 + (1 - frac) * g; }
    return g - cfg.fee_pct;
  }

  /* what an open signal is doing right now, in plain words, from its levels and the live price */
  function tradeStatus(r, price) {
    if (r.manual_close_requested) return 'CLOSE REQUESTED';
    var s = r.direction === 'LONG' ? 1 : -1;
    if (r.actual_entry == null) {
      if (price == null) return 'WAITING FOR ENTRY';
      return (price >= r.entry_low && price <= r.entry_high) ? 'IN ENTRY ZONE' : 'WAITING FOR ENTRY';
    }
    if (price == null) return r.tp1_time ? 'TP1 HIT' : 'ACTIVE';
    var e = r.actual_entry;
    if (!r.tp1_time) {
      if ((price - e) * s > 0 && (r.tp1 - price) * s / ((r.tp1 - e) * s) <= 0.25) return 'TP1 APPROACHING';
      if ((price - e) * s < 0 && (price - r.stop) * s / ((e - r.stop) * s) <= 0.25) return 'NEAR STOP';
      return 'ACTIVE';
    }
    if ((r.tp2 - price) * s / ((r.tp2 - e) * s) <= 0.25) return 'TP2 APPROACHING';
    return 'TP1 HIT';
  }

  /* LIVE / DELAYED / STALE / DISCONNECTED from the engine's own report, how old its analysis is, and whether prices still arrive */
  function dataStatus(serverStatus, analysisAgeMin, liveOk, liveEverOk) {
    if (serverStatus === 'STALE' || serverStatus === 'DISCONNECTED') return serverStatus;
    if (analysisAgeMin != null && analysisAgeMin > 30) return 'STALE';
    if (!liveOk) return liveEverOk ? 'DELAYED' : 'DISCONNECTED';
    if (serverStatus === 'DELAYED' || (analysisAgeMin != null && analysisAgeMin > 12)) return 'DELAYED';
    return 'LIVE';
  }

  function sortRows(rows, col, dir) {
    var key = { coin: 'coin', side: 'direction', entry: 'actual_entry', exit: 'exit_time', result: 'state', pnl: 'pnl_pct', duration: 'duration_min', score: 'setup_score' }[col] || 'exit_time';
    return rows.slice().sort(function (a, b) {
      var x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }

  function resultLabel(r) {
    if (r.exit_reason === 'tp2') return 'TP2';
    if (r.exit_reason === 'tp1_then_breakeven') return 'TP1';
    return { STOP_LOSS: 'SL', EXPIRED: 'EXPIRED', INVALIDATED: 'INVALID', CLOSED: 'CLOSED', TP2_HIT: 'TP2', TP1_HIT: 'TP1' }[r.state] || r.state;
  }

  /* volume-weighted average price for the current UTC day (VWAP); null until the day has enough candles */
  function sessionVwap(kl) {
    if (!kl || !kl.length) return null;
    var d = new Date(+kl[kl.length - 1][0]), m = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    var pv = 0, v = 0, n = 0;
    kl.forEach(function (k) { if (+k[0] >= m) { var vol = +k[5]; pv += (+k[2] + +k[3] + +k[4]) / 3 * vol; v += vol; n += 1; } });
    return n >= 3 && v > 0 ? pv / v : null;
  }

  var api = { sessionVwap: sessionVwap, fmtPrice: fmtPrice, applyFilters: applyFilters, perfStats: perfStats, openPnl: openPnl, tradeStatus: tradeStatus, dataStatus: dataStatus, sortRows: sortRows, resultLabel: resultLabel };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  /* ---------------- UI ---------------- */
  var ST = { data: null, ctx: null, prices: {}, priceTs: 0, everOk: false, fails: 0, filters: {}, sort: { col: 'exit', dir: -1 }, showN: 12, msg: '', draft: null, dirty: false, open: {}, timer: null, tick: null, busy: false, lastStatus: null, iv: '5m', kl: {}, klBusy: false, n: 0 };
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function root() { return document.getElementById('scalping-root'); }
  function pct(v, d) { return v == null || isNaN(v) ? 'n/a' : (v >= 0 ? '+' : '') + v.toFixed(d == null ? 2 : d) + '%'; }
  function cls(v) { return v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : ''; }
  function ago(iso) {
    var s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    return s < 90 ? Math.round(s) + ' sec ago' : s < 5400 ? Math.round(s / 60) + ' min ago' : Math.round(s / 3600) + ' h ago';
  }
  function mins(m) { return m == null ? 'n/a' : m < 60 ? Math.round(m) + 'm' : Math.floor(m / 60) + 'h ' + Math.round(m % 60) + 'm'; }
  function hhmm(iso) { var d = new Date(iso); return isNaN(d) ? 'n/a' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }); }
  function dt(iso) { var d = new Date(iso); return isNaN(d) ? 'n/a' : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }); }
  function livePrice(sym, fallback) { return ST.prices[sym] != null ? ST.prices[sym] : fallback; }
  function analysisAge() { return ST.data ? (Date.now() - Date.parse(ST.data.generated_at)) / 60000 : null; }
  function status() {
    var trying = !ST.priceTs && ST.fails === 0;             // first price request still in flight: do not cry "disconnected" yet
    var liveOk = trying || (ST.priceTs && (Date.now() - ST.priceTs) < 30000);
    return dataStatus(ST.data.market.data, analysisAge(), liveOk, ST.everOk || trying);
  }

  function header() {
    var m = ST.data.market, ds = status(), paused = m.state === 'PAUSED' || ds === 'STALE' || ds === 'DISCONNECTED';
    var mstate = paused ? 'PAUSED' : m.state;
    var regime = m.regime, last = ST.priceTs ? Math.round((Date.now() - ST.priceTs) / 1000) + ' sec ago' : 'n/a';
    var h = '<div class="sc2-head"><div class="sc2-title">⚡ SCALPING</div><div class="sc2-meta">' +
      '<span>Market <b class="sc2-m-' + mstate.toLowerCase() + '">' + esc(mstate) + '</b></span>' +
      '<span>Regime <b>' + esc(regime) + '</b></span>' +
      '<span>Data <b class="sc2-d-' + ds.toLowerCase() + '">' + ds + '</b></span>' +
      '<span>Last update <b id="sc-last">' + esc(last) + '</b></span>' +
      '<span>Active setups <b>' + m.active_setups + ' / ' + m.monitored + '</b></span></div>';
    if (paused) {
      h += '<div class="sc2-warn sc2-warn-red"><b>⚠ MARKET DATA ' + esc(ds === 'DISCONNECTED' ? 'DISCONNECTED' : 'STALE') + '</b><br>New signals temporarily disabled. ' +
        'Last analysis: ' + (ST.data.generated_at ? esc(ago(ST.data.generated_at)) : 'n/a') + '.</div>';
    } else if (m.restricted) {
      h += '<div class="sc2-warn"><b>' + esc(regime) + '</b><br>New scalps temporarily restricted.</div>';
    } else if (ds === 'DELAYED') {
      h += '<div class="sc2-warn"><b>Data delayed</b><br>Last analysis: ' + esc(ago(ST.data.generated_at)) + '. Treat the levels with extra care.</div>';
    }
    return h + '</div>';
  }

  function answer() {
    var d = ST.data, act = d.active.length, m = d.market;
    if (m.state === 'PAUSED' || status() === 'STALE' || status() === 'DISCONNECTED') return '';
    if (act) return '<div class="sc2-answer sc2-a-yes">' + act + ' ACTIVE SCALP' + (act > 1 ? 'S' : '') + '</div>';
    return '<div class="sc2-answer sc2-a-no">NO VALID SCALP SETUP<span>' + (m.restricted ? 'The market is too rough right now.' : 'KAIRO shows a signal only when every required check passes.') + '</span></div>';
  }

  /* distance from entry as a signed % (what you would type into a Binance order), e.g. stop -0.62%, target +0.94% */
  function away(r, v) {
    var b = r.actual_entry != null ? r.actual_entry : (r.entry_low + r.entry_high) / 2;
    return v == null || !b ? '' : ' <small>' + pct((v - b) / b * 100) + '</small>';
  }
  function levelsGrid(r, price) {
    var wait = r.actual_entry == null;
    return '<div class="sc2-lv">' +
      '<div><span>' + (wait ? 'Entry zone' : 'Entry') + '</span><b>' + (wait ? fmtPrice(r.entry_low) + ' – ' + fmtPrice(r.entry_high) : fmtPrice(r.actual_entry)) + '</b></div>' +
      '<div><span>Stop loss</span><b class="neg">' + fmtPrice(r.stop) + away(r, r.stop) + '</b></div>' +
      '<div><span>TP1</span><b class="pos">' + fmtPrice(r.tp1) + away(r, r.tp1) + '</b></div><div><span>TP2</span><b class="pos">' + fmtPrice(r.tp2) + away(r, r.tp2) + '</b></div>' +
      '<div><span>Risk / Reward</span><b>1 : ' + (r.rr != null ? r.rr.toFixed(1) : 'n/a') + '</b></div>' + '</div>';
  }

  function activeBlock() {
    var rows = ST.data.active;
    if (!rows.length) return '';
    var cfg = ST.data.config, h = '<div class="sc2-sec">ACTIVE SCALPS</div>';
    rows.forEach(function (r) {
      var px = livePrice(r.coin, r.last_price), s = tradeStatus(r, px), pnl = openPnl(r, px, cfg);
      var since = r.actual_entry != null ? r.entry_time : r.created_at;
      h += '<div class="sc2-card sc2-active sc2-s-' + (r.direction === 'LONG' ? 'long' : 'short') + '" data-id="' + esc(r.id) + '">' +
        '<div class="sc2-card-h"><b>' + esc(r.coin) + ' ' + esc(r.direction) + '</b><span class="badge ' + (r.actual_entry != null ? 'bullish' : 'neutral') + '" data-st="' + esc(r.id) + '">' + esc(s) + '</span></div>' +
        '<div class="sc2-now"><span>Current</span><b data-px="' + esc(r.coin) + '">' + fmtPrice(px) + '</b>' +
        (r.actual_entry != null ? '<span>P&amp;L</span><b class="' + cls(pnl) + '" data-pnl="' + esc(r.id) + '">' + pct(pnl) + '</b>' : '') + '</div>' +
        chartWrap(r.coin, r.id) + levelsGrid(r, px) +
        '<div class="sc2-sub">Setup Score ' + (r.setup_score != null ? r.setup_score.toFixed(1) : 'n/a') + ' / 10 · ' + esc(r.setup_type) + ' · ' +
        (r.actual_entry != null ? 'in trade ' + esc(mins(Math.max(0, (Date.now() - Date.parse(r.entry_time)) / 60000))) : 'created ' + esc(hhmm(r.created_at)) + ' · expires ' + esc(hhmm(r.expires_at))) + '</div>' +
        (ST.ctx && ST.ctx.isAdmin && !r.manual_close_requested ? '<button type="button" class="sc2-btn" data-close="' + esc(r.id) + '">Close manually</button>' : '') +
        '<details class="fold"' + (ST.open['t' + r.id] ? ' open' : '') + ' data-key="t' + esc(r.id) + '"><summary>Timeline</summary><ul class="sc2-tl">' +
        (r.timeline || []).map(function (t) { return '<li><span>' + esc(hhmm(t.ts)) + '</span>' + esc(t.note) + '</li>'; }).join('') + '</ul></details></div>';
    });
    return h;
  }

  var STATE_CLASS = { 'LONG SETUP': 'bullish', 'SHORT SETUP': 'bearish', 'ENTRY TRIGGERED': 'bullish', 'ACTIVE TRADE': 'bullish', 'TP1 HIT': 'bullish', 'TP2 HIT': 'bullish', 'WATCH': 'neutral',
    'STOP LOSS HIT': 'bearish', 'EXPIRED': 'neutral', 'INVALIDATED': 'neutral', 'CLOSED': 'neutral', 'NO SETUP': 'locked', 'NO DATA': 'locked' };

  function coinCards() {
    var order = { 'ENTRY TRIGGERED': 0, 'ACTIVE TRADE': 0, 'TP1 HIT': 0, 'LONG SETUP': 1, 'SHORT SETUP': 1, 'WATCH': 2 };
    var coins = ST.data.coins.slice().sort(function (a, b) { return (order[a.state] != null ? order[a.state] : 5) - (order[b.state] != null ? order[b.state] : 5); });
    var h = '<div class="sc2-sec">COINS</div><div class="sc2-grid">';
    coins.forEach(function (c) {
      var px = livePrice(c.symbol, c.price), open = ST.data.active.filter(function (r) { return r.id === c.signal_id; })[0];
      var rec = !open && c.signal_id ? ST.data.recent.filter(function (r) { return r.id === c.signal_id; })[0] : null;
      h += '<div class="sc2-card sc2-coin"><div class="sc2-card-h"><span><b>' + esc(c.symbol) + '</b><span class="watch">/USDT</span></span>' +
        '<b class="sc2-px" data-px="' + esc(c.symbol) + '">$' + fmtPrice(px) + '</b></div>' +
        '<div class="sc2-row"><span>Trend <b class="sc2-t-' + esc(c.trend.toLowerCase()) + '">' + esc(c.trend.charAt(0) + c.trend.slice(1).toLowerCase()) + '</b></span>' +
        '<span>Regime <b>' + esc(c.regime || 'n/a') + '</b></span></div>' +
        '<div class="sc2-state"><span class="badge ' + (STATE_CLASS[c.state] || 'locked') + '">' + esc(c.state) + '</span>' +
        (c.score != null && c.checks.length ? '<span class="sc2-score">Setup Score ' + c.score.toFixed(1) + ' / 10</span>' : '') + '</div>';
      h += chartWrap(c.symbol, c.signal_id);
      if (open) {
        h += '<div class="sc2-sub">Active scalp above ↑</div>';
      } else if (rec) {
        h += levelsGrid(rec, px) + '<div class="sc2-sub">' + (rec.pnl_pct != null ? 'Result ' + esc(pct(rec.pnl_pct)) + ' · ' : '') + esc((rec.timeline && rec.timeline.length ? rec.timeline[rec.timeline.length - 1].note : '')) + '</div>';
      } else {
        h += '<div class="sc2-why"><b>' + (c.state === 'NO SETUP' || c.state === 'WATCH' || c.state === 'NO DATA' ? (c.state === 'WATCH' ? 'WATCHING' : c.state === 'NO DATA' ? 'NO DATA' : 'NO VALID SETUP') : '') + '</b> ' +
          '<span>' + esc(c.reason || '') + '</span></div>';
      }
      if (c.checks && c.checks.length) {
        h += '<details class="fold" data-key="c' + esc(c.symbol) + '"' + (ST.open['c' + c.symbol] ? ' open' : '') + '><summary>Why?</summary><ul class="sc2-checks">' +
          c.checks.map(function (k) {
            return '<li class="sc2-' + esc(k.state) + '"><span class="sc2-mark">' + (k.state === 'pass' ? '✓' : k.state === 'fail' ? '✕' : '?') + '</span><b>' + esc(k.label) + '</b><span>' + esc(k.text) + '</span></li>';
          }).join('') + '</ul><div class="sub">Setup Score is a rule score out of 10, not a probability. Trend, Entry trigger, Volatility (fees) and Risk/Reward must all pass.</div></details>';
      }
      h += '</div>';
    });
    return h + '</div>';
  }

  function perfBlock() {
    var all = ST.data.history.concat(ST.data.active), f = ST.filters;
    function uniq(k) { var s = {}; all.forEach(function (r) { if (r[k]) s[r[k]] = 1; }); return Object.keys(s).sort(); }
    var tfs = {}; all.forEach(function (r) { tfs[r.timeframe + '/' + r.htf] = 1; });
    function sel(id, label, opts) {
      return '<label class="sc2-f">' + label + '<select data-f="' + id + '"><option value="">All</option>' + opts.map(function (o) { return '<option' + (f[id] === o ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select></label>';
    }
    var st = perfStats(applyFilters(all, f));
    function cell(l, v, c) { return '<div class="sc2-stat"><span>' + l + '</span><b class="' + (c || '') + '">' + v + '</b></div>'; }
    var h = '<div class="sc2-sec">SCALPING PERFORMANCE</div>' +
      '<details class="fold" data-key="filters"' + (ST.open.filters ? ' open' : '') + '><summary>Filters' + (Object.keys(f).some(function (k) { return f[k]; }) ? ' (on)' : '') + '</summary><div class="sc2-filters">' +
      sel('coin', 'Coin', uniq('coin')) + sel('side', 'Side', ['LONG', 'SHORT']) + sel('tf', 'Timeframe', Object.keys(tfs).sort()) + sel('regime', 'Regime', uniq('regime')) + sel('type', 'Setup type', uniq('setup_type')) +
      '<label class="sc2-f">From<input type="date" data-f="from" value="' + esc(f.from || '') + '"></label><label class="sc2-f">To<input type="date" data-f="to" value="' + esc(f.to || '') + '"></label>' +
      '<button type="button" class="sc2-btn" data-clear="1">Clear</button></div></details>';
    if (!st.total) return h + '<div class="sc2-empty">No signals recorded yet. Every signal is saved here, including the ones that lose.</div>';
    h += '<div class="sc2-stats">' + cell('Total setups', st.total) + cell('Triggered', st.triggered) + cell('Completed', st.completed) + cell('Winners', st.wins, 'pos') + cell('Losers', st.losses, 'neg') +
      cell('Win rate', st.winRate == null ? 'n/a' : st.winRate.toFixed(0) + '%') + cell('Avg R:R (result)', st.avgR == null ? 'n/a' : st.avgR.toFixed(2) + ' R') +
      cell('Avg profit', pct(st.avgProfit), 'pos') + cell('Avg loss', pct(st.avgLoss), 'neg') + cell('Total P&amp;L', pct(st.totalPnl), cls(st.totalPnl)) +
      cell('Profit factor', st.profitFactor == null ? 'n/a' : st.profitFactor === Infinity ? '∞' : st.profitFactor.toFixed(2)) +
      cell('Max drawdown', st.maxDrawdown == null ? 'n/a' : '-' + st.maxDrawdown.toFixed(2) + '%', 'neg') + cell('Avg duration', mins(st.avgDuration)) + '</div>' +
      (st.completed < 30 ? '<div class="sub">Only ' + st.completed + ' completed trade' + (st.completed === 1 ? '' : 's') + ': too few to say whether this works.</div>' : '');
    return h;
  }

  function recentBlock() {
    var rows = applyFilters(ST.data.history, ST.filters);
    rows = sortRows(rows, ST.sort.col, ST.sort.dir);
    var h = '<div class="sc2-sec">RECENT SCALPS</div>';
    if (!rows.length) return h + '<div class="sc2-empty">Nothing here yet.</div>';
    function th(col, label) { return '<th data-sort="' + col + '" class="sc2-th' + (ST.sort.col === col ? ' on' : '') + '">' + label + (ST.sort.col === col ? (ST.sort.dir > 0 ? ' ▲' : ' ▼') : '') + '</th>'; }
    h += '<div class="wl-scroll"><table class="signal-table sc2-table no-stack"><thead><tr>' + th('coin', 'COIN') + th('side', 'SIDE') + th('entry', 'ENTRY') + th('exit', 'EXIT') + th('result', 'RESULT') + th('pnl', 'P&amp;L') + th('duration', 'TIME') + th('score', 'SCORE') + '</tr></thead><tbody>';
    rows.slice(0, ST.showN).forEach(function (r) {
      h += '<tr title="' + esc(dt(r.created_at)) + '"><td><b>' + esc(r.coin) + '</b></td><td>' + esc(r.direction) + '</td><td>' + (r.actual_entry != null ? fmtPrice(r.actual_entry) : '—') + '</td>' +
        '<td>' + (r.exit_price != null ? fmtPrice(r.exit_price) : '—') + '</td><td><span class="badge ' + (r.pnl_pct > 0 ? 'bullish' : r.pnl_pct < 0 ? 'bearish' : 'neutral') + '">' + esc(resultLabel(r)) + '</span></td>' +
        '<td class="' + cls(r.pnl_pct) + '">' + (r.pnl_pct != null ? pct(r.pnl_pct) : '—') + '</td><td>' + (r.duration_min != null ? esc(mins(r.duration_min)) : '—') + '</td><td>' + (r.setup_score != null ? r.setup_score.toFixed(1) : '—') + '</td></tr>';
    });
    h += '</tbody></table></div>';
    if (rows.length > ST.showN) h += '<button type="button" class="sc2-btn" data-more="1">Show more (' + (rows.length - ST.showN) + ')</button>';
    return h;
  }

  function field(k, label, cfg, lim, step) {
    var v = cfg[k], l = lim[k] || [];
    return '<label class="sc2-f">' + label + '<input type="number" data-cfg="' + k + '" value="' + esc(v) + '" step="' + (step || 'any') + '"' + (l.length ? ' min="' + l[0] + '" max="' + l[1] + '"' : '') + '></label>';
  }
  function settingsBlock() {
    if (!ST.ctx || !ST.ctx.isAdmin) return '';
    var d = ST.data, cfg = (ST.dirty && ST.draft) ? ST.draft : d.config, lim = d.limits;
    function chk(k, label, on) { return '<label class="sc2-c"><input type="checkbox" data-cfg="' + k + '"' + (on ? ' checked' : '') + '> ' + esc(label) + '</label>'; }
    var h = '<div class="sc2-sec">SETTINGS <span class="watch">admin only</span></div><details class="fold" data-key="settings"' + (ST.open.settings ? ' open' : '') + '><summary>Engine settings</summary><div class="sc2-set">' +
      '<div class="sc2-g"><b>Coins</b>' + d.coin_list.map(function (c) { return '<label class="sc2-c"><input type="checkbox" data-coin="' + c.symbol + '"' + (cfg.enabled_coins.indexOf(c.symbol) >= 0 ? ' checked' : '') + '> ' + esc(c.symbol) + '</label>'; }).join('') + '</div>' +
      '<div class="sc2-g"><b>Timeframes</b><label class="sc2-f">Trend timeframe<select data-cfg="htf"><option' + (cfg.htf === '15m' ? ' selected' : '') + '>15m</option><option' + (cfg.htf === '1h' ? ' selected' : '') + '>1h</option></select></label>' +
      '<label class="sc2-f">Entry timeframe<select disabled><option>5m</option></select></label></div>' +
      '<div class="sc2-g"><b>Signal quality</b>' + field('min_score', 'Min setup score (of 10)', cfg, lim, 0.5) + field('min_rr', 'Min risk / reward', cfg, lim, 0.1) + field('alert_min_score', 'Alert only if score at least', cfg, lim, 0.5) + '</div>' +
      '<div class="sc2-g"><b>Timing and spam control</b>' + field('signal_expiry_min', 'Setup expires after (min)', cfg, lim, 5) + field('trade_max_min', 'Trade time limit (min)', cfg, lim, 15) + field('cooldown_min', 'Cooldown after a signal (min)', cfg, lim, 5) +
      field('sl_cooldown_min', 'Cooldown after a stop-loss (min)', cfg, lim, 5) + field('max_simultaneous', 'Max simultaneous scalps', cfg, lim, 1) + '</div>' +
      '<div class="sc2-g"><b>Risk</b>' + field('fee_pct', 'Round-trip fees (%)', cfg, lim, 0.01) + field('stop_atr_min', 'Smallest stop (x typical candle move)', cfg, lim, 0.1) + field('stop_atr_max', 'Largest stop (x typical candle move)', cfg, lim, 0.1) +
      field('tp1_atr', 'Target 1 (x typical candle move)', cfg, lim, 0.1) + field('tp2_atr', 'Target 2 (x typical candle move)', cfg, lim, 0.1) + field('partial_tp1_pct', 'Close at target 1 (%)', cfg, lim, 5) + chk('allow_short', 'Allow SHORT setups (off = long only)', cfg.allow_short) + '</div>' +
      '<div class="sc2-g"><b>Restrict new scalps when the market is</b>' + d.regimes.map(function (r) { return '<label class="sc2-c"><input type="checkbox" data-reg="' + r + '"' + (cfg.restricted_regimes.indexOf(r) >= 0 ? ' checked' : '') + '> ' + esc(r) + '</label>'; }).join('') +
      field('high_vol_ratio', 'HIGH VOLATILITY when candles are this many times bigger than usual', cfg, lim, 0.1) + field('vol_min', 'Min volume vs normal', cfg, lim, 0.1) + '</div>' +
      '<div class="sc2-g"><b>Alerts</b>' + Object.keys(cfg.alerts).map(function (k) { return '<label class="sc2-c"><input type="checkbox" data-alert="' + k + '"' + (cfg.alerts[k] ? ' checked' : '') + '> ' + esc({ setup: 'New setup', entry: 'Entry triggered', tp1: 'TP1 hit', tp2: 'TP2 hit', stop: 'Stop loss', invalidated: 'Setup invalid', regime: 'Regime change', expired: 'Setup expired' }[k] || k) + '</label>'; }).join('') + '</div>' +
      '</div><div class="sc2-actions"><button type="button" class="sc2-btn sc2-primary" data-save="1">Save settings</button><button type="button" class="sc2-btn" data-reset="1">Reset to defaults</button></div>' +
      '<div class="sub">Changes apply on the next engine run (within about 5 minutes). They never change signals that already exist.</div></details>';
    return h;
  }

  function howBlock() {
    return '<details class="fold sc2-how" data-key="how"' + (ST.open.how ? ' open' : '') + '><summary>How signals are decided</summary>' +
      '<div class="sub">The engine checks 7 things on the 15-minute trend and the 5-minute entry: <b>Trend</b> (2 pts), <b>Momentum</b> (1.5), <b>Volume</b> (1.5), <b>Structure</b> (1.5), <b>Volatility</b> / fees (1), <b>Entry trigger</b> (1.5) and <b>Risk / Reward</b> (1). ' +
      'The total is the <b>Setup Score</b> out of 10. It is a rule score, not a probability. A setup needs Trend, Entry trigger, Volatility and Risk/Reward to pass <i>and</i> a score at or above the minimum. ' +
      'Stops sit just beyond market structure and are kept within a sensible distance; targets come from the coin\u2019s typical candle move. Every level is shown as a price and a % from entry so you can enter it as a Binance order. Half the position is closed at TP1 and the stop moved to breakeven. If a candle touches both stop and target, the stop is assumed first. ' +
      'Nothing here is proven to be profitable: the Performance section is how you find out.</div></details>';
  }

  /* ---------------- chart: candles + VWAP (+ entry zone, stop, targets when the coin has a signal) ---------------- */
  function chartWrap(sym, sigId) { return '<div class="sc2-chartwrap" data-chart="' + esc(sym) + '" data-sig="' + esc(sigId || '') + '"><div class="sc2-loading">Loading chart\u2026</div></div>'; }

  function chartSvg(kl, vw, lv) {
    var rows = kl.slice(-72), w = 640, h = 190, pad = 6, hi = -Infinity, lo = Infinity;
    rows.forEach(function (k) { hi = Math.max(hi, +k[2]); lo = Math.min(lo, +k[3]); });
    var marks = [];
    if (vw != null) marks.push(vw);
    if (lv) [lv.entry_low, lv.entry_high, lv.stop, lv.tp1, lv.tp2].forEach(function (v) { if (v != null && v > lo * 0.9 && v < hi * 1.1) marks.push(v); });
    marks.forEach(function (v) { hi = Math.max(hi, v); lo = Math.min(lo, v); });
    var span = (hi - lo) || 1, cw = (w - pad * 2) / rows.length;
    function y(v) { return pad + (hi - v) / span * (h - pad * 2); }
    var out = '<svg class="sc-chart" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" role="img" aria-label="Recent candles with VWAP">';
    if (lv && lv.entry_low != null) out += '<rect x="0" width="' + w + '" y="' + y(lv.entry_high).toFixed(1) + '" height="' + Math.max(2, y(lv.entry_low) - y(lv.entry_high)).toFixed(1) + '" class="sc2-zone"/>';
    rows.forEach(function (k, i) {
      var o = +k[1], c = +k[4], x = pad + i * cw + cw / 2, up = c >= o;
      out += '<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + y(+k[2]).toFixed(1) + '" y2="' + y(+k[3]).toFixed(1) + '" class="' + (up ? 'sc-up' : 'sc-dn') + '"/>' +
        '<rect x="' + (x - cw * 0.35).toFixed(1) + '" y="' + y(Math.max(o, c)).toFixed(1) + '" width="' + (cw * 0.7).toFixed(1) + '" height="' + Math.max(1, Math.abs(y(o) - y(c))).toFixed(1) + '" class="' + (up ? 'sc-up-f' : 'sc-dn-f') + '"/>';
    });
    function line(v, c, label) { return v == null ? '' : '<line x1="0" x2="' + w + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" class="' + c + '"/><text x="' + (w - 4) + '" y="' + (y(v) - 3).toFixed(1) + '" text-anchor="end" class="sc-lbl">' + label + '</text>'; }
    out += line(vw, 'sc-vwap', 'VWAP');
    if (lv) out += line(lv.stop, 'sc-s', 'Stop') + line(lv.tp1, 'sc-t', 'TP1') + line(lv.tp2, 'sc-t', 'TP2');
    return out + '</svg>';
  }

  var IV_MS = { '1m': 60000, '5m': 300000, '15m': 900000 };
  function chartSpec(sym, kl, lv, vw) {
    var o = [];
    if (vw != null) o.push({ kind: 'hline', p: vw, label: 'VWAP', color: '#2962ff' });
    if (lv) {
      if (lv.actual_entry != null) o.push({ kind: 'hline', p: lv.actual_entry, label: 'Entry', color: '#9aa0ad', dash: '2 3' });
      else o.push({ kind: 'zone', p1: lv.entry_low, p2: lv.entry_high, color: '#2962ff' });
      o.push({ kind: 'hline', p: lv.stop, label: 'Stop', color: '#f23645' }, { kind: 'hline', p: lv.tp1, label: 'TP1', color: '#089981' }, { kind: 'hline', p: lv.tp2, label: 'TP2', color: '#089981' });
    }
    return { kind: 'candle', intraday: true, window: 90, height: 230, ivLabel: ST.iv, barMs: IV_MS[ST.iv], key: 'scalp:' + sym, title: sym + ' / TetherUS \u00B7 ' + ST.iv + ' \u00B7 Binance',
             d: kl.slice(-300).map(function (k) { return [+k[0], +k[1], +k[2], +k[3], +k[4]]; }), overlays: o };
  }

  function paintCharts() {
    var el = root(); if (!el || !ST.data) return;
    el.querySelectorAll('.sc2-chartwrap').forEach(function (n) {
      var sym = n.getAttribute('data-chart'), kl = ST.kl[sym]; if (!kl) return;
      if (n.querySelector('[data-busy="1"]')) return;                      // the admin is mid-drawing: do not redraw under their hand
      var id = n.getAttribute('data-sig'), lv = null;
      if (id) lv = ST.data.active.concat(ST.data.recent).filter(function (r) { return r.id === id; })[0] || null;
      var vw = sessionVwap(kl), px = livePrice(sym, +kl[kl.length - 1][4]);
      var facts = '<span>' + esc(ST.iv) + ' candles</span>' +
        (vw != null ? '<span>VWAP <b>' + fmtPrice(vw) + '</b></span><span class="' + (px >= vw ? 'pos' : 'neg') + '">' + (px >= vw ? 'Above' : 'Below') + ' VWAP</span>' : '<span>VWAP n/a (too little of today yet)</span>');
      if (window.KairoChart && window.KairoChart.mount) {
        var box = n.querySelector('.sc2-kc');
        if (!box) { n.innerHTML = '<div class="sc2-kc"></div><div class="sc2-chartfacts"></div>'; box = n.querySelector('.sc2-kc'); }
        var spec = chartSpec(sym, kl, lv, vw), stateKey = 'sc:' + sym + (id ? ':a' : ':c');
        spec.onExpand = function () { window.KairoChart.expand(chartSpec(sym, ST.kl[sym] || kl, lv, sessionVwap(ST.kl[sym] || kl)), stateKey); };
        window.KairoChart.mount(box, spec, stateKey);
        n.querySelector('.sc2-chartfacts').innerHTML = facts;
      } else {                                                              // the chart engine did not load: fall back to the simple picture
        n.innerHTML = chartSvg(kl, vw, lv) + '<div class="sc2-chartfacts">' + facts + '</div>';
      }
    });
  }

  function loadCharts() {
    if (!ST.data || ST.klBusy) return;
    ST.klBusy = true;
    var iv = ST.iv;
    Promise.all(ST.data.coin_list.map(function (c) {
      return fetch('https://data-api.binance.vision/api/v3/klines?symbol=' + c.symbol + 'USDT&interval=' + iv + '&limit=300')
        .then(function (r) { if (!r.ok) throw new Error('bad'); return r.json(); }).then(function (rows) { return [c.symbol, rows]; }).catch(function () { return [c.symbol, null]; });
    })).then(function (res) {
      if (iv === ST.iv) res.forEach(function (x) { if (x[1]) ST.kl[x[0]] = x[1]; });
    }).then(function () { ST.klBusy = false; paintCharts(); });
  }

  function ivBar() {
    return '<div class="sc2-ivs"><span>Chart</span>' + ['1m', '5m', '15m'].map(function (v) { return '<button type="button" class="sc2-iv' + (ST.iv === v ? ' on' : '') + '" data-iv="' + v + '">' + v + '</button>'; }).join('') + '</div>';
  }

  function draw() { drawBase(); paintCharts(); }
  function drawBase() {
    var el = root(); if (!el || !ST.data) return;
    el.innerHTML = header() + answer() + ivBar() + activeBlock() + coinCards() + perfBlock() + recentBlock() + settingsBlock() + howBlock() +
      (ST.msg ? '<div class="sc2-msg">' + esc(ST.msg) + '</div>' : '') + '<div class="sub sc2-foot">Analysis, not advice. Long-only unless shorts are switched on in Settings. Prices refresh every 5 seconds; signals update about every 5 minutes.</div>';
  }

  function updateLive() {
    var el = root(); if (!el || !ST.data) return;
    el.querySelectorAll('[data-px]').forEach(function (n) {
      var sym = n.getAttribute('data-px'), p = ST.prices[sym];
      if (p != null) n.textContent = (n.classList.contains('sc2-px') ? '$' : '') + fmtPrice(p);
    });
    ST.data.active.forEach(function (r) {
      var px = livePrice(r.coin, r.last_price), s = el.querySelector('[data-st="' + r.id + '"]'), p = el.querySelector('[data-pnl="' + r.id + '"]');
      if (s) s.textContent = tradeStatus(r, px);
      if (p) { var v = openPnl(r, px, ST.data.config); p.textContent = pct(v); p.className = cls(v); }
    });
    var last = el.querySelector('#sc-last'); if (last) last.textContent = ST.priceTs ? Math.round((Date.now() - ST.priceTs) / 1000) + ' sec ago' : 'n/a';
  }

  function loadPrices() {
    if (!ST.data || ST.busy) return;
    var syms = ST.data.coin_list.map(function (c) { return c.symbol + 'USDT'; });
    ST.busy = true;
    fetch('https://data-api.binance.vision/api/v3/ticker/price?symbols=' + encodeURIComponent(JSON.stringify(syms))).then(function (r) { if (!r.ok) throw new Error('bad'); return r.json(); }).then(function (rows) {
      rows.forEach(function (x) { ST.prices[x.symbol.replace(/USDT$/, '')] = +x.price; });
      ST.priceTs = Date.now(); ST.everOk = true; ST.fails = 0;
    }).catch(function () { ST.fails += 1; }).then(function () { ST.busy = false; var el = root(); if (el && ST.data) { var now = status(); if (now !== ST.lastStatus) { ST.lastStatus = now; draw(); } else updateLive(); } });
  }

  function tick() {
    var el = root();
    if (!el) { if (ST.timer) { clearInterval(ST.timer); ST.timer = null; } return; }
    var on = document.getElementById('tab-scalping');
    if (document.hidden || (on && !on.checked)) return;
    loadPrices();
    ST.n += 1; if (ST.n % 3 === 0) loadCharts();
  }

  /* ---------------- events ---------------- */
  function collect() {
    var el = root(), cfg = JSON.parse(JSON.stringify(ST.data.config));
    el.querySelectorAll('[data-cfg]').forEach(function (n) {
      var k = n.getAttribute('data-cfg');
      if (n.type === 'checkbox') cfg[k] = n.checked; else if (n.type === 'number') { if (n.value !== '') cfg[k] = +n.value; } else cfg[k] = n.value;
    });
    cfg.enabled_coins = [].slice.call(el.querySelectorAll('[data-coin]')).filter(function (n) { return n.checked; }).map(function (n) { return n.getAttribute('data-coin'); });
    cfg.restricted_regimes = [].slice.call(el.querySelectorAll('[data-reg]')).filter(function (n) { return n.checked; }).map(function (n) { return n.getAttribute('data-reg'); });
    el.querySelectorAll('[data-alert]').forEach(function (n) { cfg.alerts[n.getAttribute('data-alert')] = n.checked; });
    return cfg;
  }
  function say(m) { ST.msg = m; draw(); }

  function bind(el) {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.addEventListener('click', function (e) {
      var t = e.target, b = t.closest && t.closest('button, th');
      if (!b) return;
      if (b.hasAttribute('data-iv')) { ST.iv = b.getAttribute('data-iv'); ST.kl = {}; draw(); loadCharts(); }
      else if (b.hasAttribute('data-sort')) { var c = b.getAttribute('data-sort'); ST.sort = { col: c, dir: ST.sort.col === c ? -ST.sort.dir : -1 }; draw(); }
      else if (b.hasAttribute('data-more')) { ST.showN += 25; draw(); }
      else if (b.hasAttribute('data-clear')) { ST.filters = {}; draw(); }
      else if (b.hasAttribute('data-close')) {
        var id = b.getAttribute('data-close');
        if (!window.confirm('Close this scalp? It will be closed at the price the engine sees on its next run (within about 5 minutes).')) return;
        if (!ST.ctx || !ST.ctx.sb || ST.ctx.dev) return say('Preview mode: nothing was sent.');
        ST.ctx.sb().rpc('admin_request_scalp_close', { p_id: id }).then(function (r) {
          if (r.error) return say('Could not request the close: ' + r.error.message);
          var row = ST.data.active.filter(function (x) { return x.id === id; })[0]; if (row) row.manual_close_requested = true;
          say('Close requested. The engine will carry it out on its next run.');
        });
      } else if (b.hasAttribute('data-save')) {
        var cfg = collect();
        if (!ST.ctx || !ST.ctx.sb || ST.ctx.dev) { ST.draft = cfg; ST.dirty = true; return say('Preview mode: settings were not saved.'); }
        ST.ctx.sb().rpc('admin_set_scalp_config', { p_value: cfg }).then(function (r) {
          if (r.error) return say('Could not save: ' + r.error.message);
          ST.data.config = cfg; ST.dirty = false; ST.draft = null; say('Saved. It applies on the next engine run (within about 5 minutes).');
        });
      } else if (b.hasAttribute('data-reset')) {
        ST.draft = JSON.parse(JSON.stringify(ST.data.defaults || ST.data.config)); ST.dirty = true; draw();
      }
    });
    el.addEventListener('change', function (e) {
      var n = e.target;
      if (n.hasAttribute('data-f')) { ST.filters[n.getAttribute('data-f')] = n.value; draw(); }
      else if (n.hasAttribute('data-cfg') || n.hasAttribute('data-coin') || n.hasAttribute('data-reg') || n.hasAttribute('data-alert')) { ST.draft = collect(); ST.dirty = true; }
    });
    el.addEventListener('toggle', function (e) { var k = e.target.getAttribute && e.target.getAttribute('data-key'); if (k) ST.open[k] = e.target.open; }, true);
  }
  window.kairoInitScalping = function (row, ctx) {
    var data = row && row.data;
    var el = root(); if (!el) return;
    if (!data || !data.coins || !data.market || !data.active || !data.history) {      // an older payload, or the engine has not run yet
      el.innerHTML = '<div class="sc2-head"><div class="sc2-title">\u26A1 SCALPING</div><div class="sc2-meta"><span>Waiting for the scalping engine\u2019s first run. It runs about every 5 minutes.</span></div></div>';
      return;
    }
    ST.data = data; ST.ctx = ctx || ST.ctx; ST.lastStatus = null;
    bind(el);
    draw();
    loadPrices();
    loadCharts();
    if (ST.timer) clearInterval(ST.timer);
    ST.timer = setInterval(tick, 5000);
  };
})();
