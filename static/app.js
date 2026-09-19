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
  var PORTION_LABELS = { screener: 'Scanner', bigcoins: 'Big Coins', mypicks: 'My Picks', performance: 'Performance (shown inside Scanner)' };
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
    initWatchlist();
    initSignalPrices();
    if (window.kairoInitEvents && has.events) {
      window.kairoInitEvents(has.events, { sb: function () { return sb; }, isAdmin: !!(S.profile && S.profile.is_admin), dev: DEV });
    }
  }

  async function refresh(initial) {
    if (S.loading) return;
    S.loading = true;
    try {
      var rows = await fetchRows();
      S.rows = rows;
      var secs = rows.filter(function (r) { return r.key !== '_meta'; });
      if (!secs.length) { showNoAccess(); return; }
      if (initial) showOnly('app');
      render(rows);
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

  /* ---------------- boot ---------------- */

  async function boot() {
    $('btn-signout').onclick = doSignOut;
    $('noaccess-signout').onclick = doSignOut;
    $('btn-account').onclick = openAccount;
    $('btn-admin').onclick = openAdmin;
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
