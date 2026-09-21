/* KairoDraw: a TradingView-style chart editor for Kairo's SVG charts.
 *
 * Tools (left toolbar, same set and order as TradingView's basic drawing bar): cursor, trend line, Fibonacci retracement,
 * path / pattern, long-short position, brush, text, emoji, measure, zoom in, magnet, lock, hide, remove all.
 * Drawings are stored in this browser (localStorage) as TIME and PRICE points, so they stay put when the range, zoom or
 * timeframe changes. Nothing is sent anywhere. The chart engine (chart.js) calls attach() after it draws; this file knows
 * nothing about where the data comes from. Plain SVG, no libraries.
 *
 * Pure helpers are exported for node tests; everything that touches the DOM is skipped there. */
(function (root) {
  'use strict';

  /* ---------------- pure helpers ---------------- */
  var FIB = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  function fibLevels(p0, p1) { return FIB.map(function (r) { return { ratio: r, price: p1 - (p1 - p0) * r }; }); }
  function spanText(ms) {
    ms = Math.abs(ms);
    var m = Math.round(ms / 60000);
    if (m < 60) return m + 'm';
    var h = Math.floor(m / 60);
    if (h < 48) return h + 'h ' + (m % 60) + 'm';
    var d = Math.floor(h / 24);
    return d + 'd ' + (h % 24) + 'h';
  }
  function measure(a, b, barMs) {
    var dp = b.p - a.p;
    return { dp: dp, pct: a.p ? dp / a.p * 100 : null, bars: barMs ? Math.round((b.t - a.t) / barMs) : null, ms: b.t - a.t };
  }
  function positionStats(entry, stop, target) {
    var risk = Math.abs(entry - stop), reward = Math.abs(target - entry);
    return { side: target >= entry ? 'LONG' : 'SHORT', risk: risk, reward: reward, rr: risk ? reward / risk : null,
             riskPct: entry ? risk / entry * 100 : null, rewardPct: entry ? reward / entry * 100 : null };
  }
  function distToSegment(px, py, x1, y1, x2, y2) {
    var dx = x2 - x1, dy = y2 - y1, l2 = dx * dx + dy * dy;
    var t = l2 ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / l2)) : 0;
    var cx = x1 + t * dx, cy = y1 + t * dy;
    return Math.sqrt((px - cx) * (px - cx) + (py - cy) * (py - cy));
  }
  /* the open/high/low/close of a candle that is closest to price p (used by the magnet) */
  function nearestOHLC(p, candle) { return [candle[1], candle[2], candle[3], candle[4]].reduce(function (b, v) { return Math.abs(v - p) < Math.abs(b - p) ? v : b; }); }
  function simplify(pts, minDist) {           // thin out a freehand stroke so it stays small in storage
    var out = [];
    pts.forEach(function (p, i) {
      var l = out[out.length - 1];
      if (!l || i === pts.length - 1 || Math.abs(p.x - l.x) + Math.abs(p.y - l.y) >= minDist) out.push(p);
    });
    return out;
  }
  var PREFIX = 'kairo.draw.v1.';
  function loadDrawings(key) {
    try { var v = JSON.parse(localStorage.getItem(PREFIX + key) || '[]'); return Array.isArray(v) ? v.filter(function (d) { return d && d.type && Array.isArray(d.pts); }) : []; } catch (e) { return []; }
  }
  function saveDrawings(key, list) {
    try { if (list.length) localStorage.setItem(PREFIX + key, JSON.stringify(list)); else localStorage.removeItem(PREFIX + key); } catch (e) { /* private mode: drawings just are not remembered */ }
  }
  function loadPrefs() { try { return JSON.parse(localStorage.getItem(PREFIX + 'prefs') || '{}') || {}; } catch (e) { return {}; } }
  function savePrefs(p) { try { localStorage.setItem(PREFIX + 'prefs', JSON.stringify({ magnet: !!p.magnet, lock: !!p.lock, hide: !!p.hide })); } catch (e) { /* ignore */ } }

  var api = { fibLevels: fibLevels, spanText: spanText, measure: measure, positionStats: positionStats, distToSegment: distToSegment, nearestOHLC: nearestOHLC,
              simplify: simplify, loadDrawings: loadDrawings, saveDrawings: saveDrawings, FIB: FIB };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }
  root.KairoDraw = api;

  /* ---------------- toolbar ---------------- */
  var S = 'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"';
  function ico(inner) { return '<svg viewBox="0 0 24 24" width="22" height="22" ' + S + ' aria-hidden="true">' + inner + '</svg>'; }
  var ICONS = {
    cursor: ico('<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>'),
    trend: ico('<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M7.5 16.5 16.5 7.5"/>'),
    fib: ico('<path d="M4 5h16M4 10h16M8 15h12M8 20h12"/><path d="M4 5v15"/>'),
    path: ico('<circle cx="5" cy="17" r="1.8"/><circle cx="9" cy="6" r="1.8"/><circle cx="15" cy="15" r="1.8"/><circle cx="19" cy="5" r="1.8"/><path d="M6 15.5 8.4 7.6M10.4 7 14 13.6M15.6 13.4 18.4 6.6"/>'),
    position: ico('<rect x="5" y="4" width="14" height="7" fill="#089981" fill-opacity=".35"/><rect x="5" y="11" width="14" height="8" fill="#f23645" fill-opacity=".35"/><path d="M5 11h14"/>'),
    brush: ico('<path d="M4 19c3 0 3-3 5-3s2 3-1 4c-2 .7-4 0-4-1z" fill="currentColor" fill-opacity=".2"/><path d="M9 16 19 5c.8-.8 2 .3 1.2 1.2L11 17"/>'),
    text: ico('<path d="M6 6h12M12 6v13M9 19h6"/>'),
    emoji: ico('<circle cx="12" cy="12" r="8.5"/><circle cx="9" cy="10" r=".8" fill="currentColor"/><circle cx="15" cy="10" r=".8" fill="currentColor"/><path d="M8.5 14c1 1.7 2.2 2.4 3.5 2.4s2.5-.7 3.5-2.4"/>'),
    measure: ico('<rect x="3" y="9" width="18" height="7" rx="1" transform="rotate(-35 12 12)"/><path d="M7.4 14.1l1.2-.9M10 12.3l1.2-.9M12.6 10.5l1.2-.9M15.2 8.7l1.2-.9"/>'),
    zoom: ico('<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M10.5 8v5M8 10.5h5"/>'),
    magnet: ico('<path d="M6 4v8a6 6 0 0 0 12 0V4h-3.5v8a2.5 2.5 0 0 1-5 0V4z"/><path d="M6 8h3.5M14.5 8H18"/>'),
    lock: ico('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
    unlock: ico('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>'),
    eye: ico('<path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/>'),
    eyeoff: ico('<path d="M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6"/><path d="M4 20 20 4"/>'),
    trash: ico('<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6"/>')
  };
  var TOOLS = [['cursor', 'Cursor'], ['trend', 'Trend line: click two points, or drag'], ['fib', 'Fib retracement: click two points, or drag'],
               ['path', 'Path: click each point, double-click to finish'], ['position', 'Long / short position: click entry, stop, then target'],
               ['brush', 'Brush: drag to draw freehand'], ['text', 'Text: click to place a note'], ['emoji', 'Emoji: pick one, then click the chart'],
               ['measure', 'Measure: click two points (price, %, bars, time)'], ['zoom', 'Zoom in: drag a box']];
  var EMOJIS = ['🚀', '📈', '📉', '⚠️', '🎯', '⭐', '🔥', '✅', '❌', '👀', '💰', '😀'];
  var COLORS = ['#2962ff', '#089981', '#f23645', '#f0b90b', '#b39ddb', '#e0e3eb'];
  var NS = 'http://www.w3.org/2000/svg';
  var uid = 0;

  function toolbarHtml() {
    var h = TOOLS.map(function (t) { return '<button type="button" class="kd-b" data-tool="' + t[0] + '" title="' + t[1] + '" aria-label="' + t[1] + '">' + ICONS[t[0]] + '</button>'; }).join('');
    h += '<span class="kd-sep"></span>';
    h += '<button type="button" class="kd-b" data-toggle="magnet" title="Magnet: snap to candle highs, lows, opens and closes" aria-label="Magnet">' + ICONS.magnet + '</button>';
    h += '<button type="button" class="kd-b" data-toggle="lock" title="Lock drawings (no edits)" aria-label="Lock drawings"><span class="kd-i">' + ICONS.unlock + '</span></button>';
    h += '<button type="button" class="kd-b" data-toggle="hide" title="Hide / show drawings" aria-label="Hide drawings"><span class="kd-i">' + ICONS.eye + '</span></button>';
    h += '<span class="kd-sep"></span>';
    h += '<button type="button" class="kd-b" data-act="clear" title="Remove the selected drawing, or all drawings" aria-label="Remove drawings">' + ICONS.trash + '</button>';
    return h;
  }

  /* ---------------- editor ---------------- */
  function el(name, attrs, text) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  /* ctx: {host, svg, tools (toolbar element), W, H, ml, mt, pw, ph, step, data, X(i), Y(v), pOfY(y), dec, fmt(v,d), barMs, key, st, zoomTo(t0,t1)} */
  function attach(ctx) {
    var svg = ctx.svg, data = ctx.data, n = data.length, host = ctx.host, st = ctx.st;
    var prefs = loadPrefs();
    ['magnet', 'lock', 'hide'].forEach(function (k) { if (st[k] == null) st[k] = !!prefs[k]; });
    if (!st.tool) st.tool = 'cursor';
    if (!st.emoji) st.emoji = EMOJIS[0];
    var bar = ctx.barMs || (n > 1 ? (data[n - 1][0] - data[0][0]) / (n - 1) : 86400000);
    var drawings = loadDrawings(ctx.key), sel = null, cur = null, busyDrag = false, id = ++uid;
    var layer = el('g', { class: 'dt-layer', 'clip-path': 'url(#dtclip' + id + ')' });
    var defs = el('defs'); var cp = el('clipPath', { id: 'dtclip' + id }); cp.appendChild(el('rect', { x: ctx.ml, y: ctx.mt, width: ctx.pw, height: ctx.ph })); defs.appendChild(cp);
    var hit = el('rect', { class: 'dt-hit', x: ctx.ml, y: ctx.mt, width: ctx.pw, height: ctx.ph, fill: 'transparent', style: 'display:none;touch-action:none;cursor:crosshair' });
    svg.appendChild(defs); svg.appendChild(layer); svg.appendChild(hit);
    var selBox = host.querySelector('.kd-sel');

    /* ---- coordinate mapping (time <-> x, price <-> y) ---- */
    function idxOfT(t) {
      if (t <= data[0][0]) return (t - data[0][0]) / bar;
      if (t >= data[n - 1][0]) return n - 1 + (t - data[n - 1][0]) / bar;
      var lo = 0, hi = n - 1;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (data[mid][0] <= t) lo = mid; else hi = mid; }
      return lo + (t - data[lo][0]) / (data[hi][0] - data[lo][0]);
    }
    function tOfX(x) {
      var f = (x - ctx.ml) / ctx.step - 0.5;
      if (f <= 0) return data[0][0] + f * bar;
      if (f >= n - 1) return data[n - 1][0] + (f - (n - 1)) * bar;
      var i = Math.floor(f);
      return data[i][0] + (data[i + 1][0] - data[i][0]) * (f - i);
    }
    function xOfT(t) { return ctx.X(idxOfT(t)); }
    function yOfP(p) { return ctx.Y(p); }
    function svgPt(ev) {
      var r = svg.getBoundingClientRect(), s = ctx.W / r.width;
      return { x: (ev.clientX - r.left) * s, y: (ev.clientY - r.top) * s };
    }
    function point(ev, raw) {
      var q = svgPt(ev), x = Math.max(ctx.ml, Math.min(ctx.ml + ctx.pw, q.x)), y = Math.max(ctx.mt, Math.min(ctx.mt + ctx.ph, q.y));
      var t = tOfX(x), p = ctx.pOfY(y);
      if (st.magnet && !raw) {
        var i = Math.max(0, Math.min(n - 1, Math.round((x - ctx.ml) / ctx.step - 0.5)));
        t = data[i][0];
        var c = data[i];
        var cand = c.length >= 5 ? nearestOHLC(p, c) : c[1];
        if (Math.abs(yOfP(cand) - y) < 16) p = cand;
        x = ctx.X(i); y = yOfP(p);
      }
      return { x: x, y: y, t: t, p: p };
    }

    /* ---- storage ---- */
    function persist() { saveDrawings(ctx.key, drawings); }
    function setBusy(b) { host.setAttribute('data-busy', b ? '1' : '0'); }

    /* ---- drawing renderers ---- */
    function colorOf(d) { return d.color || COLORS[0]; }
    function px(d) { return d.pts.map(function (q) { return { x: xOfT(q.t), y: yOfP(q.p) }; }); }
    function line(x1, y1, x2, y2, attrs) { return el('line', Object.assign({ x1: x1, y1: y1, x2: x2, y2: y2 }, attrs || {})); }
    function label(x, y, text, attrs) {
      var g = el('g', { 'pointer-events': 'none' });
      var t = el('text', Object.assign({ x: x, y: y, 'font-size': 11, fill: '#fff' }, attrs || {}), text);
      g.appendChild(el('rect', { x: (attrs && attrs['text-anchor'] === 'end') ? x - text.length * 6.2 - 6 : x - 4, y: y - 12, width: text.length * 6.2 + 8, height: 16, rx: 3, fill: (attrs && attrs.bg) || '#2a2e39' }));
      g.appendChild(t); return g;
    }
    function shape(d, isSel) {
      var g = el('g', { 'data-dt-id': d.id, style: 'touch-action:none' }), c = colorOf(d), p = px(d), sw = isSel ? 3 : 2;
      function hitLine(x1, y1, x2, y2) { g.appendChild(line(x1, y1, x2, y2, { stroke: 'transparent', 'stroke-width': 14, 'pointer-events': 'stroke', style: 'cursor:move' })); }
      if (d.type === 'trend' && p.length >= 2) {
        g.appendChild(line(p[0].x, p[0].y, p[1].x, p[1].y, { stroke: c, 'stroke-width': sw })); hitLine(p[0].x, p[0].y, p[1].x, p[1].y);
      } else if (d.type === 'measure' && p.length >= 2) {
        var m = measure(d.pts[0], d.pts[1], bar), up = m.dp >= 0, mc = up ? '#089981' : '#f23645';
        g.appendChild(el('rect', { x: Math.min(p[0].x, p[1].x), y: Math.min(p[0].y, p[1].y), width: Math.abs(p[1].x - p[0].x), height: Math.abs(p[1].y - p[0].y), fill: mc, 'fill-opacity': 0.12, stroke: mc, 'stroke-dasharray': '4 3' }));
        g.appendChild(line(p[0].x, p[0].y, p[1].x, p[1].y, { stroke: mc, 'stroke-width': 1.6 }));
        var txt = (m.dp >= 0 ? '+' : '') + ctx.fmt(m.dp, ctx.dec) + (m.pct != null ? ' (' + (m.pct >= 0 ? '+' : '') + m.pct.toFixed(2) + '%)' : '') + '  ·  ' + (m.bars != null ? m.bars + ' bars, ' : '') + spanText(m.ms);
        g.appendChild(label(Math.min(ctx.ml + ctx.pw - txt.length * 6.2 - 10, Math.max(ctx.ml + 4, p[1].x)), Math.max(ctx.mt + 14, p[1].y + (up ? -8 : 20)), txt, { bg: mc }));
      } else if (d.type === 'fib' && p.length >= 2) {
        var lv = fibLevels(d.pts[0].p, d.pts[1].p), xl = Math.min(p[0].x, p[1].x), xr = Math.max(p[0].x, p[1].x);
        if (xr - xl < 60) xr = xl + 60;
        lv.forEach(function (L, i) {
          var y = yOfP(L.price), ny = i < lv.length - 1 ? yOfP(lv[i + 1].price) : null;
          if (ny != null) g.appendChild(el('rect', { x: xl, y: Math.min(y, ny), width: xr - xl, height: Math.abs(ny - y), fill: c, 'fill-opacity': i % 2 ? 0.05 : 0.11 }));
          g.appendChild(line(xl, y, xr, y, { stroke: c, 'stroke-width': L.ratio === 0 || L.ratio === 1 ? 1.6 : 1, 'stroke-opacity': 0.9 }));
          g.appendChild(el('text', { x: xl + 4, y: y - 3, 'font-size': 10.5, fill: c, 'pointer-events': 'none' }, L.ratio + '  (' + ctx.fmt(L.price, ctx.dec) + ')'));
          g.appendChild(line(xl, y, xr, y, { stroke: 'transparent', 'stroke-width': 10, 'pointer-events': 'stroke', style: 'cursor:move' }));
        });
        g.appendChild(line(p[0].x, p[0].y, p[1].x, p[1].y, { stroke: c, 'stroke-dasharray': '4 4', 'stroke-width': 1 }));
      } else if ((d.type === 'path' || d.type === 'brush') && p.length >= 2) {
        var pts = p.map(function (q) { return q.x.toFixed(1) + ',' + q.y.toFixed(1); }).join(' ');
        g.appendChild(el('polyline', { points: pts, fill: 'none', stroke: c, 'stroke-width': d.type === 'brush' ? 2.2 : sw, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
        g.appendChild(el('polyline', { points: pts, fill: 'none', stroke: 'transparent', 'stroke-width': 14, 'pointer-events': 'stroke', style: 'cursor:move' }));
        if (d.type === 'path') p.forEach(function (q) { g.appendChild(el('circle', { cx: q.x, cy: q.y, r: 2.6, fill: c, 'pointer-events': 'none' })); });
      } else if (d.type === 'position' && p.length >= 3) {
        var e = d.pts[0].p, sp = d.pts[1].p, tp = d.pts[2].p, ps = positionStats(e, sp, tp), x0 = p[0].x, w = Math.max(40, Math.min(ctx.step * 16, ctx.ml + ctx.pw - x0));
        var ye = yOfP(e), ys = yOfP(sp), yt = yOfP(tp);
        g.appendChild(el('rect', { x: x0, y: Math.min(ye, yt), width: w, height: Math.abs(yt - ye), fill: '#089981', 'fill-opacity': 0.22, stroke: '#089981', style: 'cursor:move' }));
        g.appendChild(el('rect', { x: x0, y: Math.min(ye, ys), width: w, height: Math.abs(ys - ye), fill: '#f23645', 'fill-opacity': 0.22, stroke: '#f23645', style: 'cursor:move' }));
        g.appendChild(line(x0, ye, x0 + w, ye, { stroke: '#787b86', 'stroke-width': 1.4 }));
        g.appendChild(label(x0 + 4, Math.min(yt, ye) + 14, (ps.side === 'LONG' ? 'Target ' : 'Target ') + '+' + ps.rewardPct.toFixed(2) + '%', { bg: '#089981' }));
        g.appendChild(label(x0 + 4, Math.max(ys, ye) - 4, 'Stop -' + ps.riskPct.toFixed(2) + '%', { bg: '#f23645' }));
        g.appendChild(label(x0 + w / 2 - 34, ye - 4, ps.side + '  R:R 1 : ' + (ps.rr != null ? ps.rr.toFixed(2) : 'n/a')));
      } else if (d.type === 'text') {
        var tx = p[0].x, ty = p[0].y, s = d.text || 'Text';
        g.appendChild(el('rect', { x: tx - 4, y: ty - 15, width: s.length * 7.4 + 10, height: 22, rx: 4, fill: '#131722', 'fill-opacity': 0.85, stroke: c, style: 'cursor:move' }));
        g.appendChild(el('text', { x: tx + 1, y: ty, 'font-size': 13, 'font-weight': 700, fill: c, 'pointer-events': 'none' }, s));
      } else if (d.type === 'emoji') {
        g.appendChild(el('text', { x: p[0].x, y: p[0].y + 8, 'font-size': 24, 'text-anchor': 'middle', style: 'cursor:move' }, d.text || '⭐'));
      }
      if (isSel && !st.lock && d.type !== 'measure') {
        p.slice(0, d.type === 'brush' ? 0 : p.length).forEach(function (q, i) {
          var hx = q.x, hy = q.y;
          if (d.type === 'position') { hx = p[0].x + Math.max(40, Math.min(ctx.step * 16, ctx.ml + ctx.pw - p[0].x)); if (i === 0) hx = p[0].x; hy = yOfP(d.pts[i].p); }
          g.appendChild(el('circle', { cx: hx, cy: hy, r: 5.5, fill: '#fff', stroke: '#2962ff', 'stroke-width': 2, 'data-h': i, style: 'cursor:grab;touch-action:none' }));
        });
      }
      return g;
    }
    function render() {
      while (layer.firstChild) layer.removeChild(layer.firstChild);
      var hidden = st.hide;
      layer.style.display = hidden ? 'none' : '';
      drawings.forEach(function (d) { layer.appendChild(shape(d, d.id === sel)); });
      if (transient) layer.appendChild(shape(transient, false));
      if (cur) {
        if (cur.type === 'zoombox') {
          var a = cur.a, b = cur.b || cur.a;
          layer.appendChild(el('rect', { x: Math.min(a.x, b.x), y: ctx.mt, width: Math.abs(b.x - a.x), height: ctx.ph, fill: '#2962ff', 'fill-opacity': 0.14, stroke: '#2962ff', 'stroke-dasharray': '4 3', 'pointer-events': 'none' }));
        } else {
          var g = shape(cur, true); g.setAttribute('pointer-events', 'none'); layer.appendChild(g);
        }
      }
      refreshSel();
    }

    /* ---- toolbar state ---- */
    function refreshTools() {
      var tb = ctx.tools; if (!tb) return;
      tb.querySelectorAll('[data-tool]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-tool') === st.tool); b.disabled = (b.getAttribute('data-tool') !== 'cursor' && b.getAttribute('data-tool') !== 'zoom' && st.lock); });
      var m = tb.querySelector('[data-toggle=magnet]'); if (m) m.classList.toggle('on', !!st.magnet);
      var l = tb.querySelector('[data-toggle=lock]'); if (l) { l.classList.toggle('on', !!st.lock); l.querySelector('.kd-i').innerHTML = st.lock ? ICONS.lock : ICONS.unlock; }
      var h = tb.querySelector('[data-toggle=hide]'); if (h) { h.classList.toggle('on', !!st.hide); h.querySelector('.kd-i').innerHTML = st.hide ? ICONS.eyeoff : ICONS.eye; }
      hit.style.display = (st.tool !== 'cursor' && !(st.lock && st.tool !== 'zoom')) ? '' : 'none';
      hit.style.cursor = st.tool === 'zoom' ? 'zoom-in' : 'crosshair';
      host.setAttribute('data-tool', st.tool);
    }
    function refreshSel() {
      if (!selBox) return;
      var d = drawings.filter(function (x) { return x.id === sel; })[0];
      if (!d || st.lock) { selBox.hidden = true; return; }
      selBox.hidden = false;
      selBox.querySelector('.kd-name').textContent = ({ trend: 'Trend line', fib: 'Fib retracement', path: 'Path', brush: 'Brush', position: 'Position', text: 'Text', emoji: 'Emoji' })[d.type] || 'Drawing';
      selBox.querySelectorAll('[data-color]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-color') === colorOf(d)); });
    }
    function setTool(t) {
      if (st.lock && t !== 'cursor' && t !== 'zoom') return;
      if (t !== 'cursor' && t !== 'zoom' && st.hide) { st.hide = false; savePrefs(st); }
      cancelCur(); transient = null; st.tool = t; sel = t === 'cursor' ? sel : null;
      var pop = host.querySelector('.kd-emoji'); if (pop) pop.hidden = t !== 'emoji-pick';
      refreshTools(); render();
    }
    function cancelCur() { cur = null; busyDrag = false; setBusy(false); }
    function finish() {
      if (!cur) return;
      var d = cur; cur = null;
      if (d.type === 'path') { d.pts = d.pts.slice(0, -1); if (d.pts.length < 2) { setBusy(false); render(); return; } }
      if (d.type === 'brush') d.pts = d.pts.filter(function (q, i) { return true; });
      d.id = 'd' + Date.now().toString(36) + Math.floor(Math.random() * 1e4);
      d.color = d.color || st.color || COLORS[0];
      if (d.type !== 'measure') { drawings.push(d); sel = d.id; persist(); } else { transient = d; }
      setBusy(false); st.tool = d.type === 'measure' ? 'measure' : 'cursor'; refreshTools(); render();
    }
    var transient = null;

    /* ---- pointer handling while a drawing tool is active ---- */
    var downAt = null;
    function need(d) { return d.type === 'position' ? 3 : 2; }
    hit.addEventListener('pointerdown', function (ev) {
      if (st.lock && st.tool !== 'zoom') return;
      ev.preventDefault(); ev.stopPropagation();
      var p = point(ev), tool = st.tool;
      if (tool === 'measure' && transient) { transient = null; }
      if (tool === 'text') {
        var s = window.prompt('Text:', ''); if (s) { cur = { type: 'text', pts: [{ t: p.t, p: p.p }], text: s.slice(0, 60) }; finish(); } return;
      }
      if (tool === 'emoji') { cur = { type: 'emoji', pts: [{ t: p.t, p: p.p }], text: st.emoji }; finish(); return; }
      if (tool === 'zoom') { cur = { type: 'zoombox', a: p, b: p }; setBusy(true); downAt = p; try { hit.setPointerCapture(ev.pointerId); } catch (e) { /* ok */ } return; }
      if (tool === 'brush') { cur = { type: 'brush', pts: [{ t: p.t, p: p.p, x: p.x, y: p.y }] }; setBusy(true); downAt = p; try { hit.setPointerCapture(ev.pointerId); } catch (e) { /* ok */ } return; }
      if (tool === 'path') {
        if (!cur) { cur = { type: 'path', pts: [{ t: p.t, p: p.p }, { t: p.t, p: p.p }] }; setBusy(true); }
        else { cur.pts[cur.pts.length - 1] = { t: p.t, p: p.p }; cur.pts.push({ t: p.t, p: p.p }); }
        render(); return;
      }
      if (tool === 'position') {
        if (!cur) { cur = { type: 'position', pts: [{ t: p.t, p: p.p }, { t: p.t, p: p.p }, { t: p.t, p: p.p }], stage: 1 }; setBusy(true); }
        else if (cur.stage === 1) { cur.pts[1] = { t: cur.pts[0].t, p: p.p }; cur.pts[2] = { t: cur.pts[0].t, p: p.p }; cur.stage = 2; }
        else { cur.pts[2] = { t: cur.pts[0].t, p: p.p }; delete cur.stage; finish(); return; }
        render(); return;
      }
      // two-point tools: trend, fib, measure (click-click or press-drag-release)
      if (!cur) { cur = { type: tool, pts: [{ t: p.t, p: p.p }, { t: p.t, p: p.p }] }; setBusy(true); downAt = p; try { hit.setPointerCapture(ev.pointerId); } catch (e) { /* ok */ } render(); }
      else { cur.pts[1] = { t: p.t, p: p.p }; finish(); }
    });
    hit.addEventListener('pointermove', function (ev) {
      if (!cur) return;
      var p = point(ev);
      if (cur.type === 'zoombox') { cur.b = p; }
      else if (cur.type === 'brush') { if (ev.buttons || downAt) { cur.pts.push({ t: p.t, p: p.p, x: p.x, y: p.y }); } }
      else if (cur.type === 'path') { cur.pts[cur.pts.length - 1] = { t: p.t, p: p.p }; }
      else if (cur.type === 'position') {
        if (cur.stage === 1) { cur.pts[1] = { t: cur.pts[0].t, p: p.p }; cur.pts[2] = { t: cur.pts[0].t, p: p.p }; }
        else { cur.pts[2] = { t: cur.pts[0].t, p: p.p }; }
      } else { cur.pts[1] = { t: p.t, p: p.p }; }
      render();
    });
    function up(ev) {
      if (!cur || !downAt) return;
      var p = point(ev, true), moved = Math.abs(p.x - downAt.x) + Math.abs(p.y - downAt.y);
      if (cur.type === 'zoombox') {
        var a = cur.a, b = cur.b || cur.a; cur = null; downAt = null; setBusy(false); st.tool = 'cursor'; refreshTools();
        if (Math.abs(b.x - a.x) > 10) { var t0 = Math.min(tOfX(a.x), tOfX(b.x)), t1 = Math.max(tOfX(a.x), tOfX(b.x)); if (ctx.zoomTo) ctx.zoomTo(t0, t1); }
        render(); return;
      }
      if (cur.type === 'brush') { downAt = null; if (cur.pts.length > 2) { cur.pts = simplify(cur.pts, 3).map(function (q) { return { t: q.t, p: q.p }; }); finish(); } else { cancelCur(); render(); } return; }
      if (moved > 8 && (cur.type === 'trend' || cur.type === 'fib' || cur.type === 'measure')) { downAt = null; cur.pts[1] = { t: p.t, p: p.p }; finish(); }
      else downAt = null;                                   // a plain click: wait for the second click
    }
    hit.addEventListener('pointerup', up);
    hit.addEventListener('pointercancel', function () { downAt = null; });
    hit.addEventListener('dblclick', function (ev) { if (cur && cur.type === 'path') { ev.preventDefault(); finish(); } });

    /* ---- cursor mode: select, move, edit ---- */
    svg.addEventListener('pointerdown', function (ev) {
      if (st.tool !== 'cursor' || st.hide) return;
      var t = ev.target, g = t.closest ? t.closest('[data-dt-id]') : null;
      if (!g) { if (sel) { sel = null; render(); } return; }
      if (st.lock) return;
      ev.stopPropagation(); ev.preventDefault();
      sel = g.getAttribute('data-dt-id'); render();
      var d = drawings.filter(function (x) { return x.id === sel; })[0]; if (!d) return;
      var hIdx = t.getAttribute && t.getAttribute('data-h');
      var start = point(ev, true), orig = JSON.parse(JSON.stringify(d.pts));
      busyDrag = true; setBusy(true);
      function mv(e2) {
        var q = point(e2), dt = q.t - start.t, dp = q.p - start.p;
        if (hIdx != null && hIdx !== '') {
          var i = +hIdx;
          if (d.type === 'position') { d.pts[i] = { t: i === 0 ? q.t : d.pts[0].t, p: q.p }; if (i === 0) { d.pts[1].t = q.t; d.pts[2].t = q.t; } }
          else d.pts[i] = { t: q.t, p: q.p };
        } else d.pts = orig.map(function (o) { return { t: o.t + dt, p: o.p + dp }; });
        render();
      }
      function end() { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', end); window.removeEventListener('pointercancel', end); busyDrag = false; setBusy(false); persist(); render(); }
      window.addEventListener('pointermove', mv); window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
    });
    svg.addEventListener('dblclick', function (ev) {
      if (st.lock || st.tool !== 'cursor') return;
      var g = ev.target.closest && ev.target.closest('[data-dt-id]'); if (!g) return;
      var d = drawings.filter(function (x) { return x.id === g.getAttribute('data-dt-id'); })[0];
      if (d && d.type === 'text') { var s = window.prompt('Text:', d.text || ''); if (s != null && s !== '') { d.text = s.slice(0, 60); persist(); render(); } }
    });

    /* ---- keyboard (only while this chart is on the page) ---- */
    function kd(ev) {
      if (!host.isConnected) { document.removeEventListener('keydown', kd); return; }
      if (ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
      if (ev.key === 'Escape') { if (cur) { cancelCur(); render(); } else if (sel) { sel = null; render(); } else if (st.tool !== 'cursor') setTool('cursor'); }
      else if (ev.key === 'Enter' && cur && cur.type === 'path') finish();
      else if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel && !st.lock) { ev.preventDefault(); remove(sel); }
    }
    document.addEventListener('keydown', kd);
    function remove(idd) { drawings = drawings.filter(function (x) { return x.id !== idd; }); if (sel === idd) sel = null; persist(); render(); }

    /* ---- toolbar and selection-box clicks ---- */
    if (ctx.tools) {
      ctx.tools.onclick = function (ev) {
        var b = ev.target.closest && ev.target.closest('button'); if (!b) return;
        var tool = b.getAttribute('data-tool'), tog = b.getAttribute('data-toggle'), act = b.getAttribute('data-act');
        var pop = host.querySelector('.kd-emoji');
        if (tool === 'emoji') { if (pop) pop.hidden = !pop.hidden; if (!pop || !pop.hidden) { /* choosing happens in the popover */ } return; }
        if (pop) pop.hidden = true;
        if (tool) setTool(st.tool === tool && tool !== 'cursor' ? 'cursor' : tool);
        else if (tog) { st[tog] = !st[tog]; savePrefs(st); if (tog === 'lock' && st.lock) { cancelCur(); sel = null; if (st.tool !== 'cursor' && st.tool !== 'zoom') st.tool = 'cursor'; } refreshTools(); render(); }
        else if (act === 'clear') {
          if (st.lock) return;
          if (sel) remove(sel);
          else if (drawings.length && window.confirm('Remove all ' + drawings.length + ' drawing' + (drawings.length === 1 ? '' : 's') + ' on this chart?')) { drawings = []; persist(); render(); }
        }
      };
    }
    var pop2 = host.querySelector('.kd-emoji');
    if (pop2) pop2.onclick = function (ev) {
      var b = ev.target.closest && ev.target.closest('[data-emoji]'); if (!b) return;
      st.emoji = b.getAttribute('data-emoji'); pop2.hidden = true; setTool('emoji');
    };
    if (selBox) selBox.onclick = function (ev) {
      var b = ev.target.closest && ev.target.closest('button'); if (!b || st.lock) return;
      var d = drawings.filter(function (x) { return x.id === sel; })[0]; if (!d) return;
      if (b.hasAttribute('data-color')) { d.color = b.getAttribute('data-color'); st.color = d.color; persist(); render(); }
      else if (b.hasAttribute('data-del')) remove(sel);
    };

    refreshTools(); render();
    return { render: render, count: function () { return drawings.length; } };
  }
  api.attach = attach;
  api.toolbarHtml = toolbarHtml;
  api.EMOJIS = EMOJIS;
  api.COLORS = COLORS;
})(typeof window !== 'undefined' ? window : globalThis);
