/* SCALPING (admin-only, long-only). One coin at a time, one verdict, a handful of plain checks.
 *
 * The rules and every threshold come from scalping/config.py (published with the section), so they are defined once.
 * Prices, candles and the order book are fetched live from Binance's public API in the browser; funding and open interest
 * come from the scheduled job. Anything missing shows "n/a" and is never estimated. Analysis, not advice: none of this is
 * backtested to be profitable, and fees are the main enemy of short-term trades. */
(function () {
  'use strict';

  /* ---------------- analysis (pure; exported for node tests) ---------------- */
  function ema(values, n) {
    if (values.length < n) return [];
    var k = 2 / (n + 1), out = [], e = 0, i;
    for (i = 0; i < n; i++) e += values[i];
    e /= n;
    for (i = 0; i < values.length; i++) { if (i >= n) e = values[i] * k + e * (1 - k); out.push(i >= n - 1 ? e : null); }
    return out;
  }
  function last(a) { return a.length ? a[a.length - 1] : null; }
  function atrValue(kl, n) {
    var tr = [];
    for (var i = 1; i < kl.length; i++) {
      var h = +kl[i][2], l = +kl[i][3], pc = +kl[i - 1][4];
      tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    }
    return last(ema(tr, n));
  }
  function utcMidnightMs(ms) { var d = new Date(ms); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); }
  function sessionCandles(kl) {
    if (!kl.length) return [];
    var m = utcMidnightMs(+kl[kl.length - 1][0]);
    return kl.filter(function (k) { return +k[0] >= m; });
  }
  function vwap(kl) {
    var pv = 0, v = 0;
    kl.forEach(function (k) { var vol = +k[5]; pv += (+k[2] + +k[3] + +k[4]) / 3 * vol; v += vol; });
    return v > 0 ? pv / v : null;
  }
  function depthRatio(book, price, bandPct) {
    if (!book || !book.bids || !book.asks) return null;
    var lo = price * (1 - bandPct / 100), hi = price * (1 + bandPct / 100), b = 0, a = 0;
    book.bids.forEach(function (x) { if (+x[0] >= lo) b += +x[0] * +x[1]; });
    book.asks.forEach(function (x) { if (+x[0] <= hi) a += +x[0] * +x[1]; });
    return a > 0 ? b / a : null;
  }

  /* kl: Binance kline rows (last row = still-forming candle). book: {bids, asks} or null. ctx: {funding_pct, oi_change_pct}. */
  function analyze(kl, book, ctx, P) {
    ctx = ctx || {};
    var need = P.ema_slow + P.atr_len + 5;
    if (!kl || kl.length < need + 1) return { ok: false, reason: 'Not enough candles yet' };
    var closed = kl.slice(0, -1);
    var closes = closed.map(function (k) { return +k[4]; });
    var price = +kl[kl.length - 1][4];
    var eF = last(ema(closes, P.ema_fast)), eS = last(ema(closes, P.ema_slow));
    var sess = sessionCandles(kl);
    var vw = sess.length >= 6 ? vwap(sess) : null;
    var sHigh = sess.length ? Math.max.apply(null, sess.map(function (k) { return +k[2]; })) : null;
    var sLow = sess.length ? Math.min.apply(null, sess.map(function (k) { return +k[3]; })) : null;
    var vols = closed.map(function (k) { return +k[5]; });
    var recent = vols.slice(-P.vol_recent), base = vols.slice(-(P.vol_recent + P.vol_base), -P.vol_recent);
    var avgBase = base.reduce(function (s, x) { return s + x; }, 0) / (base.length || 1);
    var volRatio = avgBase > 0 ? (recent.reduce(function (s, x) { return s + x; }, 0) / recent.length) / avgBase : null;
    var ldr = depthRatio(book, price, P.book_band_pct);
    var atr = atrValue(closed, P.atr_len);
    var atrPct = atr && price ? atr / price * 100 : null;
    var net1 = atrPct == null ? null : P.atr_t1 * atrPct - P.fee_pct;
    var net2 = atrPct == null ? null : P.atr_t2 * atrPct - P.fee_pct;
    var funding = ctx.funding_pct == null ? null : +ctx.funding_pct;

    function chk(key, label, state, text) { return { key: key, label: label, state: state, text: text }; }
    var checks = [
      chk('trend', 'Trend', eF == null || eS == null ? 'na' : (price > eF && eF > eS ? 'pass' : 'fail'),
        eF == null || eS == null ? 'n/a' : (price > eF && eF > eS ? 'Price above a rising ' + P.ema_fast + '/' + P.ema_slow + ' average' : 'Price is not above both averages, or they are not stacked up')),
      chk('vwap', 'VWAP', vw == null ? 'na' : (price > vw ? 'pass' : 'fail'),
        vw == null ? 'n/a (too little of today yet)' : (price > vw ? 'Above today\u2019s average price (VWAP)' : 'Below today\u2019s average price (VWAP)')),
      chk('volume', 'Volume', volRatio == null ? 'na' : (volRatio >= P.vol_mult ? 'pass' : 'fail'),
        volRatio == null ? 'n/a' : volRatio.toFixed(2) + '\u00D7 normal (needs ' + P.vol_mult + '\u00D7)'),
      chk('book', 'Order book', ldr == null ? 'na' : (ldr >= P.book_min_ratio ? 'pass' : 'fail'),
        ldr == null ? 'n/a' : (ldr >= P.book_min_ratio ? 'More resting buy than sell orders nearby' : 'More resting sell than buy orders nearby') + ' (' + ldr.toFixed(2) + ')'),
      chk('funding', 'Funding', funding == null ? 'na' : (funding <= P.funding_hot_pct ? 'pass' : 'fail'),
        funding == null ? 'n/a' : (funding <= P.funding_hot_pct ? 'Not crowded' : 'Crowded longs') + ' (' + funding.toFixed(4) + '%)'),
      chk('cost', 'Fees', net1 == null ? 'na' : (net1 >= P.min_net_t1_pct ? 'pass' : 'fail'),
        net1 == null ? 'n/a' : (net1 >= P.min_net_t1_pct ? 'Target 1 keeps ' + net1.toFixed(2) + '% after fees' : 'Typical move is too small: target 1 would keep only ' + net1.toFixed(2) + '% after fees'))
    ];
    var st = {}; checks.forEach(function (c) { st[c.key] = c.state; });
    var verdict, why;
    if (price != null && eS != null && vw != null && price < eS && price < vw) { verdict = 'AVOID'; why = 'Below its trend and below today\u2019s average price. Long-only scalps have the odds against them here.'; }
    else if (st.trend === 'pass' && st.vwap === 'pass' && st.cost === 'pass' && st.funding !== 'fail' && (st.volume === 'pass' || st.book === 'pass')) { verdict = 'WATCH LONG'; why = 'Trend, VWAP and fees line up, with volume or the order book backing it.'; }
    else { verdict = 'WAIT'; why = 'No clean long setup right now.'; }
    var levels = null;
    if (atr && price) {
      levels = { entry: price, stop: price - P.atr_stop * atr, t1: price + P.atr_t1 * atr, t2: price + P.atr_t2 * atr,
                 riskPct: P.atr_stop * atrPct, net1: net1, net2: net2, rr: net1 / (P.atr_stop * atrPct + P.fee_pct) };
    }
    return { ok: true, verdict: verdict, why: why, checks: checks, price: price, vwap: vw, emaFast: eF, emaSlow: eS,
             sessionHigh: sHigh, sessionLow: sLow, atr: atr, atrPct: atrPct, volRatio: volRatio, ldr: ldr, oiChangePct: ctx.oi_change_pct == null ? null : +ctx.oi_change_pct, levels: levels };
  }

  var api = { ema: ema, atrValue: atrValue, vwap: vwap, depthRatio: depthRatio, sessionCandles: sessionCandles, analyze: analyze };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  /* ---------------- UI ---------------- */
  var ST = { data: null, coin: 0, interval: '5m', kl: null, book: null, res: null, err: null, timer: null, busy: false };
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function root() { return document.getElementById('scalping-root'); }
  function dec(p) { return p >= 100 ? 2 : p >= 1 ? 4 : 5; }
  function money(v, p) { return v == null ? 'n/a' : '$' + (+v).toLocaleString('en-US', { minimumFractionDigits: dec(p), maximumFractionDigits: dec(p) }); }
  function pct(v, d) { return v == null ? 'n/a' : (v >= 0 ? '+' : '') + v.toFixed(d == null ? 2 : d) + '%'; }
  function getJson(url) { return fetch(url).then(function (r) { if (!r.ok) throw new Error('bad status'); return r.json(); }); }

  function chartSvg(kl, res, P) {
    var rows = kl.slice(-72), w = 640, h = 220, pad = 8, i;
    var hi = Math.max.apply(null, rows.map(function (k) { return +k[2]; })), lo = Math.min.apply(null, rows.map(function (k) { return +k[3]; }));
    var extra = [res.vwap, res.levels && res.verdict === 'WATCH LONG' ? res.levels.t1 : null, res.levels && res.verdict === 'WATCH LONG' ? res.levels.stop : null];
    extra.forEach(function (v) { if (v != null) { hi = Math.max(hi, v); lo = Math.min(lo, v); } });
    var span = (hi - lo) || 1, cw = (w - pad * 2) / rows.length;
    function y(v) { return pad + (hi - v) / span * (h - pad * 2); }
    var out = '<svg class="sc-chart" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" role="img" aria-label="Recent candles">';
    rows.forEach(function (k, idx) {
      var o = +k[1], c = +k[4], x = pad + idx * cw + cw / 2, up = c >= o;
      out += '<line x1="' + x.toFixed(1) + '" x2="' + x.toFixed(1) + '" y1="' + y(+k[2]).toFixed(1) + '" y2="' + y(+k[3]).toFixed(1) + '" class="' + (up ? 'sc-up' : 'sc-dn') + '"/>' +
        '<rect x="' + (x - cw * 0.35).toFixed(1) + '" y="' + y(Math.max(o, c)).toFixed(1) + '" width="' + (cw * 0.7).toFixed(1) + '" height="' + Math.max(1, Math.abs(y(o) - y(c))).toFixed(1) + '" class="' + (up ? 'sc-up-f' : 'sc-dn-f') + '"/>';
    });
    function line(v, cls, label) { return v == null ? '' : '<line x1="0" x2="' + w + '" y1="' + y(v).toFixed(1) + '" y2="' + y(v).toFixed(1) + '" class="' + cls + '"/><text x="' + (w - 4) + '" y="' + (y(v) - 3).toFixed(1) + '" text-anchor="end" class="sc-lbl">' + label + '</text>'; }
    out += line(res.vwap, 'sc-vwap', 'VWAP');
    if (res.verdict === 'WATCH LONG' && res.levels) { out += line(res.levels.t1, 'sc-t', 'Target 1') + line(res.levels.stop, 'sc-s', 'Stop'); }
    return out + '</svg>';
  }

  function draw() {
    var el = root(); if (!el || !ST.data) return;
    var P = ST.data.params, coins = ST.data.coins, c = coins[ST.coin], res = ST.res, price = res && res.ok ? res.price : null;
    var h = '<div class="sc-head"><div class="sc-coins" role="tablist">' + coins.map(function (x, i) {
      return '<button type="button" class="sc-coin' + (i === ST.coin ? ' on' : '') + '" data-coin="' + i + '">' + esc(x.symbol) + '</button>'; }).join('') + '</div>' +
      '<div class="sc-ivs">' + P.intervals.map(function (iv) { return '<button type="button" class="sc-iv' + (iv === ST.interval ? ' on' : '') + '" data-iv="' + iv + '">' + iv + '</button>'; }).join('') + '</div></div>';
    if (ST.err && !res) h += '<div class="sc-card"><div class="sub">Could not load live data for ' + esc(c.symbol) + ' (' + esc(ST.err) + '). Retrying\u2026</div></div>';
    else if (!res) h += '<div class="sc-card"><div class="sub">Loading ' + esc(c.symbol) + '\u2026</div></div>';
    else if (!res.ok) h += '<div class="sc-card"><div class="sub">' + esc(res.reason) + '.</div></div>';
    else {
      var vcls = res.verdict === 'WATCH LONG' ? 'bullish' : res.verdict === 'AVOID' ? 'bearish' : 'neutral';
      h += '<div class="sc-card"><div class="sc-top"><div><div class="sc-name">' + esc(c.name) + ' <span class="watch">' + esc(c.symbol) + 'USDT &middot; ' + esc(ST.interval) + '</span></div>' +
        '<div class="sc-price">' + money(price, price) + '</div></div><div class="sc-verdict"><span class="badge ' + vcls + '">' + esc(res.verdict) + '</span></div></div>' +
        '<div class="sub sc-why">' + esc(res.why) + '</div>' + chartSvg(ST.kl, res, P) +
        '<ul class="sc-checks">' + res.checks.map(function (k) {
          return '<li class="sc-' + k.state + '"><span class="sc-mark">' + (k.state === 'pass' ? '\u2713' : k.state === 'fail' ? '\u2717' : '\u2013') + '</span><b>' + esc(k.label) + '</b><span class="sc-txt">' + esc(k.text) + '</span></li>'; }).join('') + '</ul>';
      if (res.verdict === 'WATCH LONG' && res.levels) {
        var L = res.levels;
        h += '<table class="signal-table sc-levels"><thead><tr><th>Entry</th><th>Stop</th><th>Target 1</th><th>Target 2</th></tr></thead><tbody><tr>' +
          '<td data-label="Entry">' + money(L.entry, price) + '</td><td data-label="Stop" class="neg">' + money(L.stop, price) + '<span class="wl-note">' + L.riskPct.toFixed(2) + '% risk</span></td>' +
          '<td data-label="Target 1" class="pos">' + money(L.t1, price) + '<span class="wl-note">' + pct(L.net1) + ' after fees</span></td>' +
          '<td data-label="Target 2" class="pos">' + money(L.t2, price) + '<span class="wl-note">' + pct(L.net2) + ' after fees</span></td></tr></tbody></table>' +
          '<div class="sub">Reward vs risk after fees: ' + (L.rr == null ? 'n/a' : L.rr.toFixed(2) + ' : 1') + '. Exit at the stop if it is hit; do not widen it.</div>';
      } else {
        h += '<div class="sub">Stop and targets appear only when a long setup forms.</div>';
      }
      h += '<div class="sc-facts"><div><span>VWAP</span><b>' + money(res.vwap, price) + '</b></div><div><span>Today high</span><b>' + money(res.sessionHigh, price) + '</b></div>' +
        '<div><span>Today low</span><b>' + money(res.sessionLow, price) + '</b></div><div><span>Typical move / candle</span><b>' + (res.atrPct == null ? 'n/a' : res.atrPct.toFixed(2) + '%') + '</b></div>' +
        '<div><span>Open interest 24h</span><b>' + pct(res.oiChangePct) + '</b></div><div><span>Fees assumed</span><b>' + P.fee_pct + '% round trip</b></div></div>';
    }
    h += '<div class="sub sc-foot">Long-only analysis, not advice. These rules are not proven to make money after fees: judge them by your own results. Refreshes every ' + P.refresh_seconds + 's while this tab is open.</div>';
    el.innerHTML = h;
  }

  function load() {
    if (ST.busy || !ST.data) return;
    var c = ST.data.coins[ST.coin], sym = c.symbol + 'USDT', iv = ST.interval, coinIdx = ST.coin;
    ST.busy = true;
    Promise.all([
      getJson('https://data-api.binance.vision/api/v3/klines?symbol=' + sym + '&interval=' + iv + '&limit=300'),
      getJson('https://data-api.binance.vision/api/v3/depth?symbol=' + sym + '&limit=100').catch(function () { return null; })
    ]).then(function (r) {
      if (coinIdx !== ST.coin || iv !== ST.interval) return;
      ST.kl = r[0]; ST.book = r[1]; ST.err = null;
      ST.res = analyze(r[0], r[1], c, ST.data.params);
    }).catch(function (e) { ST.err = e && e.message || 'network'; }).then(function () { ST.busy = false; draw(); });
  }

  function tick() {
    var el = root();
    if (!el) { if (ST.timer) { clearInterval(ST.timer); ST.timer = null; } return; }
    var on = document.getElementById('tab-scalping');
    if (document.hidden || (on && !on.checked)) return;      // only poll while the admin is actually looking at it
    load();
  }

  window.kairoInitScalping = function (row) {
    var data = row && row.data;
    if (!data || !data.coins || !data.coins.length) return;
    ST.data = data; ST.coin = Math.min(ST.coin, data.coins.length - 1); ST.interval = ST.interval || data.params.default_interval;
    var el = root(); if (!el) return;
    if (!el.dataset.bound) {
      el.dataset.bound = '1';
      el.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('button'); if (!b) return;
        if (b.dataset.coin != null) { ST.coin = +b.dataset.coin; ST.res = null; ST.kl = null; ST.err = null; draw(); load(); }
        else if (b.dataset.iv) { ST.interval = b.dataset.iv; ST.res = null; ST.kl = null; ST.err = null; draw(); load(); }
      });
    }
    draw(); load();
    if (ST.timer) clearInterval(ST.timer);
    ST.timer = setInterval(tick, (data.params.refresh_seconds || 10) * 1000);
  };
})();
