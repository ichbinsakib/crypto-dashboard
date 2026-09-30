/* Kairo app shell: login, section rendering, admin + account panels.
 *
 * The published page holds no data. After sign-in, Supabase row-level security returns only the
 * sections this account was granted (plus the header/meta row for anyone with at least one), so
 * a section that isn't assigned never reaches the browser at all -- it isn't merely hidden.
 * No alert()/confirm()/prompt(): the Android WebView wrapper doesn't implement JS dialogs. */
(function () {
  'use strict';

  var CFG = window.KAIRO_CONFIG || {};
  var DEV = !CFG.supabaseUrl;                       // no backend configured -> standalone preview, no login
  var PORTION_LABELS = { screener: 'Signals', bigcoins: 'Market', mypicks: 'My Picks', performance: 'Performance (shown inside Signals)' };
  var PORTION_KEYS = ['screener', 'bigcoins', 'mypicks', 'performance'];
  var sb = null;
  var S = { session: null, profile: null, rows: [], generatedAt: null, refreshSeconds: 120, refreshTimer: null, tickTimer: null, loading: false };

  function $(id) { return document.getElementById(id); }
  function show(id, on) { var el = $(id); if (el) el.hidden = !on; }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }


  /* ---------------- theme (light / dark / auto) ---------------- */
  var THEMES = ['light', 'dark', 'auto'];
  var THEME_LABEL = { light: '\u2600 Light', dark: '\u263E Dark', auto: '\u25D1 Auto' };
  var THEME_COLOR = { light: '#eef3fb', dark: '#0a0e14' };
  function currentTheme() { return document.documentElement.getAttribute('data-theme') || 'light'; }
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('kairo_theme', t); } catch (e) { /* storage unavailable */ }
    var dark = t === 'dark' || (t === 'auto' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var m = document.querySelector('meta[name=theme-color]'); if (m) m.setAttribute('content', dark ? THEME_COLOR.dark : THEME_COLOR.light);
    var b = $('btn-theme'); if (b) b.textContent = THEME_LABEL[t];
  }
  function cycleTheme() { applyTheme(THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length]); }


  /* ---------------- live watchlist (Binance rows refresh in the browser) ---------------- */
  var wlTimer = null;
  function initWatchlist() {
    if (wlTimer) { clearInterval(wlTimer); wlTimer = null; }
    if (pxTimer) { clearInterval(pxTimer); pxTimer = null; }
    if (!document.querySelector('tr[data-live]')) return;
    async function tick() {
      var rows = document.querySelectorAll('tr[data-live]');
      if (!rows.length) { clearInterval(wlTimer); wlTimer = null; return; }
      var syms = Array.prototype.map.call(rows, function (r) { return r.getAttribute('data-live'); });
      var stamp = document.getElementById('wl-live-stamp');
      try {
        var res = await fetch('https://data-api.binance.vision/api/v3/ticker/24hr?symbols=' + encodeURIComponent(JSON.stringify(syms)));
        if (!res.ok) throw new Error('bad status');
        var list = await res.json();
        list.forEach(function (t) {
          var row = document.querySelector('tr[data-live="' + t.symbol + '"]'); if (!row) return;
          var p = parseFloat(t.lastPrice), c = parseFloat(t.priceChangePercent);
          row.querySelector('.wl-price').textContent = t.symbol.slice(-3) === 'BTC' ? p.toFixed(8).replace(/0+$/, '') : p.toLocaleString('en-US', { minimumFractionDigits: p >= 1 ? 2 : 4, maximumFractionDigits: p >= 1 ? 2 : 4 });
          var cell = row.querySelector('.wl-chg');
          cell.textContent = (c >= 0 ? '+' : '') + c.toFixed(2) + '%';
          cell.className = 'wl-chg ' + (c > 0 ? 'pos' : c < 0 ? 'neg' : 'watch');
        });
        if (stamp) stamp.textContent = 'Binance rows live - ' + new Date().toLocaleTimeString();
      } catch (e) {
        if (stamp) stamp.textContent = 'live update unavailable - showing the latest snapshot';
      }
    }
    tick();
    wlTimer = setInterval(tick, 20000);
  }


  /* ---------------- live prices for the dip-scanner rows ---------------- */
  var pxTimer = null;
  function initSignalPrices() {
    if (pxTimer) { clearInterval(pxTimer); pxTimer = null; }
    if (!document.querySelector('td[data-px]')) return;
    async function one(sym) {
      for (var q of ['USDT', 'USD']) {
        try {
          var r = await fetch('https://data-api.binance.vision/api/v3/ticker/price?symbol=' + encodeURIComponent(sym + q));
          if (!r.ok) continue;
          var j = await r.json(); var p = parseFloat(j.price);
          if (p > 0) return p;
        } catch (e) { /* try next quote */ }
      }
      return null;
    }
    function fmt(p) {
      if (p >= 1000) return '$' + p.toLocaleString('en-US', { maximumFractionDigits: 0 });
      if (p >= 1) return '$' + p.toFixed(2);
      var dec = Math.min(10, Math.max(4, 2 - Math.floor(Math.log10(p))));
      return '$' + p.toFixed(dec);
    }
    async function tick() {
      var cells = document.querySelectorAll('td[data-px]');
      if (!cells.length) { clearInterval(pxTimer); pxTimer = null; return; }
      var syms = {}; cells.forEach(function (c) { syms[c.getAttribute('data-px')] = 1; });
      for (var s of Object.keys(syms)) {
        var p = await one(s);
        if (p == null) continue;
        document.querySelectorAll('td[data-px="' + s + '"]').forEach(function (c) { c.textContent = fmt(p); c.classList.add('px-live'); });
      }
    }
    tick();
    pxTimer = setInterval(tick, 30000);
  }


  /* ---------------- mobile: header menu + stacked tables ---------------- */
  function initMobileMenu() {
    var header = document.querySelector('header');
    var actions = header && header.querySelector('.header-actions');
    if (!header || !actions || document.getElementById('btn-menu')) return;
    var btn = document.createElement('button');
    btn.type = 'button'; btn.id = 'btn-menu'; btn.className = 'hdr-btn menu-only';
    btn.setAttribute('aria-label', 'Menu'); btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = '&#9776;';
    header.insertBefore(btn, actions);
    function close() { actions.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = actions.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    actions.addEventListener('click', close);
    document.addEventListener('click', function (e) { if (!actions.contains(e.target) && e.target !== btn) close(); });
  }

  /* Tables with 4+ columns are hard to read on a phone. Give each cell its column name so CSS can turn rows into cards
     (only applied below 720px by the stylesheet; desktop keeps the normal table). */
  function enhanceTables(rootEl) {
    (rootEl || document).querySelectorAll('table').forEach(function (t) {
      if (t.classList.contains('no-stack') || t.closest('.ev-scroll')) return;
      var ths = t.querySelectorAll('thead th');
      if (ths.length < 4) return;
      var names = Array.prototype.map.call(ths, function (th) { return (th.textContent || '').trim(); });
      t.querySelectorAll('tbody tr').forEach(function (tr) {
        var cells = tr.children, i = 0;
        Array.prototype.forEach.call(cells, function (td) {
          if (!td.hasAttribute('data-label')) td.setAttribute('data-label', names[i] || '');
          i += td.colSpan || 1;
          if (!td.querySelector(':scope > .rt-val') && td.childNodes.length && !td.querySelector('button')) {
            var w = document.createElement('span'); w.className = 'rt-val';
            while (td.firstChild) w.appendChild(td.firstChild);
            td.appendChild(w);
          }
        });
      });
      t.classList.add('rt');
    });
  }


  /* ---------------- overview cards (and notification taps) open the matching tab ---------------- */
  // "performance" has no tab of its own -- render() embeds it inside "screener" -- so a
  // notification stamped with that portion_key (win/loss/expiry results) needs to land there instead.
  var PORTION_ALIAS = { performance: 'screener' };
  function goToPortion(portion, sub) {
    var t = document.getElementById('tab-' + (PORTION_ALIAS[portion] || portion));
    if (!t) return false;                             // the reader has no access to that section
    t.checked = true;
    var sr = sub && document.getElementById(sub);
    if (sr) sr.checked = true;
    var root = document.getElementById('tabs-root');
    if (root && root.scrollIntoView) root.scrollIntoView({ block: 'start' });
    return true;
  }
  function goTo(a) { goToPortion(a.getAttribute('data-goto'), a.getAttribute('data-sub')); }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-goto]');
    if (a) { e.preventDefault(); goTo(a); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var a = e.target.closest && e.target.closest('[data-goto]');
    if (a) { e.preventDefault(); goTo(a); }
  });
  // The Android app opens a tapped notification's target by loading this same page with
  // #goto=<portion_key> (portion_key is exactly the same tab key notification_events already
  // stamps on every event server-side). Applied once, right after the first render, and then
  // cleared so a later manual refresh of the page doesn't jump the reader away from where they are.
  window.kairoGoto = goToPortion;
  function applyPendingDeepLink() {
    var m = /(?:^|[#&])goto=([^&]+)/.exec(location.hash);
    if (!m) return;
    history.replaceState(null, '', location.pathname + location.search);
    goToPortion(decodeURIComponent(m[1]));
  }

  /* ---------------- scanner rows: local time + expandable readout ---------------- */
  function timeAgo(ms) {
    var m = Math.round((Date.now() - ms) / 60000);
    if (m < 1) return 'just now';
    if (m < 90) return m + ' min ago';
    if (m < 2880) return Math.round(m / 60) + ' h ago';
    return Math.round(m / 1440) + ' d ago';
  }
  function localizeTimes(rootEl) {
    (rootEl || document).querySelectorAll('time.loc-time').forEach(function (t) {
      var d = new Date(t.getAttribute('datetime'));
      if (isNaN(d)) return;
      t.textContent = d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
      t.title = d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
      var age = t.parentElement && t.parentElement.querySelector('.loc-age');
      if (age) age.textContent = timeAgo(d.getTime());
    });
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.sig-detail-btn');
    if (!btn) return;
    var row = btn.closest('tr'), det = row && row.nextElementSibling;
    if (!det || !det.classList.contains('sig-detail')) return;
    var open = det.hidden;
    det.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.innerHTML = open ? 'Hide &#9652;' : 'Details &#9662;';
  });

  function showOnly(which) {
    ['splash', 'auth-screen', 'noaccess', 'app'].forEach(function (id) { show(id, id === which); });
  }

  /* ---------------- data ---------------- */

  async function fetchRows() {
    if (DEV) {
      var r = await fetch('portions.json?t=' + Date.now(), { cache: 'no-store' });
      if (!r.ok) throw new Error('portions.json not found (run dashboard.py locally first)');
      return r.json();
    }
    var res = await sb.from('portions').select('key,title,sort_order,html,data,updated_at');
    if (res.error) throw res.error;
    return res.data || [];
  }

  async function loadProfile() {
    if (DEV) return { is_admin: false, email: 'preview' };
    var uid = S.session.user.id;
    var res = await sb.from('profiles').select('email,is_admin').eq('user_id', uid).maybeSingle();
    return (res && res.data) || { email: S.session.user.email, is_admin: false };
  }

  /* ---------------- rendering ---------------- */

  function renderMeta(meta) {
    var d = (meta && meta.data) || {};
    S.generatedAt = d.generated_at_iso ? new Date(d.generated_at_iso).getTime() : null;
    S.refreshSeconds = d.refresh_seconds || 120;
    $('meta-line').innerHTML =
      'Fear &amp; Greed: ' + esc(d.fng_top || 'N/A') +
      '<span class="info-tip" tabindex="0" data-tip="A 0-100 index of overall crypto market sentiment from Alternative.me, based on volatility, volume, social media, and surveys. Low = fear (often washed-out), high = greed (often euphoric). A contrarian gauge, not a timing signal on its own.">&#9432;</span>' +
      ' &nbsp;|&nbsp; <span id="updated-ago">just now</span>' +
      '<span class="info-tip" tabindex="0" data-tip="Generated: ' + esc(d.generated_at || '') + ' UTC. Data regenerated ' + esc(d.data_refresh_label || 'every few minutes') + '.">&#9432;</span>';
    $('banner').innerHTML = ((meta && meta.html) || '').replace(/&nbsp;&middot;&nbsp; ?/g, '<span class="sep">&nbsp;&middot;&nbsp; </span>');
    tick();
  }

  function tick() {
    var el = $('updated-ago');
    if (!el || !S.generatedAt) return;
    var mins = Math.max(0, Math.round((Date.now() - S.generatedAt) / 60000));
    el.textContent = mins <= 0 ? 'just now' : ('updated ' + mins + 'm ago');
  }

  function tabLabel(title) {
    var m = /^(\S+)\s+([\s\S]*)$/.exec(title || '');
    return m ? '<span class="tab-ico">' + m[1] + '</span><span class="tab-txt">' + m[2] + '</span>' : title;
  }

  function render(rows) {
    var meta = rows.filter(function (r) { return r.key === '_meta'; })[0];
    var secs = rows.filter(function (r) { return r.key !== '_meta'; })
      .sort(function (a, b) { return (a.sort_order || 0) - (b.sort_order || 0); });
    var root = $('tabs-root');

    // Scanner and Performance are one screen: the performance record sits under the scanner tables. Access control is
    // unchanged - someone who only has one of the two sections just sees that one.
    var scr = secs.filter(function (r) { return r.key === 'screener'; })[0];
    var perf = secs.filter(function (r) { return r.key === 'performance'; })[0];
    if (scr && perf) {
      var cut = scr.html.lastIndexOf('</div>');
      var embedded = String(perf.html || '').replace('class="panel panel-performance"', 'class="perf-embed"');
      scr = Object.assign({}, scr, { html: scr.html.slice(0, cut) + '<div class="perf-head">\uD83D\uDCCA PERFORMANCE <span>how the signals above have actually done</span></div>' + embedded + scr.html.slice(cut) });
      secs = secs.filter(function (r) { return r.key !== 'performance' && r.key !== 'screener'; });
      secs.push(scr);
      secs.sort(function (a, b) { return (a.sort_order || 0) - (b.sort_order || 0); });
    }

    // Keep the reader where they were across a refresh: which top-level tab and nested sub-tab.
    var checked = {};
    root.querySelectorAll('input[type=radio]:checked').forEach(function (i) { checked[i.id] = true; });

    var haveChecked = secs.some(function (r) { return checked['tab-' + r.key]; });
    var html = '';
    secs.forEach(function (r, i) {
      var on = haveChecked ? checked['tab-' + r.key] : i === 0;
      html += '<input type="radio" name="tabs" id="tab-' + r.key + '"' + (on ? ' checked' : '') + '>\n';
    });
    html += '<div class="tabbar">' + secs.map(function (r) { return '<label for="tab-' + r.key + '">' + tabLabel(r.title) + '</label>'; }).join('\n') + '</div>\n';
    secs.forEach(function (r) { html += r.html + '\n'; });
    root.innerHTML = html;

    Object.keys(checked).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.type === 'radio') el.checked = true;
    });

    if (meta) renderMeta(meta);

    var has = {};
    secs.forEach(function (r) { has[r.key] = r; });
    // Follow buttons feed My Picks; without that section they'd save into a list nobody can open.
    if (!has.mypicks) root.querySelectorAll('.follow-btn').forEach(function (b) { b.remove(); });
    if (window.kairoInitIntraday) window.kairoInitIntraday(has.screener ? (has.screener.data || {}).intraday_cards : []);
    if (window.kairoInitFollow && has.mypicks) window.kairoInitFollow();
    if (window.kairoInitPnlSearch) window.kairoInitPnlSearch();
    enhanceTables(root);
    localizeTimes(root);
    initWatchlist();
    if (window.kairoInitCharts) window.kairoInitCharts(has.bigcoins ? ((has.bigcoins.data || {}).charts || {}) : {});
    initSignalPrices();
    // Admin-only: the server only returns this row to admins, so for everyone else `has.scalping` is simply undefined.
    if (window.kairoInitScalping && has.scalping) window.kairoInitScalping(has.scalping, { sb: function () { return sb; }, isAdmin: !!(S.profile && S.profile.is_admin) || DEV, dev: DEV });
    if (window.kairoInitEvents && has.events) {
      window.kairoInitEvents(has.events, { sb: function () { return sb; }, isAdmin: !!(S.profile && S.profile.is_admin), dev: DEV });
    }
  }

  async function refresh(initial) {
    if (S.loading) return;
    if (!initial && document.querySelector('[data-busy="1"]')) return;      // mid-drawing: skip this refresh, the next one will catch up
    S.loading = true;
    try {
      var rows = await fetchRows();
      S.rows = rows;
      var secs = rows.filter(function (r) { return r.key !== '_meta'; });
      if (!secs.length) { showNoAccess(); return; }
      if (initial) showOnly('app');
      render(rows);
      if (initial) applyPendingDeepLink();
    } catch (e) {
      if (initial) {
        showLogin('Could not load the dashboard. Check your connection and try again.');
      } else {
        var m = $('updated-ago'); if (m) m.textContent = 'offline - retrying';
      }
    } finally {
      S.loading = false;
    }
  }

  function startLoops() {
    stopLoops();
    S.tickTimer = setInterval(tick, 15000);
    S.refreshTimer = setInterval(function () { refresh(false); }, S.refreshSeconds * 1000);
  }
  function stopLoops() {
    if (S.tickTimer) clearInterval(S.tickTimer);
    if (S.refreshTimer) clearInterval(S.refreshTimer);
    S.tickTimer = S.refreshTimer = null;
    if (wlTimer) { clearInterval(wlTimer); wlTimer = null; }
  }
  // Timers freeze while a phone app is backgrounded; refresh the moment it comes back if stale.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden || (!DEV && !S.session)) return;
    if (S.generatedAt && Date.now() - S.generatedAt > S.refreshSeconds * 1000) refresh(false);
  });

  /* ---------------- screens ---------------- */

  function showLogin(msg) {
    stopLoops();
    $('tabs-root').innerHTML = '';                  // don't leave section HTML in the DOM once signed out
    $('meta-line').innerHTML = ''; $('banner').innerHTML = '';
    $('login-error').textContent = msg || '';
    $('login-password').value = '';
    showOnly('auth-screen');
  }

  function showNoAccess() {
    stopLoops();
    $('tabs-root').innerHTML = '';
    $('noaccess-email').textContent = (S.profile && S.profile.email) || '';
    showOnly('noaccess');
  }

  /* ---------------- auth ---------------- */

  function bridgeToAndroid(token) {
    // The Android wrapper's background check reads notifications with a per-user, read-only,
    // revocable token instead of sharing this session's refresh token (two clients refreshing
    // one rotating token would sign each other out).
    if (window.KairoAndroid && token) {
      try { window.KairoAndroid.saveNotifyConfig(CFG.supabaseUrl, CFG.anonKey, token); } catch (e) { /* not in the app */ }
    }
  }

  async function onSignedIn(session) {
    S.session = session;
    // Local "My Picks" belong to whoever saved them -- don't show one account's list to the next
    // account that signs in on the same browser.
    try {
      if (localStorage.getItem('kairo_last_user') !== session.user.id) {
        localStorage.removeItem('kairo_followed_picks');
        localStorage.setItem('kairo_last_user', session.user.id);
      }
    } catch (e) { /* storage unavailable */ }
    S.profile = await loadProfile();
    show('btn-admin', !!S.profile.is_admin);
    show('btn-alerts', !!S.profile.is_admin);
    show('btn-watchlist', !!S.profile.is_admin);
    if (window.KairoAndroid) {
      sb.rpc('get_notify_token').then(function (r) { if (!r.error) bridgeToAndroid(r.data); });
    }
    await refresh(true);
    if (!$('app').hidden) startLoops();
  }

  async function doSignOut() {
    stopLoops();
    if (!DEV) {
      try { await sb.rpc('clear_notify_token'); } catch (e) { /* best effort */ }
      if (window.KairoAndroid) { try { window.KairoAndroid.clearNotifyConfig(); } catch (e) { /* ignore */ } }
      await sb.auth.signOut();
    }
    S.session = null; S.profile = null; S.rows = [];
    closeOverlay();
    showLogin('');
  }

  /* ---------------- overlays (account + admin) ---------------- */

  function openOverlay(html) { $('overlay-card').innerHTML = html; show('overlay', true); }
  function closeOverlay() { show('overlay', false); $('overlay-card').innerHTML = ''; }
  function setMsg(text, kind) { var m = $('ov-msg'); if (m) { m.textContent = text || ''; m.className = 'overlay-msg' + (kind ? ' ' + kind : ''); } }

  function openAccount() {
    openOverlay(
      '<div class="overlay-row"><h2>Account</h2><button type="button" class="ghost" id="ov-close">Close</button></div>' +
      '<div class="sub">Signed in as <strong>' + esc(S.profile && S.profile.email) + '</strong></div>' +
      (window.KairoAndroid && window.KairoAndroid.getVersion ? '<div class="sub">Android app version: <strong>' + esc(window.KairoAndroid.getVersion()) + '</strong></div>' : '') +
      '<h3>Change password</h3>' +
      '<input type="password" id="pw-new" placeholder="New password (min 10 characters)" autocomplete="new-password">' +
      '<input type="password" id="pw-new2" placeholder="Repeat new password" autocomplete="new-password">' +
      '<button type="button" class="primary" id="pw-save">Update password</button>' +
      '<div class="overlay-msg" id="ov-msg"></div>');
    $('ov-close').onclick = closeOverlay;
    $('pw-save').onclick = async function () {
      var a = $('pw-new').value, b = $('pw-new2').value;
      if (a.length < 10) return setMsg('Use at least 10 characters.', 'err');
      if (a !== b) return setMsg('The two passwords don\'t match.', 'err');
      if (DEV) return setMsg('Preview mode: no account to update.', 'err');
      this.disabled = true;
      var r = await sb.auth.updateUser({ password: a });
      this.disabled = false;
      if (r.error) return setMsg(r.error.message, 'err');
      $('pw-new').value = ''; $('pw-new2').value = '';
      setMsg('Password updated.', 'ok');
    };
  }

  async function openAdmin() {
    openOverlay('<div class="overlay-row"><h2>Users &amp; access</h2><button type="button" class="ghost" id="ov-close">Close</button></div>' +
      '<div class="sub">Only accounts you add here can sign in, and each sees only the sections ticked for it.</div>' +
      '<div class="overlay-msg" id="ov-msg">Loading&hellip;</div><div id="ov-body"></div>');
    $('ov-close').onclick = closeOverlay;
    await renderAdminBody();
  }

  async function renderAdminBody() {
    var r = await sb.rpc('admin_list_users');
    if (r.error) return setMsg(r.error.message, 'err');
    setMsg('');
    var html = '<div class="user-list">' + (r.data || []).map(function (u) {
      var perms = PORTION_KEYS.map(function (k) {
        var on = u.is_admin || (u.portions || []).indexOf(k) >= 0;
        return '<label><input type="checkbox" data-user="' + esc(u.user_id) + '" data-portion="' + k + '"' +
          (on ? ' checked' : '') + (u.is_admin ? ' disabled' : '') + '> ' + PORTION_LABELS[k] + '</label>';
      }).join('');
      var isSelf = S.session && u.user_id === S.session.user.id;
      return '<div class="user-card"><div class="who">' + esc(u.email) + (u.is_admin ? '<span class="tag">ADMIN</span>' : '') + '</div>' +
        '<div class="perms">' + perms + '</div>' +
        (u.is_admin ? '<div class="sub">Admins can see every section.</div>' :
          '<div class="actions">' +
          '<input type="text" placeholder="New password (min 10)" data-pw-for="' + esc(u.user_id) + '" autocomplete="off">' +
          '<button type="button" class="ghost" data-reset="' + esc(u.user_id) + '">Set password</button>' +
          (isSelf ? '' : '<button type="button" class="ghost danger" data-del="' + esc(u.user_id) + '">Remove</button>') +
          '</div>') + '</div>';
    }).join('') + '</div>' +
      '<h3>Add a user</h3>' +
      '<input type="email" id="new-email" placeholder="Email" autocomplete="off">' +
      '<input type="text" id="new-pass" placeholder="Temporary password (min 10 characters)" autocomplete="off">' +
      '<button type="button" class="primary" id="new-add">Add user</button>' +
      '<div class="sub" style="margin-top:8px;">They start with no sections. Tick what they may see above, then send them the email and password (they can change it under Account).</div>';
    $('ov-body').innerHTML = html;

    $('ov-body').querySelectorAll('input[type=checkbox][data-user]').forEach(function (cb) {
      cb.onchange = async function () {
        cb.disabled = true;
        var res = await sb.rpc('admin_set_access', { p_user: cb.dataset.user, p_portion: cb.dataset.portion, p_granted: cb.checked });
        cb.disabled = false;
        if (res.error) { cb.checked = !cb.checked; setMsg(res.error.message, 'err'); } else { setMsg('Saved.', 'ok'); }
      };
    });
    $('ov-body').querySelectorAll('[data-reset]').forEach(function (btn) {
      btn.onclick = async function () {
        var pw = $('ov-body').querySelector('[data-pw-for="' + btn.dataset.reset + '"]').value;
        var res = await sb.rpc('admin_reset_password', { p_user: btn.dataset.reset, p_password: pw });
        setMsg(res.error ? res.error.message : 'Password set.', res.error ? 'err' : 'ok');
      };
    });
    $('ov-body').querySelectorAll('[data-del]').forEach(function (btn) {
      btn.onclick = async function () {
        if (btn.dataset.armed !== '1') { btn.dataset.armed = '1'; btn.textContent = 'Really remove?'; return; }
        var res = await sb.rpc('admin_delete_user', { p_user: btn.dataset.del });
        if (res.error) return setMsg(res.error.message, 'err');
        await renderAdminBody(); setMsg('User removed.', 'ok');
      };
    });
    $('new-add').onclick = async function () {
      var email = $('new-email').value.trim(), pw = $('new-pass').value;
      var res = await sb.rpc('admin_create_user', { p_email: email, p_password: pw });
      if (res.error) return setMsg(res.error.message, 'err');
      await renderAdminBody(); setMsg('User added. Now tick the sections they may see.', 'ok');
    };
  }

  /* ---------------- price alerts (admin) ---------------- */

  var ALERT_COINS = ['BTC', 'ETH'];

  async function openAlerts() {
    openOverlay('<div class="overlay-row"><h2>Price alerts</h2><button type="button" class="ghost" id="ov-close">Close</button></div>' +
      '<div class="sub">Shown to everyone on the Overview once triggered. Only BTC and ETH have a page to alert on.</div>' +
      '<div class="overlay-msg" id="ov-msg">Loading&hellip;</div><div id="ov-body"></div>');
    $('ov-close').onclick = closeOverlay;
    await renderAlertsBody();
  }

  function alertRowHtml(a) {
    return '<div class="user-card" data-alert-row="' + esc(a.id) + '">' +
      '<div class="who">' + esc(a.label) + '<span class="tag">' + esc(a.coin) + '</span></div>' +
      '<div class="sub">' + esc(a.coin) + ' ' + esc(a.condition) + ' ' + esc(String(a.price)) + (a.enabled ? '' : ' &middot; disabled') + '</div>' +
      '<div class="actions">' +
      '<label><input type="checkbox" data-alert-enable="' + esc(a.id) + '"' + (a.enabled ? ' checked' : '') + '> Enabled</label>' +
      '<button type="button" class="ghost" data-alert-edit="' + esc(a.id) + '">Edit</button>' +
      '<button type="button" class="ghost danger" data-alert-del="' + esc(a.id) + '">Delete</button>' +
      '</div></div>';
  }

  function alertFormHtml(a) {
    a = a || { id: '', coin: 'BTC', condition: 'above', price: '', label: '', enabled: true };
    return '<input type="hidden" id="al-id" value="' + esc(a.id) + '">' +
      '<label>Coin<select id="al-coin">' + ALERT_COINS.map(function (c) { return '<option' + (c === a.coin ? ' selected' : '') + '>' + c + '</option>'; }).join('') + '</select></label>' +
      '<label>Condition<select id="al-cond"><option value="above"' + (a.condition === 'above' ? ' selected' : '') + '>Price rises above</option>' +
      '<option value="below"' + (a.condition === 'below' ? ' selected' : '') + '>Price falls below</option></select></label>' +
      '<input type="number" id="al-price" step="any" placeholder="Price" value="' + esc(a.price) + '">' +
      '<input type="text" id="al-label" placeholder="Label shown on the alert" value="' + esc(a.label) + '">' +
      '<button type="button" class="primary" id="al-save">' + (a.id ? 'Save changes' : 'Add alert') + '</button>' +
      (a.id ? '<button type="button" class="ghost" id="al-cancel">Cancel</button>' : '');
  }

  async function renderAlertsBody(editing) {
    var r = await sb.from('price_alerts').select('*').order('coin').order('price');
    if (r.error) return setMsg(r.error.message, 'err');
    setMsg('');
    var rows = r.data || [];
    var editRow = editing && rows.filter(function (a) { return a.id === editing; })[0];
    $('ov-body').innerHTML = '<div class="user-list">' + rows.map(alertRowHtml).join('') + '</div>' +
      (rows.length ? '' : '<div class="sub">No alerts yet.</div>') +
      '<h3>' + (editRow ? 'Edit alert' : 'Add an alert') + '</h3>' + alertFormHtml(editRow);

    $('ov-body').querySelectorAll('[data-alert-enable]').forEach(function (cb) {
      cb.onchange = async function () {
        var a = rows.filter(function (x) { return x.id === cb.dataset.alertEnable; })[0];
        cb.disabled = true;
        var res = await sb.rpc('admin_upsert_price_alert', { p_id: a.id, p_coin: a.coin, p_condition: a.condition, p_price: a.price, p_label: a.label, p_enabled: cb.checked });
        if (res.error) { cb.checked = !cb.checked; setMsg(res.error.message, 'err'); } else { setMsg('Saved.', 'ok'); }
        cb.disabled = false;
      };
    });
    $('ov-body').querySelectorAll('[data-alert-edit]').forEach(function (btn) {
      btn.onclick = function () { renderAlertsBody(btn.dataset.alertEdit); };
    });
    $('ov-body').querySelectorAll('[data-alert-del]').forEach(function (btn) {
      btn.onclick = async function () {
        if (btn.dataset.armed !== '1') { btn.dataset.armed = '1'; btn.textContent = 'Really delete?'; return; }
        var res = await sb.rpc('admin_delete_price_alert', { p_id: btn.dataset.alertDel });
        if (res.error) return setMsg(res.error.message, 'err');
        await renderAlertsBody(); setMsg('Alert deleted.', 'ok');
      };
    });
    var cancel = $('al-cancel'); if (cancel) cancel.onclick = function () { renderAlertsBody(); };
    $('al-save').onclick = async function () {
      var id = $('al-id').value.trim() || ($('al-coin').value.toLowerCase() + '-' + Date.now());
      var price = parseFloat($('al-price').value);
      var label = $('al-label').value.trim();
      if (!label) return setMsg('Give the alert a label.', 'err');
      if (!(price > 0)) return setMsg('Enter a valid price.', 'err');
      var res = await sb.rpc('admin_upsert_price_alert', { p_id: id, p_coin: $('al-coin').value, p_condition: $('al-cond').value, p_price: price, p_label: label, p_enabled: true });
      if (res.error) return setMsg(res.error.message, 'err');
      await renderAlertsBody(); setMsg('Saved. Shown after the next refresh.', 'ok');
    };
  }

  /* ---------------- trend-breakout pinned watchlist (admin) ---------------- */

  async function openWatchlist() {
    openOverlay('<div class="overlay-row"><h2>Trend Breakout watchlist</h2><button type="button" class="ghost" id="ov-close">Close</button></div>' +
      '<div class="sub">These coins are checked for a Trend Breakout setup every single run, regardless of the ' +
      'random pool rotation that otherwise decides which coins get scanned. Use this for a coin you specifically ' +
      'want the engine watching (QNT and MOVR both had real qualifying breakouts missed purely because neither ' +
      'was ever scanned) -- a long list here means fewer of the pool’s random slots, so keep it to coins you ' +
      'actually care about.</div>' +
      '<div class="overlay-msg" id="ov-msg">Loading&hellip;</div><div id="ov-body"></div>');
    $('ov-close').onclick = closeOverlay;
    await renderWatchlistBody();
  }

  async function renderWatchlistBody() {
    var q = await sb.from('trend_settings').select('value').eq('key', 'config').maybeSingle();
    if (q.error) return setMsg(q.error.message, 'err');
    setMsg('');
    var v = (q.data && q.data.value) || {};
    var pinned = v.pinned_coins || [];
    $('ov-body').innerHTML =
      '<textarea id="wl-coins" rows="3" placeholder="e.g. QNT, MOVR, INJ" style="width:100%; resize:vertical;">' + esc(pinned.join(', ')) + '</textarea>' +
      '<div class="sub" style="margin-top:6px;">Comma-separated symbols, as they trade on Binance against USDT (no need to add USDT yourself).</div>' +
      '<label style="display:flex; align-items:center; gap:8px; margin-top:14px;"><input type="checkbox" id="wl-short"' + (v.allow_short ? ' checked' : '') + '> Also scan for SHORT (downside) breakouts</label>' +
      '<div class="sub" style="margin-top:4px;">A mirrored sign-flip of the LONG rule, backtested against 2 years of real history: LONG holds up out-of-sample, SHORT does not (net -757% over the full period, an unstable/overfit result, not a real edge). Every SHORT signal is labelled as unvalidated on the Signals page — this switch is here because it was asked for, not because the backtest recommends it.</div>' +
      '<button type="button" class="primary" id="wl-save" style="margin-top:10px;">Save watchlist</button>';
    $('wl-save').onclick = async function () {
      var coins = $('wl-coins').value.split(',').map(function (s) { return s.trim().toUpperCase(); }).filter(Boolean);
      var res = await sb.rpc('admin_set_trend_config', { p_value: { pinned_coins: coins, allow_short: $('wl-short').checked } });
      if (res.error) return setMsg(res.error.message, 'err');
      setMsg('Saved. Takes effect on the next scheduled run.', 'ok');
    };
  }

  /* ---------------- boot ---------------- */

  async function boot() {
    $('btn-signout').onclick = doSignOut;
    $('noaccess-signout').onclick = doSignOut;
    $('btn-account').onclick = openAccount;
    $('btn-admin').onclick = openAdmin;
    $('btn-alerts').onclick = openAlerts;
    $('btn-watchlist').onclick = openWatchlist;
    if ($('btn-theme')) { $('btn-theme').onclick = cycleTheme; applyTheme(currentTheme()); }
    initMobileMenu();
    $('overlay').addEventListener('click', function (e) { if (e.target === $('overlay')) closeOverlay(); });

    if (DEV) {
      show('btn-account', false); show('btn-signout', false);
      S.profile = await loadProfile();
      await refresh(true);
      if (!$('app').hidden) startLoops();
      return;
    }

    sb = window.supabase.createClient(CFG.supabaseUrl, CFG.anonKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false }
    });

    $('login-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      var btn = $('login-btn'); btn.disabled = true; $('login-error').textContent = '';
      var r = await sb.auth.signInWithPassword({ email: $('login-email').value.trim(), password: $('login-password').value });
      btn.disabled = false;
      if (r.error || !r.data.session) { $('login-error').textContent = 'Incorrect email or password.'; return; }
      await onSignedIn(r.data.session);
    });

    sb.auth.onAuthStateChange(function (event) {
      if (event === 'SIGNED_OUT' && S.session) { S.session = null; showLogin('Signed out.'); }
    });

    var s = await sb.auth.getSession();
    if (s.data && s.data.session) await onSignedIn(s.data.session);
    else showLogin('');
  }

  boot();
})();
