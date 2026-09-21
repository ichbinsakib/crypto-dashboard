/* Market Events (admin-only). Built around: SIMPLE (summary + timeline) -> INTERPRETATION (why it matters, what could
 * happen) -> DETAIL (numbers, sources, history behind "View details").
 *
 * All wording comes from the scheduled job (events/explain.py) so it can be tested; this file only lays it out, filters it
 * and offers the admin controls (forecast, FedWatch snapshot, settings) through admin-checked database functions.
 * Nothing here predicts prices. Anything unknown is shown as "Data unavailable". */
(function () {
  'use strict';

  var ST = { data: null, ctx: null, view: 'main', eventId: null, mode: 'upcoming', when: 'all', level: 'important', cat: '', limit: 25 };
  var ET = 'America/New_York';
  var CAT_NOTE = 'No data source is connected for this yet.';

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function root() { return document.getElementById('events-root'); }
  function num(v) { return v == null ? 'Data unavailable' : (typeof v === 'number' ? String(+v.toFixed(3)) : esc(v)); }

  /* ---------- glossary: hover / tap a term for a one-line meaning ---------- */
  var GL_RE = null;
  function glossaryRe() {
    if (GL_RE) return GL_RE;
    var keys = Object.keys((ST.data && ST.data.glossary) || {}).sort(function (a, b) { return b.length - a.length; });
    GL_RE = keys.length ? new RegExp('\\b(' + keys.map(function (k) { return k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')\\b', 'gi') : null;
    return GL_RE;
  }
  /* Escapes text and wraps the first use of each known term. Only ever call this on plain text, never on HTML. */
  function gl(text) {
    var g = (ST.data && ST.data.glossary) || {}, re = glossaryRe(), seen = {}, lower = {};
    Object.keys(g).forEach(function (k) { lower[k.toLowerCase()] = k; });
    var t = String(text == null ? '' : text);
    if (!re) return esc(t);
    var out = '', last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(t)) !== null) {
      var key = lower[m[1].toLowerCase()];
      if (!key || seen[key]) continue;
      seen[key] = 1;
      out += esc(t.slice(last, m.index)) + '<span class="gl" tabindex="0" data-tip="' + esc(g[key]) + '">' + esc(m[1]) + '</span>';
      last = m.index + m[1].length;
    }
    return out + esc(t.slice(last));
  }

  /* ---------- time helpers (all display in US Eastern, DST-aware via Intl) ---------- */
  function etKey(iso) {
    return new Date(iso).toLocaleDateString('en-CA', { timeZone: ET });                 // YYYY-MM-DD
  }
  function etTime(iso) { return new Date(iso).toLocaleTimeString('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit' }); }
  function addDays(key, n) { var d = new Date(key + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
  function dow(key) { return new Date(key + 'T12:00:00Z').getUTCDay(); }                 // 0 = Sunday
  function todayKey() { return new Date().toLocaleDateString('en-CA', { timeZone: ET }); }
  function weekRange(offset) {
    var t = todayKey(), toMon = (dow(t) + 6) % 7, monday = addDays(t, -toMon + 7 * offset);
    return offset === 0 ? [t, addDays(monday, 6)] : [monday, addDays(monday, 6)];
  }
  function dayLabel(key) {
    var t = todayKey();
    if (key === t) return 'TODAY';
    if (key === addDays(t, 1)) return 'TOMORROW';
    if (key === addDays(t, -1)) return 'YESTERDAY';
    var d = new Date(key + 'T12:00:00Z');
    var name = d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'long' }).toUpperCase();
    return (key > t && key <= addDays(t, 6)) ? name : d.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }) + ' · ' + name.slice(0, 3);
  }
  function ago(iso) {
    if (!iso) return 'never';
    var m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return 'just now';
    if (m < 90) return m + ' min ago';
    if (m < 2880) return Math.round(m / 60) + ' h ago';
    return Math.round(m / 1440) + ' d ago';
  }
  function etFull(iso) {
    return iso ? new Date(iso).toLocaleString('en-US', { timeZone: ET, month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }) : 'Data unavailable';
  }

  /* ---------- small pieces ---------- */
  function tierChip(t) { return '<span class="ev-tier t-' + esc(t.key) + '">' + esc(t.emoji) + ' ' + esc(t.label) + '</span>'; }
  function byId(id) { return (ST.data.events || []).filter(function (e) { return e.id === id; })[0]; }
  function isImportant(e) { return e.tier.key === 'major' || e.tier.key === 'high'; }

  function passes(e) {
    var isPast = e.status === 'RELEASED';
    if (ST.mode === 'upcoming' && isPast) return false;
    if (ST.mode === 'completed' && !isPast) return false;
    if (ST.level === 'important' && !isImportant(e)) return false;
    if (ST.level === 'major' && e.tier.key !== 'major') return false;
    if (ST.cat && e.category !== ST.cat) return false;
    if (ST.mode === 'upcoming') {
      var k = etKey(e.release_datetime), t = todayKey(), w;
      if (k < t) return false;
      if (ST.when === 'today') return k === t;
      if (ST.when === 'tomorrow') return k === addDays(t, 1);
      if (ST.when === 'week') { w = weekRange(0); return k >= w[0] && k <= w[1]; }
      if (ST.when === 'next') { w = weekRange(1); return k >= w[0] && k <= w[1]; }
    }
    return true;
  }

  /* ---------- 1. summary ---------- */
  function scale(s) {
    return '<div class="ev-scale">' + s.scale.map(function (l) {
      return '<span class="' + (l === s.label ? 'on lv-' + esc(s.level) : '') + '">' + esc(l) + '</span>';
    }).join('') + '</div>';
  }
  function summaryCard(d) {
    var s = d.summary;
    var drivers = (s.drivers || []).map(function (x) {
      return '<li><a href="#" data-open="' + esc(x.id) + '">' + esc(x.tier.emoji) + ' ' + esc(x.title) + '</a> - ' + esc(x.when) + '</li>';
    }).join('');
    return '<div class="ev-card ev-sum lv-' + esc(s.level) + '"><div class="ev-sumtop"><div class="ev-sumhead"><small>MARKET EVENT SUMMARY</small>' +
      '<div class="ev-level">' + esc(s.emoji) + ' ' + esc(s.label) + ' EVENT RISK</div>' + scale(s) + '</div>' +
      '<div class="ev-sub">Event risk = how much volatility to expect, not which way prices will go.</div></div>' +
      '<p class="ev-headline">' + gl(s.headline) + '</p>' +
      (s.today ? '<p class="ev-line">' + gl(s.today) + '</p>' : '') +
      '<div class="ev-two"><div><h4>What this means</h4><p>' + gl(s.what_it_means) + '</p></div>' +
      '<div><h4>What to watch</h4><ul class="ev-ul">' + (s.watch || []).map(function (w) { return '<li>' + gl(w) + '</li>'; }).join('') + '</ul></div></div>' +
      (s.theme ? '<p class="ev-line">' + gl(s.theme) + '</p>' : '') + (s.recent ? '<p class="ev-line">' + gl(s.recent) + '</p>' : '') +
      '<div class="ev-take"><b>Simple takeaway:</b> ' + gl(s.takeaway) + '</div>' +
      '<details class="ev-why"><summary>Why is the risk ' + esc(s.label.toLowerCase()) + '?</summary><p>' + esc(s.why) + '</p>' +
      (drivers ? '<ul class="ev-ul">' + drivers + '</ul>' : '') + '</details></div>';
  }
  /* ---------- 0. why the market moved ---------- */
  function pctChip(v, label) {
    if (v == null) return '';
    return '<span class="mv-chip ' + (v > 0 ? 'up' : v < 0 ? 'down' : '') + '"><small>' + esc(label) + '</small><b>' + (v > 0 ? '+' : '') + v.toFixed(1) + '%</b></span>';
  }
  function mvItem(f) {
    return '<li><span class="mv-str s-' + esc(f.strength.toLowerCase()) + '">' + esc(f.strength.charAt(0) + f.strength.slice(1).toLowerCase()) + '</span> <b>' + esc(f.title) + '</b>' +
      '<div class="ev-sub">' + esc(f.text) + '</div><div class="mv-evd">' + esc(f.evidence) + '</div></li>';
  }
  function moversCard(d) {
    var m = d.movers; if (!m) return '';
    var up = m.direction === 'UP', down = m.direction === 'DOWN';
    var forList = up ? m.up : down ? m.down : m.up, againstList = up ? m.down : down ? m.up : m.down;
    var forHead = up ? 'Why it went up' : down ? 'Why it went down' : 'Pushing up', againstHead = up ? 'What held it back' : down ? 'What cushioned the fall' : 'Pushing down';
    var hist = (m.history || []).slice().reverse().slice(0, 14).map(function (r) {
      function c(v) { return v == null ? '<td>n/a</td>' : '<td class="' + (v > 0 ? 'pos' : v < 0 ? 'neg' : '') + '">' + (v > 0 ? '+' : '') + v.toFixed(1) + '%</td>'; }
      return '<tr><td>' + esc(dayLabel(r.date)) + '</td>' + c(r.btc_pct) + c(r.eth_pct) + c(r.total_pct) + '<td>' + esc((r.main || []).join('; ') || (r.direction === 'FLAT' ? 'Quiet day' : 'No clear driver in the data')) + '</td></tr>';
    }).join('');
    return '<div class="ev-card ev-mv mv-' + esc(m.direction.toLowerCase()) + '"><small>WHY THE MARKET MOVED &middot; LAST 24 HOURS</small>' +
      '<div class="mv-top"><span class="mv-dir">' + esc(m.emoji) + ' ' + esc(m.direction) + '</span><div class="mv-chips">' + pctChip(m.btc_pct, 'Bitcoin') + pctChip(m.eth_pct, 'Ethereum') + pctChip(m.total_pct, 'Whole market') + '</div></div>' +
      '<p class="ev-headline">' + esc(m.headline) + '</p>' + (m.with ? '<p class="ev-line">' + esc(m.with) + '</p>' : '') +
      '<p class="ev-line"><b>' + esc(m.summary) + '</b></p>' +
      '<div class="ev-two"><div><h4>' + esc(forHead) + '</h4>' + (forList.length ? '<ul class="mv-list">' + forList.map(mvItem).join('') + '</ul>' : '<div class="ev-sub">Nothing in the data the app tracks points this way.</div>') + '</div>' +
      '<div><h4>' + esc(againstHead) + '</h4>' + (againstList.length ? '<ul class="mv-list">' + againstList.map(mvItem).join('') + '</ul>' : '<div class="ev-sub">Nothing found.</div>') + '</div></div>' +
      ((m.notes || []).length ? '<ul class="ev-ul mv-notes">' + m.notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>' : '') +
      '<div class="ev-take"><b>Please note:</b> ' + esc(m.disclaimer) + '</div>' +
      '<details class="ev-why"><summary>What the app cannot see</summary><ul class="ev-ul">' + (m.cant_see || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul></details>' +
      (hist ? '<details class="ev-why"><summary>Recent days (log)</summary><div class="ev-scroll"><table class="signal-table no-stack mv-log"><thead><tr><th>Day</th><th>Bitcoin</th><th>Ethereum</th><th>Whole market</th><th>Main signals</th></tr></thead><tbody>' + hist + '</tbody></table></div></details>' : '') +
      '</div>';
  }

  function problemLine(d) {
    var p = d.data_problems || [];
    var age = (Date.now() - new Date(d.generated_at).getTime()) / 60000;
    var msgs = [];
    if (age > 20) msgs.push('This page was last refreshed ' + ago(d.generated_at) + ', so it may be out of date.');
    if (p.length) msgs.push('Some data sources are not up to date (' + p.map(function (k) { return k.replace(/_/g, ' '); }).join(', ') + '). Affected items say "Data unavailable".');
    return msgs.length ? '<div class="ev-warn">' + msgs.map(esc).join('<br>') + '</div>' : '';
  }

  /* ---------- FOMC card ---------- */
  function fomcCard(d) {
    var f = d.fomc; if (!f || (!f.next && !f.last)) return '';
    var n = f.next, l = f.last, h = '<div class="ev-card ev-fomc"><h3>🏛 Federal Reserve (FOMC)</h3>';
    if (n) {
      var exp = n.expected ? esc(n.expected.outcome) + ' (' + esc(n.expected.probability) + '% odds, ' + esc(ago(n.expected.as_of)) + ')' : 'Data unavailable';
      h += '<div class="ev-kvgrid"><div><small>Meeting</small><b>' + esc(n.dates) + '</b></div><div><small>Decision</small><b>' + esc(n.decision_time) + '</b></div>' +
        '<div><small>Current rate</small><b>' + esc(n.previous_rate) + '</b></div><div><small>Expected</small><b>' + exp + '</b></div>' +
        '<div><small>Actual</small><b>' + esc(n.actual) + '</b></div></div>' +
        '<p class="ev-line">' + esc(n.press_note) + (n.projections_note ? ' ' + esc(n.projections_note) : '') + ' ' + esc(n.minutes) + '</p>' +
        '<button type="button" class="ghost" data-open="' + esc(n.id) + '">Details &rsaquo;</button>';
    }
    if (l) {
      h += '<div class="ev-last"><h4>Last decision (' + esc(l.date) + ')</h4><p>' + esc(l.decision) + '</p>' +
        (l.market ? '<p class="ev-sub">' + esc(l.market) + '</p>' : '') +
        (l.minutes_url ? '<a href="' + esc(l.minutes_url) + '" target="_blank" rel="noopener noreferrer">Read the minutes</a>' : '') + '</div>';
    }
    return h + '<details class="ev-why"><summary>' + esc(f.why_title) + '</summary><p>' + gl(f.why) + '</p></details></div>';
  }

  /* ---------- filters ---------- */
  function chips(name, opts, cur) {
    return '<div class="ev-chips" role="group" aria-label="' + esc(name) + '">' + opts.map(function (o) {
      var dis = o.disabled ? ' disabled title="' + esc(CAT_NOTE) + '"' : '';
      return '<button type="button" class="ev-chipbtn' + (o.v === cur ? ' on' : '') + '" data-f="' + esc(name) + '" data-v="' + esc(o.v) + '"' + dis + '>' + esc(o.l) + '</button>';
    }).join('') + '</div>';
  }
  function filtersBar(d) {
    var cats = [{ v: '', l: 'All types' }];
    var have = {}; (d.categories || []).forEach(function (c) { have[c.key] = c.label; cats.push({ v: c.key, l: c.label }); });
    if (!have.growth) cats.push({ v: '__growth', l: 'GDP', disabled: true });
    var out = chips('mode', [{ v: 'upcoming', l: 'Upcoming' }, { v: 'completed', l: 'Completed' }], ST.mode);
    if (ST.mode === 'upcoming') out += chips('when', [{ v: 'all', l: 'All upcoming' }, { v: 'today', l: 'Today' }, { v: 'tomorrow', l: 'Tomorrow' }, { v: 'week', l: 'This week' }, { v: 'next', l: 'Next week' }], ST.when);
    out += chips('level', [{ v: 'important', l: 'Important only' }, { v: 'major', l: 'Major only' }, { v: 'all', l: 'Everything' }], ST.level);
    out += chips('cat', cats, ST.cat);
    return '<div class="ev-filters">' + out + '</div>';
  }

  /* ---------- 2. timeline ---------- */
  function rowHtml(e) {
    var past = e.status === 'RELEASED';
    var sub = past ? (e.result_line || 'Result not recorded yet.') : e.one_liner;
    return '<button type="button" class="ev-tl" data-open="' + esc(e.id) + '"><span class="ev-time">' + esc(etTime(e.release_datetime)) + '</span>' +
      '<span class="ev-tlbody"><span class="ev-tltitle">' + tierChip(e.tier) + ' <b>' + esc(e.plain_title) + '</b>' +
      (e.reference_period && past === false ? '<em>' + esc(e.reference_period) + '</em>' : '') + '</span>' +
      '<span class="ev-tlsub">' + esc(sub) + '</span></span><span class="ev-go">&rsaquo;</span></button>';
  }
  function timeline(d) {
    var list = (d.events || []).filter(passes);
    list.sort(function (a, b) { return ST.mode === 'completed' ? new Date(b.release_datetime) - new Date(a.release_datetime) : new Date(a.release_datetime) - new Date(b.release_datetime); });
    var hiddenLow = (d.events || []).filter(function (e) {
      return ST.level !== 'all' && (ST.mode === 'completed' ? e.status === 'RELEASED' : e.status !== 'RELEASED') && !(ST.level === 'important' ? isImportant(e) : e.tier.key === 'major') && (!ST.cat || e.category === ST.cat);
    }).length;
    var note = '';
    if (!list.length) {
      var nextUp = ST.mode === 'upcoming' && ST.when !== 'all';
      note = '<div class="ev-empty">' + (ST.mode === 'completed' ? 'No completed events match these filters.' : 'No events match these filters' + (nextUp ? ' in this time range.' : '.')) +
        (nextUp ? ' <a href="#" data-set="when=all">Show all upcoming</a>' : '') + '</div>';
    }
    var html = '', cur = null, shown = list.slice(0, ST.limit);
    shown.forEach(function (e) {
      var k = etKey(e.release_datetime);
      if (k !== cur) { cur = k; html += '<div class="ev-day">' + esc(dayLabel(k)) + '</div>'; }
      html += rowHtml(e);
    });
    if (list.length > shown.length) html += '<button type="button" class="ghost" data-more="1">Show ' + (list.length - shown.length) + ' more</button>';
    if (hiddenLow > 0 && ST.level !== 'all') html += '<div class="ev-sub">Hiding ' + hiddenLow + ' lower-impact event' + (hiddenLow !== 1 ? 's' : '') + '. <a href="#" data-set="level=all">Show everything</a></div>';
    var nt = (d.not_tracked || []).length ? '<div class="ev-sub">Not tracked yet (no connected data source): ' + esc(d.not_tracked.join(', ')) + '.</div>' : '';
    return '<div class="ev-card"><h3>' + (ST.mode === 'completed' ? 'What happened' : 'Timeline') + ' <small>times in US Eastern</small></h3>' + (html || '') + note + nt + '</div>';
  }

  /* ---------- 3. detail: explain -> interpret -> details ---------- */
  function sensBlock(e) {
    if (!e.sensitivity || e.tier.key === 'low') return '<p class="ev-sub">Little direct effect on markets.</p>';
    return '<div class="ev-sens">' + e.sensitivity.map(function (s) {
      return '<div><span>' + esc(s.asset) + '</span><i class="s' + s.level + '"></i><b>' + esc(s.emoji) + ' ' + esc(s.label) + '</b></div>';
    }).join('') + '</div><div class="ev-sub">How sensitive each market may be to this event (volatility), not the direction it will move.</div>';
  }
  function scenarioTable(e) {
    if (!e.scenarios || !e.scenarios.length) return '';
    return '<h4>What could happen?</h4><table class="ev-scen"><thead><tr><th>Scenario</th><th>Possible market reaction</th></tr></thead><tbody>' +
      e.scenarios.map(function (s) { return '<tr><td>' + esc(s.scenario) + '</td><td>' + gl(s.reaction) + '</td></tr>'; }).join('') + '</tbody></table>' +
      '<div class="ev-sub"><b>' + esc(e.scenario_note) + '</b></div>';
  }
  function happened(e) {
    var box = function (l, v) { return '<div><small>' + l + '</small><b>' + (v == null ? 'Data unavailable' : esc(v)) + '</b></div>'; };
    var fomc = e.family === 'FOMC';
    var det = e.details || {};
    var a = fomc ? (det.rate_range || null) : e.actual, f = fomc ? (det.expected_outcome ? det.expected_outcome + ' (' + det.expected_probability + '% odds)' : null) : e.forecast;
    var h = '<h4>What actually happened?</h4><div class="ev-kvgrid">' + box('Expected', f) + box('Actual', a) + box(fomc ? 'Previous rate' : 'Previous', fomc ? (det.prev_range || null) : e.previous) + '</div>' +
      '<p class="ev-result">' + gl(e.result_line || 'Data unavailable') + '</p>';
    if (e.interpretation) h += '<p><b>Simple interpretation:</b> ' + gl(e.interpretation) + '</p>';
    h += '<p><b>Market reaction:</b> ' + esc(e.market_line || 'Data unavailable (not recorded for this event).') + '</p>';
    return h;
  }
  function detailRaw(d, e) {
    var rows = [['Forecast', num(e.forecast) + (e.forecast_source ? ' (' + esc(e.forecast_source) + ')' : '')], ['Actual', num(e.actual)], ['Previous', num(e.previous)],
      ['Revision to previous', e.revision ? num(e.revision) : 'None recorded'], ['Surprise', e.surprise_classification ? esc(e.surprise_classification) + (e.surprise != null ? ' (' + num(e.surprise) + ')' : '') : 'Data unavailable'],
      ['Reference period', esc(e.reference_period || 'n/a')], ['Release (ET)', esc(e.release_et)], ['Release (UTC)', esc(e.release_datetime)],
      ['Source', esc(e.source) + (e.source_url ? ' - <a href="' + esc(e.source_url) + '" target="_blank" rel="noopener noreferrer">official page</a>' : '')],
      ['Data status', esc(e.data_status) + ', retrieved ' + esc(etFull(e.retrieved_at))], ['Related assets', esc((e.sensitivity || []).filter(function (s) { return s.level >= 2; }).map(function (s) { return s.asset; }).join(', ') || 'None significant')]];
    var det = e.details || {};
    if (det.core_cpi_mom != null) rows.push(['Core CPI (m/m)', num(det.core_cpi_mom)]);
    if (det.unemployment_rate != null) rows.push(['Unemployment rate', num(det.unemployment_rate) + '%']);
    var h = '<table class="ev-kv">' + rows.map(function (r) { return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>'; }).join('') + '</table>';
    var a = e.assessment;
    if (a) h += '<h4>System reading (a lean, not a forecast)</h4><p><b>' + esc(a.label.replace(/_/g, ' ').toLowerCase()) + '</b>, confidence ' + esc(a.confidence.toLowerCase()) + '</p><ul class="ev-ul">' + a.evidence.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>';
    if ((e.reactions || []).length) h += reactionTable(e.reactions);
    var hist = (d.history || {})[e.family];
    if (hist) h += '<h4>History: ' + esc(e.family) + ' releases (' + hist.events + ' stored)</h4>' + ['15m', '1h', '4h'].map(function (k) {
      var s = hist[k];
      return '<div class="ev-sub">' + k + ' ' + esc(d.reaction_assets[0]) + ': ' + (s && s.sufficient ? 'median ' + s.median + '%, ' + s.pct_positive + '% up (n=' + s.n + ')' : esc((s && s.note) || 'no data')) + '</div>';
    }).join('');
    if (e.scenario_history) h += '<h4>Past reactions by outcome</h4>' + e.scenario_history.map(function (c) { return '<div class="ev-sub"><b>' + esc(c.title) + ':</b> ' + esc(c.history) + '</div>'; }).join('');
    if (ST.ctx.isAdmin && e.status === 'SCHEDULED') {
      h += '<h4>Consensus forecast (admin)</h4><div class="ev-sub">No official source provides one. Enter one you trust; it is saved as "manual (admin)" in the audit log.</div>' +
        '<div class="ev-inline"><input id="fc-val" type="number" step="any" value="' + (e.forecast == null ? '' : esc(e.forecast)) + '"><button type="button" class="ghost" id="fc-save">Save</button><button type="button" class="ghost" id="fc-clear">Clear</button></div><div class="ev-msg" id="fc-msg"></div>';
    }
    return h;
  }
  function reactionTable(rows) {
    var HOR = ['5m', '15m', '30m', '1h', '4h', '24h'];
    return '<h4>Market move after release</h4><div class="ev-scroll"><table class="ev-table"><thead><tr><th>Asset</th>' + HOR.map(function (h) { return '<th>' + h + '</th>'; }).join('') + '<th>Max up</th><th>Max down</th></tr></thead><tbody>' +
      rows.map(function (r) {
        return '<tr><td>' + esc(r.asset.replace('USDT', '')) + '</td>' + HOR.map(function (h) { return '<td>' + (r['return_' + h] == null ? '-' : (+r['return_' + h]).toFixed(2) + '%') + '</td>'; }).join('') +
          '<td>' + (r.max_favorable_excursion == null ? '-' : (+r.max_favorable_excursion).toFixed(2) + '%') + '</td><td>' + (r.max_adverse_excursion == null ? '-' : (+r.max_adverse_excursion).toFixed(2) + '%') + '</td></tr>';
      }).join('') + '</tbody></table></div><div class="ev-sub">Measured from the last 1-minute price before the release. One event is an example, not a pattern.</div>';
  }
  function detail(d, e) {
    var back = '<button type="button" class="ghost" id="ev-back">&larr; Back to Market Events</button>';
    if (!e) return back + '<div class="ev-card">This event is outside the stored window.</div>';
    var past = e.status === 'RELEASED';
    var h = back + '<div class="ev-card"><div class="ev-dtitle">' + tierChip(e.tier) + '<h3>' + esc(e.plain_title) + '</h3></div>' +
      '<div class="ev-sub">' + (past ? 'Completed · ' : 'Upcoming · ') + esc(e.release_et) + (e.reference_period ? ' · covers ' + esc(e.reference_period) : '') + '</div>' +
      (past ? happened(e) : '') +
      '<div class="ev-three"><div><h4>What is it?</h4><p>' + gl(e.what) + '</p></div><div><h4>Why does it matter?</h4><p>' + gl(e.why) + '</p></div><div><h4>Why should I care?</h4><p>' + gl(e.care) + '</p></div></div>' +
      '<h4>What could it affect?</h4>' + sensBlock(e) + (past ? '' : scenarioTable(e)) +
      (!past && e.watch && e.watch.length ? '<h4>What to watch</h4><ul class="ev-ul">' + e.watch.map(function (w) { return '<li>' + gl(w) + '</li>'; }).join('') + '</ul>' : '') +
      '<details class="ev-why" id="ev-raw"><summary>View details (numbers, sources, history)</summary>' + detailRaw(d, e) + '</details></div>';
    return h;
  }

  /* ---------- extras (kept, but tucked away) ---------- */
  function contextCard(d) {
    var items = d.context || []; if (!items.length) return '';
    return '<details class="ev-card ev-fold"><summary>Analyst context (news and opinions, not signals)</summary>' + items.map(function (c) {
      return '<div class="ev-scn"><b>' + (c.kind === 'news' ? 'News' : 'Opinion') + ': ' + esc(c.author) + ' · ' + esc(c.date) + '</b><p>' + esc(c.claim) + '</p>' +
        '<small>' + esc(c.how_to_use) + ' Source: ' + esc(c.source) + (c.kind === 'news' ? ' (not verified by this system).' : ' (an opinion, not a fact).') + '</small></div>';
    }).join('') + '</details>';
  }
  function sourcesCard(d) {
    var names = { bls_schedule: 'BLS calendar', fed_calendar: 'Fed calendar', bls_actuals: 'BLS results', fed_rates: 'Fed rates', reactions: 'Market reactions', fedwatch: 'FedWatch' };
    return '<details class="ev-card ev-fold"><summary>Data sources and freshness</summary><div class="ev-sources">' + Object.keys(d.sources).map(function (k) {
      var s = d.sources[k];
      return '<div><b>' + esc(names[k] || k) + '</b> <span class="ev-badge st-' + esc(String(s.data_status).toLowerCase()) + '">' + esc(s.data_status) + '</span> <small>' +
        (s.retrieved_at ? 'retrieved ' + esc(etFull(s.retrieved_at)) : 'no data') + (s.message ? ' · ' + esc(s.message) : '') + '</small></div>';
    }).join('') + '</div>' + fedwatchAdmin(d) + '</details>';
  }
  function fedwatchAdmin(d) {
    var f = d.fedwatch, next = (d.meetings || []).filter(function (m) { return new Date(m.decision_datetime) > new Date(); })
      .sort(function (a, b) { return new Date(a.decision_datetime) - new Date(b.decision_datetime); })[0];
    var h = '<h4>CME FedWatch</h4>';
    if (f) h += '<div class="ev-sub">Meeting ' + esc(f.meeting_date) + ': cut ' + num(f.cut_probability) + '%, hold ' + num(f.hold_probability) + '%, hike ' + num(f.hike_probability) + '% · entered ' + esc(ago(f.snapshot_datetime)) + ' · ' + esc(f.source) + '</div>';
    else h += '<div class="ev-sub">Data unavailable. CME has no permitted automated feed, so probabilities are never scraped or estimated.</div>';
    if (ST.ctx.isAdmin && next) {
      h += '<div class="ev-grid"><label>Meeting<input id="fw-meeting" value="' + esc(String(next.end_date)) + '"></label><label>Target rate<input id="fw-target" placeholder="e.g. 4.25-4.50"></label>' +
        '<label>Cut %<input id="fw-cut" type="number" step="0.1" min="0" max="100"></label><label>Hold %<input id="fw-hold" type="number" step="0.1" min="0" max="100"></label>' +
        '<label>Hike %<input id="fw-hike" type="number" step="0.1" min="0" max="100"></label></div><button type="button" class="ghost" id="fw-save">Record a FedWatch snapshot</button><div class="ev-msg" id="fw-msg"></div>';
    }
    return h;
  }
  function settingsCard(d) {
    if (!ST.ctx.isAdmin) return '';
    var n = d.config.notifications, th = d.config.thresholds, im = d.config.impact.rules;
    return '<details class="ev-card ev-fold"><summary>Settings (admin)</summary><h4>Notifications</h4><div class="ev-toggles">' +
      Object.keys(n).filter(function (k) { return typeof n[k] === 'boolean'; }).map(function (k) { return '<label><input type="checkbox" data-nk="' + esc(k) + '"' + (n[k] ? ' checked' : '') + '> ' + esc(k.replace(/_/g, ' ')) + '</label>'; }).join('') +
      '</div><button type="button" class="ghost" id="set-notif">Save notification settings</button>' +
      '<h4>How surprising must a result be? (in each event\'s own unit)</h4><div class="ev-grid">' + Object.keys(th).map(function (k) {
        return '<div class="ev-th"><b>' + esc(k) + '</b> <small>' + esc(th[k].unit || '') + '</small><label>inline &lt;<input type="number" step="any" data-tk="' + esc(k) + '" data-f="inline" value="' + th[k].inline + '"></label>' +
          '<label>moderate &lt;<input type="number" step="any" data-tk="' + esc(k) + '" data-f="moderate" value="' + th[k].moderate + '"></label></div>';
      }).join('') + '</div><button type="button" class="ghost" id="set-th">Save thresholds</button>' +
      '<h4>Importance level of each event type</h4><div class="ev-grid">' + im.map(function (r, i) {
        return '<label>' + esc(r.match) + '<select data-ik="' + i + '">' + ['LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'].map(function (l) { return '<option' + (l === r.level ? ' selected' : '') + '>' + l + '</option>'; }).join('') + '</select></label>';
      }).join('') + '</div><button type="button" class="ghost" id="set-im">Save importance levels</button><div class="ev-msg" id="set-msg"></div>' +
      '<div class="ev-sub">Changes apply from the next refresh (a few minutes).</div></details>';
  }

  /* ---------- draw + wiring ---------- */
  function draw() {
    var el = root(); if (!el || !ST.data) return;
    var d = ST.data, keepY = window.scrollY;
    var body;
    if (ST.view === 'detail') body = detail(d, byId(ST.eventId));
    else body = problemLine(d) + moversCard(d) + summaryCard(d) + fomcCard(d) + '<div class="ev-card ev-fcard">' + filtersBar(d) + '</div>' + timeline(d) + contextCard(d) + sourcesCard(d) + settingsCard(d);
    el.innerHTML = '<div class="ev-head"><h2>Market Events <small>Admin only</small></h2><div class="ev-sub">Updated ' + esc(ago(d.generated_at)) + ' · times in US Eastern · hover a dotted term for its meaning</div></div>' + body;
    bind(el, d);
    if (ST.view === 'main') window.scrollTo(0, keepY);
  }

  function rpc(name, args, msgId, okText) {
    var m = document.getElementById(msgId);
    if (ST.ctx.dev) { if (m) { m.textContent = 'Preview mode: not saved.'; m.className = 'ev-msg err'; } return Promise.resolve(); }
    return ST.ctx.sb().rpc(name, args).then(function (r) {
      if (m) { m.textContent = r.error ? r.error.message : okText; m.className = 'ev-msg ' + (r.error ? 'err' : 'ok'); }
      return r;
    });
  }

  function bind(el, d) {
    el.querySelectorAll('[data-open]').forEach(function (n) {
      n.addEventListener('click', function (ev) { ev.preventDefault(); ST.view = 'detail'; ST.eventId = n.getAttribute('data-open'); draw(); window.scrollTo(0, 0); });
    });
    var back = document.getElementById('ev-back'); if (back) back.onclick = function () { ST.view = 'main'; draw(); };
    el.querySelectorAll('.ev-chipbtn').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.disabled) return;
        var f = b.getAttribute('data-f'), v = b.getAttribute('data-v');
        if (f === 'cat' && v === '__growth') return;
        ST[f] = v; ST.limit = 25; draw();
      });
    });
    el.querySelectorAll('[data-set]').forEach(function (a) {
      a.addEventListener('click', function (ev) { ev.preventDefault(); var kv = a.getAttribute('data-set').split('='); ST[kv[0]] = kv[1]; draw(); });
    });
    var more = el.querySelector('[data-more]'); if (more) more.onclick = function () { ST.limit += 25; draw(); };
    var fw = document.getElementById('fw-save');
    if (fw) fw.onclick = function () {
      var v = function (id) { var x = document.getElementById(id).value; return x === '' ? null : parseFloat(x); };
      rpc('admin_add_fedwatch_snapshot', { p_meeting: document.getElementById('fw-meeting').value, p_target: document.getElementById('fw-target').value || null,
        p_cut: v('fw-cut'), p_hold: v('fw-hold'), p_hike: v('fw-hike'), p_note: 'entered in dashboard' }, 'fw-msg', 'Saved. Shown after the next refresh.');
    };
    var fcs = document.getElementById('fc-save'), fcc = document.getElementById('fc-clear');
    if (fcs) fcs.onclick = function () {
      var x = document.getElementById('fc-val').value;
      rpc('admin_set_event_forecast', { p_event: ST.eventId, p_value: x === '' ? null : parseFloat(x) }, 'fc-msg', x === '' ? 'Cleared.' : 'Saved. Shown after the next refresh.');
    };
    if (fcc) fcc.onclick = function () { rpc('admin_set_event_forecast', { p_event: ST.eventId, p_value: null }, 'fc-msg', 'Cleared.'); };
    var sn = document.getElementById('set-notif');
    if (sn) {
      sn.onclick = function () {
        var v = JSON.parse(JSON.stringify(d.config.notifications));
        el.querySelectorAll('[data-nk]').forEach(function (c) { v[c.getAttribute('data-nk')] = c.checked; });
        rpc('admin_set_event_config', { p_key: 'notifications', p_value: v }, 'set-msg', 'Saved.');
      };
      document.getElementById('set-th').onclick = function () {
        var v = JSON.parse(JSON.stringify(d.config.thresholds));
        el.querySelectorAll('[data-tk]').forEach(function (i) { var x = parseFloat(i.value); if (!isNaN(x) && x >= 0) v[i.getAttribute('data-tk')][i.getAttribute('data-f')] = x; });
        rpc('admin_set_event_config', { p_key: 'thresholds', p_value: v }, 'set-msg', 'Saved.');
      };
      document.getElementById('set-im').onclick = function () {
        var v = JSON.parse(JSON.stringify(d.config.impact)), score = { LOW: 2, MEDIUM: 5, HIGH: 7, VERY_HIGH: 9 };
        el.querySelectorAll('[data-ik]').forEach(function (s) { var r = v.rules[+s.getAttribute('data-ik')]; r.level = s.value; r.score = score[s.value]; });
        rpc('admin_set_event_config', { p_key: 'impact', p_value: v }, 'set-msg', 'Saved.');
      };
    }
  }

  window.kairoInitEvents = function (section, ctx) {
    var d = (section && section.data) || null;
    if (d !== ST.data) GL_RE = null;
    ST.data = d; ST.ctx = ctx;
    if (!d) return;
    if (!d.summary) { root().innerHTML = '<div class="ev-card">The Market Events data is being updated to the new format; check back in a few minutes.</div>'; return; }
    draw();
  };
})();
