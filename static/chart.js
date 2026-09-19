/* Price charts for the Cross-Market Watchlist: click a row's "Chart" button and a candlestick chart opens under it
 * (daily candles, moving averages, crosshair with OHLC readout, last-price tag) in the style of a trading terminal.
 *
 * Data: Binance symbols are fetched live in the browser; everything else (dollar index, yields, oil, gold, stocks) is
 * shipped by the scheduled job in the Big Coins section's data. Symbols with no free history say so - nothing is drawn
 * from made-up numbers. No libraries; plain SVG. */
(function (root) {
  'use strict';

  /* ---------------- pure helpers (unit-tested with node) ---------------- */

  function ema(values, n) {
    var out = new Array(values.length).fill(null);
    if (values.length < n) return out;
    var k = 2 / (n + 1), e = 0, i;
    for (i = 0; i < n; i++) e += values[i];
    e /= n; out[n - 1] = e;
    for (i = n; i < values.length; i++) { e = values[i] * k + e * (1 - k); out[i] = e; }
    return out;
  }

  function niceTicks(min, max, count) {
    var span = max - min;
    if (!(span > 0)) return [min];
    var raw = span / Math.max(2, count), mag = Math.pow(10, Math.floor(Math.log10(raw))), norm = raw / mag;
    var step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * mag;
    var ticks = [], t = Math.ceil(min / step) * step;
    for (; t <= max + step * 1e-9; t += step) ticks.push(+t.toFixed(10));
    return ticks;
  }

  function decimalsFor(range) {
    if (!(range > 0)) return 2;
    return Math.max(0, Math.min(8, Math.ceil(-Math.log10(range / 6)) + 1));
  }
  function fmt(v, dec) { return v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }); }

  function sliceRange(series, range) {
    var n = { '3M': 65, '6M': 130, '1Y': 260 }[range];
    return n ? series.slice(-n) : series.slice();
  }

  var api = { ema: ema, niceTicks: niceTicks, decimalsFor: decimalsFor, fmt: fmt, sliceRange: sliceRange };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.KairoChart = api;

  /* ---------------- rendering ---------------- */

  var COL = { bg: '#0f1115', grid: '#1e222b', text: '#aeb4c0', up: '#089981', down: '#f23645', line: '#2962ff', cross: '#787b86' };
  var EMA_COL = { 20: '#f0b90b', 50: '#ff9800', 100: '#2962ff', 200: '#b39ddb' };
  var NS = 'http://www.w3.org/2000/svg';
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var TITLES = {
    BTCUSDT: 'BTC / TetherUS · 1D · Binance', ETHUSDT: 'ETH / TetherUS · 1D · Binance', XRPUSDT: 'XRP / TetherUS · 1D · Binance',
    SOLUSDT: 'SOL / TetherUS · 1D · Binance', SOLBTC: 'SOL / Bitcoin · 1D · Binance', DXY: 'US Dollar Index (DXY) · 1D · Yahoo Finance',
    US10Y: 'US 10-Year Treasury Yield · 1D · Yahoo Finance', USOIL: 'Crude Oil futures · 1D · Yahoo Finance', XAUUSD: 'Gold futures · 1D · Yahoo Finance',
    XAGUSD: 'Silver futures · 1D · Yahoo Finance', 'ES1!': 'S&P 500 E-mini futures · 1D · Yahoo Finance', NDX: 'Nasdaq 100 · 1D · Yahoo Finance',
    NVDA: 'NVIDIA · 1D · Yahoo Finance', UNRATE: 'US Unemployment Rate (monthly) · FRED', 'US10Y-US02Y': '10Y minus 2Y yield spread · 1D · Yahoo Finance',
    'US10Y-US03MY': '10Y minus 3M yield spread · 1D · Yahoo Finance'
  };
  var DATA = {}, OPEN = null, STATE = {};

  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function dateLabel(ms) {
    var d = new Date(ms);
    return d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', day: '2-digit', month: 'short', year: '2-digit' }).replace(',', '');
  }

  function fetchBinance(sym) {
    return fetch('https://data-api.binance.vision/api/v3/klines?symbol=' + encodeURIComponent(sym) + '&interval=1d&limit=500').then(function (r) {
      if (!r.ok) throw new Error('bad status');
      return r.json();
    }).then(function (rows) {
      return { kind: 'candle', d: rows.map(function (k) { return [k[0], +k[1], +k[2], +k[3], +k[4]]; }) };
    });
  }

  function getSeries(row) {
    var sym = row.getAttribute('data-sym'), b = row.getAttribute('data-binance');
    if (b) return fetchBinance(b);
    if (DATA[sym]) return Promise.resolve(DATA[sym]);
    return Promise.reject(new Error('none'));
  }

  function draw(host, spec, st) {
    var plotBox = host.querySelector('.kc-plot');
    plotBox.innerHTML = '';
    var candle = spec.kind === 'candle';
    var all = spec.d;
    var data = sliceRange(all, st.range);
    var n = data.length;
    if (n < 2) { plotBox.innerHTML = '<div class="kc-note">Not enough history to draw a chart.</div>'; return; }
    var W = Math.max(300, plotBox.clientWidth || 320), H = W < 520 ? 300 : 380;
    var ml = 6, mr = 66, mt = 10, mb = 26, pw = W - ml - mr, ph = H - mt - mb, step = pw / n;

    var closes = all.map(function (r) { return candle ? r[4] : r[1]; });
    var emaLines = [];
    if (candle) {
      [20, 50, 100, 200].forEach(function (p) {
        if (st.emas[p]) emaLines.push({ p: p, v: ema(closes, p).slice(-n) });
      });
    }
    var lo = Infinity, hi = -Infinity;
    data.forEach(function (r) { if (candle) { lo = Math.min(lo, r[3]); hi = Math.max(hi, r[2]); } else { lo = Math.min(lo, r[1]); hi = Math.max(hi, r[1]); } });
    emaLines.forEach(function (l) { l.v.forEach(function (v) { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
    var pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1; lo -= pad; hi += pad;
    var dec = decimalsFor(hi - lo);
    function X(i) { return ml + step * (i + 0.5); }
    function Y(v) { return mt + (hi - v) / (hi - lo) * ph; }

    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', height: H, role: 'img', 'aria-label': spec.title, class: 'kc-svg' });
    svg.appendChild(el('rect', { x: 0, y: 0, width: W, height: H, fill: COL.bg }));
    niceTicks(lo, hi, 7).forEach(function (t) {
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(t), y2: Y(t), stroke: COL.grid, 'stroke-width': 1 }));
      svg.appendChild(el('text', { x: W - mr + 8, y: Y(t) + 4, fill: COL.text, 'font-size': 11 }, fmt(t, dec)));
    });
    var lastLabelX = -100;
    data.forEach(function (r, i) {
      var d = new Date(r[0]), m = d.getUTCMonth();
      var prev = i > 0 ? new Date(data[i - 1][0]).getUTCMonth() : -1;
      if (m !== prev && X(i) - lastLabelX > 44) {
        lastLabelX = X(i);
        svg.appendChild(el('line', { x1: X(i), x2: X(i), y1: mt, y2: mt + ph, stroke: COL.grid, 'stroke-width': 1 }));
        svg.appendChild(el('text', { x: X(i), y: H - 8, fill: COL.text, 'font-size': 11, 'text-anchor': 'middle' }, m === 0 ? String(d.getUTCFullYear()) : MONTHS[m]));
      }
    });

    if (candle) {
      var bw = Math.max(1, step * 0.66);
      data.forEach(function (r, i) {
        var up = r[4] >= r[1], c = up ? COL.up : COL.down;
        svg.appendChild(el('line', { x1: X(i), x2: X(i), y1: Y(r[2]), y2: Y(r[3]), stroke: c, 'stroke-width': 1 }));
        var top = Y(Math.max(r[1], r[4])), h = Math.max(1, Math.abs(Y(r[1]) - Y(r[4])));
        svg.appendChild(el('rect', { x: X(i) - bw / 2, y: top, width: bw, height: h, fill: c }));
      });
    } else {
      var pts = data.map(function (r, i) { return X(i).toFixed(1) + ',' + Y(r[1]).toFixed(1); }).join(' ');
      svg.appendChild(el('polygon', { points: X(0).toFixed(1) + ',' + (mt + ph) + ' ' + pts + ' ' + X(n - 1).toFixed(1) + ',' + (mt + ph), fill: 'rgba(41,98,255,0.14)' }));
      svg.appendChild(el('polyline', { points: pts, fill: 'none', stroke: COL.line, 'stroke-width': 2 }));
    }
    emaLines.forEach(function (l) {
      var seg = [];
      l.v.forEach(function (v, i) { if (v != null) seg.push(X(i).toFixed(1) + ',' + Y(v).toFixed(1)); });
      if (seg.length > 1) svg.appendChild(el('polyline', { points: seg.join(' '), fill: 'none', stroke: EMA_COL[l.p], 'stroke-width': 1.4 }));
    });

    var last = data[n - 1], lastC = candle ? last[4] : last[1], prevC = n > 1 ? (candle ? data[n - 2][4] : data[n - 2][1]) : lastC;
    var lastUp = lastC >= prevC;
    svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(lastC), y2: Y(lastC), stroke: lastUp ? COL.up : COL.down, 'stroke-dasharray': '2 3', 'stroke-width': 1 }));
    svg.appendChild(el('rect', { x: W - mr + 2, y: Y(lastC) - 9, width: mr - 4, height: 18, rx: 3, fill: lastUp ? COL.up : COL.down }));
    svg.appendChild(el('text', { x: W - mr + 6, y: Y(lastC) + 4, fill: '#fff', 'font-size': 11, 'font-weight': 700 }, fmt(lastC, dec)));

    var cross = el('g', { style: 'display:none', 'pointer-events': 'none' });
    var vl = el('line', { y1: mt, y2: mt + ph, stroke: COL.cross, 'stroke-dasharray': '3 3' });
    var hl = el('line', { x1: ml, x2: ml + pw, stroke: COL.cross, 'stroke-dasharray': '3 3' });
    var pr = el('rect', { x: W - mr + 2, width: mr - 4, height: 18, rx: 3, fill: '#2a2e39' });
    var pt = el('text', { x: W - mr + 6, fill: '#fff', 'font-size': 11 });
    var dr = el('rect', { y: H - mb + 2, height: 18, rx: 3, fill: '#2a2e39', width: 96 });
    var dt = el('text', { y: H - mb + 15, fill: '#fff', 'font-size': 11, 'text-anchor': 'middle' });
    [vl, hl, pr, pt, dr, dt].forEach(function (x) { cross.appendChild(x); });
    svg.appendChild(cross);

    var info = host.querySelector('.kc-ohlc');
    var rd = Math.min(8, dec + 2);                       // readout shows two more digits than the axis
    function readout(i) {
      var r = data[i], pc = i > 0 ? (candle ? data[i - 1][4] : data[i - 1][1]) : (candle ? r[1] : r[1]);
      if (candle) {
        var ch = r[4] - pc, pct = pc ? ch / pc * 100 : 0, cls = ch >= 0 ? 'up' : 'down';
        info.innerHTML = 'O <b>' + fmt(r[1], rd) + '</b> H <b>' + fmt(r[2], rd) + '</b> L <b>' + fmt(r[3], rd) + '</b> C <b>' + fmt(r[4], rd) +
          '</b> <span class="' + cls + '">' + (ch >= 0 ? '+' : '') + fmt(ch, rd) + ' (' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%)</span>';
      } else {
        var chl = r[1] - pc;
        info.innerHTML = '<b>' + fmt(r[1], rd) + '</b> <span class="' + (chl >= 0 ? 'up' : 'down') + '">' + (chl >= 0 ? '+' : '') + fmt(chl, rd) + '</span>';
      }
    }
    readout(n - 1);
    function move(ev) {
      var rect = svg.getBoundingClientRect(), sx = W / rect.width;
      var x = (ev.clientX - rect.left) * sx, y = (ev.clientY - rect.top) * sx;
      var i = Math.max(0, Math.min(n - 1, Math.floor((x - ml) / step)));
      if (y < mt || y > mt + ph) y = Math.max(mt, Math.min(mt + ph, y));
      cross.style.display = '';
      vl.setAttribute('x1', X(i)); vl.setAttribute('x2', X(i)); hl.setAttribute('y1', y); hl.setAttribute('y2', y);
      var v = hi - (y - mt) / ph * (hi - lo);
      pr.setAttribute('y', y - 9); pt.setAttribute('y', y + 4); pt.textContent = fmt(v, dec);
      dr.setAttribute('x', Math.max(ml, Math.min(ml + pw - 96, X(i) - 48))); dt.setAttribute('x', Math.max(ml, Math.min(ml + pw - 96, X(i) - 48)) + 48);
      dt.textContent = dateLabel(data[i][0]);
      readout(i);
    }
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', function () { cross.style.display = 'none'; readout(n - 1); });
    plotBox.appendChild(svg);
  }

  function mount(host, spec, sym) {
    var st = STATE[sym] || (STATE[sym] = { range: '1Y', emas: { 20: false, 50: false, 100: true, 200: false } });
    var candle = spec.kind === 'candle';
    host.innerHTML = '<div class="kc"><div class="kc-head"><b class="kc-title">' + esc(TITLES[sym] || sym) + '</b><span class="kc-ohlc"></span></div>' +
      '<div class="kc-ctl"><div class="kc-ranges">' + ['3M', '6M', '1Y', 'MAX'].map(function (r) { return '<button type="button" data-r="' + r + '" class="' + (r === st.range ? 'on' : '') + '">' + r + '</button>'; }).join('') + '</div>' +
      (candle ? '<div class="kc-emas">' + [20, 50, 100, 200].map(function (p) {
        return '<button type="button" data-e="' + p + '" class="' + (st.emas[p] ? 'on' : '') + '" style="--c:' + EMA_COL[p] + '">EMA ' + p + '</button>';
      }).join('') + '</div>' : '') + '</div><div class="kc-plot"></div>' +
      '<div class="kc-note">Daily ' + (candle ? 'candles' : 'values') + ' · move over the chart for exact values. Chart data may be delayed; not a trading recommendation.</div></div>';
    draw(host, spec, st);
    host.querySelectorAll('.kc-ranges button').forEach(function (b) {
      b.addEventListener('click', function () { st.range = b.getAttribute('data-r'); mount(host, spec, sym); });
    });
    host.querySelectorAll('.kc-emas button').forEach(function (b) {
      b.addEventListener('click', function () { var p = +b.getAttribute('data-e'); st.emas[p] = !st.emas[p]; mount(host, spec, sym); });
    });
  }

  function closeAll() {
    document.querySelectorAll('.wl-chart-row').forEach(function (r) { r.parentNode.removeChild(r); });
    document.querySelectorAll('.wl-row.open').forEach(function (r) { r.classList.remove('open'); });
  }

  function openFor(row) {
    var sym = row.getAttribute('data-sym');
    closeAll();
    OPEN = sym; row.classList.add('open');
    var tr = document.createElement('tr'); tr.className = 'wl-chart-row';
    var td = document.createElement('td'); td.colSpan = 4;
    var host = document.createElement('div'); host.className = 'kc-host';
    host.innerHTML = '<div class="kc-note">Loading chart…</div>';
    td.appendChild(host); tr.appendChild(td); row.parentNode.insertBefore(tr, row.nextSibling);
    getSeries(row).then(function (spec) { if (OPEN === sym && host.isConnected) mount(host, spec, sym); }).catch(function (e) {
      host.innerHTML = '<div class="kc-note">' + (e && e.message === 'none'
        ? 'No chart for ' + esc(sym) + ': there is no free historical data feed for this one, and nothing is drawn from estimates.'
        : 'Could not load the chart data right now. Try again in a moment.') + '</div>';
    });
  }

  root.kairoInitCharts = function (charts) {
    DATA = charts || {};
    document.querySelectorAll('.wl-table tr.wl-row').forEach(function (row) {
      row.addEventListener('click', function (ev) {
        if (ev.target.closest('.kc-host')) return;
        if (row.classList.contains('open')) { closeAll(); OPEN = null; return; }
        openFor(row);
      });
    });
    if (OPEN) {                                            // keep an open chart across the section's periodic refresh
      var row = document.querySelector('.wl-table tr.wl-row[data-sym="' + OPEN.replace(/"/g, '') + '"]');
      if (row) openFor(row); else OPEN = null;
    }
  };
  var rt; window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      var row = OPEN && document.querySelector('.wl-table tr.wl-row[data-sym="' + OPEN.replace(/"/g, '') + '"]');
      if (row && row.classList.contains('open')) openFor(row);
    }, 250);
  });
})(typeof window !== 'undefined' ? window : globalThis);
