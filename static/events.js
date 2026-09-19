/* Market Events (admin-only) section UI.
 *
 * Renders the payload the scheduled job stores in the 'events' section (which row-level security only
 * returns to admins) and offers the admin controls (forecast, FedWatch snapshot, settings) through
 * admin-checked database functions. Nothing here predicts prices: "Observed data" and the system's
 * "assessment" are shown separately, with the evidence and the age of every source. */
(function () {
  'use strict';

  var HOR = ['5m', '15m', '30m', '1h', '4h', '24h'];
  var LABELS = {
    BULLISH_PRESSURE: 'Bullish pressure', BEARISH_PRESSURE: 'Bearish pressure', NEUTRAL: 'Neutral',
    HIGH_VOLATILITY_UNCERTAINTY: 'High volatility / uncertainty'
  };
  var SRC_NAMES = { bls_schedule: 'BLS calendar', fed_calendar: 'Fed calendar', bls_actuals: 'BLS results',
                    reactions: 'Market reactions', fedwatch: 'FedWatch' };
  var ST = { data: null, ctx: null, view: 'dash', eventId: null, filters: { q: '', impact: '', family: '', range: '30', status: '' }, panel: null };

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function num(v, d) { return v == null ? 'n/a' : (typeof v === 'number' ? String(+v.toFixed(d == null ? 3 : d)) : esc(v)); }
  function etFmt(iso, withDate) {
    if (!iso) return 'n/a';
    try {
      return new Date(iso).toLocaleString('en-US', {
        timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        year: withDate ? 'numeric' : undefined, timeZoneName: 'short'
      });
    } catch (e) { return String(iso); }
  }
  function ago(iso) {
    if (!iso) return 'never';
    var m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 1) return 'just now';
    if (m < 90) return m + ' min ago';
    if (m < 2880) return Math.round(m / 60) + ' h ago';
    return Math.round(m / 1440) + ' d ago';
  }
  function badge(status) { return '<span class="ev-badge st-' + esc(String(status).toLowerCase()) + '">' + esc(status) + '</span>'; }
  function impact(l) { return '<span class="ev-impact im-' + esc(String(l).toLowerCase()) + '">' + esc(String(l).replace('_', ' ')) + '</span>'; }
  function root() { return document.getElementById('events-root'); }

  /* ---------- helpers on data ---------- */

  function inRange(e) {
    var f = ST.filters, t = new Date(e.release_datetime).getTime(), now = Date.now();
    if (f.range !== 'all') {
      var d = parseInt(f.range, 10) * 86400000;
      if (t < now - d || t > now + d) return false;
    }
    if (f.impact && e.impact_level !== f.impact) return false;
    if (f.family && e.family !== f.family) return false;
    if (f.status && e.status !== f.status) return false;
    if (f.q) {
      var q = f.q.toLowerCase();
      if ((e.event_name + ' ' + (e.reference_period || '') + ' ' + e.family).toLowerCase().indexOf(q) < 0) return false;
    }
    return true;
  }
  function byId(id) { return (ST.data.events || []).filter(function (e) { return e.id === id; })[0]; }

  /* ---------- pieces ---------- */

  function freshnessBanner(d) {
    var age = (Date.now() - new Date(d.generated_at).getTime()) / 60000, msgs = [];
    if (age > 20) msgs.push('This section was last refreshed ' + ago(d.generated_at) + ' - it is not current.');
    Object.keys(d.sources || {}).forEach(function (k) {
      var s = d.sources[k];
      if (k !== 'fedwatch' && (s.data_status === 'STALE' || s.data_status === 'ERROR' || s.data_status === 'UNAVAILABLE')) {
        msgs.push((SRC_NAMES[k] || k) + ': ' + s.data_status + (s.message ? ' (' + s.message + ')' : '') + '.');
      }
    });
    return msgs.length ? '<div class="ev-warn">' + msgs.map(esc).join('<br>') + '</div>' : '';
  }

  function sourcesRow(d) {
    return '<div class="ev-sources">' + Object.keys(d.sources).map(function (k) {
      var s = d.sources[k];
      return '<span class="ev-src" title="' + esc(s.message || '') + '">' + esc(SRC_NAMES[k] || k) + ' ' + badge(s.data_status) +
        ' <small>' + (s.retrieved_at ? 'retrieved ' + esc(etFmt(s.retrieved_at)) : 'no data') + '</small></span>';
    }).join('') + '</div>';
  }

  function riskCard(d) {
    var r = d.risk;
    return '<div class="ev-card"><h3>Event risk</h3><div class="ev-big">' + esc(r.label) + '</div>' +
      '<div class="ev-meter"><span style="width:' + Math.min(100, r.event_risk_score) + '%"></span></div>' +
      '<div class="ev-sub">Score ' + r.event_risk_score + '/100 &middot; high-impact events: ' + r.events_next_24h + ' in 24h, ' +
      r.events_next_3d + ' in 3 days, ' + r.events_next_7d + ' in 7 days</div></div>';
  }

  function fedwatchCard(d) {
    var f = d.fedwatch, admin = ST.ctx.isAdmin;
    var next = (d.meetings || []).filter(function (m) { return new Date(m.decision_datetime) > new Date(); })
      .sort(function (a, b) { return new Date(a.decision_datetime) - new Date(b.decision_datetime); })[0];
    var body;
    if (f) {
      body = '<div class="ev-fw">' + [['Cut', f.cut_probability], ['Hold', f.hold_probability], ['Hike', f.hike_probability]].map(function (x) {
        return '<div><b>' + num(x[1], 1) + '%</b><span>' + x[0] + '</span></div>';
      }).join('') + '</div><div class="ev-sub">Meeting ' + esc(f.meeting_date) + ' &middot; snapshot ' + esc(etFmt(f.snapshot_datetime)) +
        ' (' + esc(ago(f.snapshot_datetime)) + ') ' + badge(f.data_status) + '<br>Source: ' + esc(f.source) +
        (f._shift_pp != null ? '<br>Cut probability change since previous snapshot: ' + (f._shift_pp > 0 ? '+' : '') + f._shift_pp + ' pp' : '') + '</div>';
    } else {
      body = '<div class="ev-sub">' + badge('UNAVAILABLE') + ' No FedWatch data. CME does not offer permitted automated access, so probabilities are never scraped or estimated here. ' +
        'An admin can record a snapshot read from the CME FedWatch page.</div>';
    }
    var form = '';
    if (admin && next) {
      form = '<details class="ev-form"><summary>Record a FedWatch snapshot</summary>' +
        '<div class="ev-grid"><label>Meeting<input id="fw-meeting" value="' + esc(String(next.end_date)) + '"></label>' +
        '<label>Target rate<input id="fw-target" placeholder="e.g. 4.25-4.50"></label>' +
        '<label>Cut %<input id="fw-cut" type="number" step="0.1" min="0" max="100"></label>' +
        '<label>Hold %<input id="fw-hold" type="number" step="0.1" min="0" max="100"></label>' +
        '<label>Hike %<input id="fw-hike" type="number" step="0.1" min="0" max="100"></label></div>' +
        '<button type="button" class="ghost" id="fw-save">Save snapshot</button><div class="ev-msg" id="fw-msg"></div></details>';
    }
    return '<div class="ev-card"><h3>CME FedWatch</h3>' + body + form + '</div>';
  }

  function assessmentBlock(e) {
    var a = e.assessment;
    var obs = a.observed;
    var rows = [['Event', esc(obs.event)], ['Release', esc(e.release_et)], ['Forecast', num(obs.forecast)], ['Actual', num(obs.actual)],
      ['Previous', num(obs.previous)], ['Surprise', obs.surprise_classification ? esc(obs.surprise_classification) + (obs.surprise != null ? ' (' + num(obs.surprise) + ')' : '') : 'n/a']];
    return '<div class="ev-two"><div><h4>Observed data</h4><table class="ev-kv">' + rows.map(function (r) {
      return '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>';
    }).join('') + '</table></div><div><h4>System assessment</h4>' +
      '<div class="ev-label lb-' + esc(a.label.toLowerCase()) + '">' + esc(LABELS[a.label] || a.label) + '</div>' +
      '<div class="ev-sub">Confidence: <b>' + esc(a.confidence) + '</b></div><p>' + esc(a.assessment) + '</p>' +
      '<ul class="ev-evidence">' + a.evidence.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' +
      '<div class="ev-sub">A reading of stored data - not a prediction of price.</div></div></div>';
  }

  function focusEvent(d) {
    var now = Date.now(), ev = d.events;
    var up = ev.filter(function (e) { return e.status === 'SCHEDULED' && new Date(e.release_datetime) > now && (e.impact_level === 'HIGH' || e.impact_level === 'VERY_HIGH'); })
      .sort(function (a, b) { return new Date(a.release_datetime) - new Date(b.release_datetime); })[0];
    var last = ev.filter(function (e) { return e.status === 'RELEASED' && (e.impact_level === 'HIGH' || e.impact_level === 'VERY_HIGH'); })
      .sort(function (a, b) { return new Date(b.release_datetime) - new Date(a.release_datetime); })[0];
    var out = '';
    if (up) out += '<div class="ev-card"><h3>Next high-impact event <small>' + esc(up.event_name) + ' - ' + esc(up.release_et) + '</small></h3>' + assessmentBlock(up) +
      '<button type="button" class="ghost" data-open="' + esc(up.id) + '">Details</button></div>';
    if (last) out += '<div class="ev-card"><h3>Latest high-impact release <small>' + esc(last.event_name) + ' - ' + esc(last.release_et) + '</small></h3>' + assessmentBlock(last) +
      '<button type="button" class="ghost" data-open="' + esc(last.id) + '">Details</button></div>';
    return out || '<div class="ev-card"><div class="ev-sub">No high-impact events in the stored window.</div></div>';
  }

  function eventRow(e) {
    return '<tr class="ev-row" data-open="' + esc(e.id) + '"><td>' + esc(e.release_et) + '</td><td>' + esc(e.event_name) +
      '<small>' + esc(e.reference_period || '') + '</small></td><td>' + impact(e.impact_level) + '</td><td>' + num(e.forecast) +
      '</td><td>' + num(e.actual) + '</td><td>' + num(e.previous) + '</td><td>' + esc(e.surprise_classification || (e.status === 'SCHEDULED' ? '-' : 'n/a')) +
      '</td><td>' + esc(e.status.toLowerCase()) + '</td></tr>';
  }
  function eventTable(list, empty) {
    if (!list.length) return '<div class="ev-sub">' + esc(empty) + '</div>';
    return '<div class="ev-scroll"><table class="ev-table"><thead><tr><th>Time (ET)</th><th>Event</th><th>Impact</th><th>Forecast</th><th>Actual</th><th>Prev.</th><th>Surprise</th><th>Status</th></tr></thead><tbody>' +
      list.map(eventRow).join('') + '</tbody></table></div>';
  }

  function filtersBar(d) {
    var fams = {}; d.events.forEach(function (e) { fams[e.family] = 1; });
    var f = ST.filters;
    function sel(id, opts, cur) {
      return '<select id="' + id + '">' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === cur ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join('') + '</select>';
    }
    return '<div class="ev-filters"><input id="f-q" placeholder="Search events" value="' + esc(f.q) + '">' +
      sel('f-impact', [['', 'All impact'], ['VERY_HIGH', 'Very high'], ['HIGH', 'High'], ['MEDIUM', 'Medium'], ['LOW', 'Low']], f.impact) +
      sel('f-family', [['', 'All types']].concat(Object.keys(fams).sort().map(function (k) { return [k, k]; })), f.family) +
      sel('f-status', [['', 'Any status'], ['SCHEDULED', 'Scheduled'], ['RELEASED', 'Released']], f.status) +
      sel('f-range', [['7', '+/- 7 days'], ['30', '+/- 30 days'], ['90', '+/- 90 days'], ['all', 'All stored']], f.range) + '</div>';
  }

  function contextCard(d) {
    var items = d.context || [];
    if (!items.length) return '';
    return '<div class="ev-card"><h3>Market backdrop <small>Reported news and opinions - context only, not signals</small></h3>' + items.map(function (c) {
      return '<div class="ev-scn"><b>' + (c.kind === 'news' ? 'News' : 'Opinion') + ': ' + esc(c.author) + ' &middot; ' + esc(c.date) + '</b><p>' + esc(c.claim) + '</p>' +
        (c.points ? '<ul class="ev-evidence">' + c.points.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') +
        '<small>' + esc(c.how_to_use) + ' Source: ' + esc(c.source) + (c.kind === 'news' ? ' (not verified by this system).' : ' (an opinion, not a fact).') + '</small></div>';
    }).join('') + '</div>';
  }

  function dashboard(d) {
    var now = Date.now(), dayEnd = new Date(); dayEnd.setHours(23, 59, 59, 999);
    var todayEt = new Date().toLocaleDateString('en-US', { timeZone: 'America/New_York' });
    var today = d.events.filter(function (e) { return new Date(e.release_datetime).toLocaleDateString('en-US', { timeZone: 'America/New_York' }) === todayEt; });
    var week = d.events.filter(function (e) { var t = new Date(e.release_datetime).getTime(); return t > now && t <= now + 7 * 86400000 && e.status === 'SCHEDULED'; });
    var filtered = d.events.filter(inRange).sort(function (a, b) { return new Date(b.release_datetime) - new Date(a.release_datetime); });
    return freshnessBanner(d) + sourcesRow(d) +
      '<div class="ev-cards">' + riskCard(d) + fedwatchCard(d) + '</div>' + contextCard(d) + focusEvent(d) +
      '<div class="ev-card"><h3>Today (ET)</h3>' + eventTable(today, 'No events today.') + '</div>' +
      '<div class="ev-card"><h3>Next 7 days</h3>' + eventTable(week, 'No scheduled events in the next 7 days.') + '</div>' +
      '<div class="ev-card"><h3>All events</h3>' + filtersBar(d) + '<div id="ev-list">' + eventTable(filtered, 'No events match these filters.') + '</div></div>' +
      '<div class="ev-actions"><button type="button" class="ghost" id="ev-settings">Settings</button></div><div id="ev-settings-panel"></div>';
  }

  /* ---------- details ---------- */

  function returnsChart(rows) {
    if (!rows.length) return '';
    var vals = [];
    rows.forEach(function (r) { HOR.forEach(function (h) { if (r['return_' + h] != null) vals.push(Math.abs(r['return_' + h])); }); });
    var max = Math.max.apply(null, vals.concat([0.5])), W = 320, H = 130, mid = H / 2, bw = 14, gap = 8;
    return rows.map(function (r) {
      var x = 30, bars = '';
      HOR.forEach(function (h) {
        var v = r['return_' + h];
        if (v != null) {
          var hh = Math.abs(v) / max * (mid - 14);
          bars += '<rect x="' + x + '" y="' + (v >= 0 ? mid - hh : mid) + '" width="' + bw + '" height="' + Math.max(1, hh) + '" class="' + (v >= 0 ? 'up' : 'down') + '"><title>' + h + ': ' + v.toFixed(2) + '%</title></rect>';
        }
        bars += '<text x="' + (x + bw / 2) + '" y="' + (H - 2) + '" text-anchor="middle">' + h + '</text>';
        x += bw + gap + 22;
      });
      return '<div class="ev-chart"><b>' + esc(r.asset) + '</b> return vs price at release (%)<svg viewBox="0 0 ' + (x + 6) + ' ' + H + '" role="img" aria-label="' + esc(r.asset) + ' returns">' +
        '<line x1="24" x2="' + (x + 4) + '" y1="' + mid + '" y2="' + mid + '"/><text x="2" y="' + (mid - 2) + '">0</text>' + bars + '</svg></div>';
    }).join('');
  }

  function reactionTable(rows) {
    if (!rows.length) return '<div class="ev-sub">No market reaction stored yet (computed after release from 1-minute candles).</div>';
    return '<div class="ev-scroll"><table class="ev-table"><thead><tr><th>Asset</th>' + HOR.map(function (h) { return '<th>' + h + '</th>'; }).join('') +
      '<th>Max fav.</th><th>Max adv.</th><th>Vol. change</th></tr></thead><tbody>' + rows.map(function (r) {
        return '<tr><td>' + esc(r.asset) + '</td>' + HOR.map(function (h) { return '<td>' + (r['return_' + h] == null ? '-' : num(r['return_' + h], 2) + '%') + '</td>'; }).join('') +
          '<td>' + (r.max_favorable_excursion == null ? '-' : num(r.max_favorable_excursion, 2) + '%') + '</td><td>' + (r.max_adverse_excursion == null ? '-' : num(r.max_adverse_excursion, 2) + '%') +
          '</td><td>' + (r.volatility_change == null ? '-' : num(r.volatility_change, 0) + '%') + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<div class="ev-sub">Returns are measured from the last 1-minute close before the release. Max favorable/adverse = best/worst excursion in the 4 hours after. Volatility change = average 1-minute range in the hour after vs the hour before.</div>';
  }

  function detail(d, e) {
    if (!e) return '<button type="button" class="ghost" id="ev-back">&larr; Back</button><div class="ev-card">Event not found in the stored window.</div>';
    var h = '<button type="button" class="ghost" id="ev-back">&larr; Back</button>' + freshnessBanner(d) +
      '<div class="ev-card"><h3>' + esc(e.event_name) + ' ' + impact(e.impact_level) + '</h3><div class="ev-sub">' + esc(e.reference_period || '') +
      ' &middot; ' + esc(e.release_et) + ' (' + esc(etFmt(e.release_datetime, true)) + ') &middot; ' + esc(e.source) + ' &middot; ' + badge(e.status) +
      '<br>Retrieved ' + esc(etFmt(e.retrieved_at)) + ' &middot; ' + badge(e.data_status) +
      (e.source_url ? ' &middot; <a href="' + esc(e.source_url) + '" target="_blank" rel="noopener noreferrer">official source</a>' : '') + '</div>' +
      assessmentBlock(e);
    var det = e.details || {};
    if (det.core_cpi_mom != null) h += '<div class="ev-sub">Core CPI (m/m): ' + num(det.core_cpi_mom) + '</div>';
    if (det.unemployment_rate != null) h += '<div class="ev-sub">Unemployment rate: ' + num(det.unemployment_rate) + '%</div>';
    if (e.revision) h += '<div class="ev-sub">Previous reading was revised by ' + num(e.revision) + '.</div>';
    h += '</div>';
    if (e.status === 'SCHEDULED') {
      if (e.scenarios) {
        h += '<div class="ev-card"><h3>Scenarios (conditional, not forecasts)</h3><div class="ev-cards">' + e.scenarios.map(function (c) {
          return '<div class="ev-scn"><b>' + esc(c.title) + '</b><p>' + esc(c.reading) + '</p><small>' + esc(c.history) + '</small></div>';
        }).join('') + '</div></div>';
      }
      if (ST.ctx.isAdmin) {
        h += '<div class="ev-card"><h3>Consensus forecast</h3><div class="ev-sub">Not available from official sources. Enter one from a source you trust; it is recorded as "manual (admin)" in the audit log.</div>' +
          '<div class="ev-inline"><input id="fc-val" type="number" step="any" value="' + (e.forecast == null ? '' : esc(e.forecast)) + '"><button type="button" class="ghost" id="fc-save">Save</button>' +
          '<button type="button" class="ghost" id="fc-clear">Clear</button></div><div class="ev-msg" id="fc-msg"></div></div>';
      }
    } else {
      h += '<div class="ev-card"><h3>What happened?</h3><p>' + esc(e.what_happened || 'No summary stored.') + '</p></div>' +
        '<div class="ev-card"><h3>Market reaction</h3>' + reactionTable(e.reactions || []) + returnsChart(e.reactions || []) + '</div>';
    }
    var hist = (d.history || {})[e.family];
    if (hist) {
      h += '<div class="ev-card"><h3>History: ' + esc(e.family) + ' releases</h3><div class="ev-sub">Based on ' + hist.events + ' stored releases.</div>' +
        ['15m', '1h', '4h'].map(function (k) {
          var s = hist[k];
          return '<div class="ev-sub">' + k + ' ' + esc(d.reaction_assets[0]) + ': ' + (s && s.sufficient ?
            'median ' + s.median + '%, ' + s.pct_positive + '% up (n=' + s.n + ')' : esc((s && s.note) || 'no data')) + '</div>';
        }).join('') + '</div>';
    }
    return h;
  }

  /* ---------- settings ---------- */

  function settingsHtml(d) {
    var n = d.config.notifications, th = d.config.thresholds, im = d.config.impact.rules;
    return '<div class="ev-card"><h3>Settings (admin)</h3><h4>Notifications</h4><div class="ev-toggles">' +
      Object.keys(n).filter(function (k) { return typeof n[k] === 'boolean'; }).map(function (k) {
        return '<label><input type="checkbox" data-nk="' + esc(k) + '"' + (n[k] ? ' checked' : '') + '> ' + esc(k.replace(/_/g, ' ')) + '</label>';
      }).join('') + '</div><button type="button" class="ghost" id="set-notif">Save notification settings</button>' +
      '<h4>Surprise thresholds (in each event\'s own unit)</h4><div class="ev-grid">' + Object.keys(th).map(function (k) {
        return '<div class="ev-th"><b>' + esc(k) + '</b> <small>' + esc(th[k].unit || '') + '</small><label>inline &lt;<input type="number" step="any" data-tk="' + esc(k) + '" data-f="inline" value="' + th[k].inline + '"></label>' +
          '<label>moderate &lt;<input type="number" step="any" data-tk="' + esc(k) + '" data-f="moderate" value="' + th[k].moderate + '"></label></div>';
      }).join('') + '</div><button type="button" class="ghost" id="set-th">Save thresholds</button>' +
      '<h4>Impact levels</h4><div class="ev-grid">' + im.map(function (r, i) {
        return '<label>' + esc(r.match) + '<select data-ik="' + i + '">' + ['LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH'].map(function (l) {
          return '<option' + (l === r.level ? ' selected' : '') + '>' + l + '</option>'; }).join('') + '</select></label>';
      }).join('') + '</div><button type="button" class="ghost" id="set-im">Save impact levels</button><div class="ev-msg" id="set-msg"></div>' +
      '<div class="ev-sub">Changes apply from the next refresh (a few minutes).</div></div>';
  }

  /* ---------- rendering + events ---------- */

  function draw() {
    var el = root(); if (!el || !ST.data) return;
    var d = ST.data, focus = document.activeElement && document.activeElement.id;
    var sel = focus && document.activeElement.selectionStart;
    el.innerHTML = '<div class="ev-head"><h2>Market Events <small>Admin only</small></h2><div class="ev-sub">Times in US Eastern (DST-aware). Stored in UTC. Updated ' +
      esc(ago(d.generated_at)) + '.</div></div>' + (ST.view === 'detail' ? detail(d, byId(ST.eventId)) : dashboard(d));
    bind(el, d);
    if (focus === 'f-q') { var q = document.getElementById('f-q'); if (q) { q.focus(); try { q.setSelectionRange(sel, sel); } catch (e) { /* noop */ } } }
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
      n.addEventListener('click', function () { ST.view = 'detail'; ST.eventId = n.getAttribute('data-open'); draw(); window.scrollTo(0, 0); });
    });
    var back = document.getElementById('ev-back');
    if (back) back.onclick = function () { ST.view = 'dash'; draw(); };
    [['f-q', 'q'], ['f-impact', 'impact'], ['f-family', 'family'], ['f-status', 'status'], ['f-range', 'range']].forEach(function (p) {
      var n = document.getElementById(p[0]); if (!n) return;
      n.addEventListener(p[0] === 'f-q' ? 'input' : 'change', function () { ST.filters[p[1]] = n.value; draw(); });
    });
    var fw = document.getElementById('fw-save');
    if (fw) fw.onclick = function () {
      var v = function (id) { var x = document.getElementById(id).value; return x === '' ? null : parseFloat(x); };
      rpc('admin_add_fedwatch_snapshot', { p_meeting: document.getElementById('fw-meeting').value, p_target: document.getElementById('fw-target').value || null,
        p_cut: v('fw-cut'), p_hold: v('fw-hold'), p_hike: v('fw-hike'), p_note: 'entered in dashboard' }, 'fw-msg', 'Saved. Shown after the next refresh.');
    };
    var fcs = document.getElementById('fc-save'), fcc = document.getElementById('fc-clear');
    if (fcs) fcs.onclick = function () {
      var x = document.getElementById('fc-val').value;
      if (x === '') return rpc('admin_set_event_forecast', { p_event: ST.eventId, p_value: null }, 'fc-msg', 'Cleared.');
      rpc('admin_set_event_forecast', { p_event: ST.eventId, p_value: parseFloat(x) }, 'fc-msg', 'Saved. Shown after the next refresh.');
    };
    if (fcc) fcc.onclick = function () { rpc('admin_set_event_forecast', { p_event: ST.eventId, p_value: null }, 'fc-msg', 'Cleared.'); };
    var sb = document.getElementById('ev-settings');
    if (sb) sb.onclick = function () {
      var p = document.getElementById('ev-settings-panel');
      if (!ST.ctx.isAdmin) { p.innerHTML = '<div class="ev-warn">Settings are for admins.</div>'; return; }
      p.innerHTML = settingsHtml(d); bindSettings(p, d);
    };
  }

  function bindSettings(p, d) {
    p.querySelector('#set-notif').onclick = function () {
      var v = JSON.parse(JSON.stringify(d.config.notifications));
      p.querySelectorAll('[data-nk]').forEach(function (c) { v[c.getAttribute('data-nk')] = c.checked; });
      rpc('admin_set_event_config', { p_key: 'notifications', p_value: v }, 'set-msg', 'Saved.');
    };
    p.querySelector('#set-th').onclick = function () {
      var v = JSON.parse(JSON.stringify(d.config.thresholds));
      p.querySelectorAll('[data-tk]').forEach(function (i) { var x = parseFloat(i.value); if (!isNaN(x) && x >= 0) v[i.getAttribute('data-tk')][i.getAttribute('data-f')] = x; });
      rpc('admin_set_event_config', { p_key: 'thresholds', p_value: v }, 'set-msg', 'Saved.');
    };
    p.querySelector('#set-im').onclick = function () {
      var v = JSON.parse(JSON.stringify(d.config.impact));
      var score = { LOW: 2, MEDIUM: 5, HIGH: 7, VERY_HIGH: 9 };
      p.querySelectorAll('[data-ik]').forEach(function (s) { var r = v.rules[+s.getAttribute('data-ik')]; r.level = s.value; r.score = score[s.value]; });
      rpc('admin_set_event_config', { p_key: 'impact', p_value: v }, 'set-msg', 'Saved.');
    };
  }

  window.kairoInitEvents = function (section, ctx) {
    ST.data = (section && section.data) || null;
    ST.ctx = ctx;
    if (ST.data) draw();
  };
})();
