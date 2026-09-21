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

  /* which candles are on screen: a zoom box, the last N bars of an intraday chart, or the chosen daily range */
  function visible(all, spec, st) {
    var i0, i1 = all.length - 1;
    if (st.zoom) {
      i0 = 0;
      for (var a = 0; a < all.length; a++) { if (all[a][0] >= st.zoom.t0) { i0 = a; break; } }
      for (var k = all.length - 1; k >= 0; k--) { if (all[k][0] <= st.zoom.t1) { i1 = k; break; } }
      if (i1 - i0 < 4) i0 = Math.max(0, i1 - 4);
      return [i0, i1];
    }
    var n = spec.intraday ? (spec.window || 120) : ({ '3M': 65, '6M': 130, '1Y': 260 }[st.range] || all.length);
    return [Math.max(0, all.length - n), i1];
  }
  function timeLabel(ms) {
    return new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
  }

  function draw(host, spec, st) {
    var plotBox = host.querySelector('.kc-plot');
    plotBox.innerHTML = '';
    var candle = spec.kind === 'candle';
    var all = spec.d;
    var vis = visible(all, spec, st), i0 = vis[0], i1 = vis[1];
    var data = all.slice(i0, i1 + 1);
    var n = data.length;
    if (n < 2) { plotBox.innerHTML = '<div class="kc-note">Not enough history to draw a chart.</div>'; return; }
    var W = Math.max(300, plotBox.clientWidth || 320), H = spec.height || (W < 520 ? 300 : 380);
    var ml = 6, mr = 66, mt = 10, mb = 26, pw = W - ml - mr, ph = H - mt - mb, step = pw / n;

    var closes = all.map(function (r) { return candle ? r[4] : r[1]; });
    var emaLines = [];
    if (candle) {
      [20, 50, 100, 200].forEach(function (p) {
        if (st.emas[p]) emaLines.push({ p: p, v: ema(closes, p).slice(i0, i1 + 1) });
      });
    }
    var lo = Infinity, hi = -Infinity;
    data.forEach(function (r) { if (candle) { lo = Math.min(lo, r[3]); hi = Math.max(hi, r[2]); } else { lo = Math.min(lo, r[1]); hi = Math.max(hi, r[1]); } });
    var lo0 = lo, hi0 = hi;
    emaLines.forEach(function (l) { l.v.forEach(function (v) { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
    var overlays = spec.overlays || [];
    overlays.forEach(function (o) {                               // levels near the price stretch the axis; far-away ones are ignored
      [o.p, o.p1, o.p2].forEach(function (v) { if (v != null && isFinite(v) && v > lo0 * 0.85 && v < hi0 * 1.15) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
    });
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
    if (spec.intraday) {
      var per = Math.max(1, Math.ceil(84 / step)), lastDay = null;
      data.forEach(function (r, i) {
        if (i % per) return;
        var d = new Date(r[0]), day = d.toDateString();
        var txt = day !== lastDay ? d.toLocaleDateString([], { month: 'short', day: 'numeric' }) : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
        lastDay = day;
        svg.appendChild(line0(X(i), mt, X(i), mt + ph));
        svg.appendChild(el('text', { x: X(i), y: H - 8, fill: COL.text, 'font-size': 11, 'text-anchor': 'middle' }, txt));
      });
    } else {
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
    }
    function line0(x1, y1, x2, y2) { return el('line', { x1: x1, x2: x2, y1: y1, y2: y2, stroke: COL.grid, 'stroke-width': 1 }); }

    overlays.forEach(function (o) {                              // shaded zones sit behind the candles
      if (o.kind === 'zone' && o.p1 != null && o.p2 != null) svg.appendChild(el('rect', { x: ml, y: Math.min(Y(o.p1), Y(o.p2)), width: pw, height: Math.max(2, Math.abs(Y(o.p1) - Y(o.p2))), fill: o.color || '#2962ff', 'fill-opacity': 0.16 }));
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
    overlays.forEach(function (o) {                              // level lines (VWAP, stop, targets) sit on top of the candles
      if (o.kind !== 'hline' || o.p == null || !isFinite(o.p) || o.p < lo || o.p > hi) return;
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(o.p), y2: Y(o.p), stroke: o.color || '#2962ff', 'stroke-width': 1.2, 'stroke-dasharray': o.dash || '5 4' }));
      if (o.label) svg.appendChild(el('text', { x: ml + pw - 4, y: Y(o.p) - 3, fill: o.color || '#2962ff', 'font-size': 10.5, 'text-anchor': 'end' }, o.label));
    });

    var last = data[n - 1], lastC = candle ? last[4] : last[1], prevC = n > 1 ? (candle ? data[n - 2][4] : data[n - 2][1]) : lastC;
    var lastUp = lastC >= prevC;
    svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(lastC), y2: Y(lastC), stroke: lastUp ? COL.up : COL.down, 'stroke-dasharray': '2 3', 'stroke-width': 1 }));
    svg.appendChild(el('rect', { x: W - mr + 2, y: Y(lastC) - 9, width: mr - 4, height: 18, rx: 3, fill: lastUp ? COL.up : COL.down }));
    svg.appendChild(el('text', { x: W - mr + 6, y: Y(lastC) + 4, fill: '#fff', 'font-size': 11, 'font-weight': 700 }, fmt(lastC, dec)));

    var dw = spec.intraday ? 124 : 96;
    var cross = el('g', { style: 'display:none', 'pointer-events': 'none' });
    var vl = el('line', { y1: mt, y2: mt + ph, stroke: COL.cross, 'stroke-dasharray': '3 3' });
    var hl = el('line', { x1: ml, x2: ml + pw, stroke: COL.cross, 'stroke-dasharray': '3 3' });
    var pr = el('rect', { x: W - mr + 2, width: mr - 4, height: 18, rx: 3, fill: '#2a2e39' });
    var pt = el('text', { x: W - mr + 6, fill: '#fff', 'font-size': 11 });
    var dr = el('rect', { y: H - mb + 2, height: 18, rx: 3, fill: '#2a2e39', width: dw });
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
      var bx = Math.max(ml, Math.min(ml + pw - dw, X(i) - dw / 2));
      dr.setAttribute('x', bx); dt.setAttribute('x', bx + dw / 2);
      dt.textContent = spec.intraday ? timeLabel(data[i][0]) : dateLabel(data[i][0]);
      readout(i);
    }
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerdown', move);
    svg.addEventListener('pointerleave', function () { cross.style.display = 'none'; readout(n - 1); });
    plotBox.appendChild(svg);

    if (root.KairoDraw) {                                // the TradingView-style editor: toolbar actions and the drawing layer
      var bar = n > 1 ? (data[n - 1][0] - data[0][0]) / (n - 1) : 86400000;
      st.editor = root.KairoDraw.attach({
        host: host, svg: svg, tools: host.querySelector('.kc-tools'), W: W, H: H, ml: ml, mt: mt, pw: pw, ph: ph, step: step, data: data, X: X, Y: Y,
        pOfY: function (y) { return hi - (y - mt) / ph * (hi - lo); }, dec: dec, fmt: fmt, barMs: spec.barMs || bar, key: spec.key || st.sym, st: st.dt,
        zoomTo: function (t0, t1) { st.zoom = { t0: t0, t1: t1 }; mount(host, spec, st.sym); }
      });
    }
  }

  function mount(host, spec, sym) {
    var st = STATE[sym] || (STATE[sym] = { range: '1Y', emas: { 20: false, 50: false, 100: true, 200: false }, dt: {} });
    st.sym = sym;
    var candle = spec.kind === 'candle', intraday = !!spec.intraday, editor = !!root.KairoDraw;
    var narrow = (host.clientWidth || 0) < 560;
    var emo = editor ? '<div class="kd-emoji" hidden>' + root.KairoDraw.EMOJIS.map(function (e) { return '<button type="button" data-emoji="' + e + '">' + e + '</button>'; }).join('') + '</div>' : '';
    var selbox = editor ? '<div class="kd-sel" hidden><span class="kd-name"></span>' + root.KairoDraw.COLORS.map(function (c) { return '<button type="button" class="kd-c" data-color="' + c + '" style="background:' + c + '" aria-label="Colour ' + c + '"></button>'; }).join('') +
      '<button type="button" class="kd-del" data-del="1">Delete</button></div>' : '';
    host.innerHTML = '<div class="kc"><div class="kc-head"><b class="kc-title">' + esc(spec.title || TITLES[sym] || sym) + '</b><span class="kc-ohlc"></span></div>' +
      '<div class="kc-ctl">' + (intraday ? '' : '<div class="kc-ranges">' + ['3M', '6M', '1Y', 'MAX'].map(function (r) { return '<button type="button" data-r="' + r + '" class="' + (r === st.range && !st.zoom ? 'on' : '') + '">' + r + '</button>'; }).join('') + '</div>') +
      (candle ? '<div class="kc-emas">' + [20, 50, 100, 200].map(function (p) {
        return '<button type="button" data-e="' + p + '" class="' + (st.emas[p] ? 'on' : '') + '" style="--c:' + EMA_COL[p] + '">EMA ' + p + '</button>';
      }).join('') + '</div>' : '') + (st.zoom ? '<button type="button" class="kc-zr">Reset zoom</button>' : '') +
      (spec.onExpand ? '<button type="button" class="kc-full-btn" title="Open this chart full screen">\u2922 Full screen</button>' : '') + '</div>' +
      '<div class="kc-body' + (narrow ? ' kc-narrow' : '') + '">' + (editor ? '<div class="kc-tools">' + root.KairoDraw.toolbarHtml() + '</div>' : '') + '<div class="kc-plot"></div>' + selbox + emo + '</div>' +
      '<div class="kc-note">' + (intraday ? (spec.ivLabel || 'Intraday') : 'Daily') + ' ' + (candle ? 'candles' : 'values') + ' \u00B7 move over the chart for exact values' + (editor ? ' \u00B7 drawings are saved in this browser' : '') + '. Chart data may be delayed; not a trading recommendation.</div></div>';
    draw(host, spec, st);
    host.querySelectorAll('.kc-ranges button').forEach(function (b) {
      b.addEventListener('click', function () { st.range = b.getAttribute('data-r'); st.zoom = null; mount(host, spec, sym); });
    });
    host.querySelectorAll('.kc-emas button').forEach(function (b) {
      b.addEventListener('click', function () { var p = +b.getAttribute('data-e'); st.emas[p] = !st.emas[p]; mount(host, spec, sym); });
    });
    var zr = host.querySelector('.kc-zr'); if (zr) zr.addEventListener('click', function () { st.zoom = null; mount(host, spec, sym); });
    var fb = host.querySelector('.kc-full-btn'); if (fb) fb.addEventListener('click', function () { spec.onExpand(); });
  }

  /* a full-screen copy of a chart (same drawings) for comfortable editing */
  function expand(spec, key) {
    var ov = document.createElement('div'); ov.className = 'kc-full';
    ov.innerHTML = '<div class="kc-full-in"><button type="button" class="kc-full-x" aria-label="Close">\u2715 Close</button><div class="kc-full-host"></div></div>';
    document.body.appendChild(ov);
    var full = Object.assign({}, spec, { onExpand: null, window: Math.max(spec.window || 120, 200), height: Math.max(380, Math.round(window.innerHeight * 0.66)) });
    var fk = key + ':full';
    mount(ov.querySelector('.kc-full-host'), full, fk);
    function close() { document.removeEventListener('keydown', esc2); if (ov.parentNode) ov.parentNode.removeChild(ov); }
    function esc2(e) { if (e.key === 'Escape' && !ov.querySelector('[data-busy="1"]')) close(); }
    ov.querySelector('.kc-full-x').addEventListener('click', close);
    document.addEventListener('keydown', esc2);
  }
  api.mount = function (host, spec, key) { return mount(host, spec, key); };
  api.expand = expand;

  function closeAll() {
    document.querySelectorAll('.wl-chart-row').forEach(function (r) { r.parentNode.removeChild(r); });
    document.querySelectorAll('.wl-row.open').forEach(function (r) { r.classList.remove('open'); });
  }

  /* On a wide screen the chart lives in a pane beside the list (like a trading terminal); on a narrow one it opens under the row. */
  function paneHost() {
    var pane = document.getElementById('wl-pane');
    return pane && pane.offsetParent !== null && pane.offsetWidth > 240 ? pane : null;
  }

  function openFor(row) {
    var sym = row.getAttribute('data-sym');
    closeAll();
    OPEN = sym; row.classList.add('open');
    var pane = paneHost(), host;
    if (pane) {
      host = pane;
      host.classList.add('kc-host');
    } else {
      var tr = document.createElement('tr'); tr.className = 'wl-chart-row';
      var td = document.createElement('td'); td.colSpan = 4;
      host = document.createElement('div'); host.className = 'kc-host';
      td.appendChild(host); tr.appendChild(td); row.parentNode.insertBefore(tr, row.nextSibling);
    }
    host.innerHTML = '<div class="kc-note">Loading chart…</div>';
    getSeries(row).then(function (spec) { if (OPEN === sym && host.isConnected) mount(host, spec, sym); }).catch(function (e) {
      host.innerHTML = '<div class="kc-note">' + (e && e.message === 'none'
        ? 'No chart for ' + esc(sym) + ': there is no free historical data feed for this one, and nothing is drawn from estimates.'
        : 'Could not load the chart data right now. Try again in a moment.') + '</div>';
    });
  }

  /* ---- reorder: drag the handle (mouse or touch) or use the arrow keys; the order is remembered in this browser ---- */
  var ORDER_KEY = 'kairo.wl.order', SERVER_ORDER = null;
  function loadOrder() { try { var v = JSON.parse(localStorage.getItem(ORDER_KEY) || 'null'); return Array.isArray(v) ? v : null; } catch (e) { return null; } }
  function saveOrder(a) { try { if (a) localStorage.setItem(ORDER_KEY, JSON.stringify(a)); else localStorage.removeItem(ORDER_KEY); } catch (e) { /* private mode: order just isn't remembered */ } }
  function isRow(n) { return n.classList && n.classList.contains('wl-row'); }
  function tbodyEl() { return document.querySelector('.wl-table tbody'); }
  function rowOrder() { return [].map.call(document.querySelectorAll('.wl-table tr.wl-row'), function (r) { return r.getAttribute('data-sym'); }); }
  function orderBy(list) {                             // group headings stay where they are; only the rows move between the row slots
    var tb = tbodyEl(); if (!tb || !list) return;
    var kids = [].slice.call(tb.children), rows = kids.filter(isRow), pos = {};
    list.forEach(function (s, i) { pos[s] = i; });
    var sorted = rows.slice().sort(function (a, b) {
      var pa = pos[a.getAttribute('data-sym')], pb = pos[b.getAttribute('data-sym')];
      if (pa == null && pb == null) return rows.indexOf(a) - rows.indexOf(b);
      return pa == null ? 1 : pb == null ? -1 : pa - pb;
    });
    var i = 0;
    kids.forEach(function (k) { tb.appendChild(isRow(k) ? sorted[i++] : k); });
  }
  function updateReset() {
    var b = document.querySelector('.wl-reset'); if (b) b.hidden = !loadOrder();
  }
  function persist() { saveOrder(rowOrder()); updateReset(); }
  function dropInlineCharts() { document.querySelectorAll('.wl-chart-row').forEach(function (r) { r.parentNode.removeChild(r); }); }

  function bindReorder() {
    var reset = document.querySelector('.wl-reset');
    if (reset) reset.addEventListener('click', function () { saveOrder(null); orderBy(SERVER_ORDER); updateReset(); });
    document.querySelectorAll('.wl-drag').forEach(function (h) {
      var row = h.closest('tr');
      h.addEventListener('click', function (e) { e.stopPropagation(); });
      h.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        e.preventDefault(); e.stopPropagation(); dropInlineCharts();
        var tb = row.parentNode, rows = [].filter.call(tb.children, isRow), i = rows.indexOf(row);
        if (e.key === 'ArrowUp' && i > 0) tb.insertBefore(row, rows[i - 1]);
        else if (e.key === 'ArrowDown' && i < rows.length - 1) tb.insertBefore(row, rows[i + 1].nextSibling);
        persist(); h.focus();
      });
      h.addEventListener('pointerdown', function (e) {
        e.preventDefault(); e.stopPropagation(); dropInlineCharts();
        var tb = row.parentNode;
        row.classList.add('dragging');
        try { h.setPointerCapture(e.pointerId); } catch (x) { /* older browsers: move events still arrive */ }
        function move(ev) {
          var y = ev.clientY, rows = [].filter.call(tb.children, isRow).filter(function (r) { return r !== row; });
          var placed = false;
          for (var i = 0; i < rows.length; i++) {
            var b = rows[i].getBoundingClientRect();
            if (y < b.top + b.height / 2) { if (row.nextElementSibling !== rows[i]) tb.insertBefore(row, rows[i]); placed = true; break; }
          }
          if (!placed && rows.length && row.previousElementSibling !== rows[rows.length - 1]) tb.insertBefore(row, rows[rows.length - 1].nextSibling);
          if (ev.clientY < 60) window.scrollBy(0, -14); else if (ev.clientY > window.innerHeight - 60) window.scrollBy(0, 14);   // scroll while dragging near the edges
        }
        function end() {
          h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', end); h.removeEventListener('pointercancel', end);
          row.classList.remove('dragging'); persist();
        }
        h.addEventListener('pointermove', move); h.addEventListener('pointerup', end); h.addEventListener('pointercancel', end);
      });
    });
  }

  root.kairoInitCharts = function (charts) {
    DATA = charts || {};
    dropInlineCharts();
    if (document.querySelector('.wl-table')) { SERVER_ORDER = rowOrder(); orderBy(loadOrder()); bindReorder(); updateReset(); }
    document.querySelectorAll('.wl-table tr.wl-row').forEach(function (row) {
      row.addEventListener('click', function (ev) {
        if (ev.target.closest('.kc-host')) return;
        if (row.classList.contains('open') && !paneHost()) { closeAll(); OPEN = null; return; }     // inline mode toggles; the pane always shows a selection
        openFor(row);
      });
    });
    if (OPEN) {                                            // keep an open chart across the section's periodic refresh
      var row = document.querySelector('.wl-table tr.wl-row[data-sym="' + OPEN.replace(/"/g, '') + '"]');
      if (row) openFor(row); else OPEN = null;
    }
    ensureSelection();
  };

  /* With the pane visible there is always a chart: TOTAL (or the first row) is selected by default. */
  function ensureSelection() {
    if (!paneHost() || OPEN) return;
    var row = document.querySelector('.wl-table tr.wl-row[data-sym="TOTAL"]') || document.querySelector('.wl-table tr.wl-row');
    if (row) openFor(row);
  }
  if (typeof document !== 'undefined') {
    // the watchlist sits in a hidden tab until it is chosen: pick the default chart when it becomes visible
    document.addEventListener('change', function (e) {
      if (e.target && e.target.type === 'radio') setTimeout(ensureSelection, 60);
    });
  }
  var rt; window.addEventListener('resize', function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      var row = OPEN && document.querySelector('.wl-table tr.wl-row[data-sym="' + OPEN.replace(/"/g, '') + '"]');
      if (row && row.classList.contains('open')) openFor(row);
    }, 250);
  });
})(typeof window !== 'undefined' ? window : globalThis);
