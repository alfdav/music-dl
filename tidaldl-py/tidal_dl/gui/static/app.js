/* music-dl — SPA core: router, state, player, views */
/* Security: All user-supplied data (track names, artist names, etc.) goes
   through textContent or the textEl() helper. innerHTML is ONLY used for
   static SVG icons and structural layout scaffolding — never with user data. */
'use strict';

// ---- CSRF ----
let CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';
let _csrfRefreshPromise = null;

async function refreshCsrfToken() {
  if (_csrfRefreshPromise) return _csrfRefreshPromise;

  _csrfRefreshPromise = (async () => {
    const resp = await fetch('/', { method: 'GET', cache: 'no-store' });
    const html = await resp.text();
    const match = html.match(/name="csrf-token" content="([^"]+)"/);
    if (!match) throw new Error('Could not refresh CSRF token');

    CSRF_TOKEN = match[1];
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.content = CSRF_TOKEN;
    return CSRF_TOKEN;
  })();

  try {
    return await _csrfRefreshPromise;
  } finally {
    _csrfRefreshPromise = null;
  }
}

// ---- HELPERS ----
function textEl(tag, text, className) {
  const el = document.createElement(tag);
  el.textContent = text;
  if (className) el.className = className;
  return el;
}

function h(tag, attrs, ...children) {
  const e = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'className') e.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (typeof c === 'string') e.appendChild(document.createTextNode(c));
    else if (c) e.appendChild(c);
  }
  return e;
}

/** Make an element keyboard-activatable (Enter/Space trigger click). */
function a11yClick(el) {
  el.setAttribute('tabindex', '0');
  el.setAttribute('role', 'button');
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      el.click();
    }
  });
}

function formatTime(seconds) {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ':' + String(s).padStart(2, '0');
}

// RPG-tier quality system
function _qualityTier(q, fmt) {
  if (!q) return { tier: 'Common', cls: 'quality-common', desc: 'Unknown quality' };
  const ql = q.toUpperCase();
  const fl = (fmt || '').toUpperCase();

  // Lossy formats always cap at Uncommon regardless of quality string.
  // An M4A reporting "44100Hz/16bit" is still lossy AAC, not lossless.
  if (fl === 'MP3' || fl === 'AAC' || fl === 'OGG' || fl === 'M4A')
    return { tier: 'Uncommon', cls: 'quality-uncommon', desc: (fmt || q) + ' · Lossy' };

  // Tidal quality constants
  if (ql === 'DOLBY_ATMOS' || ql.includes('ATMOS') || ql.includes('DOLBY'))
    return { tier: 'Mythic', cls: 'quality-mythic', desc: 'DOLBY ATMOS · Spatial Audio' };
  if (ql === 'HI_RES_LOSSLESS')
    return { tier: 'Legendary', cls: 'quality-legendary', desc: 'HI-RES LOSSLESS · 24-bit FLAC' };
  if (ql === 'HI_RES' || ql === 'MQA' || ql.includes('MASTER'))
    return { tier: 'Epic', cls: 'quality-epic', desc: 'HI-RES · MQA' };
  if (ql === 'LOSSLESS')
    return { tier: 'Rare', cls: 'quality-rare', desc: 'LOSSLESS · CD 16-bit' };
  if (ql === 'HIGH')
    return { tier: 'Uncommon', cls: 'quality-uncommon', desc: 'HIGH · 320 kbps' };
  if (ql === 'LOW')
    return { tier: 'Common', cls: 'quality-common', desc: 'LOW · 96 kbps' };

  // Local file quality strings: "44100Hz/16bit", "96000Hz/24bit", "MP3", "FLAC", etc.
  if (ql.includes('24BIT') || ql.includes('/24')) {
    const hz = parseInt(ql);
    if (hz > 48000) return { tier: 'Legendary', cls: 'quality-legendary', desc: q + ' · Hi-Res' };
    return { tier: 'Epic', cls: 'quality-epic', desc: q + ' · Hi-Res' };
  }
  if (ql.includes('16BIT') || ql.includes('/16') || ql === 'FLAC')
    return { tier: 'Rare', cls: 'quality-rare', desc: q + ' · Lossless' };
  if (ql === 'MP3' || ql === 'AAC' || ql === 'OGG' || ql === 'M4A')
    return { tier: 'Uncommon', cls: 'quality-uncommon', desc: q + ' · Lossy' };
  if (ql === 'WAV')
    return { tier: 'Rare', cls: 'quality-rare', desc: q + ' · Lossless' };

  return { tier: 'Common', cls: 'quality-common', desc: q };
}

function qualityClass(q, fmt) { return _qualityTier(q, fmt).cls; }
function qualityLabel(q, fmt) { return _qualityTier(q, fmt).tier; }
function qualityTitle(q, fmt) { return _qualityTier(q, fmt).desc; }

function artGradient(id) {
  const hue = ((id || 0) * 137.508) % 360;
  const h2 = (hue + 40) % 360;
  return 'linear-gradient(145deg, hsl(' + hue + ', 35%, 18%), hsl(' + h2 + ', 40%, 28%), hsl(' + hue + ', 30%, 12%))';
}

/** Create an SVG element from a static icon template (no user data). */
function svgIcon(pathsMarkup) {
  const wrapper = document.createElement('span');
  // SAFE: pathsMarkup is always a hardcoded string constant from ICONS below.
  // It never contains user-supplied data.
  wrapper.innerHTML = pathsMarkup; // eslint-disable-line -- static SVG only
  return wrapper.firstElementChild;
}

// ---- SVG ICON TEMPLATES (static, no user data) ----
const ICONS = {
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="20 6 9 17 4 12"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
  music: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  play: '<polygon points="5 3 19 12 5 21 5 3"/>',
  pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
};

// ---- STATE ----
const state = {
  view: 'home',
  searchQuery: '',
  searchType: 'tracks',
  searchResults: null,
  queue: [],
  queueOriginal: [],
  queueIndex: -1,
  playing: false,
  shuffle: false,
  repeat: 'off',  // 'off' | 'all' | 'one'
  volume: 0.7,
  smartShuffle: false,
  settingsReadOnly: false,
  settingsAccess: null,
};
let _settingsLoad = null;
let _queueEntrySeq = 0;

async function _ensureSettingsLoaded() {
  if (state.settings) return state.settings;
  if (!_settingsLoad) {
    _settingsLoad = api('/settings')
      .then(settings => {
        state.settings = settings;
        return settings;
      })
      .catch(err => {
        _settingsLoad = null;
        throw err;
      });
  }
  return _settingsLoad;
}

// ---- FAVORITES CACHE ----
// Keyed by path for local tracks or "tidal:{id}" for Tidal tracks
const _favCache = {};

async function loadFavCache(tracks) {
  const paths = [];
  const tids = [];
  tracks.forEach(t => {
    if (t.path) paths.push(t.path);
    else if (t.id) tids.push(t.id);
  });
  if (!paths.length && !tids.length) return;

  try {
    const params = new URLSearchParams();
    if (paths.length) params.set('paths', paths.join(','));
    if (tids.length) params.set('tidal_ids', tids.join(','));
    const data = await api('/library/favorites/check?' + params.toString());
    Object.assign(_favCache, data.favorites || {});
  } catch (_) {}
}

async function toggleFavorite(track, btn) {
  const body = {
    path: track.path || null,
    tidal_id: track.id || null,
    artist: track.artist || null,
    title: track.name || null,
    album: track.album || null,
    isrc: track.isrc || null,
    cover_url: track.cover_url || null,
  };

  // Optimistic toggle — update UI immediately, revert on failure
  const key = track.path || (track.id ? 'tidal:' + track.id : null);
  const wasFav = key ? !!_favCache[key] : btn.classList.contains('hearted');
  btn.classList.toggle('hearted', !wasFav);
  if (key) _favCache[key] = !wasFav;
  updatePlayerHeart();

  try {
    const res = await api('/library/favorites/toggle', {
      method: 'POST',
      body,
    });

    // Sync with server truth in case of race
    if (key) _favCache[key] = res.favorited;
    btn.classList.toggle('hearted', res.favorited);
    updatePlayerHeart();
  } catch (err) {
    // Revert optimistic update
    btn.classList.toggle('hearted', wasFav);
    if (key) _favCache[key] = wasFav;
    updatePlayerHeart();
    toast('Failed to update favorite', 'error');
  }
}

async function upgradeTrack(track) {
  const localPath = track.local_path || track.path;
  if (!localPath) { toast('No local file path', 'error'); return; }
  const isrc = track.isrc;
  if (!isrc) { toast('No ISRC — cannot match on Tidal', 'error'); return; }

  toast('Checking Tidal for upgrade...', 'success');

  try {
    const probeData = await api('/upgrade/probe', { method: 'POST', body: { isrcs: [isrc] } });
    const result = (probeData.results || [])[0];
    if (!result || !result.upgradeable) {
      toast('Already at best available quality', 'success');
      return;
    }
    toast('Upgrading to ' + qualityLabel(result.max_quality) + '...', 'success', 5000);
    await api('/upgrade/start', { method: 'POST', body: { track_paths: [localPath] } });
  } catch (err) {
    toast('Upgrade failed: ' + (err.message || err), 'error');
  }
}

function _playlistUpgradeTargetRank() {
  return { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
}

function _playlistUpgradeCandidates(tracks) {
  const tierRanks = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 };
  const targetRank = _playlistUpgradeTargetRank();
  return (tracks || []).filter(t => {
    if (!t || !t.is_local || !t.isrc) return false;
    const localRank = tierRanks[_qualityTier(t.quality, t.format).tier] || 0;
    return localRank < targetRank;
  });
}

function _setPlaylistUpgradeBadge(trackList, track, maxQuality) {
  const row = trackList.querySelector('[data-track-id="' + _trackKey(track) + '"]');
  if (!row) return false;
  const ex = row.querySelector('.upgrade-badge');
  if (ex) ex.remove();

  const tierRanks = { 'LOW': 0, 'HIGH': 1, 'LOSSLESS': 2, 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 };
  const localRank = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 }[_qualityTier(track.quality, track.format).tier] || 0;
  const probeRank = tierRanks[maxQuality] || 0;
  const targetRank = _playlistUpgradeTargetRank();
  if (probeRank <= localRank || probeRank < targetRank) return false;

  const badge = h('span', { className: 'upgrade-badge' });
  badge.textContent = '⬆ ' + qualityLabel(maxQuality);
  const metaCell = row.querySelector('.track-artist');
  if (metaCell && metaCell.parentElement) metaCell.parentElement.appendChild(badge);
  return true;
}

async function _scanPlaylistUpgrades(tracks, trackList, upgradeBtn, refreshBtn, options) {
  const opts = options || {};
  const force = !!opts.force;

  try {
    await _ensureSettingsLoaded();
  } catch (_) {
    upgradeBtn.style.display = 'none';
    if (refreshBtn) refreshBtn.style.display = 'none';
    return;
  }

  const candidates = _playlistUpgradeCandidates(tracks);
  if (candidates.length === 0) {
    upgradeBtn.style.display = 'none';
    if (refreshBtn) refreshBtn.style.display = 'none';
    return;
  }

  const byIsrc = new Map();
  candidates.forEach(track => {
    const list = byIsrc.get(track.isrc) || [];
    list.push(track);
    byIsrc.set(track.isrc, list);
  });

  const applyResults = (results, upgradeableMap, unresolved, resolveMisses) => {
    (results || []).forEach(result => {
      const isrc = result.isrc;
      const matches = byIsrc.get(isrc) || [];
      if (resolveMisses || (result.tidal_track_id && result.max_quality)) {
        unresolved.delete(isrc);
      }
      matches.forEach(track => {
        if (!result.tidal_track_id || !result.max_quality) return;
        if (!_setPlaylistUpgradeBadge(trackList, track, result.max_quality)) return;
        const key = (track.local_path || track.path || '') + '::' + result.tidal_track_id;
        upgradeableMap.set(key, { path: track.local_path || track.path, tidal_track_id: result.tidal_track_id });
      });
    });
  };

  const unresolved = new Set([...byIsrc.keys()]);
  const upgradeableMap = new Map();
  const isrcs = [...byIsrc.keys()];

  if (force) {
    trackList.querySelectorAll('.upgrade-badge').forEach(badge => badge.remove());
  }

  upgradeBtn.style.display = '';
  upgradeBtn.disabled = true;
  upgradeBtn.textContent = 'Checking upgrades...';
  upgradeBtn.title = 'Checking Tidal for higher quality versions';
  if (refreshBtn) {
    refreshBtn.style.display = '';
    refreshBtn.disabled = true;
    refreshBtn.title = 'Refresh upgrade availability';
  }

  try {
    if (!force) {
      for (let i = 0; i < isrcs.length; i += 100) {
        const batch = isrcs.slice(i, i + 100);
        const statusData = await api('/upgrade/status?isrcs=' + encodeURIComponent(batch.join(',')));
        applyResults(statusData.results, upgradeableMap, unresolved, false);
      }
    }

    const misses = force ? isrcs : [...unresolved];
    for (let i = 0; i < misses.length; i += 50) {
      const batch = misses.slice(i, i + 50);
      const probeData = await api('/upgrade/probe', { method: 'POST', body: { isrcs: batch, force: force } });
      applyResults(probeData.results, upgradeableMap, unresolved, true);
    }
  } catch (_) {
    upgradeBtn.style.display = 'none';
    if (refreshBtn) refreshBtn.style.display = 'none';
    return;
  }

  if (refreshBtn) {
    refreshBtn.disabled = false;
    refreshBtn.onclick = () => { _scanPlaylistUpgrades(tracks, trackList, upgradeBtn, refreshBtn, { force: true }); };
  }

  const allUpgradeable = [...upgradeableMap.values()].filter(item => item.path && item.tidal_track_id);
  if (allUpgradeable.length === 0) {
    upgradeBtn.textContent = 'No Upgrades Available';
    upgradeBtn.disabled = true;
    upgradeBtn.title = 'No higher quality playlist tracks found';
    return;
  }

  upgradeBtn.textContent = 'Upgrade ' + allUpgradeable.length + ' Tracks';
  upgradeBtn.disabled = false;
  upgradeBtn.title = 'Upgrade playlist tracks with higher quality available on Tidal';
  upgradeBtn.onclick = async () => {
    upgradeBtn.disabled = true;
    upgradeBtn.textContent = 'Upgrading...';
    try {
      const resp = await api('/upgrade/start', {
        method: 'POST',
        body: { tracks: allUpgradeable.map(u => ({ path: u.path, tidal_track_id: u.tidal_track_id })) }
      });
      if (resp.count > 0) { updateDlBadge(resp.count); _ensureGlobalSSE(); }
      toast('Upgrade started for ' + (resp.count || allUpgradeable.length) + ' tracks', 'success');
    } catch (err) {
      toast('Upgrade failed', 'error');
      upgradeBtn.disabled = false;
      upgradeBtn.textContent = 'Upgrade ' + allUpgradeable.length + ' Tracks';
    }
  };
}

// ---- GLOBAL 409 HANDLER ----
const _origFetch = window.fetch;
window.fetch = async (...args) => {
  const resp = await _origFetch(...args);
  if (resp.status === 409) {
    const data = await resp.clone().json().catch(() => null);
    toast(data?.detail || 'Operation in progress \u2014 try again shortly.', 'error');
  }
  return resp;
};

// ---- API ----
const apiCache = {};

async function api(path, options) {
  const opts = options || {};
  const method = opts.method || 'GET';
  const headers = {};

  if (method !== 'GET') {
    headers['X-CSRF-Token'] = CSRF_TOKEN;
    headers['Content-Type'] = 'application/json';
  }

  const resp = await fetch('/api' + path, {
    method,
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    if (
      resp.status === 403 &&
      detail.detail === 'Forbidden: invalid or missing CSRF token' &&
      method !== 'GET' &&
      !opts._csrfRetried
    ) {
      await refreshCsrfToken();
      return api(path, { ...opts, _csrfRetried: true });
    }
    const message = detail.detail || 'API error ' + resp.status;
    const error = new Error(message);
    error.status = resp.status;
    error.detail = message;
    throw error;
  }

  return resp.json();
}

function _isTidalAuthError(error) {
  return !!(
    error &&
    error.status === 401 &&
    typeof error.detail === 'string' &&
    error.detail.toLowerCase().includes('not logged in to tidal')
  );
}

async function apiTidal(path, options) {
  try {
    return await api(path, options);
  } catch (error) {
    if (_isTidalAuthError(error) && !_loginPoll) {
      toast('Tidal login required — opening sign-in…', 'error');
      triggerLogin();
    }
    throw error;
  }
}

// ---- TOAST ----
let toastContainer;

function toast(message, type, durationMs) {
  if (!toastContainer) {
    toastContainer = h('div', { className: 'toast-container', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(toastContainer);
  }
  const t = textEl('div', message, 'toast' + (type ? ' ' + type : ''));
  toastContainer.appendChild(t);
  setTimeout(() => { t.remove(); }, durationMs || (type === 'error' ? 5000 : 3000));
}

function toastSticky(contentEl) {
  if (!toastContainer) {
    toastContainer = h('div', { className: 'toast-container', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(toastContainer);
  }
  toastContainer.appendChild(contentEl);
  return contentEl;
}

// ---- INLINE CONFIRM ----
function inlineConfirm(message, onYes) {
  const overlay = h('div', { className: 'confirm-overlay', role: 'dialog', 'aria-modal': 'true' });
  const card = h('div', { className: 'confirm-card' });
  card.appendChild(textEl('p', message, 'confirm-msg'));
  const actions = h('div', { className: 'confirm-actions' });
  const cancelBtn = textEl('button', 'Cancel', 'confirm-btn confirm-cancel');
  const okBtn = textEl('button', 'Continue', 'confirm-btn confirm-ok');
  cancelBtn.addEventListener('click', () => overlay.remove());
  okBtn.addEventListener('click', () => { overlay.remove(); onYes(); });
  actions.appendChild(cancelBtn);
  actions.appendChild(okBtn);
  card.appendChild(actions);
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

  // Focus trap
  const focusable = [cancelBtn, okBtn];
  cancelBtn.focus();
  overlay.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { overlay.remove(); return; }
    if (e.key !== 'Tab') return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus(); }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
}

// ---- CONTEXT MENU ----
const _ctxIcons = {
  folder: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4.5V12a1 1 0 001 1h10a1 1 0 001-1V6a1 1 0 00-1-1H8L6.5 3H3a1 1 0 00-1 1v.5z"/></svg>',
  download: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 10.5V13a1 1 0 01-1 1H3a1 1 0 01-1-1v-2.5"/><polyline points="5 7.5 8 10.5 11 7.5"/><line x1="8" y1="10.5" x2="8" y2="2"/></svg>',
  play: '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><polygon points="5 3 12 8 5 13 5 3"/></svg>',
  music: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 12V3l7-1v8"/><circle cx="4" cy="12" r="2"/><circle cx="11" cy="10" r="2"/></svg>',
  trash: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10M6.5 7v4M9.5 7v4M4 4.5l.5 8a1 1 0 001 1h5a1 1 0 001-1l.5-8M6 4.5V3a1 1 0 011-1h2a1 1 0 011 1v1.5"/></svg>',
  disc: '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="1.5"/></svg>',
};

function _createSvgIcon(key) {
  const t = document.createElement('template');
  t.innerHTML = _ctxIcons[key];  // safe: hardcoded SVG literals only
  return t.content.firstChild;
}

function showContextMenu(e, items) {
  const old = document.querySelector('.ctx-menu');
  if (old) old.remove();

  const menu = h('div', { className: 'ctx-menu' });

  items.forEach(item => {
    if (item === 'sep') {
      menu.appendChild(h('div', { className: 'ctx-menu-sep' }));
      return;
    }
    const btn = h('button', { className: 'ctx-menu-item' + (item.className ? ' ' + item.className : '') });
    if (item.icon) btn.appendChild(_createSvgIcon(item.icon));
    btn.appendChild(document.createTextNode(item.label));
    btn.addEventListener('click', () => { menu.remove(); item.action(); });
    menu.appendChild(btn);
  });

  document.body.appendChild(menu);

  const rect = menu.getBoundingClientRect();
  let x = e.clientX, y = e.clientY;
  if (x + rect.width > window.innerWidth) x = window.innerWidth - rect.width - 4;
  if (y + rect.height > window.innerHeight) y = window.innerHeight - rect.height - 4;
  if (x < 0) x = 4;
  if (y < 0) y = 4;
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';

  function dismiss(ev) {
    if (!menu.contains(ev.target)) { menu.remove(); cleanup(); }
  }
  function onKey(ev) {
    if (ev.key === 'Escape') { menu.remove(); cleanup(); }
  }
  function cleanup() {
    document.removeEventListener('mousedown', dismiss, true);
    document.removeEventListener('keydown', onKey, true);
  }
  setTimeout(() => {
    document.addEventListener('mousedown', dismiss, true);
    document.addEventListener('keydown', onKey, true);
  }, 0);
}

// ---- SHORTCUTS HELP OVERLAY ----
function toggleShortcutsHelp() {
  const existing = document.querySelector('.shortcuts-overlay');
  if (existing) { existing.remove(); return; }

  const groups = [
    { label: 'Playback', keys: [
      ['Space / K', 'Play / Pause'],
      ['M', 'Mute / Unmute'],
      ['Shift+N', 'Next track'],
      ['Shift+P', 'Previous track'],
    ]},
    { label: 'Seeking', keys: [
      ['J', 'Back 10s'],
      ['L', 'Forward 10s'],
      ['\u2190', 'Back 10s'],
      ['\u2192', 'Forward 10s'],
      ['0 / Home', 'Restart track'],
      ['End', 'Jump to end'],
      ['1\u20139', 'Jump to 10\u201390%'],
    ]},
    { label: 'Volume', keys: [
      ['\u2191', 'Volume up'],
      ['\u2193', 'Volume down'],
    ]},
    { label: 'Navigation', keys: [
      ['/', 'Focus search'],
      ['Cmd/Ctrl+K', 'Focus search'],
      ['Cmd/Ctrl+L', 'Toggle lyrics'],
      ['Cmd/Ctrl+Shift+Q', 'Toggle queue'],
      ['?', 'This help'],
    ]},
  ];

  const overlay = h('div', { className: 'shortcuts-overlay', role: 'dialog', 'aria-modal': 'true' });
  const card = h('div', { className: 'shortcuts-card' });
  card.appendChild(textEl('h2', 'Keyboard Shortcuts', 'shortcuts-title'));

  for (const group of groups) {
    card.appendChild(textEl('h3', group.label, 'shortcuts-group'));
    const grid = h('div', { className: 'shortcuts-grid' });
    for (const [key, action] of group.keys) {
      grid.appendChild(textEl('span', key, 'shortcut-key'));
      grid.appendChild(textEl('span', action, 'shortcut-action'));
    }
    card.appendChild(grid);
  }

  overlay.appendChild(card);
  document.body.appendChild(overlay);

  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') overlay.remove(); });
  overlay.setAttribute('tabindex', '-1');
  overlay.focus();
}

// ---- ROUTER ----
const viewEl = document.getElementById('view');
const navItems = document.querySelectorAll('.nav-item[data-view]');

let _lastNavHash = '';
const _viewState = {};

function navigate(view) {
  // Dismiss card inspect if open
  if (_inspect.isOpen()) _inspect.dismiss();
  const safeView = normalizeView(view);

  // Save outgoing view state
  if (state.view && viewEl.firstChild) {
    const scrollEl = document.querySelector('.main');
    _viewState[state.view] = {
      scrollY: scrollEl ? scrollEl.scrollTop : 0,
    };
  }

  state.view = safeView;
  _lastNavHash = safeView;
  location.hash = safeView;

  navItems.forEach(n => {
    n.classList.toggle('active', n.dataset.view === safeView);
  });

  // Deep-linked views: highlight parent nav item
  if (!document.querySelector('.nav-item.active')) {
    const parent = safeView.startsWith('artist:') ? 'home'
      : safeView.startsWith('localalbum:') ? 'library'
      : safeView.startsWith('album:') ? 'search'
      : null;
    if (parent) {
      navItems.forEach(n => { if (n.dataset.view === parent) n.classList.add('active'); });
    }
  }

  // Run cleanup hooks (e.g. close EventSource connections) before tearing down DOM
  if (viewEl._viewCleanup) { viewEl._viewCleanup(); viewEl._viewCleanup = null; }
  while (viewEl.firstChild) viewEl.removeChild(viewEl.firstChild);

  const container = h('div', { className: 'view-enter' });

  switch (safeView) {
    case 'home': renderHome(container); break;
    case 'search': renderSearch(container); break;
    case 'library': renderLibrary(container); break;
    case 'recent-added': renderLibrary(container); break;
    case 'recent': renderRecentlyPlayed(container); break;
    case 'playlists': renderPlaylists(container); break;
    case 'favorites': renderFavorites(container); break;
    case 'downloads': renderDownloads(container); break;
    case 'settings': renderSettings(container); break;
    case 'djai': renderDjai(container); break;
    case 'upgrades': renderUpgradeScanner(container); break;
    default:
      if (safeView.startsWith('localalbum:')) {
        const parts = safeView.substring(11).split(':');
        renderLocalAlbumDetail(container, decodeURIComponent(parts[0]), decodeURIComponent(parts.slice(1).join(':')));
      } else if (safeView.startsWith('artist:')) {
        renderArtistGallery(container, decodeURIComponent(safeView.substring(7)));
      } else if (safeView.startsWith('album:')) {
        renderAlbumDetail(container, safeView.split(':')[1]);
      } else {
        renderPlaceholder(container, 'Not Found', 'This view does not exist.');
      }
  }

  viewEl.appendChild(container);

  // Restore saved scroll position or reset to top
  const scrollEl = document.querySelector('.main');
  if (scrollEl) {
    const saved = _viewState[safeView];
    if (saved && saved.scrollY) {
      requestAnimationFrame(() => { scrollEl.scrollTop = saved.scrollY; });
    } else {
      scrollEl.scrollTop = 0;
    }
  }

  // Check for error banners after view renders
  _checkErrorBanners();
}

navItems.forEach(n => {
  n.addEventListener('click', () => navigate(n.dataset.view));
  a11yClick(n);
});

window.addEventListener('hashchange', () => {
  const hash = location.hash.slice(1) || 'home';
  if (hash === _lastNavHash) return; // already handled by navigate()
  navigate(normalizeView(hash));
});

// Sidebar Sync Library button
const navSyncBtn = document.getElementById('nav-sync-library');
if (navSyncBtn) {
  navSyncBtn.addEventListener('click', async () => {
    navigate('library');
    const resultsArea = document.querySelector('.results');
    if (!resultsArea) return;

    // Incremental sync by default — only picks up new files
    triggerScan(navSyncBtn, resultsArea, false);
  });
}

// ---- HOME VIEW ----
async function renderHome(container) {
  const wrap = h('div', { className: 'home-wrap home-loading' });

  // Paint the header + a loading hint synchronously so the view is never
  // blank while /home is in flight. On a cold sidecar (Tauri first launch,
  // NAS volume probe) /home can take several seconds; without this
  // skeleton the user sees a blank view and a second navigate() can
  // orphan the in-progress render.
  const header = h('div', { className: 'home-header' });
  const title = h('h1', { className: 'home-title' });
  title.appendChild(document.createTextNode(_greeting() + ' welcome to '));
  title.appendChild(h('em', { className: 'home-your' }, 'your'));
  title.appendChild(document.createTextNode(' library'));
  header.appendChild(title);
  wrap.appendChild(header);
  const loadingHint = textEl('p', 'Loading your library…', 'home-loading-hint');
  wrap.appendChild(loadingHint);
  container.appendChild(wrap);

  let data;
  try {
    data = await api('/home');
  } catch (_) {
    data = { total_plays: 0, weekly_activity: [0,0,0,0,0,0,0] };
  }

  // If the user navigated away (and maybe back) while we were awaiting,
  // this wrap was torn out of the DOM by navigate()'s cleanup. Bail out
  // silently so the newer render owns the view.
  if (!wrap.isConnected) return;

  wrap.classList.remove('home-loading');
  loadingHint.remove();

  const totalPlays = data.total_plays || 0;

  // Count how many tiles will render to determine density
  let tileCount = 0;
  if (data.top_artist && data.top_artist.play_count >= 5) tileCount++;
  if (data.most_replayed && data.most_replayed.play_count >= 10) tileCount++;
  if (data.genre_breakdown && data.genre_breakdown.length > 0) tileCount++;
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) tileCount++;
  const extraArtistCount = (data.top_artists || []).slice(1, 3).filter(a => a.play_count >= 3).length;
  tileCount += extraArtistCount;
  if (totalPlays >= 100 || data.track_count > 0) tileCount++;
  if (totalPlays >= 100 || data.album_count > 0) tileCount++;

  // Density class: sparse (≤4), moderate (5-6), dense (7+)
  const density = tileCount <= 4 ? 'sparse' : tileCount <= 6 ? 'moderate' : 'dense';
  wrap.classList.add('home-' + density);

  if (data.volume_available === false) {
    const banner = h('div', { className: 'volume-offline-banner' });
    banner.textContent = 'Your music drive is offline — showing what we remember';
    wrap.appendChild(banner);
  }

  _renderContinueListening(wrap);

  if (totalPlays === 0) {
    _renderHomeCold(wrap);
  } else {
    _renderHomeGrid(wrap, data, totalPlays);
  }

  if (recentlyPlayed.length > 0) {
    _renderRecentStrip(wrap);
  }
}

function _getContinueListeningState() {
  try {
    const current = state.queue[state.queueIndex];
    if (!current) return null;
    const raw = localStorage.getItem('playerPosition');
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (!saved || saved.key !== _trackKey(current) || !(saved.time > 0)) return null;
    return { track: current, time: saved.time };
  } catch (_) {
    return null;
  }
}

function _continueListeningLabel(track, time) {
  const duration = Number(track.duration || 0);
  if (duration > time + 5) return formatTime(duration - time) + ' left';
  return 'Resume at ' + formatTime(time);
}

function _resumeContinueListening(track, time) {
  if (!track) return;
  const index = _findTrackIndex(state.queue, track);
  if (index >= 0) state.queueIndex = index;
  audio.addEventListener('loadedmetadata', function _seekResume() {
    audio.currentTime = Math.min(time, audio.duration || time);
  }, { once: true });
  playTrack(state.queue[state.queueIndex] || track);
}

function _renderContinueListening(container) {
  const resume = _getContinueListeningState();
  if (!resume) return;
  const track = resume.track;
  const card = h('div', { className: 'continue-card', role: 'button', tabIndex: '0' });
  const art = h('div', { className: 'continue-art' });
  if (track.cover_url) {
    const img = h('img', { src: track.cover_url, alt: '', loading: 'lazy' });
    img.onerror = function() { this.replaceWith(h('div', { className: 'art-gradient', style: { background: artGradient(track.id || track.name) } })); };
    art.appendChild(img);
  } else {
    art.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(track.id || track.name) } }));
  }
  const meta = h('div', { className: 'continue-meta' },
    textEl('div', 'Continue Listening', 'continue-eyebrow'),
    textEl('div', track.name || 'Unknown', 'continue-title'),
    textEl('div', track.artist || '', 'continue-artist'),
    textEl('div', _continueListeningLabel(track, resume.time), 'continue-time')
  );
  card.appendChild(art);
  card.appendChild(meta);
  card.addEventListener('click', () => _resumeContinueListening(track, resume.time));
  a11yClick(card);
  container.appendChild(card);
}

function _renderHomeCold(container) {
  const grid = h('div', { className: 'home-grid home-cold' });
  const card = h('div', { className: 'bento-tile bento-lucky', onClick: feelingLucky });
  card.appendChild(textEl('div', '\u266B', 'bento-lucky-note'));
  card.appendChild(textEl('div', "I'm feeling lucky", 'bento-lucky-label'));
  card.appendChild(textEl('div', 'plays a random track from your library', 'bento-lucky-sub'));
  grid.appendChild(card);
  container.appendChild(grid);
  container.appendChild(textEl('p', 'This space is yours. Play some music and watch it come alive.', 'home-invite'));
}

function _renderHomeGrid(container, data, totalPlays) {
  const established = totalPlays >= 100;
  const tw = data.this_week || {};
  const hasRecent = (tw.total_plays || 0) > 0;
  const grid = h('div', { className: 'home-grid' });

  // Adaptive column count + density classes via ResizeObserver
  new ResizeObserver(entries => {
    for (const e of entries) {
      const w = e.contentRect.width;
      const cols = Math.max(2, Math.min(6, Math.floor(w / 280)));
      e.target.style.setProperty('--cols', cols);
      e.target.classList.toggle('density-compact', cols <= 2);
      // Balance last row: stretch last tile to fill any gap
      const prev = e.target.querySelector('.bento-row-fill');
      if (prev) { prev.classList.remove('bento-row-fill'); prev.style.removeProperty('grid-column'); }
      const compact = cols <= 2;
      const vis = Array.from(e.target.children).filter(t => !(compact && t.dataset.tier));
      let slots = 0;
      for (const t of vis) slots += t.classList.contains('bento-hero') ? 2 : 1;
      const gap = slots % cols;
      if (gap && vis.length) {
        vis[vis.length - 1].classList.add('bento-row-fill');
        vis[vis.length - 1].style.gridColumn = 'span ' + (1 + cols - gap);
      }
    }
  }).observe(grid);

  // Helper: tag a tile with a priority tier for adaptive hiding
  function _t(tile, tier) { tile.dataset.tier = tier; return tile; }

  // === Core tiles (always visible) ===
  // Prefer this_week artist data when available
  const heroArtist = hasRecent && tw.top_artist ? tw.top_artist : data.top_artist;
  if (heroArtist && heroArtist.play_count >= 5) {
    grid.appendChild(_artistTile(heroArtist, true));
  }
  // Genre tile: prefer this_week genre data, split if on-repeat qualifies
  const recentGenres = hasRecent && tw.genre_breakdown && tw.genre_breakdown.length > 0;
  const hasPlayGenres = recentGenres || (data.genre_breakdown && data.genre_breakdown.length > 0);
  const genreSource = recentGenres ? tw.genre_breakdown
    : (data.genre_breakdown && data.genre_breakdown.length > 0) ? data.genre_breakdown
    : (data.track_genres || []);
  const genreLabel = genreSource.length > 0 ? genreSource[0].genre : null;
  const fromLibrary = !recentGenres && !(data.genre_breakdown && data.genre_breakdown.length > 0);
  const onRepeatTrack = hasRecent && tw.most_replayed && tw.most_replayed.play_count >= 3
    ? tw.most_replayed : null;
  if (genreSource.length > 0) {
    const genreTile = _genreTile(genreLabel, genreSource, fromLibrary, onRepeatTrack);
    genreTile._homeData = data;
    // For split tiles, also set on the genre half
    if (onRepeatTrack) {
      const genreHalf = genreTile.querySelector('.bento-half:not(.bento-on-repeat)');
      if (genreHalf) genreHalf._homeData = data;
    }
    grid.appendChild(genreTile);
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    const ltTile = _listeningTimeTile(data.listening_time_hours, data.weekly_activity, data);
    ltTile._homeData = data;
    grid.appendChild(ltTile);
  }

  // === Secondary tiles (tier 1 — hidden on compact) ===
  const allTimeExtra = (data.top_artists || []).slice(1, 3);
  const recentExtra = hasRecent ? (tw.top_artists || []).slice(1, 3) : [];
  const extraArtists = recentExtra.length > 0 ? recentExtra : allTimeExtra;
  for (const a of extraArtists) {
    if (a.play_count >= 3) {
      grid.appendChild(_t(_artistTile(a, false), 1));
    }
  }

  // === Library tiles (tier 2 — hidden on compact) ===
  if (established || data.track_count > 0) {
    const tTile = _tracksTile(data.track_count, data.track_genres || [], data);
    tTile._homeData = data;
    grid.appendChild(_t(tTile, 2));
  }
  if (established || data.album_count > 0) {
    const aTile = _albumsTile(data.album_count, data.album_artists, data);
    aTile._homeData = data;
    grid.appendChild(_t(aTile, 2));
  }

  container.appendChild(grid);
}


function _artistTile(artist, hero) {
  const tile = h('div', { className: 'bento-tile bento-artist' + (hero ? ' bento-hero' : '') });
  // Artist photo only — no album cover fallback (prevents flash of album art)
  const img = h('img', { className: 'bento-bg-art', alt: '', style: 'opacity:0;transition:opacity 0.3s ease;' });
  tile.appendChild(img);
  tile.appendChild(h('div', { className: 'bento-overlay' }));
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', artist.name, 'bento-label'));
  body.appendChild(textEl('div', artist.play_count + ' plays', 'bento-sub'));
  const stats = [];
  if (artist.track_count) stats.push(artist.track_count + ' tracks');
  if (artist.album_count) stats.push(artist.album_count + ' albums');
  if (artist.genre) stats.push(artist.genre);
  if (stats.length) {
    body.appendChild(textEl('div', stats.join(' · '), 'bento-artist-stats'));
  }
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View albums', 'bento-hint'));
  tile.addEventListener('click', () => navigate('artist:' + encodeURIComponent(artist.name)));
  a11yClick(tile);
  // Show cached artist image immediately if available in home_stats payload
  if (artist.artist_image_url) {
    img.src = artist.artist_image_url;
    img.onload = () => { img.style.opacity = '1'; };
  } else {
    // Fetch artist photo (no album art fallback — tile stays clean until real photo arrives)
    fetch('/api/home/artist-image?name=' + encodeURIComponent(artist.name))
      .then(r => r.json())
      .then(data => {
        if (data.image_url) { img.src = data.image_url; img.onload = () => { img.style.opacity = '1'; }; }
      })
      .catch(() => {});
  }
  return tile;
}


// Build an insight line: text with one gold keyword
function _insight(before, keyword, after) {
  const el = h('div', { className: 'bento-insight-line' });
  if (before) el.appendChild(document.createTextNode(before));
  el.appendChild(h('span', { className: 'insight-gold' }, keyword));
  if (after) el.appendChild(document.createTextNode(after));
  return el;
}

// Build a multi-line insight block
function _insightBlock(lines) {
  const block = h('div', { className: 'bento-insight' });
  for (const line of lines) {
    if (line) block.appendChild(line);
  }
  return block;
}

function _genreInsight(topGenre, breakdown, fromLibrary) {
  const lines = [];
  if (fromLibrary && breakdown.length >= 2) {
    const total = breakdown.reduce((s, g) => s + g.count, 0);
    const pct = Math.round((breakdown[0].count / total) * 100);
    lines.push(_insight(pct + '% of your library is ', topGenre, ''));
    if (breakdown[1]) lines.push(_insight('', breakdown[1].genre, ' takes second at ' + Math.round((breakdown[1].count / total) * 100) + '%'));
  } else if (breakdown.length >= 2) {
    lines.push(_insight('You\'ve been vibing with ', topGenre, ' lately'));
    lines.push(_insight('', breakdown[1].genre, ' is not far behind'));
  } else {
    lines.push(_insight('Your world revolves around ', topGenre, ''));
  }
  return _insightBlock(lines);
}

function _listeningInsight(hours, weekly) {
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const max = Math.max(...weekly);
  if (max === 0) return null;
  const maxIdx = weekly.indexOf(max);
  const total = weekly.reduce((a, b) => a + b, 0);
  const lines = [];
  lines.push(_insight('You listen most on ', days[maxIdx], 's'));
  if (total > 0) {
    const avg = (total / 7).toFixed(1);
    lines.push(_insight('That\'s about ', avg + 'h', ' per day on average'));
  }
  return _insightBlock(lines);
}

function _tracksInsight(count, genres) {
  const lines = [];
  if (genres && genres.length >= 2) {
    lines.push(_insight('Mostly ', genres[0].genre, ' · ' + genres[0].count.toLocaleString() + ' tracks'));
    lines.push(_insight('', genres[1].genre, ' follows with ' + genres[1].count.toLocaleString()));
    if (genres[2]) lines.push(_insight('Then ', genres[2].genre, ' at ' + genres[2].count.toLocaleString()));
  } else if (genres && genres.length === 1) {
    lines.push(_insight('', genres[0].genre, ' is all we\'ve seen so far'));
    lines.push(_insight('Sync your library to uncover ', 'all genres', ''));
  } else if (count >= 10000) {
    lines.push(_insight('', count.toLocaleString(), ' tracks across your collection'));
    lines.push(_insight('Sync your library to see the ', 'genre breakdown', ''));
  } else if (count >= 1000) {
    lines.push(_insight('', count.toLocaleString(), ' tracks and counting'));
    lines.push(_insight('Sync to discover your ', 'genre mix', ''));
  } else {
    lines.push(_insight('Your library has ', count.toLocaleString(), ' tracks so far'));
  }
  return _insightBlock(lines);
}

function _albumsInsight(count, artists) {
  const lines = [];
  if (artists && artists.length >= 1) {
    lines.push(_insight('', artists[0].artist, ' leads with ' + artists[0].count + ' albums'));
  }
  if (artists && artists.length >= 2) {
    const a = artists[1];
    if (a.count === artists[0].count) {
      lines.push(_insight('', a.artist, ' ties at ' + a.count + ' — neck and neck'));
    } else {
      lines.push(_insight('', a.artist, ' follows with ' + a.count));
    }
  }
  if (artists && artists.length >= 3) {
    const a = artists[2];
    if (artists.length >= 2 && a.count === artists[1].count) {
      lines.push(_insight('', a.artist, ' tied for second with ' + a.count));
    } else {
      lines.push(_insight('', a.artist, ' rounds it out with ' + a.count));
    }
  }
  if (lines.length === 0) {
    lines.push(_insight('', count.toLocaleString(), ' albums in your collection'));
  }
  return _insightBlock(lines);
}

function _genreTile(topGenre, breakdown, fromLibrary, onRepeatTrack) {
  if (onRepeatTrack) {
    // Split tile: condensed genre on top, on-repeat on bottom
    const tile = h('div', { className: 'bento-tile bento-stat-tile bento-split' });
    const genreHalf = h('div', { className: 'bento-half' });
    const body = h('div', { className: 'bento-body' });
    body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
    body.appendChild(textEl('div', fromLibrary ? 'Top genre' : 'Recent genre', 'bento-stat-label'));
    body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
    genreHalf.appendChild(body);
    genreHalf.addEventListener('click', (e) => {
      e.stopPropagation();
      const deck = _genreDeck(topGenre, breakdown, fromLibrary, genreHalf._homeData || {});
      if (deck.length > 1) _inspect.open(genreHalf, deck);
    });
    a11yClick(genreHalf);
    tile.appendChild(genreHalf);
    tile.appendChild(_onRepeatHalf(onRepeatTrack));
    return tile;
  }
  // Full-size genre tile — unchanged
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
  body.appendChild(textEl('div', fromLibrary ? 'Top genre' : 'Recent genre', 'bento-stat-label'));
  body.appendChild(_genreInsight(topGenre, breakdown, fromLibrary));
  body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  tile.appendChild(body);
  tile._inspectDeck = null; // lazy — built on click
  tile._inspectDeckArgs = { topGenre, breakdown, fromLibrary };
  tile.addEventListener('click', () => {
    if (!tile._inspectDeck) tile._inspectDeck = _genreDeck(tile._inspectDeckArgs.topGenre, tile._inspectDeckArgs.breakdown, tile._inspectDeckArgs.fromLibrary, tile._homeData || {});
    if (tile._inspectDeck.length > 1) _inspect.open(tile, tile._inspectDeck);
  });
  a11yClick(tile);
  return tile;
}

function _onRepeatHalf(track) {
  const half = h('div', { className: 'bento-half bento-on-repeat' });
  if (track.cover_url) {
    half.appendChild(h('img', { className: 'bento-bg-art', src: track.cover_url, alt: '' }));
  }
  half.appendChild(h('div', { className: 'bento-overlay' }));
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', track.name || 'Unknown', 'bento-label'));
  body.appendChild(textEl('div', track.play_count + ' plays this week', 'bento-sub'));
  body.appendChild(textEl('div', track.artist + ' \u2014 On repeat', 'bento-stat'));
  half.appendChild(body);
  half.addEventListener('click', (e) => {
    e.stopPropagation();
    const t = { ...track, local_path: track.path, is_local: true };
    playTrack(t);
  });
  a11yClick(half);
  return half;
}

// ---- CARD INSPECT OVERLAY ----
// TCG-inspired stat card inspect: click tile → fan deck → keyboard browse → dismiss

const _inspect = (() => {
  let _state = null; // { scrim, cards, activeIndex, originalTile, originalRect, cleanup }
  const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DUR = REDUCED_MOTION ? 0 : 300;
  const DUR_FAST = REDUCED_MOTION ? 0 : 200;
  const EASE_PRIMARY = 'cubic-bezier(0.22, 0.61, 0.36, 1)';
  const EASE_BOUNCE = 'cubic-bezier(0.175, 0.885, 0.32, 1.275)';
  const FAN_ANGLE = 6; // degrees between cards
  const FAN_LIFT = -12; // px vertical lift per offset
  const CARD_W = Math.min(340, window.innerWidth * 0.85);
  const CARD_H = Math.min(CARD_W * 1.5, window.innerHeight * 0.6);

  function _noteIcon() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '12');
    svg.setAttribute('height', '12');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z');
    svg.appendChild(path);
    return svg;
  }

  function _makeCard(data, index) {
    const card = h('div', { className: 'inspect-card' });
    card.style.width = CARD_W + 'px';
    card.style.height = CARD_H + 'px';
    card.dataset.index = index;
    card.dataset.rarity = data.rarity || 'common';

    // TCG corner marks
    const tl = h('div', { className: 'card-corner top-left' });
    tl.appendChild(_noteIcon());
    card.appendChild(tl);
    const br = h('div', { className: 'card-corner bottom-right' });
    br.appendChild(_noteIcon());
    card.appendChild(br);

    // Rarity label
    if (data.rarity && data.rarity !== 'common') {
      card.appendChild(textEl('span', data.rarity.toUpperCase(), 'card-rarity'));
    }

    // Body — Format B layout
    const body = h('div', { className: 'bento-body' });
    body.style.padding = '0';
    body.style.flex = '1';
    body.style.display = 'flex';
    body.style.flexDirection = 'column';

    body.appendChild(textEl('div', data.title, 'bento-label'));
    body.appendChild(textEl('div', data.statLabel, 'bento-stat-label'));

    // Content area — render function provided by the deck builder
    // Wrapped in a flex container that fills the middle space and centers content
    if (data.renderContent) {
      const content = data.renderContent();
      if (content) {
        const contentWrap = h('div', { className: 'card-content-area' });
        contentWrap.appendChild(content);
        body.appendChild(contentWrap);
      }
    }

    // Stats key-value pairs
    if (data.stats && data.stats.length > 0) {
      const statsEl = h('div', { className: 'card-stats' });
      for (const s of data.stats) {
        const row = h('div', { className: 'card-stats-row' });
        row.appendChild(textEl('span', s.key, 'card-stats-key'));
        const val = textEl('span', s.value, 'card-stats-val');
        if (s.color) val.style.color = s.color;
        row.appendChild(val);
        statsEl.appendChild(row);
      }
      body.appendChild(statsEl);
    }

    // Flavor text
    if (data.flavor) {
      body.appendChild(textEl('div', data.flavor, 'card-flavor'));
    }

    card.appendChild(body);
    return card;
  }

  function _fanPosition(index, activeIndex, total) {
    if (index === activeIndex) return { angle: 0, lift: 0, z: total + 1, opacity: 1 };
    const offset = index - activeIndex;
    return {
      angle: offset * FAN_ANGLE,
      lift: Math.abs(offset) * FAN_LIFT,
      z: total - Math.abs(offset),
      opacity: 0.4,
    };
  }

  function _setFan(cards, activeIndex) {
    cards.forEach((card, i) => {
      const pos = _fanPosition(i, activeIndex, cards.length);
      const isFront = i === activeIndex;
      card.className = 'inspect-card ' + (isFront ? 'inspect-front' : 'inspect-back');
      card.dataset.rarity = card._data.rarity || 'common';
      card.style.zIndex = pos.z;
      card.style.transform = `translate(${_state.centerX}px, ${_state.centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`;
      card.style.opacity = pos.opacity;
    });
  }

  function _animateSwap(fromIndex, toIndex) {
    if (!_state) return;
    const cards = _state.cards;
    _state.activeIndex = toIndex;

    cards.forEach((card, i) => {
      const pos = _fanPosition(i, toIndex, cards.length);
      const isFront = i === toIndex;
      card.className = 'inspect-card ' + (isFront ? 'inspect-front' : 'inspect-back');
      card.dataset.rarity = card._data.rarity || 'common';
      const anim = card.animate([
        { transform: card.style.transform, opacity: parseFloat(card.style.opacity) },
        { transform: `translate(${_state.centerX}px, ${_state.centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`, opacity: pos.opacity }
      ], { duration: DUR, easing: EASE_PRIMARY, fill: 'forwards' });
      anim.finished.then(() => { anim.commitStyles(); anim.cancel(); });
      card.style.zIndex = pos.z;
    });

    _updateDots(toIndex);
  }

  function _createDots(count, container) {
    const dots = h('div', { className: 'pip-dots' });
    for (let i = 0; i < count; i++) {
      dots.appendChild(h('div', { className: 'pip-dot' + (i === 0 ? ' active' : '') }));
    }
    container.appendChild(dots);
    return dots;
  }

  function _updateDots(activeIndex) {
    if (!_state) return;
    const dots = _state.scrim.querySelectorAll('.pip-dot');
    dots.forEach((d, i) => d.classList.toggle('active', i === activeIndex));
  }

  function open(tileEl, deckData) {
    if (_state) return; // already open

    const rect = tileEl.getBoundingClientRect();
    // Use visibility:hidden for half-tiles (preserves space, doesn't affect siblings)
    // Use opacity:0 for standalone tiles
    const isHalf = tileEl.classList.contains('bento-half');
    if (isHalf) {
      tileEl.style.visibility = 'hidden';
    } else {
      tileEl.style.opacity = '0';
    }

    // Create scrim
    const scrim = h('div', { className: 'inspect-scrim' });
    scrim.style.opacity = '0';
    document.body.appendChild(scrim);

    // Animate scrim in
    const scrimAnim = scrim.animate(
      [{ opacity: 0 }, { opacity: 1 }],
      { duration: DUR_FAST, fill: 'forwards' }
    );
    scrimAnim.finished.then(() => { scrimAnim.commitStyles(); scrimAnim.cancel(); });

    // Calculate center position
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const centerX = (vw - CARD_W) / 2;
    const centerY = (vh - CARD_H) / 2 - 20; // slight upward offset for pip dots

    // Build cards
    const cards = deckData.map((data, i) => {
      const card = _makeCard(data, i);
      card._data = data;
      card.style.position = 'fixed';
      card.style.top = '0';
      card.style.left = '0';
      // Start all cards at the tile's position
      card.style.transform = `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`;
      card.style.opacity = '0';
      scrim.appendChild(card);
      return card;
    });

    _state = {
      scrim, cards, activeIndex: 0,
      originalTile: tileEl, originalRect: rect,
      centerX, centerY,
    };

    // Animate main card (index 0) from tile position to center
    const mainCard = cards[0];
    mainCard.style.opacity = '1';
    const mainAnim = mainCard.animate([
      { transform: `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`, opacity: 1 },
      { transform: `translate(${centerX}px, ${centerY}px) scale(1)`, opacity: 1 }
    ], { duration: DUR, easing: EASE_PRIMARY, fill: 'forwards' });
    mainAnim.finished.then(() => {
      mainAnim.commitStyles(); mainAnim.cancel();
      // Fan out remaining cards with stagger
      cards.forEach((card, i) => {
        if (i === 0) { card.className = 'inspect-card inspect-front'; card.dataset.rarity = card._data.rarity || 'common'; return; }
        const pos = _fanPosition(i, 0, cards.length);
        const delay = Math.abs(i) * 50;
        card.style.opacity = '0';
        const fanAnim = card.animate([
          { transform: `translate(${centerX}px, ${centerY}px) rotate(0deg)`, opacity: 0 },
          { transform: `translate(${centerX}px, ${centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`, opacity: pos.opacity }
        ], { duration: 250, delay, easing: EASE_BOUNCE, fill: 'forwards' });
        fanAnim.finished.then(() => { fanAnim.commitStyles(); fanAnim.cancel(); });
        card.className = 'inspect-card inspect-back';
        card.dataset.rarity = card._data.rarity || 'common';
        card.style.zIndex = pos.z;

        // Click background card to swap
        card.addEventListener('click', (e) => {
          e.stopPropagation();
          if (_state && _state.activeIndex !== i) _animateSwap(_state.activeIndex, i);
        });
      });
    });

    // Pip dots
    if (cards.length > 1) {
      setTimeout(() => { if (_state) _createDots(cards.length, scrim); }, DUR + 50);
    }

    // Controls hint — show after 3s of no interaction
    let _hintTimer = setTimeout(() => {
      if (!_state || cards.length <= 1) return;
      const hint = h('div', { className: 'inspect-hint' });
      hint.appendChild(textEl('span', '\u2190 \u2192  browse', ''));
      hint.appendChild(textEl('span', ' \u00b7 ', ''));
      hint.appendChild(textEl('span', 'esc  close', ''));
      hint.style.opacity = '0';
      scrim.appendChild(hint);
      const hintAnim = hint.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 400, fill: 'forwards' });
      hintAnim.finished.then(() => { hintAnim.commitStyles(); hintAnim.cancel(); });
    }, 3000);
    const _clearHintOnInteract = () => { clearTimeout(_hintTimer); const existing = scrim.querySelector('.inspect-hint'); if (existing) existing.remove(); };
    scrim.addEventListener('click', _clearHintOnInteract, { once: true });
    document.addEventListener('keydown', _clearHintOnInteract, { once: true });

    // Scrim click to dismiss
    scrim.addEventListener('click', (e) => {
      if (e.target === scrim) dismiss();
    });

    // Keyboard handler
    function onKey(e) {
      if (!_state) return;
      const key = e.key;
      if (key === 'ArrowRight' || key === 'd' || key === 'D') {
        e.preventDefault(); e.stopPropagation();
        const next = _state.activeIndex + 1;
        if (next < _state.cards.length) _animateSwap(_state.activeIndex, next);
      } else if (key === 'ArrowLeft' || key === 'a' || key === 'A') {
        e.preventDefault(); e.stopPropagation();
        const prev = _state.activeIndex - 1;
        if (prev >= 0) _animateSwap(_state.activeIndex, prev);
      } else if (key === 'Escape') {
        e.preventDefault(); e.stopPropagation();
        dismiss();
      }
    }
    // Capture phase so we get it before the global handler
    document.addEventListener('keydown', onKey, true);
    _state.cleanup = () => document.removeEventListener('keydown', onKey, true);
  }

  function dismiss() {
    if (!_state) return;
    const { scrim, cards, originalTile, cleanup } = _state;
    // Re-measure original tile position (may have scrolled)
    const rect = originalTile.getBoundingClientRect();

    // Fade out non-active cards
    cards.forEach((card, i) => {
      if (i === _state.activeIndex) return;
      const fadeOut = card.animate([{ opacity: parseFloat(card.style.opacity) }, { opacity: 0 }], { duration: DUR_FAST, fill: 'forwards' });
      fadeOut.finished.then(() => { fadeOut.commitStyles(); fadeOut.cancel(); });
    });

    // Animate active card back to original position
    const active = cards[_state.activeIndex];
    const returnAnim = active.animate([
      { transform: active.style.transform, opacity: 1 },
      { transform: `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`, opacity: 0.5 }
    ], { duration: DUR, easing: 'ease-in', fill: 'forwards' });

    // Fade scrim
    const scrimFade = scrim.animate([{ opacity: 1 }, { opacity: 0 }], { duration: DUR_FAST, delay: 100, fill: 'forwards' });

    returnAnim.finished.then(() => {
      returnAnim.commitStyles(); returnAnim.cancel();
      originalTile.style.opacity = '';
      originalTile.style.visibility = '';
      scrim.remove();
    });
    scrimFade.finished.then(() => { scrimFade.commitStyles(); scrimFade.cancel(); });

    if (cleanup) cleanup();
    _state = null;
  }

  function isOpen() { return _state !== null; }

  return { open, dismiss, isOpen };
})();

// ---- DECK BUILDERS (card content per tile type) ----

// SVG ring chart — renders a donut arc with percentage label
function _ringChart(pct, label, opts) {
  const size = (opts && opts.size) || 150;
  const stroke = (opts && opts.stroke) || 10;
  const color = (opts && opts.color) || 'var(--accent)';
  const trackColor = (opts && opts.trackColor) || 'rgba(212,160,83,0.12)';
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(Math.max(pct, 0), 100) / 100) * circ;

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
  svg.style.display = 'block';
  svg.style.margin = '0 auto';

  // Track
  const track = document.createElementNS(ns, 'circle');
  track.setAttribute('cx', size / 2);
  track.setAttribute('cy', size / 2);
  track.setAttribute('r', r);
  track.setAttribute('fill', 'none');
  track.setAttribute('stroke', trackColor);
  track.setAttribute('stroke-width', stroke);
  svg.appendChild(track);

  // Arc
  const arc = document.createElementNS(ns, 'circle');
  arc.setAttribute('cx', size / 2);
  arc.setAttribute('cy', size / 2);
  arc.setAttribute('r', r);
  arc.setAttribute('fill', 'none');
  arc.setAttribute('stroke', color);
  arc.setAttribute('stroke-width', stroke);
  arc.setAttribute('stroke-linecap', 'round');
  arc.setAttribute('stroke-dasharray', circ);
  arc.setAttribute('stroke-dashoffset', offset);
  arc.setAttribute('transform', 'rotate(-90 ' + size / 2 + ' ' + size / 2 + ')');
  svg.appendChild(arc);

  // Center label
  if (label) {
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('x', size / 2);
    text.setAttribute('y', size / 2);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'central');
    text.setAttribute('fill', color);
    text.setAttribute('font-family', 'var(--mono)');
    text.setAttribute('font-size', size < 100 ? '12' : '16');
    text.textContent = label;
    svg.appendChild(text);
  }
  return svg;
}

// Horizontal comparison bars (this vs that)
function _comparisonBars(items) {
  const max = Math.max(...items.map(i => i.value), 1);
  const wrap = h('div', { style: 'display:flex;flex-direction:column;gap:14px;width:100%;' });
  for (const item of items) {
    const row = h('div', { style: 'display:flex;flex-direction:column;gap:3px;' });
    const labelRow = h('div', { style: 'display:flex;justify-content:space-between;font-size:12px;' });
    const lbl = h('span', { style: 'color:var(--text-muted);' });
    lbl.textContent = item.label;
    const val = h('span', { style: 'color:' + (item.color || 'var(--text-secondary)') + ';font-family:var(--mono);' });
    val.textContent = item.display || String(item.value);
    labelRow.appendChild(lbl);
    labelRow.appendChild(val);
    row.appendChild(labelRow);
    const barBg = h('div', { style: 'height:8px;border-radius:4px;background:rgba(212,160,83,0.1);overflow:hidden;' });
    const fill = h('div', { style: 'height:100%;border-radius:4px;background:' + (item.color || 'var(--accent)') + ';width:' + Math.round((item.value / max) * 100) + '%;transition:width 0.3s ease;' });
    barBg.appendChild(fill);
    row.appendChild(barBg);
    wrap.appendChild(row);
  }
  return wrap;
}

// Album art thumbnail grid
function _albumArtGrid(albums) {
  const grid = h('div', { style: 'display:grid;grid-template-columns:repeat(3,1fr);gap:6px;border-radius:8px;overflow:hidden;max-width:280px;margin:0 auto;' });
  const shown = albums.slice(0, 3);
  for (const a of shown) {
    if (a.cover_url) {
      const img = h('img', { src: a.cover_url, alt: a.album || '', style: 'width:100%;aspect-ratio:1;object-fit:cover;display:block;' });
      img.loading = 'lazy';
      grid.appendChild(img);
    } else {
      const placeholder = h('div', { style: 'width:100%;aspect-ratio:1;background:rgba(212,160,83,0.08);' });
      grid.appendChild(placeholder);
    }
  }
  return grid;
}

function _listeningTimeDeck(data) {
  const deck = [];
  const hrs = data.listening_time_hours || 0;
  const days = Math.round(hrs / 24 * 10) / 10;
  const avgPerDay = data.weekly_activity ? Math.round(data.weekly_activity.reduce((a, b) => a + b, 0) / 7 * 10) / 10 : 0;
  const totalPlays = data.total_plays || 0;
  const avgTrackLen = totalPlays > 0 ? Math.round((hrs * 60) / totalPlays * 10) / 10 : 0;
  // Card 0: Main
  deck.push({
    title: Math.round(hrs) + 'h',
    statLabel: 'Listening time',
    rarity: 'common',
    renderContent: () => {
      const wrap = h('div');
      const ins = _listeningInsight(hrs, data.weekly_activity);
      if (ins) wrap.appendChild(ins);
      wrap.appendChild(_weeklyChart(data.weekly_activity));
      return wrap;
    },
    stats: [
      { key: 'Total time', value: Math.round(hrs) + ' hours (' + days + ' days)' },
      { key: 'Lifetime plays', value: totalPlays.toLocaleString() },
      { key: 'Avg per day', value: avgPerDay + 'h' },
      { key: 'Avg track length', value: avgTrackLen + ' min' },
    ],
    flavor: hrs >= 1000 ? 'You have listened for over a thousand hours. Respect.' : null,
  });
  // Card 1: Peak Hour
  if (data.peak_hour !== undefined && data.peak_hours) {
    const h12 = data.peak_hour % 12 || 12;
    const ampm = data.peak_hour < 12 ? 'am' : 'pm';
    const totalHourPlays = data.peak_hours.reduce((a, b) => a + b, 0);
    const peakPct = totalHourPlays > 0 ? Math.round((data.peak_hours[data.peak_hour] / totalHourPlays) * 100) : 0;
    const morningPlays = data.peak_hours.slice(6, 12).reduce((a, b) => a + b, 0);
    const afternoonPlays = data.peak_hours.slice(12, 18).reduce((a, b) => a + b, 0);
    const eveningPlays = data.peak_hours.slice(18, 24).reduce((a, b) => a + b, 0);
    const nightPlays = data.peak_hours.slice(0, 6).reduce((a, b) => a + b, 0);
    const periods = [
      { name: 'Night owl', val: nightPlays }, { name: 'Morning', val: morningPlays },
      { name: 'Afternoon', val: afternoonPlays }, { name: 'Evening', val: eveningPlays },
    ].sort((a, b) => b.val - a.val);
    deck.push({
      title: h12 + ampm,
      statLabel: 'Peak hour',
      rarity: data.peak_hour >= 22 || data.peak_hour <= 4 ? 'uncommon' : 'common',
      renderContent: () => {
        const chart = h('div', { style: 'display:flex;align-items:flex-end;gap:2px;height:80px;width:100%;' });
        const max = Math.max(...data.peak_hours, 1);
        for (let i = 0; i < 24; i++) {
          const pct = (data.peak_hours[i] / max) * 100;
          chart.appendChild(h('div', {
            style: `flex:1;background:${i === data.peak_hour ? 'var(--accent)' : 'rgba(212,160,83,0.15)'};height:${Math.max(2, pct)}%;border-radius:1px;`
          }));
        }
        return chart;
      },
      stats: [
        { key: 'Peak hour', value: h12 + ':00' + ampm + ' (' + peakPct + '% of plays)' },
        { key: 'You\'re a', value: periods[0].name + ' listener' },
        { key: 'Morning (6am-12)', value: morningPlays.toLocaleString() + ' plays' },
        { key: 'Afternoon (12-6pm)', value: afternoonPlays.toLocaleString() + ' plays' },
        { key: 'Evening (6pm-12)', value: eveningPlays.toLocaleString() + ' plays' },
        { key: 'Late night (12-6am)', value: nightPlays.toLocaleString() + ' plays' },
      ],
      flavor: data.peak_hour >= 0 && data.peak_hour <= 4 ? 'Nothing good happens after midnight. Except music.' : (data.peak_hour >= 6 && data.peak_hour <= 9 ? 'Early bird gets the best playlists.' : null),
    });
  }
  // Card 2: Streak
  if (data.streak !== undefined) {
    const streakRarity = data.streak >= 30 ? 'legendary' : data.streak >= 14 ? 'epic' : data.streak >= 7 ? 'rare' : data.streak >= 3 ? 'uncommon' : 'common';
    const bestStreak = data.best_streak || data.streak;
    const streakPct = bestStreak > 0 ? Math.round((data.streak / bestStreak) * 100) : 0;
    deck.push({
      title: data.streak + (data.streak === 1 ? ' day' : ' days'),
      statLabel: 'Streak',
      rarity: streakRarity,
      renderContent: () => _ringChart(streakPct, streakPct + '%', { color: streakRarity === 'legendary' ? 'var(--accent)' : streakRarity === 'epic' ? 'rgba(160,120,210,0.8)' : 'rgba(126,201,122,0.7)' }),
      stats: [
        { key: 'Current streak', value: data.streak + ' days' },
        { key: 'Best ever', value: bestStreak + ' days' },
        { key: 'vs personal best', value: streakPct + '%', color: streakPct >= 100 ? 'var(--green)' : null },
        { key: 'Lifetime plays', value: totalPlays.toLocaleString() },
      ],
      flavor: data.streak >= 30 ? 'Gotta catch \'em all.' : (data.streak >= bestStreak && data.streak >= 3 ? 'New personal best. Keep going.' : null),
    });
  }
  // Card 3: Week vs Last
  if (data.week_vs_last && data.week_vs_last.last_week > 0) {
    const tw = data.week_vs_last.this_week;
    const lw = data.week_vs_last.last_week;
    const diff = tw - lw;
    const pct = Math.round((diff / lw) * 100);
    const twTracks = data.this_week ? data.this_week.total_plays || 0 : 0;
    deck.push({
      title: (pct >= 0 ? '+' : '') + pct + '%',
      statLabel: 'vs last week',
      rarity: Math.abs(pct) >= 50 ? 'uncommon' : 'common',
      renderContent: () => _comparisonBars([
        { label: 'This week', value: tw, display: Math.round(tw) + ' min', color: 'var(--accent)' },
        { label: 'Last week', value: lw, display: Math.round(lw) + ' min', color: 'rgba(212,160,83,0.35)' },
      ]),
      stats: [
        { key: 'This week', value: Math.round(tw) + ' min (' + twTracks + ' plays)' },
        { key: 'Last week', value: Math.round(lw) + ' min' },
        { key: 'Change', value: (pct >= 0 ? '+' : '') + pct + '%', color: pct >= 0 ? 'var(--green)' : 'var(--red)' },
        { key: 'Avg per day (this wk)', value: Math.round(tw / 7) + ' min' },
        { key: 'Avg per day (last wk)', value: Math.round(lw / 7) + ' min' },
      ],
      flavor: pct >= 100 ? 'You doubled your listening. The ears want what they want.' : null,
    });
  }
  return deck;
}

function _genreDeck(topGenre, breakdown, fromLibrary, data) {
  const deck = [];
  const tw = data.this_week || {};
  const total = breakdown.reduce((s, g) => s + g.count, 0);
  const topPct = total > 0 && breakdown[0] ? Math.round((breakdown[0].count / total) * 100) : 0;
  // Card 0: Main
  deck.push({
    title: topGenre || 'None',
    statLabel: fromLibrary ? 'Top genre' : 'Recent genre',
    rarity: 'common',
    renderContent: () => _barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))),
    stats: [
      ...breakdown.slice(0, 6).map(g => {
        const gPct = total > 0 ? Math.round((g.count / total) * 100) : 0;
        return { key: g.genre, value: g.count + (fromLibrary ? ' tracks' : ' plays') + ' (' + gPct + '%)' };
      }),
      { key: 'Total genres', value: breakdown.length.toString() },
      { key: 'Dominance', value: topPct + '% ' + (topGenre || 'None') },
    ],
    flavor: topPct >= 60 ? 'You know what you like.' : (breakdown.length >= 6 ? 'Eclectic taste. Hard to pin down.' : null),
  });
  // Card 1: Deep Cut
  if (breakdown.length >= 3) {
    const rarest = breakdown[breakdown.length - 1];
    const rarestPct = total > 0 ? Math.round((rarest.count / total) * 100) : 0;
    const top2 = breakdown.slice(0, 2).reduce((s, g) => s + g.count, 0);
    const top2Pct = total > 0 ? Math.round((top2 / total) * 100) : 0;
    deck.push({
      title: rarestPct + '%',
      statLabel: 'Deep cut',
      rarity: rarestPct <= 5 ? 'rare' : 'common',
      renderContent: () => _ringChart(rarestPct, rarest.genre, { color: 'rgba(100,160,220,0.7)' }),
      stats: [
        { key: 'Rarest genre', value: rarest.genre },
        { key: 'Plays', value: rarest.count.toLocaleString() },
        { key: 'Share of library', value: rarestPct + '%' },
        { key: 'Top 2 genres share', value: top2Pct + '% of all plays' },
        { key: 'Diversity', value: breakdown.length + ' genres explored' },
      ],
      flavor: rarestPct <= 5 ? 'A person of refined and unusual taste.' : null,
    });
  }
  // Card 2: Shifting
  const allTimeTop = data.genre_breakdown && data.genre_breakdown[0] ? data.genre_breakdown[0].genre : null;
  const weekTop = tw.genre_breakdown && tw.genre_breakdown[0] ? tw.genre_breakdown[0].genre : null;
  if (allTimeTop && weekTop && allTimeTop !== weekTop) {
    const weekTopCount = tw.genre_breakdown[0].count;
    const allTimeTopCount = data.genre_breakdown[0].count;
    deck.push({
      title: weekTop,
      statLabel: 'Shifting',
      rarity: 'uncommon',
      renderContent: () => _comparisonBars([
        { label: 'This week: ' + weekTop, value: weekTopCount, display: weekTopCount + ' plays', color: 'var(--accent)' },
        { label: 'All-time: ' + allTimeTop, value: allTimeTopCount, display: allTimeTopCount + ' plays', color: 'rgba(212,160,83,0.35)' },
      ]),
      stats: [
        { key: 'This week\'s #1', value: weekTop + ' (' + weekTopCount + ' plays)' },
        { key: 'All-time #1', value: allTimeTop + ' (' + allTimeTopCount + ' plays)' },
        { key: 'Weekly genres', value: (tw.genre_breakdown || []).length + ' active' },
        { key: 'All-time genres', value: breakdown.length + ' total' },
      ],
      flavor: 'Tastes evolve. The ear knows what it wants.',
    });
  }
  return deck;
}

function _tracksDeck(count, genres, data) {
  const deck = [];
  const played = count - (data.unplayed_count || 0);
  const playedPct = count > 0 ? Math.round((played / count) * 100) : 0;
  // Card 0: Main
  deck.push({
    title: count.toLocaleString(),
    statLabel: 'Tracks',
    rarity: 'common',
    renderContent: () => {
      if (genres && genres.length > 0) {
        return _barChart(genres.slice(0, 4).map(g => ({ label: g.genre, value: g.count })));
      }
      return null;
    },
    stats: [
      { key: 'Total tracks', value: count.toLocaleString() },
      { key: 'Played at least once', value: played.toLocaleString() + ' (' + playedPct + '%)' },
      { key: 'Albums', value: (data.album_count || 0).toLocaleString() },
      { key: 'Genres', value: (genres || []).length.toString() },
      { key: 'Lifetime plays', value: (data.total_plays || 0).toLocaleString() },
    ],
    flavor: count >= 1000 ? 'A library worthy of Alexandria.' : null,
  });
  // Card 1: Quality
  if (data.format_breakdown && data.format_breakdown.length > 0) {
    const topFormat = data.format_breakdown[0];
    const topPct = Math.round((topFormat.count / count) * 100);
    const lossless = data.format_breakdown.filter(f => ['FLAC', 'WAV', 'ALAC', 'AIFF'].includes(f.format.toUpperCase())).reduce((s, f) => s + f.count, 0);
    const lossy = count - lossless;
    const losslessPct = Math.round((lossless / count) * 100);
    const qualityRarity = losslessPct >= 80 ? 'rare' : 'common';
    deck.push({
      title: topFormat.format + ' ' + topPct + '%',
      statLabel: 'Quality',
      rarity: qualityRarity,
      renderContent: () => _barChart(data.format_breakdown.slice(0, 4).map(f => ({ label: f.format, value: f.count }))),
      stats: [
        ...data.format_breakdown.map(f => {
          const fPct = Math.round((f.count / count) * 100);
          return { key: f.format, value: f.count.toLocaleString() + ' (' + fPct + '%)' };
        }),
        { key: 'Lossless total', value: lossless.toLocaleString() + ' (' + losslessPct + '%)' },
        { key: 'Lossy total', value: lossy.toLocaleString() + ' (' + (100 - losslessPct) + '%)' },
      ],
      flavor: losslessPct >= 80 ? 'Your ears deserve nothing less.' : (losslessPct <= 20 ? 'There\'s a whole world of lossless out there.' : null),
    });
  }
  // Card 2: Unplayed
  if (data.unplayed_count > 0) {
    const unplayedPct = Math.round((data.unplayed_count / count) * 100);
    const playRatio = played > 0 ? Math.round((data.total_plays || 0) / played * 10) / 10 : 0;
    deck.push({
      title: data.unplayed_count.toLocaleString(),
      statLabel: 'Unplayed',
      rarity: unplayedPct < 10 ? 'uncommon' : 'common',
      renderContent: () => _ringChart(100 - unplayedPct, playedPct + '% played', { color: unplayedPct < 10 ? 'rgba(126,201,122,0.7)' : 'var(--accent)' }),
      stats: [
        { key: 'Never played', value: data.unplayed_count.toLocaleString() + ' tracks' },
        { key: 'Unplayed share', value: unplayedPct + '% of library' },
        { key: 'Played at least once', value: played.toLocaleString() },
        { key: 'Avg replays per played track', value: playRatio + 'x' },
      ],
      flavor: unplayedPct < 10 ? 'Achievement unlocked: No stone unturned.' : (unplayedPct >= 50 ? 'Half your library is waiting to be discovered.' : null),
    });
  }
  return deck;
}

function _albumsDeck(count, artists, data) {
  const deck = [];
  const avgTracksPerAlbum = count > 0 && data.track_count ? Math.round(data.track_count / count) : 0;
  const uniqueArtists = artists ? artists.length : 0;
  // Card 0: Main
  deck.push({
    title: count.toLocaleString(),
    statLabel: 'Albums',
    rarity: 'common',
    renderContent: () => {
      if (artists && artists.length > 0) {
        return _barChart(artists.slice(0, 4).map(a => ({ label: a.artist, value: a.count })));
      }
      return null;
    },
    stats: [
      ...(data.top_album ? [
        { key: 'Most played album', value: data.top_album.album },
        { key: 'Artist', value: data.top_album.artist },
        { key: 'Plays', value: (data.top_album.play_count || 0).toLocaleString() },
      ] : []),
      { key: 'Unique artists', value: uniqueArtists.toLocaleString() },
      { key: 'Avg tracks per album', value: avgTracksPerAlbum.toString() },
      { key: 'Favorites', value: (data.favorites_count || 0).toLocaleString() + ' tracks' },
    ],
    flavor: count >= 100 ? 'A collection worth curating.' : null,
  });
  // Card 1: Completionist
  if (data.completionist_albums && data.completionist_albums.total > 0) {
    const ca = data.completionist_albums;
    const pct = Math.round((ca.complete / ca.total) * 100);
    const incomplete = ca.total - ca.complete;
    const rarity = pct >= 100 ? 'legendary' : pct >= 50 ? 'epic' : 'common';
    deck.push({
      title: ca.complete + ' / ' + ca.total,
      statLabel: 'Completionist',
      rarity,
      renderContent: () => _ringChart(pct, pct + '%', { color: pct >= 50 ? 'rgba(126,201,122,0.7)' : 'var(--accent)' }),
      stats: [
        { key: 'Fully played', value: ca.complete + ' albums' },
        { key: 'Partially explored', value: incomplete + ' albums' },
        { key: 'Completion rate', value: pct + '%', color: pct >= 50 ? 'var(--green)' : null },
        { key: 'Total albums', value: ca.total.toLocaleString() },
      ],
      flavor: pct >= 100 ? 'Achievement unlocked: No stone unturned.' : (pct <= 10 ? 'So many albums, so little time.' : null),
    });
  }
  // Card 2: Recent
  if (data.recent_albums && data.recent_albums.length > 0) {
    deck.push({
      title: data.recent_albums.length + ' new',
      statLabel: 'Recently added',
      rarity: 'common',
      renderContent: () => _albumArtGrid(data.recent_albums),
      stats: [
        ...data.recent_albums.slice(0, 3).map(a => ({
          key: (a.artist || '').length > 18 ? a.artist.slice(0, 16) + '…' : a.artist,
          value: (a.album || '').length > 20 ? a.album.slice(0, 18) + '…' : a.album,
        })),
        { key: 'Library growth', value: (data.collection_growth || 0).toLocaleString() + ' tracks' },
      ],
      flavor: 'Fresh additions to the collection.',
    });
  }
  return deck;
}

function _listeningTimeTile(hours, weekly, data) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', Math.round(hours) + 'h', 'bento-label'));
  body.appendChild(textEl('div', 'Listening time', 'bento-stat-label'));
  const ins = _listeningInsight(hours, weekly);
  if (ins) body.appendChild(ins);
  body.appendChild(_weeklyChart(weekly));
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _listeningTimeDeck(tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
  return tile;
}

function _tracksTile(count, genres, data) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', count.toLocaleString(), 'bento-label'));
  body.appendChild(textEl('div', 'Tracks', 'bento-stat-label'));
  body.appendChild(_tracksInsight(count, genres));
  if (genres && genres.length > 0) {
    body.appendChild(_barChart(genres.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  }
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _tracksDeck(count, genres, tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
  return tile;
}

function _albumsTile(count, artists, data) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', count.toLocaleString(), 'bento-label'));
  body.appendChild(textEl('div', 'Albums', 'bento-stat-label'));
  body.appendChild(_albumsInsight(count, artists));
  if (artists && artists.length > 0) {
    body.appendChild(_barChart(artists.slice(0, 4).map(a => ({ label: a.artist, value: a.count }))));
  }
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _albumsDeck(count, artists, tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
  return tile;
}

// ---- MINI CHARTS ----
function _barChart(items) {
  if (!items || items.length === 0) return h('div');
  const max = Math.max(...items.map(i => i.value), 1);
  const chart = h('div', { className: 'mini-bar-chart' });
  for (const item of items) {
    const row = h('div', { className: 'bar-row' });
    row.appendChild(textEl('span', item.label, 'bar-label'));
    const barBg = h('div', { className: 'bar-bg' });
    const fill = h('div', { className: 'bar-fill' });
    fill.style.width = Math.round((item.value / max) * 100) + '%';
    barBg.appendChild(fill);
    row.appendChild(barBg);
    chart.appendChild(row);
  }
  return chart;
}

function _weeklyChart(values) {
  const days = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const max = Math.max(...values, 0.1);
  const chart = h('div', { className: 'mini-weekly-chart' });
  for (let i = 0; i < 7; i++) {
    const col = h('div', { className: 'weekly-col' });
    const pct = values[i] / max;
    const bar = h('div', { className: 'weekly-bar' + (pct >= 0.85 ? ' peak' : '') });
    bar.style.height = Math.round(pct * 100) + '%';
    col.appendChild(bar);
    col.appendChild(textEl('span', days[i], 'weekly-day'));
    chart.appendChild(col);
  }
  return chart;
}

function _renderRecentStrip(container) {
  const section = h('div', { className: 'home-recent-section' });
  const labelRow = h('div', { className: 'home-recent-header' });
  labelRow.appendChild(textEl('span', 'Recently played', 'home-section-label'));
  const rightBtns = h('div', { className: 'home-recent-btns' });
  const luckyBtn2 = h('button', { className: 'pill pill-sm', onClick: feelingLucky });
  luckyBtn2.textContent = "I'm feeling lucky";
  rightBtns.appendChild(luckyBtn2);
  labelRow.appendChild(rightBtns);
  section.appendChild(labelRow);

  const strip = h('div', { className: 'recent-strip' });
  for (const track of recentlyPlayed) {
    const card = h('div', { className: 'recent-card' });
    if (track.cover_url) {
      const img = h('img', { className: 'recent-card-art', src: track.cover_url, alt: '', loading: 'lazy' });
      img.onerror = function() {
        const grad = h('div', { className: 'recent-card-art' });
        grad.style.background = artGradient(track.id || track.name);
        this.replaceWith(grad);
      };
      card.appendChild(img);
    } else {
      const artPlaceholder = h('div', { className: 'recent-card-art' });
      artPlaceholder.style.background = artGradient(track.id || track.name);
      card.appendChild(artPlaceholder);
    }
    card.appendChild(textEl('div', track.name || 'Unknown', 'recent-card-name'));
    const artistEl = textEl('div', track.artist || '', 'recent-card-artist');
    artistEl.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!track.artist) return;
      navigate('artist:' + encodeURIComponent(track.artist));
    });
    card.appendChild(artistEl);
    card.addEventListener('click', () => {
      if (track.is_local && track.local_path) startPlaybackFromList(track, recentlyPlayed);
      else if (track.id) startPlaybackFromList(track, recentlyPlayed);
    });
    a11yClick(card);
    strip.appendChild(card);
  }
  section.appendChild(strip);
  container.appendChild(section);
}

// ---- SEARCH VIEW ----
let searchDebounce = null;

// ---- RECENT SEARCHES (localStorage) ----
function _getRecentSearches() {
  try { return JSON.parse(localStorage.getItem('recentSearches') || '[]'); } catch (_) { return []; }
}
function _saveRecentSearch(query, type) {
  const recent = _getRecentSearches().filter(r => !(r.query === query && r.type === type));
  recent.unshift({ query, type, ts: Date.now() });
  if (recent.length > 10) recent.pop();
  localStorage.setItem('recentSearches', JSON.stringify(recent));
}
function _removeRecentSearch(query, type) {
  const recent = _getRecentSearches().filter(r => !(r.query === query && r.type === type));
  localStorage.setItem('recentSearches', JSON.stringify(recent));
}
function _clearRecentSearches() {
  localStorage.removeItem('recentSearches');
}

function _renderRecentSearches(recentEl, input, resultsArea) {
  while (recentEl.firstChild) recentEl.removeChild(recentEl.firstChild);
  const recent = _getRecentSearches();
  if (recent.length === 0) {
    recentEl.classList.remove('visible');
    return;
  }
  const header = h('div', { className: 'recent-searches-header' },
    textEl('span', 'Recent searches', 'recent-searches-label')
  );
  const clearBtn = h('button', {
    className: 'recent-searches-clear',
    onClick: () => {
      _clearRecentSearches();
      recentEl.classList.remove('visible');
    }
  }, 'Clear all');
  header.appendChild(clearBtn);
  recentEl.appendChild(header);

  const chips = h('div', { className: 'recent-searches-chips' });
  for (const item of recent) {
    const chip = h('div', { className: 'recent-chip' });
    chip.appendChild(textEl('span', item.query));
    chip.appendChild(textEl('span', item.type, 'recent-chip-type'));
    const x = textEl('span', '\u00d7', 'recent-chip-x');
    x.addEventListener('click', (e) => {
      e.stopPropagation();
      _removeRecentSearch(item.query, item.type);
      _renderRecentSearches(recentEl, input, resultsArea);
    });
    chip.appendChild(x);
    chip.addEventListener('click', () => {
      input.value = item.query;
      state.searchQuery = item.query;
      state.searchType = item.type;
      recentEl.classList.remove('visible');
      doSearch(resultsArea);
      // Update filter pills to reflect the search type
      const pillContainer = input.closest('.search-area')?.querySelector('.filter-pills');
      if (pillContainer) {
        pillContainer.querySelectorAll('.pill').forEach(p => {
          p.classList.toggle('active', p.textContent.toLowerCase() === item.type);
        });
      }
    });
    chips.appendChild(chip);
  }
  recentEl.appendChild(chips);
  recentEl.classList.add('visible');
}

function renderSearch(container) {
  const searchArea = h('div', { className: 'search-area' });

  const searchRow = h('div', { className: 'search-row' });
  const searchField = h('div', { className: 'search-field' });
  searchField.appendChild(svgIcon(ICONS.search));
  const input = h('input', {
    className: 'search-input',
    type: 'text',
    placeholder: 'Search artists, albums, tracks on Tidal...',
  });
  input.value = state.searchQuery;
  searchField.appendChild(input);
  searchRow.appendChild(searchField);
  searchArea.appendChild(searchRow);

  // Recent searches dropdown
  const recentSearchesEl = h('div', { className: 'recent-searches' });
  searchArea.appendChild(recentSearchesEl);

  input.addEventListener('input', () => {
    state.searchQuery = input.value;
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => doSearch(resultsArea), 300);
    if ((input.value || '').trim().length < 2) {
      _renderRecentSearches(recentSearchesEl, input, resultsArea);
    } else {
      recentSearchesEl.classList.remove('visible');
    }
  });
  input.addEventListener('focus', () => {
    if ((input.value || '').trim().length < 2) {
      _renderRecentSearches(recentSearchesEl, input, resultsArea);
    }
  });
  var _blurTimer = null;
  input.addEventListener('blur', () => {
    // Delay to allow click events on chips/pills to fire first
    _blurTimer = setTimeout(() => recentSearchesEl.classList.remove('visible'), 200);
  });

  // Filter pills
  const pills = h('div', { className: 'filter-pills' });
  for (const type of ['tracks', 'albums', 'artists', 'playlists']) {
    const pill = textEl('div', type.charAt(0).toUpperCase() + type.slice(1),
      'pill' + (state.searchType === type ? ' active' : ''));
    pill.style.cursor = 'pointer';
    pill.addEventListener('click', () => {
      clearTimeout(_blurTimer);
      state.searchType = type;
      pills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      if (state.searchQuery) doSearch(resultsArea);
      else _renderRecentSearches(recentSearchesEl, input, resultsArea);
    });
    a11yClick(pill);
    pills.appendChild(pill);
  }
  searchArea.appendChild(pills);
  container.appendChild(searchArea);

  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  if (state.searchResults && state.searchQuery) {
    renderUnifiedSearchResults(resultsArea, state.searchResults.local, state.searchResults.tidal);
  } else {
    renderSearchEmpty(resultsArea);
  }

  requestAnimationFrame(() => input.focus());
}

function _greeting() {
  const h = new Date().getHours();
  if (h < 5) return 'Still up?';
  if (h < 12) return 'Good morning,';
  if (h < 17) return 'Good afternoon,';
  if (h < 21) return 'Good evening,';
  return 'Winding down?';
}

async function feelingLucky() {
  try {
    const data = await api('/library?sort=random&limit=1&offset=0');
    const tracks = data.tracks || [];
    if (tracks.length === 0) { toast('Library is empty — sync first', 'error'); return; }
    const track = tracks[0];
    track.local_path = track.path;
    playTrack(track);
  } catch (_) {
    toast('Couldn\'t pick a random track', 'error');
  }
}

function renderSearchEmpty(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const empty = h('div', { className: 'empty-state' });
  empty.appendChild(textEl('div', _greeting(), 'empty-state-title'));
  empty.appendChild(textEl('div', 'Search for something or let us surprise you.', 'empty-state-sub'));

  const luckyBtn = h('button', { className: 'lucky-btn', onClick: feelingLucky });
  luckyBtn.textContent = "I'm feeling lucky";
  empty.appendChild(luckyBtn);

  // Show recent if available
  if (recentlyPlayed.length > 0) {
    const last = recentlyPlayed[0];
    const label = last.name + (last.artist ? ' — ' + last.artist : '');
    const hint = h('div', { className: 'empty-state-sub', style: { marginTop: '16px', opacity: '0.8' } });
    hint.textContent = 'You were listening to ' + label;
    empty.appendChild(hint);
  }
  container.appendChild(empty);
}

function renderSearchSkeleton(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  container.appendChild(h('div', { className: 'results-header' },
    textEl('div', 'Searching...', 'results-title')
  ));
  for (let i = 0; i < 8; i++) {
    const row = h('div', { className: 'skeleton-track' },
      h('div', { className: 'skeleton sk-num' }),
      h('div', { className: 'skeleton sk-art' }),
      h('div', { className: 'skeleton sk-meta' }),
      h('div', { className: 'skeleton sk-album' }),
      h('div', { className: 'skeleton sk-quality' }),
      h('div', { className: 'skeleton sk-time' }),
      h('div')
    );
    container.appendChild(row);
  }
}

async function doSearch(resultsArea) {
  const q = state.searchQuery.trim();
  if (!q) {
    state.searchResults = null;
    renderSearchEmpty(resultsArea);
    return;
  }

  _saveRecentSearch(q, state.searchType);
  renderSearchSkeleton(resultsArea);

  // Local results first (instant from SQLite)
  let localData = null;
  try {
    localData = await api('/library/search?q=' + encodeURIComponent(q) + '&type=' + state.searchType + '&limit=20');
  } catch (_) { /* local search optional */ }

  // Tidal results (async, may fail if not logged in)
  let tidalData = null;
  try {
    tidalData = await apiTidal('/search?q=' + encodeURIComponent(q) + '&type=' + state.searchType + '&limit=50');
  } catch (_) { /* Tidal unavailable is OK */ }

  state.searchResults = { local: localData, tidal: tidalData };
  renderUnifiedSearchResults(resultsArea, localData, tidalData);
  refreshStatusLights();
}

function renderUnifiedSearchResults(container, localData, tidalData) {
  while (container.firstChild) container.removeChild(container.firstChild);

  const type = state.searchType;

  // Local results section
  let localItems = localData ? (localData[type] || []) : [];
  // Deduplicate library tracks by ISRC, falling back to title+artist
  if (type === 'tracks' && localItems.length > 0) {
    const seen = new Set();
    localItems = localItems.filter(t => {
      const key = t.isrc || ((t.name || '') + '|' + (t.artist || '')).toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  if (localItems.length > 0) {
    const localHeader = h('div', { className: 'results-header' });
    localHeader.appendChild(textEl('h3', 'Your Library', 'results-section-title'));
    localHeader.appendChild(textEl('span', localItems.length + ' results', 'results-count'));
    container.appendChild(localHeader);

    if (type === 'tracks') {
      // Inline column header (renderTrackHeader does not exist as standalone)
      container.appendChild(renderTrackHeader());
      var MAX_INITIAL_LOCAL = 5;
      var visibleLocal = localItems.length > MAX_INITIAL_LOCAL ? localItems.slice(0, MAX_INITIAL_LOCAL) : localItems;
      visibleLocal.forEach((t, i) => container.appendChild(renderTrackRow(t, i + 1, localItems)));
      if (localItems.length > MAX_INITIAL_LOCAL) {
        var showAllBtn = h('button', { className: 'show-more-btn' });
        showAllBtn.textContent = 'Show all ' + localItems.length + ' tracks';
        showAllBtn.addEventListener('click', function() {
          // Remove the button and render remaining tracks before the divider
          var parent = showAllBtn.parentNode;
          var nextSibling = showAllBtn.nextSibling;
          showAllBtn.remove();
          for (var si = MAX_INITIAL_LOCAL; si < localItems.length; si++) {
            var row = renderTrackRow(localItems[si], si + 1, localItems);
            if (nextSibling) parent.insertBefore(row, nextSibling);
            else parent.appendChild(row);
          }
        });
        container.appendChild(showAllBtn);
      }
    } else if (type === 'albums') {
      const grid = h('div', { className: 'album-gallery' });
      localItems.forEach(a => {
        const card = h('div', { className: 'album-card' });
        const artWrap = h('div', { className: 'album-card-art-wrap' });
        const img = h('img', { className: 'album-card-art', alt: a.name || '' });
        img.src = a.cover_url || '';
        img.onerror = function() { this.style.display = 'none'; artWrap.style.background = artGradient(a.name); };
        artWrap.appendChild(img);
        card.appendChild(artWrap);
        const meta = h('div', { className: 'album-card-meta' });
        meta.appendChild(textEl('div', a.name || 'Unknown', 'album-card-title'));
        meta.appendChild(textEl('div', a.artist || '', 'album-card-sub'));
        card.appendChild(meta);
        card.addEventListener('click', () => {
          navigate('localalbum:' + encodeURIComponent(a.artist) + ':' + encodeURIComponent(a.name));
        });
        a11yClick(card);
        grid.appendChild(card);
      });
      container.appendChild(grid);
    } else if (type === 'artists') {
      const grid = h('div', { className: 'album-gallery' });
      localItems.forEach(a => {
        const card = h('div', { className: 'album-card' });
        const artWrap = h('div', { className: 'album-card-art-wrap' });
        const img = h('img', { className: 'album-card-art', alt: a.name || '' });
        img.src = a.cover_url || '';
        img.onerror = function() { this.style.display = 'none'; artWrap.style.background = artGradient(a.name); };
        artWrap.appendChild(img);
        card.appendChild(artWrap);
        const meta = h('div', { className: 'album-card-meta' });
        meta.appendChild(textEl('div', a.name || 'Unknown', 'album-card-title'));
        meta.appendChild(textEl('div', a.track_count + ' tracks', 'album-card-sub'));
        card.appendChild(meta);
        card.addEventListener('click', () => navigate('artist:' + encodeURIComponent(a.name)));
        a11yClick(card);
        grid.appendChild(card);
      });
      container.appendChild(grid);
    }
  }

  // Divider between local and Tidal sections
  const tidalItems = tidalData ? (tidalData[type] || []) : [];
  if (localItems.length > 0 && tidalItems.length > 0) {
    const divider = h('div', { className: 'search-divider' });
    divider.appendChild(textEl('span', 'Tidal', 'search-divider-label'));
    container.appendChild(divider);
  }

  // Tidal results section — delegate to existing renderer via a sub-container
  // to prevent it from clearing the local results we just rendered
  if (tidalItems.length > 0) {
    if (localItems.length === 0) {
      const tidalHeader = h('div', { className: 'results-header' });
      tidalHeader.appendChild(textEl('h3', 'Tidal', 'results-section-title'));
      tidalHeader.appendChild(textEl('span', tidalItems.length + ' results', 'results-count'));
      container.appendChild(tidalHeader);
    }

    // Render Tidal results into a sub-container so renderSearchResults
    // doesn't wipe the local section already appended above.
    // When local results are present the divider already labels the section,
    // so remove the redundant "Search Results" header renderSearchResults adds.
    const tidalWrap = h('div', {});
    container.appendChild(tidalWrap);
    renderSearchResults(tidalWrap, tidalData);
    if (localItems.length > 0) {
      const firstHeader = tidalWrap.querySelector('.results-header');
      if (firstHeader) firstHeader.remove();
    }
  }

  if (localItems.length === 0 && tidalItems.length === 0) {
    container.appendChild(textEl('div', 'No results found', 'search-empty-text'));
  }
}

function renderSearchResults(container, data) {
  while (container.firstChild) container.removeChild(container.firstChild);

  if (state.searchType === 'tracks') {
    const tracks = data.tracks || [];
    container.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Search Results', 'results-title'),
      textEl('div', tracks.length + ' tracks', 'results-count')
    ));

    if (tracks.length === 0) {
      container.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'Nothing here', 'empty-state-title'),
        textEl('div', 'Try different words or check the spelling.', 'empty-state-sub')
      ));
      return;
    }

    // Column headers — static structural content, no user data
    container.appendChild(renderTrackHeader());

    const trackList = h('div', { className: 'tracks' });
    tracks.forEach((track, i) => {
      trackList.appendChild(renderTrackRow(track, i + 1, tracks));
    });
    container.appendChild(trackList);
  } else {
    const items = data[state.searchType] || [];
    container.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Search Results', 'results-title'),
      textEl('div', items.length + ' ' + state.searchType, 'results-count')
    ));

    if (items.length === 0) {
      container.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'Nothing here', 'empty-state-title'),
        textEl('div', 'Try different words or check the spelling.', 'empty-state-sub')
      ));
      return;
    }

    const grid = h('div', { className: 'album-grid' });
    items.forEach(item => {
      const artDiv = h('div', { className: 'album-card-art' });
      if (item.cover_url) {
        const img = h('img', { src: item.cover_url, loading: 'lazy' });
        img.alt = '';
        img.onerror = function() {
          this.style.display = 'none';
          artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(item.id || item.name) } }));
        };
        artDiv.appendChild(img);
      } else {
        artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(item.id) } }));
      }
      const meta = h('div', { className: 'album-card-meta' });
      meta.appendChild(textEl('div', item.name || '', 'album-card-title'));
      if (state.searchType === 'albums' && item.artist) {
        meta.appendChild(textEl('div', typeof item.artist === 'object' ? item.artist.name : item.artist, 'album-card-sub'));
      } else if (state.searchType === 'artists') {
        meta.appendChild(textEl('div', item.roles || 'Artist', 'album-card-sub'));
      } else if (state.searchType === 'playlists' && item.num_tracks) {
        meta.appendChild(textEl('div', item.num_tracks + ' tracks', 'album-card-sub'));
      }
      const card = h('div', { className: 'album-card' },
        artDiv,
        meta
      );
      card.style.cursor = 'pointer';
      if (state.searchType === 'albums' && item.id) {
        card.addEventListener('click', () => navigateAlbum(item.id));
      } else if (state.searchType === 'artists') {
        card.addEventListener('click', () => navigate('artist:' + encodeURIComponent(item.name)));
      } else if (state.searchType === 'playlists') {
        card.addEventListener('click', () => loadPlaylistTracks(container, item));
      }
      a11yClick(card);
      grid.appendChild(card);
    });
    container.appendChild(grid);
  }
}

function _trackKey(t) {
  // id or path is the stable identity — ISRC is NOT unique per file
  return t.id || t.path || t.local_path || '';
}

function renderTrackHeader() {
  return h('div', { className: 'track-header' },
    textEl('div', '#', 'col-label center'),
    h('div'),
    textEl('div', 'Title', 'col-label'),
    textEl('div', 'Album', 'col-label'),
    textEl('div', 'Quality', 'col-label center'),
    textEl('div', 'Format', 'col-label center'),
    textEl('div', 'Plays', 'col-label center'),
    textEl('div', 'Time', 'col-label right'),
    h('div'),
    h('div')
  );
}

function _extractFormat(track) {
  const p = track.path || track.local_path || track.file_path || '';
  if (p) {
    const ext = p.split('.').pop();
    if (ext && ext.length <= 5) return ext.toUpperCase();
  }
  if (track.format) return track.format.toUpperCase();
  return '';
}

function _sameTrack(a, b) {
  if (!a || !b) return false;
  if (a._queueEntryId != null && b._queueEntryId != null) {
    return a._queueEntryId === b._queueEntryId;
  }
  return _trackKey(a) !== '' && _trackKey(a) === _trackKey(b);
}

function _findTrackIndex(list, track) {
  if (!track || !list || !list.length) return -1;
  const sameRef = list.indexOf(track);
  if (sameRef !== -1) return sameRef;
  return list.findIndex(t => _sameTrack(t, track));
}

function _cloneQueueTrack(track, entryId) {
  return { ...track, _queueEntryId: entryId };
}

function _randomShuffle(tracks) {
  const shuffled = tracks.slice();
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

function _smartShuffleTracks(tracks) {
  const recentKeys = new Set(recentlyPlayed.map(t => _trackKey(t)).filter(Boolean));
  const fresh = [];
  const recent = [];
  tracks.forEach(track => {
    (recentKeys.has(_trackKey(track)) ? recent : fresh).push(track);
  });
  return _randomShuffle(fresh).concat(_randomShuffle(recent));
}

function _shuffleTracks(tracks) {
  return state.smartShuffle ? _smartShuffleTracks(tracks) : _randomShuffle(tracks);
}

function _setQueueOrder(tracks, currentTrack) {
  const source = tracks.slice();
  const currentSourceIdx = currentTrack ? _findTrackIndex(source, currentTrack) : 0;
  const ordered = source.map(track => _cloneQueueTrack(track, ++_queueEntrySeq));
  const current = ordered[Math.max(0, currentSourceIdx)] || ordered[0] || null;
  state.queueOriginal = ordered.slice();

  if (state.shuffle) {
    const currentIdx = _findTrackIndex(ordered, current);
    const remaining = ordered.filter((_, idx) => idx !== currentIdx);
    state.queue = current ? [current, ..._shuffleTracks(remaining)] : _shuffleTracks(ordered);
    state.queueIndex = current ? 0 : 0;
  } else {
    state.queue = ordered;
    state.queueIndex = current ? _findTrackIndex(ordered, current) : 0;
  }
}

function _reshuffleCurrentQueue() {
  if (!state.queueOriginal.length) return;
  const current = state.queue[state.queueIndex] || state.queueOriginal[0] || null;
  const currentIdx = _findTrackIndex(state.queueOriginal, current);
  const remaining = state.queueOriginal.filter((_, idx) => idx !== currentIdx);
  state.queue = current ? [current, ..._shuffleTracks(remaining)] : _shuffleTracks(state.queueOriginal);
  state.queueIndex = current ? 0 : 0;
  state.shuffle = true;
  btnShuffle.classList.add('active');
  _saveQueue();
}

function _restoreOriginalQueueOrder() {
  if (!state.queueOriginal.length) return;
  const current = state.queue[state.queueIndex] || null;
  state.queue = state.queueOriginal.slice();
  const idx = current ? _findTrackIndex(state.queueOriginal, current) : 0;
  state.queueIndex = idx >= 0 ? idx : 0;
  state.shuffle = false;
  btnShuffle.classList.remove('active');
  _saveQueue();
}

function startPlaybackFromList(track, tracks) {
  _setQueueOrder(tracks, track);
  playTrack(state.queue[state.queueIndex]);
}

function _queueTrackNext(track) {
  const entry = _cloneQueueTrack(track, ++_queueEntrySeq);
  if (!state.queue.length) {
    state.queue = [entry];
    state.queueOriginal = [entry];
    state.queueIndex = 0;
    playTrack(entry);
    toast((track.name || 'Track') + ' playing next', 'success');
    return;
  }

  const insertAt = Math.max(0, state.queueIndex + 1);
  state.queue.splice(insertAt, 0, entry);
  const current = state.queue[state.queueIndex];
  const originalAt = _findTrackIndex(state.queueOriginal, current);
  state.queueOriginal.splice(originalAt >= 0 ? originalAt + 1 : state.queueOriginal.length, 0, entry);
  _saveQueue();
  if (queuePanel.classList.contains('open')) renderQueue();
  toast((track.name || 'Track') + ' will play next', 'success');
}

function _queueTrackLast(track) {
  const entry = _cloneQueueTrack(track, ++_queueEntrySeq);
  state.queue.push(entry);
  state.queueOriginal.push(entry);
  if (state.queueIndex < 0) state.queueIndex = 0;
  _saveQueue();
  if (queuePanel.classList.contains('open')) renderQueue();
  toast((track.name || 'Track') + ' added to queue', 'success');
}

function renderTrackRow(track, num, allTracks) {
  const current = state.queue[state.queueIndex];
  const isPlaying = current && _trackKey(current) === _trackKey(track) && _trackKey(track) !== '' && state.playing;
  const row = h('div', { className: 'track' + (isPlaying ? ' playing' : ''), 'data-track-id': _trackKey(track) });

  // Number / equalizer
  const numCell = h('div', { className: 'track-num', 'data-num': String(num) });
  if (isPlaying) {
    const bars = h('div', { className: 'eq-bars' });
    for (let i = 0; i < 4; i++) bars.appendChild(h('div', { className: 'eq-bar' }));
    numCell.appendChild(bars);
  } else {
    numCell.textContent = num;
  }
  row.appendChild(numCell);

  // Art
  const artCell = h('div', { className: 'track-art' });
  if (track.cover_url) {
    const artImg = h('img', { className: 'track-art-img', src: track.cover_url, loading: 'lazy', alt: '' });
    artImg.onerror = function() { this.replaceWith(h('div', { className: 'art-gradient', style: { background: artGradient(track.id || track.name) } })); };
    artCell.appendChild(artImg);
  } else {
    artCell.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(track.id || track.name) } }));
  }
  row.appendChild(artCell);

  // Meta — user data via textContent only
  // Skip artist link when already inside an album view (prevents accidental navigation)
  const artistEl = textEl('div', track.artist || '', 'track-artist');
  const inAlbumView = state.view.startsWith('album:') || state.view.startsWith('localalbum:');
  if (track.artist && !inAlbumView) {
    artistEl.style.cursor = 'pointer';
    artistEl.addEventListener('click', (e) => {
      e.stopPropagation();
      navigate('artist:' + encodeURIComponent(track.artist));
    });
  }
  row.appendChild(h('div', { className: 'track-meta' },
    textEl('div', track.name || '', 'track-name'),
    artistEl
  ));

  // Album — clickable: Tidal albums by ID, local albums by artist+album name
  // Skip if already viewing this album (prevents accidental re-navigation)
  const albumCell = textEl('div', track.album || '', 'track-album');
  if (track.album_id && state.view !== 'album:' + track.album_id) {
    albumCell.style.cursor = 'pointer';
    albumCell.addEventListener('click', (e) => {
      e.stopPropagation();
      navigateAlbum(track.album_id);
    });
  } else if (track.album && track.artist && state.view !== 'localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album)) {
    albumCell.style.cursor = 'pointer';
    albumCell.addEventListener('click', (e) => {
      e.stopPropagation();
      navigate('localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album));
    });
  }
  row.appendChild(albumCell);

  // Quality
  const qTag = textEl('div', qualityLabel(track.quality, track.format), 'quality-tag ' + qualityClass(track.quality, track.format));
  qTag.title = qualityTitle(track.quality, track.format);
  row.appendChild(qTag);

  // Format
  row.appendChild(textEl('div', _extractFormat(track), 'track-format'));

  // Plays
  const plays = track.play_count || 0;
  row.appendChild(textEl('div', plays > 0 ? String(plays) : '\u2014', 'track-plays'));

  // Time
  row.appendChild(textEl('div', formatTime(track.duration), 'track-time'));

  // Actions
  const actions = h('div', { className: 'track-actions' + (track.is_local ? ' visible' : '') });
  if (track.is_local) {
    const dot = h('span', { className: 'local-dot' });
    const tag = h('span', { className: 'local-tag' }, dot, ' local');
    actions.appendChild(tag);
  } else {
    const btn = h('button', { className: 'dl-btn', title: 'Download' });
    btn.appendChild(svgIcon(ICONS.download));
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      downloadTrack(track, btn);
    });
    actions.appendChild(btn);
  }
  row.appendChild(actions);

  // Heart button
  const heartSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  heartSvg.setAttribute('viewBox', '0 0 24 24');
  heartSvg.setAttribute('fill', 'none');
  heartSvg.setAttribute('stroke', 'currentColor');
  const heartPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  heartPath.setAttribute('d', 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z');
  heartSvg.appendChild(heartPath);

  const heartBtn = h('button', {
    className: 'heart-btn',
    'aria-label': 'Toggle favorite',
  });
  heartBtn.appendChild(heartSvg);

  const favKey = track.path || (track.id ? 'tidal:' + track.id : null);
  if (favKey && _favCache[favKey]) {
    heartBtn.classList.add('hearted');
  }

  heartBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleFavorite(track, heartBtn);
  });

  row.appendChild(heartBtn);

  // Right-click context menu
  const localPath = track.local_path || track.path;
  row.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    const trackName = track.name || track.title || 'this track';
    const menuItems = [
      { label: 'Play Next', icon: 'play', action: () => _queueTrackNext(track) },
      { label: 'Add to Queue', icon: 'music', action: () => _queueTrackLast(track) },
    ];
    if (localPath) {
      menuItems.push(
        'sep',
        {
          label: 'Open in Finder',
          icon: 'folder',
          action: async () => {
            try {
              await api('/downloads/reveal', { method: 'POST', body: { path: localPath } });
              toast('Revealed in Finder', 'success');
            } catch (_) {
              toast('File not found', 'error');
            }
          }
        },
        // Upgrade Quality — only for local tracks with ISRC below user's target tier
        ...(() => {
          if (!track.isrc) return [];
          const tier = _qualityTier(track.quality, track.format);
          const targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
          const tierRanks = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 };
          if ((tierRanks[tier.tier] || 0) >= targetRank) return [];
          return [{ label: 'Upgrade Quality', icon: 'download', action: () => upgradeTrack(track) }];
        })(),
        'sep',
        {
          label: 'Delete Track',
          icon: 'trash',
          className: 'ctx-danger',
          action: () => {
            inlineConfirm('Delete "' + trackName + '"? This removes the file from disk and your library.', async () => {
              try {
                await api('/library/track', { method: 'DELETE', body: { path: localPath } });

                // Remove row from DOM
                row.remove();

                // If this track is currently playing, stop playback
                const current = state.queue[state.queueIndex];
                if (current && _trackKey(current) === _trackKey(track)) {
                  audio.pause();
                  audio.src = '';
                  state.playing = false;
                  updatePlayButton();
                  setWaveformPlaying(false);
                }

                // Remove deleted file from queue snapshots
                const removedKey = _trackKey(track);
                const currentQueueTrack = state.queue[state.queueIndex] || null;
                const removedBeforeCurrent = state.queue.slice(0, state.queueIndex).filter(t => _trackKey(t) === removedKey).length;
                const removedCurrent = currentQueueTrack && _trackKey(currentQueueTrack) === removedKey;
                state.queue = state.queue.filter(t => _trackKey(t) !== removedKey);
                state.queueOriginal = state.queueOriginal.filter(t => _trackKey(t) !== removedKey);
                if (removedBeforeCurrent) state.queueIndex -= removedBeforeCurrent;
                if (removedCurrent && state.queue.length === 0) state.queueIndex = -1;
                else if (state.queueIndex >= state.queue.length) state.queueIndex = state.queue.length - 1;
                _saveQueue();

                toast('Track deleted', 'success');
              } catch (err) {
                toast('Failed to delete track', 'error');
              }
            });
          }
        }
      );
    }
    showContextMenu(e, menuItems);
  });

  // Click to play
  row.addEventListener('click', () => {
    startPlaybackFromList(track, allTracks);
  });
  a11yClick(row);

  return row;
}

// ---- PLACEHOLDER VIEW ----
function renderPlaceholder(container, title, subtitle) {
  container.appendChild(h('div', { className: 'empty-state' },
    svgIcon(ICONS.music),
    textEl('div', title, 'empty-state-title'),
    textEl('div', subtitle, 'empty-state-sub')
  ));
}

// ---- BREADCRUMB NAV ----
function breadcrumb(crumbs) {
  // Purely navigational — uniform size, last segment is current (not clickable)
  const nav = h('nav', { className: 'breadcrumb' });
  crumbs.forEach((c, i) => {
    const isLast = i === crumbs.length - 1;
    const span = textEl('span', c.label, isLast ? 'crumb crumb-active' : 'crumb crumb-link');
    if (!isLast) {
      span.addEventListener('click', () => navigate(normalizeView(c.view)));
    }
    nav.appendChild(span);
    if (!isLast) {
      nav.appendChild(textEl('span', '/', 'crumb-sep'));
    }
  });
  return nav;
}

// ---- ARTIST ALBUM GALLERY (local library) ----
async function renderArtistGallery(container, artistName) {
  const header = h('div', { className: 'artist-gallery-header' });
  header.appendChild(breadcrumb([
    { label: 'Home', view: 'home' },
    { label: artistName },
  ]));
  const titleRow = h('div', { className: 'artist-gallery-title-row' });
  titleRow.appendChild(textEl('h1', artistName, 'artist-gallery-title'));
  header.appendChild(titleRow);
  container.appendChild(header);

  const grid = h('div', { className: 'album-gallery' });
  container.appendChild(grid);
  grid.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    const data = await api('/library/artist/' + encodeURIComponent(artistName) + '/albums');
    while (grid.firstChild) grid.removeChild(grid.firstChild);

    if (!data.albums || data.albums.length === 0) {
      grid.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'No albums found', 'empty-state-title'),
        textEl('div', 'Try syncing your library first', 'empty-state-sub')
      ));
      return;
    }

    const titleRow = header.querySelector('.artist-gallery-title-row');
    if (titleRow) titleRow.appendChild(textEl('span', data.albums.length + ' albums', 'artist-gallery-count'));

    data.albums.forEach(album => {
      const card = h('div', { className: 'album-card' });

      const artWrap = h('div', { className: 'album-card-art-wrap' });
      if (album.cover_url) {
        const img = h('img', { className: 'album-card-art', src: album.cover_url, alt: '', loading: 'lazy' });
        img.onerror = function() {
          this.style.display = 'none';
          artWrap.style.background = artGradient(album.name);
        };
        artWrap.appendChild(img);
      } else {
        artWrap.style.background = artGradient(album.name);
      }
      card.appendChild(artWrap);

      const meta = h('div', { className: 'album-card-meta' });
      meta.appendChild(textEl('div', album.name || 'Unknown Album', 'album-card-title'));
      const sub = [];
      sub.push(album.track_count + ' track' + (album.track_count !== 1 ? 's' : ''));
      if (album.best_quality) sub.push(album.best_quality);
      meta.appendChild(textEl('div', sub.join(' · '), 'album-card-sub'));
      card.appendChild(meta);

      card.addEventListener('click', () => {
        navigate(buildLocalAlbumView(artistName, album.name));
      });
      a11yClick(card);

      grid.appendChild(card);
    });
  } catch (err) {
    while (grid.firstChild) grid.removeChild(grid.firstChild);
    grid.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load albums', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}


// ---- LOCAL ALBUM DETAIL (from library click) ----
async function renderLocalAlbumDetail(container, artistName, albumName) {
  const wrapper = h('div', { className: 'album-detail-view' });
  container.appendChild(wrapper);

  wrapper.appendChild(breadcrumb([
    { label: 'Library', view: 'library' },
    { label: artistName, view: 'artist:' + encodeURIComponent(artistName) },
    { label: albumName },
  ]));

  // Fetch album info for cover art
  let coverUrl = '';
  try {
    const albumsData = await api('/library/artist/' + encodeURIComponent(artistName) + '/albums');
    const match = (albumsData.albums || []).find(a => a.name === albumName);
    if (match) coverUrl = match.cover_url;
  } catch (_) {}

  // Album header
  const albumHeader = h('div', { className: 'album-detail-header' });
  const artWrap = h('div', { className: 'album-detail-art-wrap' });
  if (coverUrl) {
    const img = h('img', { className: 'album-detail-art', src: coverUrl, alt: '' });
    img.onerror = function() { this.style.display = 'none'; artWrap.style.background = artGradient(albumName); };
    artWrap.appendChild(img);
  } else {
    artWrap.style.background = artGradient(albumName);
  }
  albumHeader.appendChild(artWrap);

  const albumMeta = h('div', { className: 'album-detail-meta' });
  albumMeta.appendChild(textEl('div', albumName, 'album-detail-title'));
  const artistLink = textEl('div', artistName, 'album-detail-artist');
  artistLink.style.cursor = 'pointer';
  artistLink.addEventListener('click', () => navigate(buildArtistView(artistName)));
  albumMeta.appendChild(artistLink);

  // Play / Shuffle / Download Missing pills
  const albumActions = h('div', { className: 'album-actions' });
  const playBtn = h('button', { className: 'pill active album-play-btn' });
  playBtn.textContent = '\u25B6  Play ' + albumName;
  playBtn.disabled = true;
  const shuffleBtn = h('button', { className: 'pill album-shuffle-btn' });
  shuffleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>Shuffle';
  shuffleBtn.disabled = true;
  // "Complete Album" pill — lazily looks up the full album on Tidal
  const completeAlbumBtn = h('button', { className: 'pill album-dl-btn' });
  const _caIcon = svgIcon(ICONS.download);
  _caIcon.style.verticalAlign = '-2px';
  _caIcon.style.marginRight = '4px';
  completeAlbumBtn.appendChild(_caIcon);
  completeAlbumBtn.appendChild(document.createTextNode('Show on Tidal'));
  completeAlbumBtn.style.display = 'none';
  albumActions.appendChild(playBtn);
  albumActions.appendChild(shuffleBtn);
  albumActions.appendChild(completeAlbumBtn);
  // "Check for Upgrades" pill
  const upgradeBtn = h('button', { className: 'pill album-upgrade-btn' });
  upgradeBtn.textContent = 'Check for Upgrades';
  upgradeBtn.style.display = 'none';
  albumActions.appendChild(upgradeBtn);
  albumMeta.appendChild(albumActions);

  albumHeader.appendChild(albumMeta);
  wrapper.appendChild(albumHeader);

  // Track header
  wrapper.appendChild(renderTrackHeader());

  const trackList = h('div', { className: 'tracks' });
  wrapper.appendChild(trackList);
  trackList.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    const data = await api('/library/artist/' + encodeURIComponent(artistName) + '/album/' + encodeURIComponent(albumName) + '/tracks');
    while (trackList.firstChild) trackList.removeChild(trackList.firstChild);

    const tracks = data.tracks || [];
    tracks.forEach((track, i) => {
      track.local_path = track.path;
      trackList.appendChild(renderTrackRow(track, i + 1, tracks));
    });

    if (tracks.length) {
      playBtn.disabled = false;
      shuffleBtn.disabled = false;
      albumMeta.querySelector('.album-detail-sub')?.remove();
      const subLine = textEl('div', tracks.length + ' track' + (tracks.length !== 1 ? 's' : ''), 'album-detail-sub');
      albumMeta.insertBefore(subLine, albumActions);

      playBtn.addEventListener('click', () => {
        state.shuffle = false;
        btnShuffle.classList.remove('active');
        _setQueueOrder(tracks, tracks[0]);
        playTrack(state.queue[state.queueIndex]);
      });
      shuffleBtn.addEventListener('click', () => {
        state.shuffle = true;
        btnShuffle.classList.add('active');
        _setQueueOrder(tracks, tracks[0]);
        playTrack(state.queue[state.queueIndex]);
      });

      // Upgrade check — show button if any tracks are below target quality
      const _tierRanks = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 };
      const _targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
      const belowTarget = tracks.filter(t => (_tierRanks[_qualityTier(t.quality, t.format).tier] || 0) < _targetRank);
      const withIsrc = belowTarget.filter(t => t.isrc);
      const noIsrc = belowTarget.filter(t => !t.isrc);

      if (belowTarget.length > 0) {
        upgradeBtn.style.display = '';
        upgradeBtn.addEventListener('click', async () => {
          upgradeBtn.disabled = true;
          upgradeBtn.textContent = 'Checking...';
          try {
            const allUpgradeable = [];

            // Probe tracks WITH ISRC
            const _qRank = { 'LOW': 0, 'HIGH': 1, 'LOSSLESS': 2, 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 };
            if (withIsrc.length > 0) {
              const probeData = await api('/upgrade/probe', { method: 'POST', body: { isrcs: withIsrc.map(t => t.isrc) } });
              (probeData.results || []).forEach(r => {
                const mt = tracks.find(t => t.isrc === r.isrc);
                if (!mt) return;
                const row = trackList.querySelector('[data-track-id="' + _trackKey(mt) + '"]');
                if (!row) return;
                const ex = row.querySelector('.upgrade-badge'); if (ex) ex.remove();
                const localRank = _tierRanks[_qualityTier(mt.quality, mt.format).tier] || 0;
                const probeRank = _qRank[r.max_quality] || 0;
                if (r.tidal_track_id && probeRank > localRank) {
                  const b = h('span', { className: 'upgrade-badge' }); b.textContent = '\u2B06 ' + qualityLabel(r.max_quality);
                  const mc = row.querySelector('.track-artist'); if (mc && mc.parentElement) mc.parentElement.appendChild(b);
                  allUpgradeable.push({ path: mt.local_path || mt.path, tidal_track_id: r.tidal_track_id });
                }
              });
            }

            // Probe tracks WITHOUT ISRC via title+artist
            if (noIsrc.length > 0) {
              const metaData = await api('/upgrade/probe-by-meta', {
                method: 'POST',
                body: { tracks: noIsrc.map(t => ({ path: t.local_path || t.path, title: t.name || '', artist: t.artist || '' })) }
              });
              (metaData.results || []).forEach(r => {
                const mt = noIsrc.find(t => (t.local_path || t.path) === r.path);
                if (!mt) return;
                const row = trackList.querySelector('[data-track-id="' + _trackKey(mt) + '"]');
                if (!row) return;
                const ex = row.querySelector('.upgrade-badge'); if (ex) ex.remove();
                const mtLocalRank = _tierRanks[_qualityTier(mt.quality, mt.format).tier] || 0;
                const mtProbeRank = _qRank[r.max_quality] || 0;
                if (r.tidal_track_id && mtProbeRank > mtLocalRank) {
                  const b = h('span', { className: 'upgrade-badge' }); b.textContent = '\u2B06 ' + qualityLabel(r.max_quality);
                  const mc = row.querySelector('.track-artist'); if (mc && mc.parentElement) mc.parentElement.appendChild(b);
                  allUpgradeable.push({ path: r.path, tidal_track_id: r.tidal_track_id });
                } else if (!r.tidal_track_id) {
                  const b = h('span', { className: 'upgrade-badge', style: { opacity: '0.5' } }); b.textContent = 'Not found';
                  const mc = row.querySelector('.track-artist'); if (mc && mc.parentElement) mc.parentElement.appendChild(b);
                }
              });
            }

            if (allUpgradeable.length === 0) {
              toast('No upgrades available on Tidal', 'success');
              upgradeBtn.textContent = 'No Upgrades Available';
            } else {
              upgradeBtn.textContent = 'Upgrade ' + allUpgradeable.length + ' Tracks';
              upgradeBtn.disabled = false;
              upgradeBtn.onclick = async () => {
                upgradeBtn.disabled = true;
                upgradeBtn.textContent = 'Upgrading...';
                try {
                  const resp = await api('/upgrade/start', {
                    method: 'POST',
                    body: { tracks: allUpgradeable.map(u => ({ path: u.path, tidal_track_id: u.tidal_track_id })) }
                  });
                  if (resp.count > 0) { updateDlBadge(resp.count); _ensureGlobalSSE(); }
                  toast('Upgrade started for ' + (resp.count || allUpgradeable.length) + ' tracks', 'success');
                } catch (err) {
                  toast('Upgrade failed', 'error');
                  upgradeBtn.disabled = false;
                }
              };
            }
          } catch (err) {
            toast('Upgrade check failed: ' + (err.message || err), 'error');
            upgradeBtn.textContent = 'Check for Upgrades';
            upgradeBtn.disabled = false;
          }
        });
      }

      // Show "Complete Album" — lazy Tidal lookup for missing tracks
      completeAlbumBtn.style.display = '';
      let _completeAlbumLoaded = false;
      completeAlbumBtn.addEventListener('click', async () => {
        if (_completeAlbumLoaded) return;

        completeAlbumBtn.disabled = true;
        completeAlbumBtn.textContent = 'Looking up on Tidal\u2026';

        try {
          const lookup = await api('/albums/lookup?artist=' + encodeURIComponent(artistName) + '&album=' + encodeURIComponent(albumName));
          _completeAlbumLoaded = true;

          const tidalTracks = lookup.tracks || [];
          const missingTracks = tidalTracks.filter(t => !t.is_local);

          if (missingTracks.length === 0) {
            completeAlbumBtn.textContent = 'Album is complete';
            completeAlbumBtn.disabled = true;
            toast('You already have every track from this album', 'success');
            return;
          }

          // Update button to show count
          completeAlbumBtn.textContent = '';
          const _caIcon2 = svgIcon(ICONS.download);
          _caIcon2.style.verticalAlign = '-2px';
          _caIcon2.style.marginRight = '4px';
          completeAlbumBtn.appendChild(_caIcon2);
          completeAlbumBtn.appendChild(document.createTextNode(
            'Download ' + missingTracks.length + ' Missing'
          ));
          completeAlbumBtn.disabled = false;

          // Replace the click handler to download all missing
          completeAlbumBtn.replaceWith(completeAlbumBtn.cloneNode(true));
          const dlAllBtn = wrapper.querySelector('.album-dl-btn');
          dlAllBtn.addEventListener('click', async () => {
            try {
              await apiTidal('/download', {
                method: 'POST',
                body: { track_ids: missingTracks.map(t => t.id) },
              });
              toast('Downloading ' + missingTracks.length + ' track' + (missingTracks.length !== 1 ? 's' : ''), 'success');
              updateDlBadge(missingTracks.length);
              _ensureGlobalSSE();
              dlAllBtn.disabled = true;
              dlAllBtn.textContent = 'Queued';
              // Hide the Tidal section — tracks are downloading
              const tidalEl = wrapper.querySelector('.tidal-missing-section');
              if (tidalEl) tidalEl.style.display = 'none';
            } catch (err) {
              toast('Download failed: ' + err.message, 'error');
            }
          });

          // Add "Available on Tidal" section below local tracks
          const tidalSection = h('div', { className: 'tidal-missing-section' });
          const tidalHeader = h('div', { className: 'tidal-missing-header' });
          tidalHeader.appendChild(textEl('span', 'Available on Tidal', 'tidal-missing-label'));
          tidalHeader.appendChild(textEl('span', missingTracks.length + ' track' + (missingTracks.length !== 1 ? 's' : '') + ' not in your library', 'tidal-missing-sub'));
          tidalSection.appendChild(tidalHeader);

          // Track header for Tidal section
          tidalSection.appendChild(renderTrackHeader());

          const tidalTrackList = h('div', { className: 'tracks' });

          // Show ALL tracks from the Tidal album — local ones marked, missing ones with download
          tidalTracks.forEach((t, i) => {
            tidalTrackList.appendChild(renderTrackRow(t, i + 1, tidalTracks));
          });

          tidalSection.appendChild(tidalTrackList);
          wrapper.appendChild(tidalSection);

        } catch (err) {
          completeAlbumBtn.disabled = false;
          completeAlbumBtn.textContent = '';
          const _caIcon3 = svgIcon(ICONS.download);
          _caIcon3.style.verticalAlign = '-2px';
          _caIcon3.style.marginRight = '4px';
          completeAlbumBtn.appendChild(_caIcon3);
          completeAlbumBtn.appendChild(document.createTextNode('Show on Tidal'));
          _completeAlbumLoaded = false;
          toast('Lookup failed: ' + err.message, 'error');
        }
      });
    }
  } catch (err) {
    while (trackList.firstChild) trackList.removeChild(trackList.firstChild);
    trackList.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load tracks', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

// ---- ALBUM DETAIL VIEW ----
function navigateAlbum(albumId) {
  navigate(buildAlbumView(albumId));
}

async function renderAlbumDetail(container, albumId) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  resultsArea.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    const data = await api('/albums/' + albumId + '/tracks');
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);

    const album = data.album || {};
    const tracks = data.tracks || [];

    // Album header
    const header = h('div', { className: 'album-header' });
    if (album.cover_url) {
      header.appendChild(h('img', {
        className: 'album-header-art',
        src: album.cover_url,
        alt: '',
      }));
    } else {
      header.appendChild(h('div', {
        className: 'album-header-art art-gradient',
        style: { background: artGradient(album.id) },
      }));
    }
    const headerMeta = h('div', { className: 'album-header-meta' });
    headerMeta.appendChild(textEl('div', album.name || 'Album', 'album-header-title'));
    headerMeta.appendChild(textEl('div', album.artist || '', 'album-header-artist'));
    headerMeta.appendChild(textEl('div', tracks.length + ' tracks', 'album-header-count'));

    // Play / Shuffle / Download Album pills
    const albumActions = h('div', { className: 'album-actions' });

    const playBtn = h('button', { className: 'pill active' });
    playBtn.textContent = '\u25B6  Play';
    playBtn.addEventListener('click', () => {
      const playable = tracks.filter(t => t.is_local);
      if (!playable.length) { toast('No local tracks to play', 'info'); return; }
      state.shuffle = false;
      btnShuffle.classList.remove('active');
      _setQueueOrder(playable, playable[0]);
      playTrack(state.queue[state.queueIndex]);
    });

    const shuffleBtn = h('button', { className: 'pill' });
    shuffleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>Shuffle';
    shuffleBtn.addEventListener('click', () => {
      const playable = tracks.filter(t => t.is_local);
      if (!playable.length) { toast('No local tracks to play', 'info'); return; }
      state.shuffle = true;
      btnShuffle.classList.add('active');
      _setQueueOrder(playable, playable[0]);
      playTrack(state.queue[state.queueIndex]);
    });

    const dlBtn = h('button', { className: 'pill' });
    dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download Album';
    dlBtn.addEventListener('click', async () => {
      const nonLocal = tracks.filter(t => !t.is_local && t.id);
      if (nonLocal.length === 0) {
        toast('Album already downloaded', 'info');
        return;
      }
      try {
        await apiTidal('/download', {
          method: 'POST',
          body: { track_ids: nonLocal.map(t => t.id) },
        });
        toast('Downloading ' + nonLocal.length + ' track' + (nonLocal.length !== 1 ? 's' : ''), 'success');
        updateDlBadge(nonLocal.length);
        _ensureGlobalSSE();
      } catch (err) {
        toast('Download failed: ' + err.message, 'error');
      }
    });

    albumActions.appendChild(playBtn);
    albumActions.appendChild(shuffleBtn);
    albumActions.appendChild(dlBtn);
    headerMeta.appendChild(albumActions);

    header.appendChild(headerMeta);
    resultsArea.appendChild(header);

    resultsArea.appendChild(renderTrackHeader());

    const trackList = h('div', { className: 'tracks' });
    tracks.forEach((track, i) => {
      trackList.appendChild(renderTrackRow(track, i + 1, tracks));
    });
    resultsArea.appendChild(trackList);
  } catch (err) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load album', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

// ---- DJAI VIEW (placeholder) ----
function renderDjai(container) {
  container.appendChild(h('div', { className: 'empty-state' },
    textEl('div', 'DJAI', 'empty-state-title'),
    textEl('div', 'Your AI DJ — picks music based on your mood. Bring your own API key.', 'empty-state-sub'),
    textEl('div', 'Coming soon.', 'empty-state-sub')
  ));
}

// ---- LIBRARY VIEW ----
let librarySort = 'artist';
let libraryQuery = '';
let libraryScanPoll = null;
const LIBRARY_PAGE_SIZE = 50;
const LIBRARY_RECENT_SHELF_LIMIT = 12;
const LIBRARY_ALBUM_BATCH_SIZE = 80;
let libraryOffset = 0;
let libraryTotal = 0;
let _libSearchTimer = null;
let _libRequestId = 0;
const _libraryAlbumCache = new Map();
const _failedAlbumArtUrls = new Set();

async function loadLibraryRecentAlbumsPage(limit, offset) {
  return api('/library/recent-albums?limit=' + limit + '&offset=' + offset);
}

async function _getLibraryAlbums(query) {
  const key = query || '';
  if (_libraryAlbumCache.has(key)) return _libraryAlbumCache.get(key);
  const data = await api('/library/albums' + (query ? '?q=' + encodeURIComponent(query) : ''));
  _libraryAlbumCache.set(key, data);
  return data;
}

function _renderAlbumCard(album) {
  const card = h('div', { className: 'album-card' });

  const artWrap = h('div', { className: 'album-card-art-wrap' });
  if (album.cover_url && !_failedAlbumArtUrls.has(album.cover_url)) {
    const img = h('img', { className: 'album-card-art', src: album.cover_url, alt: '', loading: 'lazy' });
    img.onerror = function() {
      _failedAlbumArtUrls.add(album.cover_url);
      this.style.display = 'none';
      artWrap.style.background = artGradient(album.name);
    };
    artWrap.appendChild(img);
  } else {
    artWrap.style.background = artGradient(album.name);
  }
  card.appendChild(artWrap);

  const meta = h('div', { className: 'album-card-meta' });
  meta.appendChild(textEl('div', album.name || 'Unknown Album', 'album-card-title'));
  const sub = [album.artist || 'Unknown'];
  sub.push(album.track_count + ' track' + (album.track_count !== 1 ? 's' : ''));
  meta.appendChild(textEl('div', sub.join(' · '), 'album-card-sub'));
  card.appendChild(meta);

  card.addEventListener('click', () => {
    navigate('localalbum:' + encodeURIComponent(album.artist) + ':' + encodeURIComponent(album.name));
  });
  a11yClick(card);
  return card;
}

function _renderAlbumCardsBatch(grid, albums, start, reqId) {
  if (reqId !== _libRequestId || !grid.isConnected) return;
  const end = Math.min(start + LIBRARY_ALBUM_BATCH_SIZE, albums.length);
  const fragment = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    fragment.appendChild(_renderAlbumCard(albums[i]));
  }
  grid.appendChild(fragment);
  if (end < albums.length) {
    requestAnimationFrame(() => _renderAlbumCardsBatch(grid, albums, end, reqId));
  }
}

function renderRecentAlbumCard(album) {
  const card = h('div', { className: 'album-card' });
  const artWrap = h('div', { className: 'album-card-art-wrap' });
  if (album.cover_url) {
    const img = h('img', { className: 'album-card-art', src: album.cover_url, alt: '', loading: 'lazy' });
    img.onerror = function() {
      this.style.display = 'none';
      artWrap.style.background = artGradient(album.name || album.artist);
    };
    artWrap.appendChild(img);
  } else {
    artWrap.style.background = artGradient(album.name || album.artist);
  }
  card.appendChild(artWrap);

  const meta = h('div', { className: 'album-card-meta' });
  meta.appendChild(textEl('div', album.name || 'Unknown Album', 'album-card-title'));
  const sub = [album.artist || 'Unknown Artist'];
  sub.push((album.track_count || 0) + ' track' + ((album.track_count || 0) !== 1 ? 's' : ''));
  meta.appendChild(textEl('div', sub.join(' · '), 'album-card-sub'));
  card.appendChild(meta);

  card.addEventListener('click', () => {
    navigate('localalbum:' + encodeURIComponent(album.artist || 'Unknown Artist') + ':' + encodeURIComponent(album.name || 'Unknown Album'));
  });
  a11yClick(card);
  return card;
}

function renderRecentAlbumCards(albums, existingGrid) {
  const grid = existingGrid || h('div', { className: 'album-gallery' });
  albums.forEach(album => grid.appendChild(renderRecentAlbumCard(album)));
  return grid;
}

function renderLibraryRecentShelfState(title, subtitle) {
  return h('div', { className: 'empty-state library-shelf-empty' },
    textEl('div', title, 'empty-state-title'),
    textEl('div', subtitle, 'empty-state-sub')
  );
}

async function loadLibraryRecentShelf(shelfArea) {
  while (shelfArea.firstChild) shelfArea.removeChild(shelfArea.firstChild);

  const heading = h('div', { className: 'library-shelf-heading' },
    textEl('div', 'Recently Added', 'results-title'),
    textEl('div', 'Latest albums from your library', 'results-count')
  );
  const header = h('div', { className: 'results-header library-shelf-header' }, heading);
  shelfArea.appendChild(header);

  const MAX_RETRIES = 3;
  const RETRY_DELAY = 1500; // ms — gives sidecar DB time to initialize on cold start
  let lastErr = null;

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const data = await loadLibraryRecentAlbumsPage(LIBRARY_RECENT_SHELF_LIMIT, 0);
      const albums = data.albums || [];

      if (albums.length === 0) {
        shelfArea.appendChild(renderLibraryRecentShelfState(
          'No recently added albums yet',
          'Download music or sync your library to populate this shelf.'
        ));
        return;
      }

      const seeAll = h('button', { className: 'library-shelf-action' }, 'See all');
      seeAll.addEventListener('click', () => navigate('recent-added'));
      header.appendChild(seeAll);

      const grid = renderRecentAlbumCards(albums);
      grid.classList.add('library-shelf-grid');
      shelfArea.appendChild(grid);
      return; // success
    } catch (err) {
      lastErr = err;
      if (attempt < MAX_RETRIES - 1) {
        await new Promise(r => setTimeout(r, RETRY_DELAY));
      }
    }
  }

  console.error('[shelf] Recently added failed after retries:', lastErr);
  shelfArea.appendChild(renderLibraryRecentShelfState(
    'Recently added unavailable',
    'Check your library connection and try again.'
  ));
}

function renderRecentAlbumRow(album) {
  const row = h('div', { className: 'recent-album-row' });

  // Small album art thumbnail
  const artWrap = h('div', { className: 'recent-album-art' });
  if (album.cover_url) {
    const img = h('img', { src: album.cover_url, alt: '', loading: 'lazy' });
    img.onerror = function() {
      this.style.display = 'none';
      artWrap.style.background = artGradient(album.name || album.artist);
    };
    artWrap.appendChild(img);
  } else {
    artWrap.style.background = artGradient(album.name || album.artist);
  }
  row.appendChild(artWrap);

  // Album name + artist · track count
  const meta = h('div', { className: 'recent-album-meta' });
  meta.appendChild(textEl('div', album.name || 'Unknown Album', 'recent-album-name'));
  const sub = [album.artist || 'Unknown Artist'];
  sub.push((album.track_count || 0) + ' track' + ((album.track_count || 0) !== 1 ? 's' : ''));
  meta.appendChild(textEl('div', sub.join(' \u00b7 '), 'recent-album-sub'));
  row.appendChild(meta);

  // Relative time (recent_at is epoch seconds)
  if (album.recent_at) {
    row.appendChild(textEl('div', _recentRelativeTime(album.recent_at * 1000), 'recent-album-time'));
  }

  // Source badge (download vs scan)
  if (album.recent_source === 'download') {
    row.appendChild(textEl('div', 'Downloaded', 'recent-album-source'));
  }

  row.addEventListener('click', () => {
    navigate('localalbum:' + encodeURIComponent(album.artist || 'Unknown Artist') + ':' + encodeURIComponent(album.name || 'Unknown Album'));
  });
  row.style.cursor = 'pointer';
  a11yClick(row);
  return row;
}

async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {
  try {
    const data = await loadLibraryRecentAlbumsPage(LIBRARY_PAGE_SIZE, libraryOffset);
    const albums = data.albums || [];
    libraryTotal = data.total || 0;

    if (!append) {
      while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
      resultsArea.appendChild(h('div', { className: 'results-header' },
        textEl('div', 'Recently Added', 'results-title'),
        textEl('div', libraryTotal + ' albums', 'results-count')
      ));

      if (albums.length === 0) {
        resultsArea.appendChild(h('div', { className: 'empty-state' },
          textEl('div', 'No recently added albums yet', 'empty-state-title'),
          textEl('div', 'Download music or sync your library to populate this view.', 'empty-state-sub')
        ));
        return 0;
      }

      const list = h('div', { className: 'recent-album-list', id: 'library-recent-albums' });
      // Time-group dividers like Recently Played
      let currentGroup = null;
      albums.forEach(album => {
        if (album.recent_at) {
          const group = _recentTimeGroup(album.recent_at * 1000);
          if (group !== currentGroup) {
            currentGroup = group;
            list.appendChild(textEl('div', group, 'recent-page-divider'));
          }
        }
        list.appendChild(renderRecentAlbumRow(album));
      });
      resultsArea.appendChild(list);
    } else {
      const list = document.getElementById('library-recent-albums') ||
        resultsArea.querySelector('.recent-album-list');
      let currentGroup = list.lastElementChild
        ? (list.lastElementChild.classList.contains('recent-page-divider')
          ? list.lastElementChild.textContent : null)
        : null;
      albums.forEach(album => {
        if (album.recent_at) {
          const group = _recentTimeGroup(album.recent_at * 1000);
          if (group !== currentGroup) {
            currentGroup = group;
            list.appendChild(textEl('div', group, 'recent-page-divider'));
          }
        }
        list.appendChild(renderRecentAlbumRow(album));
      });
    }

    const oldBtn = resultsArea.querySelector('.load-more');
    if (oldBtn) oldBtn.remove();

    if (libraryOffset + albums.length < libraryTotal) {
      const loadMore = h('button', {
        className: 'load-more pill active',
        onClick: () => {
          libraryOffset += LIBRARY_PAGE_SIZE;
          loadLibraryRecentAlbumsExpanded(resultsArea, true);
        },
      });
      loadMore.textContent = 'Load more (' +
        (libraryTotal - libraryOffset - albums.length) + ' remaining)';
      resultsArea.appendChild(loadMore);
    }

    return albums.length;
  } catch (err) {
    if (!append) {
      while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
      resultsArea.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'Could not load recently added albums', 'empty-state-title'),
        textEl('div', err.message || 'Check that your music folder is mounted and try again.', 'empty-state-sub')
      ));
    } else {
      toast('Could not load recently added albums', 'error');
    }
    return 0;
  }
}

function renderLibrary(container) {
  const recentAddedExpanded = state.view === 'recent-added';
  libraryOffset = 0;
  libraryQuery = '';
  const searchArea = h('div', { className: 'search-area' });

  const searchRow = h('div', { className: 'search-row' });
  const searchField = h('div', { className: 'search-field' });
  searchField.appendChild(svgIcon(ICONS.search));
  const libInput = h('input', {
    type: 'text', className: 'search-input',
    placeholder: recentAddedExpanded ? 'Recently added albums' : 'Search your library...', value: libraryQuery,
  });
  if (recentAddedExpanded) libInput.disabled = true;
  searchField.appendChild(libInput);
  searchRow.appendChild(searchField);
  searchArea.appendChild(searchRow);

  const resultsArea = h('div', { className: 'results' });
  const pills = h('div', { className: 'filter-pills' });
  const recentAddedPill = textEl('div', 'Recently Added', 'pill' + (recentAddedExpanded ? ' active' : ''));
  recentAddedPill.style.cursor = 'pointer';
  recentAddedPill.addEventListener('click', () => {
    if (state.view !== 'recent-added') navigate('recent-added');
  });
  a11yClick(recentAddedPill);
  pills.appendChild(recentAddedPill);

  for (const sort of ['artist', 'album', 'title', 'plays']) {
    const pill = textEl('div', sort.charAt(0).toUpperCase() + sort.slice(1),
      'pill' + (!recentAddedExpanded && librarySort === sort ? ' active' : ''));
    pill.style.cursor = 'pointer';
    pill.addEventListener('click', () => {
      librarySort = sort;
      libraryOffset = 0;
      if (recentAddedExpanded) {
        navigate('library');
        return;
      }
      pills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      if (sort === 'album') {
        loadLibraryAlbums(resultsArea, libraryQuery);
      } else if (sort === 'artist') {
        loadLibraryArtistGrouped(resultsArea, libraryQuery);
      } else {
        loadLibrary(resultsArea);
      }
    });
    a11yClick(pill);
    pills.appendChild(pill);
  }

  // Duplicates button
  const dupBtn = h('button', { className: 'pill dup-scan-btn' });
  dupBtn.textContent = 'Find Duplicates';
  dupBtn.addEventListener('click', () => _showDuplicatePreview(resultsArea));
  pills.appendChild(dupBtn);

  searchArea.appendChild(pills);
  container.appendChild(searchArea);

  let shelfArea = null;
  if (!recentAddedExpanded) {
    shelfArea = h('section', { className: 'library-shelf' });
    container.appendChild(shelfArea);
    loadLibraryRecentShelf(shelfArea);
  }

  container.appendChild(resultsArea);

  if (!recentAddedExpanded) {
    // Debounced search
    libInput.addEventListener('input', () => {
      clearTimeout(_libSearchTimer);
      _libSearchTimer = setTimeout(() => {
        libraryQuery = libInput.value.trim();
        libraryOffset = 0;
        shelfArea.style.display = libraryQuery ? 'none' : '';
        if (librarySort === 'album') {
          loadLibraryAlbums(resultsArea, libraryQuery);
        } else if (librarySort === 'artist') {
          loadLibraryArtistGrouped(resultsArea, libraryQuery);
        } else {
          loadLibrary(resultsArea);
        }
      }, 300);
    });

    // Load cached results — user clicks Sync Library to scan
    if (librarySort === 'album') {
      loadLibraryAlbums(resultsArea, '');
    } else if (librarySort === 'artist') {
      loadLibraryArtistGrouped(resultsArea, '');
    } else {
      loadLibrary(resultsArea, false);
    }
  } else {
    loadLibraryRecentAlbumsExpanded(resultsArea, false);
  }
}

async function _showDuplicatePreview(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  container.appendChild(textEl('div', 'Scanning for duplicates...', 'upgrade-scanner-status'));

  try {
    const data = await api('/duplicates/preview');
    while (container.firstChild) container.removeChild(container.firstChild);

    // Summary
    const summary = h('div', { className: 'dup-summary' });
    if (data.stale_count > 0) {
      summary.appendChild(textEl('div', data.stale_count + ' stale records pruned (files no longer on disk)', 'dup-stale-note'));
    }
    if (data.total_groups === 0) {
      summary.appendChild(textEl('div', 'No duplicates found \u2014 your library is clean!', 'upgrade-empty'));
      container.appendChild(summary);
      return;
    }
    summary.appendChild(textEl('div', 'Found ' + data.total_groups + ' duplicate groups (' + data.total_duplicates + ' extra copies)', 'dup-summary-text'));
    container.appendChild(summary);

    // Clean Up button
    const cleanBtn = h('button', { className: 'pill active dup-clean-btn' });
    cleanBtn.textContent = 'Clean Up ' + data.total_duplicates + ' Duplicates';
    container.appendChild(cleanBtn);

    // Group list
    const groupList = h('div', { className: 'dup-groups' });
    (data.groups || []).forEach(g => {
      const card = h('div', { className: 'dup-group-card' });
      // Keeper
      const keeperRow = h('div', { className: 'dup-keeper' });
      keeperRow.appendChild(textEl('span', '\u2713 KEEP', 'dup-keep-badge'));
      keeperRow.appendChild(textEl('span', (g.keeper.tier || '') + ' \u00B7 ' + (g.keeper.format || ''), 'dup-tier'));
      keeperRow.appendChild(textEl('span', g.keeper.path, 'dup-path'));
      card.appendChild(keeperRow);
      // Duplicates
      (g.duplicates || []).forEach(d => {
        const dupRow = h('div', { className: 'dup-duplicate' });
        dupRow.appendChild(textEl('span', '\u2717 REMOVE', 'dup-remove-badge'));
        dupRow.appendChild(textEl('span', (d.tier || '') + ' \u00B7 ' + (d.format || ''), 'dup-tier'));
        dupRow.appendChild(textEl('span', d.path, 'dup-path'));
        card.appendChild(dupRow);
      });
      groupList.appendChild(card);
    });
    container.appendChild(groupList);

    // Wire clean button
    cleanBtn.addEventListener('click', async () => {
      cleanBtn.disabled = true;
      cleanBtn.textContent = 'Cleaning...';
      try {
        const result = await api('/duplicates/clean', { method: 'POST' });
        cleanBtn.textContent = 'Cleaned ' + result.duplicates_moved + ' duplicates';
        toast('Removed ' + result.duplicates_moved + ' duplicates. Undo available for 5 minutes.', 'success', 8000);

        // Show undo button
        if (result.undo_available) {
          const undoBtn = h('button', { className: 'pill dup-undo-btn' });
          undoBtn.textContent = 'Undo Cleanup';
          undoBtn.addEventListener('click', async () => {
            undoBtn.disabled = true;
            undoBtn.textContent = 'Restoring...';
            try {
              const undoResult = await api('/duplicates/undo', { method: 'POST' });
              toast('Restored ' + undoResult.restored + ' files', 'success');
              undoBtn.textContent = 'Restored';
            } catch (err) {
              toast('Undo failed: ' + (err.message || err), 'error');
              undoBtn.disabled = false;
            }
          });
          cleanBtn.parentElement.insertBefore(undoBtn, cleanBtn.nextSibling);

          // Auto-hide undo after 5 minutes
          setTimeout(() => { undoBtn.remove(); }, 300000);
        }
      } catch (err) {
        toast('Cleanup failed: ' + (err.message || err), 'error');
        cleanBtn.disabled = false;
        cleanBtn.textContent = 'Retry Clean Up';
      }
    });
  } catch (err) {
    while (container.firstChild) container.removeChild(container.firstChild);
    if (err.message && err.message.includes('409')) {
      container.appendChild(textEl('div', 'A library scan is running \u2014 try again after it completes.', 'upgrade-empty'));
    } else {
      container.appendChild(textEl('div', 'Failed to scan for duplicates: ' + (err.message || err), 'upgrade-empty'));
    }
  }
}

function _navText(el) {
  // Find or create the text node inside a nav-item (preserving the SVG icon)
  for (const n of el.childNodes) {
    if (n.nodeType === Node.TEXT_NODE && n.textContent.trim()) return n;
  }
  const t = document.createTextNode('');
  el.appendChild(t);
  return t;
}

async function triggerScan(btn, resultsArea, rescan) {
  if (!btn) return;
  const textNode = _navText(btn);
  const origLabel = textNode.textContent;
  textNode.textContent = ' Scanning...';
  btn.classList.add('scanning');
  btn.style.pointerEvents = 'none';

  try {
    await api('/library/scan' + (rescan ? '?rescan=true' : ''), { method: 'POST' });
  } catch (_) { /* already running is fine */ }

  // Poll until done, refreshing results as they come in
  if (libraryScanPoll) clearInterval(libraryScanPoll);
  libraryScanPoll = setInterval(async () => {
    try {
      const status = await api('/library/scan/status');
      if (status.scanned > 0) {
        textNode.textContent = ' New: ' + status.scanned;
      } else if (status.total > 0) {
        textNode.textContent = ' Checking... ' + status.total.toLocaleString();
      } else {
        textNode.textContent = ' Scanning...';
      }
      if (status.done || !status.scanning) {
        clearInterval(libraryScanPoll);
        libraryScanPoll = null;
        textNode.textContent = origLabel;
        btn.classList.remove('scanning');
        btn.style.pointerEvents = '';
        libraryOffset = 0;
        _libraryAlbumCache.clear();
        _failedAlbumArtUrls.clear();
        await loadLibrary(resultsArea, false);
        toast('Library synced — ' + status.scanned + ' files indexed', 'success');
      }
    } catch (_) {
      clearInterval(libraryScanPoll);
      libraryScanPoll = null;
      textNode.textContent = origLabel;
      btn.classList.remove('scanning');
      btn.style.pointerEvents = '';
    }
  }, 2000);
}

async function loadLibrary(resultsArea, append) {
  const reqId = ++_libRequestId;
  try {
    const data = await api('/library?sort=' + librarySort +
      '&limit=' + LIBRARY_PAGE_SIZE + '&offset=' + libraryOffset +
      (libraryQuery ? '&q=' + encodeURIComponent(libraryQuery) : ''));
    if (reqId !== _libRequestId) return 0; // stale response, discard
    const tracks = data.tracks || [];
    libraryTotal = data.total || 0;

    if (!append) {
      while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);

      resultsArea.appendChild(h('div', { className: 'results-header' },
        textEl('div', 'Library', 'results-title'),
        textEl('div', libraryTotal + ' tracks', 'results-count')
      ));

      if (tracks.length === 0) {
        const emptyTitle = libraryQuery ? 'Nothing for "' + libraryQuery + '"' : 'No music here yet';
        const emptySub = libraryQuery ? 'Try different words or check the spelling.' : 'Hit Sync Library in the sidebar to bring in your collection.';
        resultsArea.appendChild(h('div', { className: 'empty-state' },
          svgIcon(ICONS.music),
          textEl('div', emptyTitle, 'empty-state-title'),
          textEl('div', emptySub, 'empty-state-sub')
        ));
        return 0;
      }

      resultsArea.appendChild(renderTrackHeader());

      const trackList = h('div', { className: 'tracks', id: 'library-tracks' });
      resultsArea.appendChild(trackList);
    }

    const trackList = document.getElementById('library-tracks') ||
      resultsArea.querySelector('.tracks');

    // Check if all tracks are local — hide redundant "local" tags
    const allLocal = tracks.every(t => t.is_local);
    if (allLocal) trackList.classList.add('all-local');
    else trackList.classList.remove('all-local');

    tracks.forEach((track, i) => {
      track.local_path = track.path;
      trackList.appendChild(renderTrackRow(track, libraryOffset + i + 1, tracks));
    });

    // Remove old load-more button
    const oldBtn = resultsArea.querySelector('.load-more');
    if (oldBtn) oldBtn.remove();

    // Show load-more if there are more tracks
    if (libraryOffset + tracks.length < libraryTotal) {
      const loadMore = h('button', {
        className: 'load-more pill active',
        onClick: () => {
          libraryOffset += LIBRARY_PAGE_SIZE;
          loadLibrary(resultsArea, true);
        },
      });
      loadMore.textContent = 'Load more (' +
        (libraryTotal - libraryOffset - tracks.length) + ' remaining)';
      resultsArea.appendChild(loadMore);
    }

    return tracks.length;
  } catch (err) {
    if (!append) {
      while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
      resultsArea.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'Can\'t reach your library', 'empty-state-title'),
        textEl('div', 'Check that your music folder is mounted and try again.', 'empty-state-sub')
      ));
    }
    return 0;
  }
}

async function loadLibraryAlbums(resultsArea, query) {
  const reqId = ++_libRequestId;
  while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
  if (!_libraryAlbumCache.has(query || '')) {
    resultsArea.appendChild(h('div', { className: 'skeleton-row' }));
  }

  try {
    const data = await _getLibraryAlbums(query);
    if (reqId !== _libRequestId) return;
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);

    resultsArea.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Albums', 'results-title'),
      textEl('div', data.total + ' albums', 'results-count')
    ));

    if (!data.albums || data.albums.length === 0) {
      resultsArea.appendChild(h('div', { className: 'empty-state' },
        textEl('div', query ? 'No albums match "' + query + '"' : 'No albums yet', 'empty-state-title'),
        textEl('div', 'Sync your library to populate albums.', 'empty-state-sub')
      ));
      return;
    }

    const grid = h('div', { className: 'album-gallery' });
    resultsArea.appendChild(grid);
    _renderAlbumCardsBatch(grid, data.albums, 0, reqId);
  } catch (err) {
    if (reqId !== _libRequestId) return;
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load albums', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

async function loadLibraryArtistGrouped(resultsArea, query) {
  const reqId = ++_libRequestId;
  while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
  resultsArea.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    // Keep first paint page-sized; rendering many track rows synchronously makes navigation feel stuck.
    const data = await api('/library?sort=artist&limit=' + LIBRARY_PAGE_SIZE + '&offset=0' +
      (query ? '&q=' + encodeURIComponent(query) : ''));
    if (reqId !== _libRequestId) return;
    const tracks = data.tracks || [];

    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);

    resultsArea.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Artists', 'results-title'),
      textEl('div', (data.total || 0) + ' tracks', 'results-count')
    ));

    if (tracks.length === 0) {
      const emptyTitle = query ? 'Nothing for \u201c' + query + '\u201d' : 'No music here yet';
      const emptySub = query ? 'Try different words or check the spelling.' : 'Hit Sync Library in the sidebar to bring in your collection.';
      resultsArea.appendChild(h('div', { className: 'empty-state' },
        svgIcon(ICONS.music),
        textEl('div', emptyTitle, 'empty-state-title'),
        textEl('div', emptySub, 'empty-state-sub')
      ));
      return;
    }

    // Group tracks by artist
    const groups = [];
    let currentArtist = null;
    let currentGroup = null;
    tracks.forEach(t => {
      t.local_path = t.path;
      const artist = t.artist || 'Unknown Artist';
      if (artist !== currentArtist) {
        currentArtist = artist;
        currentGroup = { artist: artist, tracks: [] };
        groups.push(currentGroup);
      }
      currentGroup.tracks.push(t);
    });

    // Sort tracks within each group by album, then track number
    groups.forEach(g => {
      g.tracks.sort((a, b) => {
        const albumCmp = (a.album || '').localeCompare(b.album || '');
        if (albumCmp !== 0) return albumCmp;
        return (a.track_number || 0) - (b.track_number || 0);
      });
    });

    // Update header with artist count
    const countEl = resultsArea.querySelector('.results-count');
    if (countEl) countEl.textContent = groups.length + ' artists \u00b7 ' + (data.total || 0) + ' tracks';

    // Check if all tracks are local
    const allLocal = tracks.every(t => t.is_local);

    const wrapper = h('div', { className: 'library-artist-groups' + (allLocal ? ' all-local' : '') });

    let globalNum = 0;
    groups.forEach(g => {
      // Artist header
      const header = h('div', { className: 'artist-group-header' },
        textEl('div', g.artist, 'artist-group-name'),
        textEl('div', g.tracks.length + ' track' + (g.tracks.length !== 1 ? 's' : ''), 'artist-group-count')
      );
      wrapper.appendChild(header);

      // Track list for this group
      const trackList = h('div', { className: 'tracks' + (allLocal ? ' all-local' : '') });
      g.tracks.forEach(t => {
        globalNum++;
        trackList.appendChild(renderTrackRow(t, globalNum, tracks));
      });
      wrapper.appendChild(trackList);
    });

    resultsArea.appendChild(wrapper);

    // If there are more tracks beyond what we fetched, show load-more
    if (tracks.length < (data.total || 0)) {
      const loadMore = h('button', {
        className: 'load-more pill active',
      });
      loadMore.textContent = 'Load more (' + ((data.total || 0) - tracks.length) + ' remaining)';
      loadMore.addEventListener('click', async () => {
        // Fall back to flat list for remaining tracks
        libraryOffset = tracks.length;
        loadMore.remove();
        loadLibrary(resultsArea, true);
      });
      resultsArea.appendChild(loadMore);
    }
  } catch (err) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load library', 'empty-state-title'),
      textEl('div', typeof err === 'string' ? err : (err.message || 'Something went wrong'), 'empty-state-sub')
    ));
  }
}

// ---- RECENTLY PLAYED VIEW ----
function _recentRelativeTime(ts) {
  if (typeof ts !== 'number' || isNaN(ts)) return '';
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  if (days === 1) return 'Yesterday';
  if (days < 7) return days + 'd ago';
  return Math.floor(days / 7) + 'w ago';
}

function _recentTimeGroup(ts) {
  if (typeof ts !== 'number' || isNaN(ts)) return 'Earlier';
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterdayStart = todayStart - 86400000;
  const weekStart = todayStart - 6 * 86400000;
  if (ts >= todayStart) return 'Today';
  if (ts >= yesterdayStart) return 'Yesterday';
  if (ts >= weekStart) return 'This Week';
  return 'Earlier';
}

function _recentRemoveIcon() {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  l1.setAttribute('x1', '18'); l1.setAttribute('y1', '6');
  l1.setAttribute('x2', '6'); l1.setAttribute('y2', '18');
  const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  l2.setAttribute('x1', '6'); l2.setAttribute('y1', '6');
  l2.setAttribute('x2', '18'); l2.setAttribute('y2', '18');
  svg.appendChild(l1);
  svg.appendChild(l2);
  return svg;
}

function _removeRecentEntry(track) {
  const idx = recentlyPlayed.findIndex(t => _trackKey(t) === _trackKey(track));
  if (idx !== -1) recentlyPlayed.splice(idx, 1);
  _saveRecent();
  navigate('recent');
}

function _clearRecentHistory() {
  recentlyPlayed.length = 0;
  _saveRecent();
  navigate('recent');
}

function _selectedRecentFilter() {
  try {
    const saved = localStorage.getItem('recentPlayedFilter');
    return ['all', 'today', 'week', 'older'].includes(saved) ? saved : 'all';
  } catch (_) {
    return 'all';
  }
}

function _recentFilterKey(playedAt) {
  const ts = Number(playedAt || 0);
  if (!ts) return 'older';
  const age = Date.now() - ts;
  if (age < 24 * 60 * 60 * 1000) return 'today';
  if (age < 7 * 24 * 60 * 60 * 1000) return 'week';
  return 'older';
}

function _filterRecentTracks(filter) {
  if (filter === 'all') return recentlyPlayed.slice();
  return recentlyPlayed.filter(track => _recentFilterKey(track.played_at) === filter);
}

function _recentFilterCounts() {
  const counts = { all: recentlyPlayed.length, today: 0, week: 0, older: 0 };
  recentlyPlayed.forEach(track => { counts[_recentFilterKey(track.played_at)]++; });
  return counts;
}

function _setRecentFilter(filter) {
  try { localStorage.setItem('recentPlayedFilter', filter); } catch (_) {}
  navigate('recent');
}

function _clearRecentOlderThan30Days() {
  const cutoff = Date.now() - (30 * 24 * 60 * 60 * 1000);
  for (let i = recentlyPlayed.length - 1; i >= 0; i--) {
    if (Number(recentlyPlayed[i].played_at || 0) < cutoff) recentlyPlayed.splice(i, 1);
  }
  _saveRecent();
  navigate('recent');
}

function renderRecentlyPlayed(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);
  const activeFilter = _selectedRecentFilter();
  const filteredRecent = _filterRecentTracks(activeFilter);
  const counts = _recentFilterCounts();

  const headerRow = h('div', { className: 'results-header' },
    textEl('div', 'Recently Played', 'results-title'),
    textEl('div', filteredRecent.length + ' tracks', 'results-count')
  );
  if (recentlyPlayed.length > 0) {
    const clearOldBtn = h('button', { className: 'recent-page-clear-btn' }, 'Clear older than 30 days');
    clearOldBtn.addEventListener('click', () => _clearRecentOlderThan30Days());
    headerRow.appendChild(clearOldBtn);
    const clearBtn = h('button', { className: 'recent-page-clear-btn', 'data-confirm': 'false' }, 'Clear history');
    clearBtn.addEventListener('click', () => {
      if (clearBtn.dataset.confirm !== 'true') {
        clearBtn.dataset.confirm = 'true';
        clearBtn.textContent = 'Click again to clear';
        setTimeout(() => {
          clearBtn.dataset.confirm = 'false';
          clearBtn.textContent = 'Clear history';
        }, 3000);
        return;
      }
      _clearRecentHistory();
    });
    headerRow.appendChild(clearBtn);
  }
  resultsArea.appendChild(headerRow);

  const filters = h('div', { className: 'recent-filter-pills' });
  [
    ['all', 'All'],
    ['today', 'Today'],
    ['week', 'This Week'],
    ['older', 'Older'],
  ].forEach(([key, label]) => {
    const pill = h('button', { className: 'recent-filter-pill' + (activeFilter === key ? ' active' : '') });
    pill.textContent = label + ' (' + counts[key] + ')';
    pill.addEventListener('click', () => _setRecentFilter(key));
    filters.appendChild(pill);
  });
  resultsArea.appendChild(filters);

  if (recentlyPlayed.length === 0) {
    const browseBtn = h('button', { className: 'recent-page-browse-btn' }, 'Browse your library');
    browseBtn.addEventListener('click', () => navigate('library'));
    a11yClick(browseBtn);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      svgIcon(ICONS.music),
      textEl('div', 'Nothing played yet', 'empty-state-title'),
      textEl('div', 'Tracks you play will show up here.', 'empty-state-sub'),
      browseBtn
    ));
    return;
  }

  if (filteredRecent.length === 0) {
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      svgIcon(ICONS.music),
      textEl('div', 'No tracks in this filter', 'empty-state-title'),
      textEl('div', 'Change filters or play more music.', 'empty-state-sub')
    ));
    return;
  }

  const trackList = h('div', { className: 'tracks' });
  let currentGroup = null;
  let num = 0;
  filteredRecent.forEach((track, i) => {
    // Group dividers
    const group = _recentTimeGroup(track.played_at);
    if (group !== currentGroup) {
      currentGroup = group;
      trackList.appendChild(textEl('div', group, 'recent-page-divider'));
    }

    num++;
    const row = renderTrackRow(track, num, filteredRecent);

    // Wrap the row to overlay timestamp and remove button without altering grid columns
    const wrapper = h('div', { className: 'recent-page-row' });
    wrapper.appendChild(row);

    // Relative timestamp overlay
    const timeAgo = textEl('span', _recentRelativeTime(track.played_at), 'recent-page-time');
    wrapper.appendChild(timeAgo);

    // Remove button overlay (visible on hover, same pattern as download button)
    const removeBtn = h('button', { className: 'recent-page-remove-btn', title: 'Remove from history', 'aria-label': 'Remove' });
    removeBtn.appendChild(_recentRemoveIcon());
    const capturedTrack = track;
    removeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _removeRecentEntry(capturedTrack);
    });
    wrapper.appendChild(removeBtn);

    trackList.appendChild(wrapper);
  });
  resultsArea.appendChild(trackList);
}

// ---- PLAYLISTS VIEW ----
function renderPlaylists(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);
  loadPlaylists(resultsArea);
}

async function loadPlaylists(resultsArea) {
  renderSearchSkeleton(resultsArea);
  try {
    const data = await api('/playlists');
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    const playlists = data.playlists || [];

    resultsArea.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Playlists', 'results-title'),
      textEl('div', playlists.length + ' playlists', 'results-count')
    ));

    if (playlists.length === 0) {
      resultsArea.appendChild(h('div', { className: 'empty-state' },
        svgIcon(ICONS.music),
        textEl('div', 'No playlists yet', 'empty-state-title'),
        textEl('div', 'Sign in to Tidal to pull in your playlists.', 'empty-state-sub')
      ));
      return;
    }

    const grid = h('div', { className: 'album-gallery' });
    playlists.forEach(pl => {
      const card = h('div', { className: 'album-card' });

      const artWrap = h('div', { className: 'album-card-art-wrap' });
      if (pl.cover_url) {
        const img = h('img', { className: 'album-card-art', src: pl.cover_url, loading: 'lazy', alt: '' });
        img.onerror = function() { this.style.display = 'none'; artWrap.style.background = artGradient(pl.id || pl.name); };
        artWrap.appendChild(img);
      } else {
        artWrap.style.background = artGradient(pl.id || pl.name);
      }
      card.appendChild(artWrap);

      const meta = h('div', { className: 'album-card-meta' });
      meta.appendChild(textEl('div', pl.name || '', 'album-card-title'));
      meta.appendChild(textEl('div', (pl.num_tracks || 0) + ' tracks', 'album-card-sub'));
      card.appendChild(meta);

      card.addEventListener('click', () => loadPlaylistTracks(resultsArea, pl));
      a11yClick(card);
      grid.appendChild(card);
    });
    resultsArea.appendChild(grid);
  } catch (err) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Failed to load playlists', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

async function loadPlaylistTracks(resultsArea, pl) {
  while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
  resultsArea.className = 'album-detail-view';

  // Breadcrumb
  resultsArea.appendChild(breadcrumb([
    { label: 'Playlists', view: 'playlists' },
    { label: pl.name || 'Playlist' },
  ]));

  // Playlist header — art + meta + action pills
  const plHeader = h('div', { className: 'album-detail-header' });
  const artWrap = h('div', { className: 'album-detail-art-wrap' });
  if (pl.cover_url) {
    const img = h('img', { className: 'album-detail-art', src: pl.cover_url, alt: '' });
    img.onerror = function() { this.style.display = 'none'; artWrap.style.background = artGradient(pl.id); };
    artWrap.appendChild(img);
  } else {
    artWrap.style.background = artGradient(pl.id || pl.name);
  }
  plHeader.appendChild(artWrap);

  const plMeta = h('div', { className: 'album-detail-meta' });
  plMeta.appendChild(textEl('div', pl.name || 'Playlist', 'album-detail-title'));
  plMeta.appendChild(textEl('div', (pl.num_tracks || 0) + ' tracks', 'album-detail-sub'));

  // Action pills: Play, Shuffle, Download Missing
  const actions = h('div', { className: 'album-actions' });

  const playBtn = h('button', { className: 'pill active album-play-btn' });
  playBtn.textContent = '\u25B6  Play ' + (pl.name || 'Playlist');
  playBtn.disabled = true;

  const shuffleBtn = h('button', { className: 'pill album-shuffle-btn' });
  shuffleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>Shuffle';
  shuffleBtn.disabled = true;

  const dlBtn = h('button', { className: 'pill album-dl-btn' });
  dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download Missing';

  const upgradeBtn = h('button', { className: 'pill album-upgrade-btn' });
  upgradeBtn.textContent = 'Checking upgrades...';
  upgradeBtn.style.display = 'none';
  upgradeBtn.disabled = true;

  const refreshUpgradeBtn = h('button', {
    className: 'pill pill-sm album-upgrade-refresh-btn',
    title: 'Refresh upgrade availability',
    'aria-label': 'Refresh upgrade availability'
  });
  refreshUpgradeBtn.textContent = '↻';
  refreshUpgradeBtn.style.display = 'none';
  refreshUpgradeBtn.disabled = true;

  actions.appendChild(playBtn);
  actions.appendChild(shuffleBtn);
  actions.appendChild(dlBtn);
  actions.appendChild(upgradeBtn);
  actions.appendChild(refreshUpgradeBtn);
  plMeta.appendChild(actions);
  plHeader.appendChild(plMeta);
  resultsArea.appendChild(plHeader);

  // Track header
  resultsArea.appendChild(renderTrackHeader());

  const trackList = h('div', { className: 'tracks' });
  resultsArea.appendChild(trackList);
  trackList.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    const data = await api('/playlists/' + encodeURIComponent(pl.id) + '/tracks');
    while (trackList.firstChild) trackList.removeChild(trackList.firstChild);
    const tracks = data.tracks || [];

    tracks.forEach((track, i) => {
      trackList.appendChild(renderTrackRow(track, i + 1, tracks));
    });

    // Wire action buttons
    if (tracks.length) {
      playBtn.disabled = false;
      shuffleBtn.disabled = false;
      playBtn.addEventListener('click', () => {
        state.shuffle = false;
        btnShuffle.classList.remove('active');
        _setQueueOrder(tracks, tracks[0]);
        playTrack(state.queue[state.queueIndex]);
      });
      shuffleBtn.addEventListener('click', () => {
        state.shuffle = true;
        btnShuffle.classList.add('active');
        _setQueueOrder(tracks, tracks[0]);
        playTrack(state.queue[state.queueIndex]);
      });
    }

    // Download Missing — hide if all tracks are local
    const missingCount = tracks.filter(t => !t.is_local).length;
    if (missingCount === 0) {
      dlBtn.style.display = 'none';
    } else {
      dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download ' + missingCount + ' Missing';
      dlBtn.addEventListener('click', async () => {
        dlBtn.textContent = 'Syncing...';
        dlBtn.style.pointerEvents = 'none';
        try {
          const result = await api('/playlists/' + encodeURIComponent(pl.id) + '/sync', { method: 'POST' });
          if (result.status === 'up_to_date') {
            toast('All tracks are already local', 'success');
            dlBtn.style.display = 'none';
          } else {
            toast('Downloading ' + result.missing + ' missing tracks', 'success');
            updateDlBadge(result.missing);
            _ensureGlobalSSE();
            dlBtn.textContent = 'Queued';
            dlBtn.disabled = true;
          }
        } catch (err) {
          toast('Sync failed: ' + err.message, 'error');
          dlBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download ' + missingCount + ' Missing';
          dlBtn.style.pointerEvents = '';
        }
      });
    }

    _scanPlaylistUpgrades(tracks, trackList, upgradeBtn, refreshUpgradeBtn);

    // Update track count
    plMeta.querySelector('.album-detail-sub').textContent = tracks.length + ' tracks';
  } catch (err) {
    while (trackList.firstChild) trackList.removeChild(trackList.firstChild);
    trackList.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Failed to load tracks', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

// ---- DOWNLOAD TRIGGER ----
const _downloading = new Set();
const _dlCallbacks = {};  // track_id → { btn }

async function downloadTrack(track, btn) {
  if (_downloading.has(track.id)) return;
  _downloading.add(track.id);

  btn.disabled = true;
  btn.classList.add('downloading');

  try {
    await apiTidal('/download', {
      method: 'POST',
      body: { track_ids: [track.id] },
    });
    toast((track.name || 'Track') + ' queued', 'success');
    updateDlBadge(1);
    _dlCallbacks[track.id] = { btn };
    _ensureGlobalSSE();
  } catch (err) {
    toast('Download failed: ' + err.message, 'error');
    btn.disabled = false;
    btn.classList.remove('downloading');
    _downloading.delete(track.id);
  }
}

function _dlComplete(trackId, success) {
  const cb = _dlCallbacks[trackId];
  if (cb) {
    cb.btn.classList.remove('downloading');
    if (success) {
      while (cb.btn.firstChild) cb.btn.removeChild(cb.btn.firstChild);
      cb.btn.appendChild(svgIcon(ICONS.check));
      cb.btn.classList.add('done');
    } else {
      cb.btn.disabled = false;
    }
    delete _dlCallbacks[trackId];
  }
  _downloading.delete(trackId);
  updateDlBadge(-1);
}

// Global SSE for download progress (shared across views)
let _globalSSE = null;
function _ensureGlobalSSE() {
  if (_globalSSE) return;
  _globalSSE = new EventSource('/api/downloads/active');
  _globalSSE.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'ping') return;
      if (data.type === 'batch_queued') {
        updateDlBadge(data.count || 0);
        const activeEl = document.getElementById('dl-active');
        if (activeEl) {
          const emptyEl = activeEl.querySelector('.dl-empty');
          if (emptyEl) emptyEl.remove();
          // Show a single summary card instead of 1600 individual cards
          let summary = activeEl.querySelector('.dl-batch-summary');
          if (!summary) {
            summary = h('div', { className: 'dl-card dl-batch-summary' });
            activeEl.prepend(summary);
          }
          while (summary.firstChild) summary.removeChild(summary.firstChild);
          summary.appendChild(textEl('div', (data.count || 0) + ' tracks queued', 'dl-card-name'));
          summary.appendChild(textEl('div', 'Waiting to start...', 'dl-card-status dl-status-queued'));
        }
        return;
      }
      if (data.type === 'complete') _dlComplete(data.track_id, true);
      else if (data.type === 'error') {
        toast('Download failed: ' + (data.error || 'unknown'), 'error');
        _dlComplete(data.track_id, false);
      }
      else if (data.type === 'cancelled') {
        _dlComplete(data.track_id, false);
      }
      // Queue control events
      else if (data.type === 'queue_paused') {
        _setQueuePaused(true);
      } else if (data.type === 'queue_resumed') {
        _setQueuePaused(false);
      } else if (data.type === 'queue_cancelled') {
        _setQueuePaused(false);
        const activeEl = document.getElementById('dl-active');
        if (activeEl) {
          while (activeEl.firstChild) activeEl.removeChild(activeEl.firstChild);
          _showActiveEmpty(activeEl);
        }
        _scheduleHistoryReload();
      }
      // Upgrade events — update badge and inline scanner rows
      else if (data.type === 'upgrade_complete') {
        updateDlBadge(-1);
        _updateUpgradeRow(data.old_path, 'done', data.name);
      } else if (data.type === 'upgrade_error') {
        updateDlBadge(-1);
        _updateUpgradeRow(data.old_path, 'error', data.error);
      } else if (data.type === 'upgrade_progress') {
        _updateUpgradeRow(data.old_path, 'upgrading', data.name);
      }
      // Also update the downloads view if visible (only for standard download events)
      if (data.type === 'progress' || data.type === 'complete' || data.type === 'error') {
        const activeEl = document.getElementById('dl-active');
        if (activeEl) updateActiveDownload(activeEl, data);
      }
    } catch (_) {}
  };
  _globalSSE.onerror = () => {
    _globalSSE.close();
    _globalSSE = null;
    // Reconnect if there are pending downloads
    if (Object.keys(_dlCallbacks).length > 0) {
      setTimeout(_ensureGlobalSSE, 3000);
    }
  };
}

function updateDlBadge(delta) {
  const badge = document.getElementById('dl-badge');
  if (!badge) return;
  let count = parseInt(badge.textContent || '0', 10) + delta;
  if (count < 0) count = 0;
  badge.textContent = count;
  badge.style.display = count > 0 ? '' : 'none';
}

function _updateUpgradeRow(oldPath, status, detail) {
  if (!oldPath) return;
  const row = document.querySelector('.upgrade-row[data-track-path="' + CSS.escape(oldPath) + '"]');
  if (!row) return;
  const btn = row.querySelector('button');
  if (!btn) return;
  if (status === 'upgrading') {
    btn.disabled = true;
    btn.textContent = 'Downloading\u2026';
  } else if (status === 'done') {
    btn.disabled = true;
    btn.textContent = 'Done';
    btn.classList.add('done');
    row.style.opacity = '0.5';
  } else if (status === 'error') {
    btn.disabled = false;
    btn.textContent = 'Retry';
    btn.classList.add('error');
  }
}

// ---- FAVORITES VIEW ----
async function renderFavorites(container) {
  container.appendChild(breadcrumb([{ label: 'Favorites' }]));

  const title = textEl('h1', 'Favorites', 'view-title');
  container.appendChild(title);

  const subtitle = h('div', { className: 'view-subtitle', id: 'fav-subtitle' });
  container.appendChild(subtitle);

  const pills = h('div', { className: 'filter-pills' });
  ['All', 'Downloaded', 'Pending'].forEach(label => {
    const pill = textEl('button', label, 'pill' + (label === 'All' ? ' active' : ''));
    pill.addEventListener('click', () => {
      pills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      loadFavorites(listArea, label.toLowerCase());
    });
    pills.appendChild(pill);
  });
  container.appendChild(pills);

  const listArea = h('div', { className: 'favorites-list' });
  container.appendChild(listArea);
  loadFavorites(listArea, 'all');
}

async function loadFavorites(container, filter) {
  while (container.firstChild) container.removeChild(container.firstChild);

  try {
    const data = await api('/library/favorites');
    let favs = data.favorites || [];

    // Update subtitle with track count + total listening time
    const subtitleEl = document.getElementById('fav-subtitle');
    if (subtitleEl) {
      const totalDur = data.total_duration || 0;
      const parts = [];
      parts.push(favs.length + (favs.length === 1 ? ' track' : ' tracks'));
      if (totalDur > 0) {
        const hrs = Math.floor(totalDur / 3600);
        const mins = Math.floor((totalDur % 3600) / 60);
        if (hrs > 0) parts.push(hrs + 'h ' + mins + 'm');
        else parts.push(mins + ' min');
      }
      subtitleEl.textContent = parts.join(' \u00b7 ');
    }

    if (filter === 'downloaded') {
      favs = favs.filter(f => f.is_local);
    } else if (filter === 'pending') {
      favs = favs.filter(f => !f.is_local && f.tidal_id);
    }

    if (favs.length === 0) {
      const empty = h('div', { className: 'empty-state' });
      empty.appendChild(textEl('div', filter === 'all' ? 'No favorites yet' : 'None in this category', 'empty-state-title'));
      empty.appendChild(textEl('div', 'Heart tracks to save them here', 'empty-state-sub'));
      container.appendChild(empty);
      return;
    }

    container.appendChild(renderTrackHeader());

    const trackList = favs.map(f => ({
      path: f.path,
      id: f.tidal_id,
      name: f.name,
      artist: f.artist,
      album: f.album,
      cover_url: f.cover_url,
      quality: f.quality || null,
      duration: f.duration || 0,
      is_local: f.is_local,
      isrc: f.isrc,
    }));

    // Pre-load fav cache so hearts show as filled
    await loadFavCache(trackList);

    trackList.forEach((track, i) => {
      const row = renderTrackRow(track, i + 1, trackList);
      if (!track.is_local) {
        row.style.opacity = '0.6';
      }
      container.appendChild(row);
    });
  } catch (err) {
    container.appendChild(textEl('div', 'Failed to load favorites', 'error-text'));
  }
}

// ---- DOWNLOADS VIEW ----

function _dlArtThumb(coverUrl, trackId) {
  const wrap = h('div', { className: 'dl-card-art' });
  if (coverUrl) {
    wrap.appendChild(h('img', { src: coverUrl, loading: 'lazy', alt: '', className: 'dl-card-art-img' }));
  } else {
    const grad = h('div', { className: 'dl-card-art-grad' });
    grad.style.background = artGradient(trackId);
    wrap.appendChild(grad);
  }
  return wrap;
}

function _setQueuePaused(paused) {
  const pauseBtn = document.getElementById('dl-pause-btn');
  const resumeBtn = document.getElementById('dl-resume-btn');
  if (pauseBtn) pauseBtn.style.display = paused ? 'none' : '';
  if (resumeBtn) resumeBtn.style.display = paused ? '' : 'none';
  // Update batch summary text if visible
  const summary = document.querySelector('.dl-batch-summary');
  if (summary) {
    const statusEl = summary.querySelector('.dl-card-status');
    if (statusEl) statusEl.textContent = paused ? 'Paused' : 'Waiting to start...';
  }
}

function _timeAgo(ts) {
  if (!ts) return '';
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
  return new Date(ts * 1000).toLocaleDateString();
}

function renderDownloads(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  resultsArea.appendChild(h('div', { className: 'results-header' },
    textEl('div', 'Downloads', 'results-title')
  ));

  // Active section header with queue controls
  const activeHeader = h('div', { className: 'dl-active-header' });
  activeHeader.appendChild(textEl('div', 'Active', 'dl-section-label'));

  const queueControls = h('div', { id: 'dl-queue-controls', className: 'dl-queue-controls' });

  const pauseBtn = h('button', { className: 'dl-ctrl-btn', id: 'dl-pause-btn' });
  pauseBtn.textContent = 'Pause';
  pauseBtn.onclick = async () => {
    pauseBtn.disabled = true;
    try {
      await api('/downloads/pause', { method: 'POST' });
    } catch (_) { toast('Failed to pause', 'error'); }
    pauseBtn.disabled = false;
  };

  const resumeBtn = h('button', { className: 'dl-ctrl-btn', id: 'dl-resume-btn' });
  resumeBtn.textContent = 'Resume';
  resumeBtn.style.display = 'none';
  resumeBtn.onclick = async () => {
    resumeBtn.disabled = true;
    try {
      await api('/downloads/resume', { method: 'POST' });
    } catch (_) { toast('Failed to resume', 'error'); }
    resumeBtn.disabled = false;
  };

  const cancelBtn = h('button', { className: 'dl-ctrl-btn dl-ctrl-cancel' });
  cancelBtn.textContent = 'Cancel All';
  cancelBtn.onclick = () => {
    inlineConfirm('Cancel all remaining downloads?', async () => {
      try {
        await api('/downloads/cancel', { method: 'POST' });
        toast('Downloads cancelled', 'success');
      } catch (_) { toast('Failed to cancel', 'error'); }
    });
  };

  queueControls.appendChild(pauseBtn);
  queueControls.appendChild(resumeBtn);
  queueControls.appendChild(cancelBtn);
  activeHeader.appendChild(queueControls);
  resultsArea.appendChild(activeHeader);

  const activeSection = h('div', { id: 'dl-active', className: 'dl-card-list' });
  resultsArea.appendChild(activeSection);

  // Spacer
  resultsArea.appendChild(h('div', { style: { height: '32px' } }));

  // History section header with clear buttons
  const historyHeader = h('div', { className: 'dl-history-header' });
  historyHeader.appendChild(textEl('div', 'History', 'dl-section-label'));
  const clearBtns = h('div', { className: 'dl-clear-btns' });
  ['Failed', 'Done', 'All'].forEach(label => {
    const btn = h('button', { className: 'dl-clear-btn' });
    btn.textContent = 'Clear ' + label;
    btn.onclick = async () => {
      const status = label === 'All' ? null : (label === 'Failed' ? 'error' : 'done');
      const qs = status ? '?status=' + status : '';
      await api('/downloads/history' + qs, { method: 'DELETE' });
      const histEl = document.getElementById('dl-history');
      if (histEl) loadDownloadHistory(histEl);
    };
    clearBtns.appendChild(btn);
  });
  historyHeader.appendChild(clearBtns);
  resultsArea.appendChild(historyHeader);
  const historySection = h('div', { id: 'dl-history', className: 'dl-card-list' });
  resultsArea.appendChild(historySection);

  // Sync queue control state (paused/running)
  api('/downloads/queue-state').then(qs => {
    _setQueuePaused(qs.paused);
  }).catch(() => {});

  // Seed active section from current server state, then let SSE keep it updated
  api('/downloads/active/snapshot').then(data => {
    const entries = data.active || [];
    const queuedCount = data.queued_count || 0;
    if (entries.length === 0 && queuedCount === 0) {
      _showActiveEmpty(activeSection);
    } else {
      entries.forEach(e => updateActiveDownload(activeSection, { type: 'progress', ...e }));
      if (queuedCount > 0) {
        const summary = h('div', { className: 'dl-card dl-batch-summary' });
        summary.appendChild(textEl('div', queuedCount + ' tracks queued', 'dl-card-name'));
        summary.appendChild(textEl('div', 'Waiting to start...', 'dl-card-status dl-status-queued'));
        activeSection.prepend(summary);
      }
    }
  }).catch(() => {
    _showActiveEmpty(activeSection);
  });

  _ensureGlobalSSE();

  // Load history
  loadDownloadHistory(historySection);
}

let _historyReloadTimer = null;
function _scheduleHistoryReload() {
  clearTimeout(_historyReloadTimer);
  _historyReloadTimer = setTimeout(() => {
    const histEl = document.getElementById('dl-history');
    if (histEl) loadDownloadHistory(histEl);
  }, 800);
}

function updateActiveDownload(container, data) {
  let card = container.querySelector('[data-dl-id="' + data.track_id + '"]');

  if (data.type === 'complete' || data.type === 'error') {
    if (card) card.remove();
    // Remove batch summary if no real download cards remain
    const remaining = container.querySelectorAll('.dl-card:not(.dl-batch-summary):not(.dl-empty)');
    if (!remaining.length) {
      const summary = container.querySelector('.dl-batch-summary');
      if (summary) summary.remove();
    }
    if (!container.children.length) {
      _showActiveEmpty(container);
    }
    // Debounce history reload — prevents 1600 re-renders during bulk downloads
    _scheduleHistoryReload();
    return;
  }

  // Remove empty state if present
  const emptyEl = container.querySelector('.dl-empty');
  if (emptyEl) emptyEl.remove();

  if (!card) {
    card = h('div', { 'data-dl-id': String(data.track_id), className: 'dl-card' });
    container.appendChild(card);
  }

  while (card.firstChild) card.removeChild(card.firstChild);

  card.appendChild(_dlArtThumb(data.cover_url, data.track_id));

  const info = h('div', { className: 'dl-card-info' });
  info.appendChild(textEl('div', data.name || 'Track ' + data.track_id, 'dl-card-name'));
  if (data.artist || data.album) {
    const parts = [data.artist, data.album].filter(Boolean);
    info.appendChild(textEl('div', parts.join(' \u2014 '), 'dl-card-artist'));
  }

  // Progress bar
  const barWrap = h('div', { className: 'dl-progress-wrap' });
  const barFill = h('div', { className: 'dl-progress-fill' });
  if (data.status === 'downloading') {
    barFill.classList.add('dl-progress-active');
    barFill.style.width = (data.progress || 0) + '%';
  } else {
    // queued
    barFill.classList.add('dl-progress-queued');
    barFill.style.width = '0%';
  }
  barWrap.appendChild(barFill);
  info.appendChild(barWrap);

  const statusText = textEl('div',
    data.status === 'queued' ? 'Waiting...' : 'Downloading',
    'dl-card-status' + (data.status === 'queued' ? ' dl-status-queued' : '')
  );
  info.appendChild(statusText);

  card.appendChild(info);
}

function _showActiveEmpty(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const empty = h('div', { className: 'dl-empty' });
  empty.appendChild(textEl('div', 'Your downloads are clear', 'dl-empty-text'));
  container.appendChild(empty);
}

async function loadDownloadHistory(container) {
  while (container.firstChild) container.removeChild(container.firstChild);

  try {
    const data = await api('/downloads/history');
    const downloads = data.downloads || [];

    if (downloads.length === 0) {
      const empty = h('div', { className: 'dl-empty-state' });
      const iconWrap = h('div', { className: 'dl-empty-icon' });
      // SAFE: static SVG markup
      iconWrap.innerHTML = ICONS.music; // eslint-disable-line -- static SVG
      empty.appendChild(iconWrap);
      empty.appendChild(textEl('div', 'No downloads yet', 'empty-state-title'));
      empty.appendChild(textEl('div', 'Tracks you download will appear here', 'empty-state-sub'));
      container.appendChild(empty);
      return;
    }

    downloads.forEach((dl, i) => {
      const card = h('div', { className: 'dl-card dl-history-card' });
      card.style.animationDelay = Math.min(i * 0.03, 0.3) + 's';

      // Click to play track
      if (dl.file_path && dl.status === 'done') {
        card.style.cursor = 'pointer';
        card.title = 'Click to play';
        card.addEventListener('click', () => {
          const track = {
            is_local: true,
            local_path: dl.file_path,
            path: dl.file_path,
            name: dl.name,
            artist: dl.artist,
            album: dl.album,
            cover_url: dl.cover_url,
            quality: dl.quality,
            format: dl.quality,
          };
          const queuedTrack = _cloneQueueTrack(track, ++_queueEntrySeq);
          state.queueOriginal = [queuedTrack];
          state.queue = [queuedTrack];
          state.queueIndex = 0;
          playTrack(track);
        });
      }

      // Right-click context menu
      card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        const items = [];
        if (dl.album && dl.artist) {
          items.push({
            label: 'Go to Album',
            icon: 'disc',
            action: () => navigate('localalbum:' + encodeURIComponent(dl.artist) + ':' + encodeURIComponent(dl.album))
          });
        }
        if (dl.file_path) {
          items.push({
            label: 'Open in Finder',
            icon: 'folder',
            action: async () => {
              try {
                await api('/downloads/reveal', { method: 'POST', body: { path: dl.file_path } });
                toast('Revealed in Finder', 'success');
              } catch (_) { toast('File not found', 'error'); }
            }
          });
          items.push('sep');
          items.push({
            label: 'Delete Track',
            icon: 'trash',
            className: 'ctx-danger',
            action: () => {
              inlineConfirm('Delete "' + (dl.name || 'track') + '"? This removes the file from disk.', async () => {
                try {
                  await api('/library/track', { method: 'DELETE', body: { path: dl.file_path } });
                  card.remove();
                  toast('Track deleted', 'success');
                } catch (err) { toast('Failed to delete', 'error'); }
              });
            }
          });
        }
        if (items.length) showContextMenu(e, items);
      });

      card.appendChild(_dlArtThumb(dl.cover_url, dl.track_id));

      const info = h('div', { className: 'dl-card-info' });

      const nameEl = textEl('div', dl.name || 'Track ' + dl.track_id, 'dl-card-name');
      info.appendChild(nameEl);

      if (dl.artist) {
        info.appendChild(textEl('div', dl.artist, 'dl-card-artist'));
      }
      if (dl.album) {
        info.appendChild(textEl('div', dl.album, 'dl-card-album'));
      }

      // Bottom row: quality badge + status + time + retry
      const meta = h('div', { className: 'dl-card-meta' });

      if (dl.quality && dl.status === 'done') {
        const qCls = qualityClass(dl.quality);
        const qLabel = qualityLabel(dl.quality);
        const badge = textEl('span', qLabel, 'quality-tag ' + qCls);
        badge.title = qualityTitle(dl.quality);
        meta.appendChild(badge);
      }

      if (dl.status === 'done') {
        const dot = h('span', { className: 'dl-status-dot dl-status-done' });
        meta.appendChild(dot);
        meta.appendChild(textEl('span', 'Done', 'dl-status-label dl-status-done-text'));
      } else if (dl.status === 'error') {
        const dot = h('span', { className: 'dl-status-dot dl-status-error' });
        meta.appendChild(dot);
        meta.appendChild(textEl('span', 'Failed', 'dl-status-label dl-status-error-text'));
        // Retry button
        const retryBtn = h('button', { className: 'dl-retry-btn' });
        retryBtn.textContent = 'Retry';
        retryBtn.onclick = async (e) => {
          e.stopPropagation();
          retryBtn.disabled = true;
          retryBtn.textContent = 'Retrying\u2026';
          try {
            await apiTidal('/download', { method: 'POST', body: { track_ids: [dl.track_id] } });
          } catch (_) {
            retryBtn.disabled = false;
            retryBtn.textContent = 'Retry';
          }
        };
        meta.appendChild(retryBtn);
      }

      if (dl.finished_at) {
        meta.appendChild(textEl('span', _timeAgo(dl.finished_at), 'dl-card-time'));
      }

      info.appendChild(meta);
      card.appendChild(info);
      container.appendChild(card);
    });
  } catch (_) {
    container.appendChild(textEl('div', 'Could not load download history', 'dl-error-text'));
  }
}

// ---- SETTINGS VIEW ----
function renderSettings(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  resultsArea.appendChild(h('div', { className: 'results-header' },
    textEl('div', 'Settings', 'results-title')
  ));

  renderPlaybackPrefsSection(resultsArea);

  // Auth status
  const authSection = h('div', { id: 'settings-auth-status', style: { marginBottom: '24px' } });
  resultsArea.appendChild(authSection);
  loadAuthStatus(authSection);

  const accessSection = h('div', { id: 'settings-access-status' });
  resultsArea.appendChild(accessSection);

  // Settings form
  const formSection = h('div');
  resultsArea.appendChild(formSection);
  loadSettingsForm(formSection, accessSection);

  // Server section
  const sidecarSection = h('div', { id: 'sidecar-section' });
  resultsArea.appendChild(sidecarSection);
  _sidecar.el = sidecarSection;
  _renderSidecarSection(sidecarSection);
  _startSidecarPoll();

  // Clean up poll timer when navigating away from settings
  const prevCleanup = viewEl._viewCleanup;
  viewEl._viewCleanup = () => {
    _stopSidecarPoll();
    _sidecar.el = null;
    if (prevCleanup) prevCleanup();
  };

  // Updater section
  const updaterSection = h('div', { id: 'settings-updater' });
  resultsArea.appendChild(updaterSection);
  _updater.settingsEl = updaterSection;
  try {
    if (_isTauri()) {
      if (_updater.state) {
        renderUpdaterSettings(updaterSection, _updater.state);
      } else {
        Promise.resolve().then(() => _tauriInvoke('get_updater_state')).then(us => {
          _onUpdaterState(us);
        }).catch(() => {});
      }
    } else {
      _renderWebUpdaterPanel(updaterSection);
    }
    // Web update notification card (shown in both modes)
    if (_updater.webUpdate && _updater.webUpdate.update_available) {
      _renderWebUpdaterSettings(updaterSection);
    }
  } catch (e) {
    console.error('Updater settings error:', e);
  }
}

async function loadAuthStatus(container) {
  try {
    const data = await api('/auth/status');
    while (container.firstChild) container.removeChild(container.firstChild);
    if (data.logged_in) {
      const dot = h('span', { className: 'connection-dot' });
      container.appendChild(h('div', { className: 'connection', style: { padding: '0 0 16px' } },
        dot,
        document.createTextNode('Connected' + (data.username ? ' as ' + data.username : ''))
      ));
    } else {
      const dot = h('span', { className: 'connection-dot disconnected' });
      const row = h('div', { className: 'connection', style: { padding: '0 0 16px', gap: '12px' } },
        dot,
        document.createTextNode('Not logged in to Tidal')
      );
      const loginBtn = textEl('button', 'Log in to Tidal', 'banner-action');
      loginBtn.addEventListener('click', () => { triggerLogin(); });
      row.appendChild(loginBtn);
      container.appendChild(row);
    }
  } catch (_) {
    container.appendChild(textEl('div', 'Could not check auth status', 'track-artist'));
  }
}

function renderPlaybackPrefsSection(container) {
  const section = h('div', { className: 'settings-section player-prefs-section' });
  section.appendChild(textEl('div', 'Playback', 'settings-section-header'));

  const smartRow = h('div', { className: 'settings-row' });
  const smartLabel = h('div', { className: 'settings-label-group' },
    textEl('label', 'Smart Shuffle', 'settings-label'),
    textEl('span', 'Deprioritize recently played tracks when shuffle is on', 'settings-helper')
  );
  const smartToggle = h('div', {
    className: 'settings-toggle' + (state.smartShuffle ? ' on' : ''),
    tabIndex: '0', role: 'switch', 'aria-checked': state.smartShuffle ? 'true' : 'false',
  });
  const flipSmart = () => {
    state.smartShuffle = !state.smartShuffle;
    smartToggle.className = 'settings-toggle' + (state.smartShuffle ? ' on' : '');
    smartToggle.setAttribute('aria-checked', state.smartShuffle ? 'true' : 'false');
    _savePlayerPrefs();
    if (state.shuffle && state.queue.length) _reshuffleCurrentQueue();
  };
  smartToggle.addEventListener('click', flipSmart);
  smartToggle.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flipSmart(); } });
  smartRow.appendChild(smartLabel);
  smartRow.appendChild(smartToggle);
  section.appendChild(smartRow);

  const shortcuts = h('div', { className: 'settings-shortcuts' });
  [
    ['Space', 'Play / Pause'],
    ['ArrowLeft', 'Back 10s'],
    ['ArrowRight', 'Forward 10s'],
    ['Cmd/Ctrl+K', 'Search'],
    ['Cmd/Ctrl+L', 'Lyrics'],
    ['Cmd/Ctrl+Shift+Q', 'Queue'],
  ].forEach(([key, label]) => {
    shortcuts.appendChild(h('div', { className: 'settings-shortcut-row' },
      textEl('span', key, 'shortcut-key'),
      textEl('span', label, 'shortcut-action')
    ));
  });
  section.appendChild(shortcuts);
  container.appendChild(section);
}

function _setVersionChip(version) {
  if (!version) return;
  const chip = document.getElementById('app-version-chip');
  if (!chip) return;
  chip.textContent = 'v' + String(version).replace(/^v/i, '');
}

function setSettingsReadOnly(container, readOnly) {
  state.settingsReadOnly = !!readOnly;
  container.dataset.readOnly = readOnly ? 'true' : 'false';
  container.classList.toggle('settings-read-only', !!readOnly);

  container.querySelectorAll('.settings-input, .settings-browse-btn').forEach(el => {
    el.disabled = !!readOnly;
  });

  container.querySelectorAll('.settings-toggle').forEach(toggle => {
    toggle.dataset.disabled = readOnly ? 'true' : 'false';
    toggle.classList.toggle('disabled', !!readOnly);
    toggle.setAttribute('aria-disabled', readOnly ? 'true' : 'false');
    toggle.tabIndex = readOnly ? -1 : 0;
  });
}

async function chooseSettingsFolder(formContainer, accessContainer, currentSettings) {
  try {
    const result = await api('/browse-directory', { method: 'POST' });
    if (!result.path) return;

    const body = { download_base_path: result.path };
    const currentScan = (currentSettings.scan_paths || '').trim();
    const currentDownload = (currentSettings.download_base_path || '').trim();
    if (!currentScan || currentScan === currentDownload) {
      body.scan_paths = result.path;
    }

    await api('/settings', { method: 'PATCH', body });
    toast('Music folder updated', 'success');
    await loadSettingsForm(formContainer, accessContainer);
  } catch (err) {
    if (!String(err.message || '').includes('No directory selected')) {
      toast('Browse failed: ' + err.message, 'error');
    }
  }
}

function renderSettingsAccessBanner(container, access, formContainer, currentSettings) {
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!access || !access.read_only) return;

  const banner = h('div', { className: 'error-banner settings-status-banner' });
  banner.appendChild(textEl('span', access.banner_message || 'Settings are read-only until access is restored.', ''));

  const retryBtn = textEl('button', 'Retry Access', 'banner-action');
  retryBtn.addEventListener('click', () => { loadSettingsForm(formContainer, container); });
  banner.appendChild(retryBtn);

  const chooseBtn = textEl('button', 'Choose Folder', 'banner-action');
  chooseBtn.style.marginLeft = '0';
  chooseBtn.addEventListener('click', () => { chooseSettingsFolder(formContainer, container, currentSettings); });
  banner.appendChild(chooseBtn);

  container.appendChild(banner);
}

async function loadSettingsForm(container, accessContainer) {
  try {
    const [data, access] = await Promise.all([
      api('/settings'),
      api('/settings/status').catch(() => ({ read_only: false, banner_message: null, paths: [], version: null })),
    ]);
    state.settings = data;
    _settingsLoad = Promise.resolve(data);
    state.settingsAccess = access;
    _setVersionChip(access.version);

    while (container.firstChild) container.removeChild(container.firstChild);
    renderSettingsAccessBanner(accessContainer, access, container, data);

    if (access && access.read_only) {
      container.appendChild(textEl('div', 'Settings are read-only until access is restored.', 'settings-read-only-note'));
    }

    const sections = [
      { title: 'Storage', fields: [
        { key: 'download_base_path', label: 'Download Path', type: 'path', helper: 'Where your music is saved' },
        { key: 'skip_existing', label: 'Skip Existing', type: 'toggle', helper: 'Skip tracks already downloaded to this path' },
      ]},
      { title: 'Quality', fields: [
        { key: 'quality_audio', label: 'Audio Quality', type: 'select', options: ['HI_RES_LOSSLESS', 'HI_RES', 'LOSSLESS', 'HIGH', 'LOW'], helper: 'Higher quality = larger files' },
        { key: 'extract_flac', label: 'Extract FLAC', type: 'toggle', helper: 'Converts MQA to standard FLAC' },
        { key: 'upgrade_target_quality', label: 'Upgrade Target', type: 'select', options: ['HI_RES_LOSSLESS', 'HI_RES'], helper: 'Minimum quality tier for upgrades' },
      ]},
      { title: 'Downloads', fields: [
        { key: 'downloads_concurrent_max', label: 'Max Concurrent Downloads', type: 'number', helper: '1\u201310 recommended for stability' },
        { key: 'download_delay', label: 'Download Delay', type: 'toggle', helper: 'Adds a pause between downloads to avoid rate limits' },
      ]},
      { title: 'Metadata', fields: [
        { key: 'metadata_cover_embed', label: 'Embed Cover Art', type: 'toggle', helper: 'Saves album art inside the audio file' },
        { key: 'lyrics_embed', label: 'Embed Lyrics', type: 'toggle', helper: 'Saves synced lyrics inside the audio file' },
        { key: 'lyrics_file', label: 'Save Lyrics File', type: 'toggle', helper: 'Creates a separate .lrc lyrics file' },
        { key: 'cover_album_file', label: 'Save Album Cover', type: 'toggle', helper: 'Saves cover.jpg in the album folder' },
      ]},
      { title: 'Library', fields: [
        { key: 'scan_paths', label: 'Scan Paths', type: 'text', helper: 'Additional folders to scan for music' },
        { key: 'skip_duplicate_isrc', label: 'Skip Duplicate ISRC', type: 'toggle', helper: 'Skips tracks with the same recording code' },
      ]},
    ];

    sections.forEach(section => {
      const sectionEl = h('div', { className: 'settings-section' });
      sectionEl.appendChild(textEl('div', section.title, 'settings-section-header'));

      section.fields.forEach(field => {
        const row = h('div', { className: 'settings-row' });
        const labelGroup = h('div', { className: 'settings-label-group' });
        labelGroup.appendChild(textEl('label', field.label, 'settings-label'));
        if (field.helper) {
          labelGroup.appendChild(textEl('span', field.helper, 'settings-helper'));
        }
        row.appendChild(labelGroup);

        if (field.type === 'path') {
          const wrapper = h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } });
          const input = h('input', { className: 'settings-input', type: 'text' });
          input.style.width = '260px';
          input.value = data[field.key] || '';
          input.addEventListener('blur', () => { if (!state.settingsReadOnly) saveSetting(field.key, input.value); });
          wrapper.appendChild(input);
          const browseBtn = textEl('button', 'Browse', 'pill active settings-browse-btn');
          browseBtn.style.cursor = 'pointer';
          browseBtn.style.whiteSpace = 'nowrap';
          browseBtn.addEventListener('click', async () => {
            if (state.settingsReadOnly) return;
            browseBtn.textContent = '...';
            try {
              const result = await api('/browse-directory', { method: 'POST' });
              if (result.path) {
                input.value = result.path;
                await saveSetting(field.key, result.path);
              }
            } catch (err) {
              if (!err.message.includes('No directory selected')) {
                toast('Browse failed: ' + err.message, 'error');
              }
            }
            browseBtn.textContent = 'Browse';
          });
          wrapper.appendChild(browseBtn);
          row.appendChild(wrapper);
        } else if (field.type === 'text') {
          const input = h('input', { className: 'settings-input', type: 'text' });
          input.style.width = '300px';
          input.value = data[field.key] || '';
          input.addEventListener('blur', () => { if (!state.settingsReadOnly) saveSetting(field.key, input.value); });
          row.appendChild(input);
        } else if (field.type === 'number') {
          const input = h('input', { className: 'settings-input', type: 'number' });
          input.style.width = '80px';
          input.min = '1';
          input.max = '10';
          input.value = data[field.key] || 3;
          input.addEventListener('blur', () => {
            if (state.settingsReadOnly) return;
            let v = parseInt(input.value, 10);
            if (isNaN(v) || v < 1) v = 1;
            if (v > 10) v = 10;
            input.value = v;
            saveSetting(field.key, v);
          });
          row.appendChild(input);
        } else if (field.type === 'select') {
          const select = h('select', { className: 'settings-input' });
          select.style.width = '320px';
          select.style.background = 'var(--surface)';
          select.style.color = 'var(--text)';
          field.options.forEach(opt => {
            const option = h('option', { value: opt });
            const tier = _qualityTier(opt);
            option.textContent = tier.tier + ' (' + tier.desc + ')';
            if (data[field.key] === opt) option.selected = true;
            select.appendChild(option);
          });
          select.addEventListener('change', () => saveSetting(field.key, select.value));
          row.appendChild(select);
        } else if (field.type === 'toggle') {
          const toggle = h('div', {
            className: 'settings-toggle' + (data[field.key] ? ' on' : ''),
            tabIndex: '0', role: 'switch', 'aria-checked': data[field.key] ? 'true' : 'false',
          });
          let val = !!data[field.key];
          const flipToggle = () => {
            if (toggle.dataset.disabled === 'true') return;
            val = !val;
            toggle.className = 'settings-toggle' + (val ? ' on' : '');
            toggle.setAttribute('aria-checked', val ? 'true' : 'false');
            saveSetting(field.key, val);
          };
          toggle.addEventListener('click', flipToggle);
          toggle.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flipToggle(); } });
          row.appendChild(toggle);
        }

        sectionEl.appendChild(row);
      });

      container.appendChild(sectionEl);
    });

    setSettingsReadOnly(container, !!(access && access.read_only));
  } catch (err) {
    container.appendChild(textEl('div', 'Failed to load settings: ' + err.message, 'track-artist'));
  }
}

async function saveSetting(key, value) {
  if (state.settingsReadOnly) {
    toast('Settings are read-only until access is restored.', 'error', 5000);
    return;
  }
  try {
    const body = {};
    body[key] = value;
    const updated = await api('/settings', { method: 'PATCH', body });
    state.settings = updated;
    _settingsLoad = Promise.resolve(updated);
    toast('Setting saved', 'success');
  } catch (err) {
    toast('Failed to save: ' + err.message, 'error');
  }
}

// ---- PLAYER ----
const audio = document.getElementById('audio');

// Kill any residual playback from browser cache/bfcache on page load
audio.pause();
audio.removeAttribute('src');
audio.load();

const btnPlay = document.getElementById('btn-play');
const playIcon = document.getElementById('play-icon');
const btnPrev = document.getElementById('btn-prev');
const btnNext = document.getElementById('btn-next');
const btnShuffle = document.getElementById('btn-shuffle');
const btnRepeat = document.getElementById('btn-repeat');
const progressBar = document.getElementById('progress-bar');
const progressFill = document.getElementById('progress-fill');
const timeElapsed = document.getElementById('time-elapsed');
const timeTotal = document.getElementById('time-total');
const nowTitle = document.getElementById('now-title');
const nowSub = document.getElementById('now-sub');
const nowArt = document.getElementById('now-art');
const volSlider = document.getElementById('vol-slider');
const volFill = document.getElementById('vol-fill');
const waveform = document.getElementById('waveform');

// Idle player title → feeling lucky
nowTitle.addEventListener('click', () => {
  if (nowTitle.classList.contains('idle-clickable')) feelingLucky();
});

a11yClick(nowArt);
const lyricsPanel = document.getElementById('lyrics-panel');
const lyricsBody = document.getElementById('lyrics-body');
const btnLyricsClose = document.getElementById('lyrics-close');
const lyricsArtworkBg = document.getElementById('lyrics-artwork-bg');
const lyricsState = {
  lyricsPanelState: 'closed',
  lyricsData: null,
  lyricsCanonicalTrackPath: null,
  lyricsRequestToken: 0,
  lyricsCache: {},
  lyricsError: null,
  lyricsRequestPath: null,
  lyricsFocusReturnEl: null,
  lyricsLineEls: null,
  lyricsListEl: null,
};
const _lyricsReduceMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

function _currentTrack() {
  return state.queue[state.queueIndex] || null;
}

function _currentTrackLocalPath(track) {
  if (!track) return null;
  return track.local_path || track.path || null;
}

function _lyricsOpen() {
  return lyricsState.lyricsPanelState !== 'closed';
}

function _setLyricsPanelOpen(open) {
  lyricsPanel.classList.toggle('open', open);
  lyricsPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
  document.body.classList.toggle('lyrics-open', open);
}

function _clearLyricsBody() {
  while (lyricsBody.firstChild) lyricsBody.removeChild(lyricsBody.firstChild);
}

function _renderLyricsShell(shellClass, title, subtext) {
  _clearLyricsBody();
  const shell = h('div', { className: 'lyrics-shell ' + shellClass });
  const content = h('div', { className: 'lyrics-shell-copy' });
  content.appendChild(textEl('div', title, 'empty-state-title'));
  if (subtext) content.appendChild(textEl('div', subtext, 'empty-state-sub'));
  shell.appendChild(content);
  lyricsBody.appendChild(shell);
}

function renderUnsyncedLyrics(payload) {
  _clearLyricsBody();
  const shell = h('div', { className: 'lyrics-shell lyrics-shell-unsynced' });
  const copy = h('div', { className: 'lyrics-unsynced-copy' });
  payload.text.split('\n').forEach((line) => {
    copy.appendChild(textEl('div', line, 'lyrics-unsynced-line'));
  });
  shell.appendChild(copy);
  lyricsBody.appendChild(shell);
}

let _lyricsAnimId = null;
function applyLyricsArtworkBackground(track) {
  if (!lyricsArtworkBg) return;
  if (track && track.cover_url) {
    const coverUrl = String(track.cover_url).replace(/["\\()]/g, '\\$&');
    lyricsArtworkBg.style.backgroundImage = [
      'linear-gradient(180deg, rgba(15, 14, 13, 0.22), rgba(15, 14, 13, 0.86))',
      'url("' + coverUrl + '")',
    ].join(', ');
    lyricsArtworkBg.style.backgroundSize = 'cover';
    lyricsArtworkBg.style.backgroundPosition = 'center';
    return;
  }
  lyricsArtworkBg.style.backgroundImage = [
    'radial-gradient(circle at 20% 20%, rgba(212, 160, 83, 0.18), transparent 45%)',
    'radial-gradient(circle at 80% 30%, rgba(120, 88, 180, 0.16), transparent 42%)',
    'linear-gradient(180deg, rgba(15, 14, 13, 0.2), rgba(15, 14, 13, 0.85))',
  ].join(', ');
  lyricsArtworkBg.style.backgroundSize = '';
  lyricsArtworkBg.style.backgroundPosition = '';
}

function renderSyncedLyrics(payload) {
  _clearLyricsBody();
  const shell = h('div', { className: 'lyrics-shell lyrics-shell-synced' });
  const viewport = h('div', { className: 'lyrics-synced-viewport' });
  const list = h('div', { className: 'lyrics-synced-list' });
  lyricsState.lyricsLineEls = payload.lines.map((line) => textEl('div', line.text, 'lyrics-synced-line'));
  lyricsState.lyricsLineEls.forEach((lineEl) => list.appendChild(lineEl));
  viewport.appendChild(list);
  shell.appendChild(viewport);
  lyricsBody.appendChild(shell);
  lyricsState.lyricsListEl = list;
  if (_lyricsAnimId) cancelAnimationFrame(_lyricsAnimId);
  _lyricsAnimId = requestAnimationFrame(syncActiveLyricLine);
}

function syncActiveLyricLine() {
  if (!_lyricsOpen() || lyricsState.lyricsPanelState !== 'synced' || !lyricsState.lyricsData || !lyricsState.lyricsListEl) {
    _lyricsAnimId = null;
    return;
  }
  const currentTimeMs = Math.floor(audio.currentTime * 1000);
  let activeIndex = -1;
  lyricsState.lyricsData.lines.forEach((line, index) => {
    if (line.start_ms <= currentTimeMs && currentTimeMs < line.end_ms) activeIndex = index;
  });
  lyricsState.lyricsLineEls.forEach((lineEl, index) => lineEl.classList.toggle('active', index === activeIndex));
  const activeEl = activeIndex >= 0 ? lyricsState.lyricsLineEls[activeIndex] : null;
  const reduceMotion = _lyricsReduceMotionQuery.matches;
  lyricsState.lyricsListEl.style.transition = reduceMotion ? 'none' : 'transform 220ms ease';
  if (activeEl) {
    const targetOffset = Math.max(0, activeEl.offsetTop - ((lyricsBody.clientHeight / 2) - (activeEl.offsetHeight / 2)));
    lyricsState.lyricsListEl.style.transform = 'translateY(' + (-targetOffset) + 'px)';
  } else {
    lyricsState.lyricsListEl.style.transform = 'translateY(0px)';
  }
  _lyricsAnimId = requestAnimationFrame(syncActiveLyricLine);
}

function validateLyricsPayload(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('Invalid lyrics payload');
  if (!['synced', 'unsynced', 'none'].includes(payload.mode)) throw new Error('Invalid lyrics mode');
  if (typeof payload.track_path !== 'string' || !payload.track_path.trim()) throw new Error('Missing track_path');
  if (!Object.prototype.hasOwnProperty.call(payload, 'source')) throw new Error('Missing lyrics source');
  if (!Array.isArray(payload.lines) || typeof payload.text !== 'string') throw new Error('Invalid lyrics shape');
  const sourceByMode = {
    synced: ['lrc-synced', 'embedded-synced'],
    unsynced: ['lrc-unsynced', 'embedded-unsynced'],
    none: ['none'],
  };
  if (!sourceByMode[payload.mode].includes(payload.source)) throw new Error('Incompatible lyrics source');
  if (payload.mode === 'synced') {
    if (!payload.lines.length) throw new Error('Synced lyrics require lines');
    payload.lines.forEach((line) => {
      if (!Number.isInteger(line.start_ms) || line.start_ms < 0) throw new Error('Invalid lyric start');
      if (!Number.isInteger(line.end_ms) || line.end_ms < 0 || line.end_ms <= line.start_ms) throw new Error('Invalid lyric end');
      if (!line.text || !String(line.text).trim()) throw new Error('Invalid lyric text');
    });
    if (payload.text !== '') throw new Error('Synced lyrics text must be empty');
  }
  if (payload.mode === 'unsynced') {
    if (!payload.text.trim()) throw new Error('Unsynced lyrics must have text');
    if (payload.lines.length !== 0) throw new Error('Unsynced lyrics cannot include lines');
  }
  if (payload.mode === 'none') {
    if (payload.text !== '' || payload.lines.length !== 0) throw new Error('Empty lyrics payload malformed');
  }
  return payload;
}

function renderLyricsPanel() {
  if (!_lyricsOpen()) {
    _setLyricsPanelOpen(false);
    return;
  }
  _setLyricsPanelOpen(true);
  applyLyricsArtworkBackground(_currentTrack());
  if (lyricsState.lyricsPanelState === 'loading') {
    _renderLyricsShell('lyrics-shell-loading', 'Loading lyrics…', '');
    return;
  }
  if (lyricsState.lyricsPanelState === 'error') {
    _renderLyricsShell('lyrics-shell-error', 'Could not load lyrics', 'Try again while playback continues.');
    return;
  }
  if (lyricsState.lyricsPanelState === 'empty') {
    _renderLyricsShell('lyrics-shell-empty', 'Lyrics not available', 'This local track does not have synced, embedded, or sidecar lyrics yet.');
    return;
  }
  if (lyricsState.lyricsPanelState === 'unsynced' && lyricsState.lyricsData) {
    renderUnsyncedLyrics(lyricsState.lyricsData);
    return;
  }
  if (lyricsState.lyricsPanelState === 'synced' && lyricsState.lyricsData) {
    renderSyncedLyrics(lyricsState.lyricsData);
    return;
  }
  _renderLyricsShell('lyrics-shell-error', 'Could not load lyrics', 'Try again while playback continues.');
}

function _applyLyricsPayload(payload, requestPath) {
  lyricsState.lyricsError = null;
  lyricsState.lyricsData = payload;
  lyricsState.lyricsRequestPath = requestPath;
  lyricsState.lyricsCanonicalTrackPath = payload.track_path;
  lyricsState.lyricsCache[payload.track_path] = payload;
  if (payload.mode === 'synced') lyricsState.lyricsPanelState = 'synced';
  else if (payload.mode === 'unsynced') lyricsState.lyricsPanelState = 'unsynced';
  else lyricsState.lyricsPanelState = 'empty';
  renderLyricsPanel();
}

async function loadLyricsForCurrentTrack(trackOverride) {
  const track = trackOverride || _currentTrack();
  const localPath = _currentTrackLocalPath(track);
  if (!track || !track.is_local || !localPath) return;

  const requestToken = ++lyricsState.lyricsRequestToken;
  lyricsState.lyricsRequestPath = localPath;

  try {
    const payload = validateLyricsPayload(await api('/lyrics/local?path=' + encodeURIComponent(localPath)));
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
    _applyLyricsPayload(payload, localPath);
  } catch (err) {
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
    lyricsState.lyricsData = null;
    lyricsState.lyricsError = err.message || String(err);
    lyricsState.lyricsPanelState = 'error';
    renderLyricsPanel();
  }
}

function closeLyricsPanel(opts) {
  const options = opts || {};
  lyricsState.lyricsRequestToken++;
  lyricsState.lyricsPanelState = 'closed';
  lyricsState.lyricsData = null;
  lyricsState.lyricsError = null;
  lyricsState.lyricsLineEls = null;
  lyricsState.lyricsListEl = null;
  if (_lyricsAnimId) { cancelAnimationFrame(_lyricsAnimId); _lyricsAnimId = null; }
  _setLyricsPanelOpen(false);
  if (options.restoreFocus && lyricsState.lyricsFocusReturnEl && lyricsState.lyricsFocusReturnEl.focus) {
    lyricsState.lyricsFocusReturnEl.focus();
  }
}

function openLyricsPanel(opts) {
  const options = opts || {};
  const track = options.track || _currentTrack();
  const localPath = _currentTrackLocalPath(track);
  if (!track || !track.is_local || !localPath) return;

  if (queuePanel.classList.contains('open')) toggleQueue();
  lyricsState.lyricsFocusReturnEl = options.focusReturnEl || document.activeElement || nowArt;
  _setLyricsPanelOpen(true);

  if (
    lyricsState.lyricsCanonicalTrackPath &&
    lyricsState.lyricsRequestPath === localPath &&
    lyricsState.lyricsCache[lyricsState.lyricsCanonicalTrackPath]
  ) {
    lyricsState.lyricsData = lyricsState.lyricsCache[lyricsState.lyricsCanonicalTrackPath];
    lyricsState.lyricsPanelState = lyricsState.lyricsData.mode === 'synced'
      ? 'synced'
      : (lyricsState.lyricsData.mode === 'unsynced' ? 'unsynced' : 'empty');
    renderLyricsPanel();
    return;
  }

  lyricsState.lyricsData = null;
  lyricsState.lyricsError = null;
  lyricsState.lyricsCanonicalTrackPath = null;
  lyricsState.lyricsPanelState = 'loading';
  renderLyricsPanel();
  loadLyricsForCurrentTrack(track);
}

function toggleLyricsPanel() {
  if (_lyricsOpen()) {
    closeLyricsPanel({ restoreFocus: true });
    return;
  }
  openLyricsPanel({ focusReturnEl: nowArt });
}

function handleLyricsTrackChange(track) {
  const localPath = _currentTrackLocalPath(track);
  if (!track || !track.is_local || !localPath) {
    lyricsState.lyricsRequestToken++;
    lyricsState.lyricsCanonicalTrackPath = null;
    lyricsState.lyricsRequestPath = null;
    lyricsState.lyricsData = null;
    lyricsState.lyricsError = null;
    if (_lyricsOpen()) closeLyricsPanel();
    return;
  }
  if (_lyricsOpen()) {
    lyricsState.lyricsCanonicalTrackPath = null;
    lyricsState.lyricsData = null;
    lyricsState.lyricsError = null;
    lyricsState.lyricsPanelState = 'loading';
    renderLyricsPanel();
    loadLyricsForCurrentTrack(track);
  }
}

if (btnLyricsClose) {
  btnLyricsClose.addEventListener('click', () => closeLyricsPanel({ restoreFocus: true }));
}
if (lyricsBody) {
  lyricsBody.addEventListener('wheel', (e) => {
    if (lyricsState.lyricsPanelState === 'synced') e.preventDefault();
  }, { passive: false });
}

// ── Waveform visualization (no Web Audio API — audio path stays untouched) ──
// Display peaks (~100) define the static bar shape.
// Hires peaks (~10/sec) drive per-frame animation — bars pulse to the music
// using pre-computed amplitude data, like a DAW waveform display.
// The <audio> element is NEVER wrapped in an AudioContext.
const WF_BARS = 100;
let _wfAnimId = null;
let _wfBars = [];
let _wfPeaks = null;    // display-resolution peaks (100 bars)
let _wfHires = null;    // high-res peaks (~10/sec) for animation
let _wfPrevActive = -1; // last active bar index for cleanup

function generateWaveform(peaks, hires) {
  while (waveform.firstChild) waveform.removeChild(waveform.firstChild);
  _wfBars = [];
  _wfPeaks = peaks;
  _wfHires = hires || null;
  _wfPrevActive = -1;
  const count = peaks ? peaks.length : WF_BARS;
  for (let i = 0; i < count; i++) {
    const bar = h('div', { className: 'wf-bar' });
    const scale = peaks ? Math.max(0.05, peaks[i]) : (0.15 + Math.random() * 0.6);
    // Set base height — mirrored via transform-origin: center in CSS
    bar.style.height = '100%';
    bar.style.transform = 'scaleY(' + scale.toFixed(3) + ')';
    bar._baseScale = scale;  // stash for animation
    waveform.appendChild(bar);
    _wfBars.push(bar);
  }
}
generateWaveform();

// Animation loop: yellow sweep + ALL bars modulated by hires amplitude data.
// Each bar maps to a time slice. The hires array has ~10 peaks/sec, so each
// bar's height is driven by the real amplitude at its corresponding moment
// in the song. The whole waveform breathes — not just near the playhead.
function _wfLoop() {
  const total = _wfBars.length;
  const pct = audio.duration ? (audio.currentTime / audio.duration) : 0;
  const activeIdx = Math.floor(pct * total);
  const hiLen = _wfHires ? _wfHires.length : 0;

  for (let i = 0; i < total; i++) {
    const bar = _wfBars[i];
    const barPct = (i + 1) / total;

    // Yellow sweep — played bars get accent color
    if (barPct <= pct) {
      bar.classList.add('wf-played');
    } else {
      bar.classList.remove('wf-played');
    }

    // Active glow on playhead bar
    if (i === activeIdx) {
      bar.classList.add('wf-active');
    } else {
      bar.classList.remove('wf-active');
    }

    // Ripple propagation: amplitude at the playhead ripples outward.
    // Bars further from the playhead show the amplitude from earlier
    // in time, as if the energy is radiating out from the play position.
    // Uses only pre-computed hires data — zero audio processing.
    if (hiLen > 0) {
      const dist = Math.abs(i - activeIdx);
      const RADIUS = 16;             // wider ripple reach
      if (dist <= RADIUS) {
        // Each bar-distance = ~0.12s of delay into the past
        const delay = dist * 0.12;
        const delayedTime = Math.max(0, audio.currentTime - delay);
        const delayedPct = audio.duration ? (delayedTime / audio.duration) : 0;
        const hiIdx = Math.min(Math.floor(delayedPct * hiLen), hiLen - 1);
        const amp = _wfHires[hiIdx];
        // Influence fades with distance from playhead
        const influence = 1 - (dist / (RADIUS + 1));
        const pulse = 1 + (amp * 0.5 * influence);
        bar.style.transform = 'scaleY(' + (bar._baseScale * pulse).toFixed(3) + ')';
      } else if (i < activeIdx) {
        // Played bars (yellow, behind playhead): keep them alive.
        // They breathe with the current amplitude, fading gently
        // the further back they are from the ripple edge.
        var tailDist = activeIdx - RADIUS - i;
        var tailMax = activeIdx - RADIUS;
        // Gentle influence: 20% at ripple edge, fading to 5% at bar 0
        var tailInf = tailMax > 0 ? 0.05 + 0.15 * (1 - tailDist / tailMax) : 0.1;
        var hiNow = Math.min(Math.floor(pct * hiLen), hiLen - 1);
        var ampNow = _wfHires[hiNow];
        var pulse = 1 + (ampNow * tailInf);
        bar.style.transform = 'scaleY(' + (bar._baseScale * pulse).toFixed(3) + ')';
      } else {
        // Unplayed bars (ahead of playhead): settle to idle
        var idle = bar._baseScale * 0.35;
        if (idle < 0.05) idle = 0.05;
        bar.style.transform = 'scaleY(' + idle.toFixed(3) + ')';
      }
    }
  }

  _wfAnimId = requestAnimationFrame(_wfLoop);
}

function _fetchWaveform(track) {
  if (!track || !track.is_local || !track.local_path) {
    generateWaveform();
    return;
  }
  fetch('/api/playback/waveform?path=' + encodeURIComponent(track.local_path))
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data && data.peaks && data.peaks.length > 0) {
        generateWaveform(data.peaks, data.hires || null);
      } else {
        generateWaveform();
      }
    })
    .catch(() => generateWaveform());
}

function setWaveformPlaying(playing) {
  waveform.classList.toggle('playing', playing);
  waveform.classList.toggle('paused', !playing);
  if (playing) {
    if (!_wfPeaks) {
      for (let i = 0; i < _wfBars.length; i++) {
        const s = 0.15 + Math.random() * 0.6;
        _wfBars[i].style.transform = 'scaleY(' + s.toFixed(2) + ')';
        _wfBars[i]._baseScale = s;
      }
    }
    if (!_wfAnimId) _wfAnimId = requestAnimationFrame(_wfLoop);
  } else {
    if (_wfAnimId) { cancelAnimationFrame(_wfAnimId); _wfAnimId = null; }
  }
}

// Set initial volume
audio.volume = state.volume;
volFill.style.width = (state.volume * 100) + '%';

// Detect external audio device (DAC/interface)
// Browser hides device labels without microphone permission.
// Strategy: request mic permission once to unlock labels, then detect.
const _builtinKeywords = ['built-in', 'internal', 'speakers', 'macbook'];
function _applyDac(volArea, deviceName) {
  volArea.classList.add('has-dac');
  const btn = volArea.querySelector('.vol-btn');
  const slider = volArea.querySelector('.vol-slider');
  if (btn) btn.style.display = 'none';
  if (slider) slider.style.display = 'none';
  let label = volArea.querySelector('.dac-label');
  if (!label) {
    label = textEl('span', '', 'dac-label');
    volArea.insertBefore(label, volArea.querySelector('.queue-toggle'));
  }
  label.textContent = deviceName;
  label.title = deviceName;
}
function _clearDac(volArea) {
  volArea.classList.remove('has-dac');
  const btn = volArea.querySelector('.vol-btn');
  const slider = volArea.querySelector('.vol-slider');
  if (btn) btn.style.display = '';
  if (slider) slider.style.display = '';
  const label = volArea.querySelector('.dac-label');
  if (label) label.remove();
}
function _detectAudioOutput() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  navigator.mediaDevices.enumerateDevices().then(devices => {
    const outputs = devices.filter(d => d.kind === 'audiooutput');
    const volArea = document.querySelector('.volume-area');
    if (!volArea) return;
    // Check if labels are available (empty = no permission)
    const hasLabels = outputs.some(d => d.label);
    if (!hasLabels) {
      // No labels — any output beyond built-in speakers suggests external DAC
      if (outputs.length > 1) {
        _applyDac(volArea, 'External DAC');
      }
      return;
    }
    const external = outputs.find(d => {
      if (d.deviceId === 'default' || !d.label) return false;
      return !_builtinKeywords.some(k => d.label.toLowerCase().includes(k));
    });
    if (external) {
      _applyDac(volArea, external.label.replace(/\s*\(.*?\)/, '').trim());
    } else {
      _clearDac(volArea);
    }
  }).catch(() => {});
}
_detectAudioOutput();
navigator.mediaDevices?.addEventListener('devicechange', _detectAudioOutput);

const MAX_RECENT = 50;
const recentlyPlayed = (() => {
  try {
    return JSON.parse(localStorage.getItem('recentlyPlayed') || '[]').slice(0, MAX_RECENT);
  } catch (_) { return []; }
})();

function _saveRecent() {
  try { localStorage.setItem('recentlyPlayed', JSON.stringify(recentlyPlayed)); } catch (_) {}
}

function updatePlayerHeart() {
  const current = state.queue[state.queueIndex];
  let heartEl = document.getElementById('now-heart');

  if (!heartEl) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z');
    svg.appendChild(path);

    heartEl = h('button', { id: 'now-heart', className: 'heart-btn now-heart', 'aria-label': 'Toggle favorite' });
    heartEl.appendChild(svg);
    document.getElementById('now-playing').appendChild(heartEl);
    heartEl.addEventListener('click', () => {
      const trk = state.queue[state.queueIndex];
      if (trk) toggleFavorite(trk, heartEl);
    });
  }

  // Download button — only for non-local tracks
  let dlEl = document.getElementById('now-download');
  if (!dlEl) {
    const dlSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    dlSvg.setAttribute('viewBox', '0 0 24 24');
    dlSvg.setAttribute('fill', 'none');
    dlSvg.setAttribute('stroke', 'currentColor');
    const dlPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    dlPath.setAttribute('d', 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3');
    dlSvg.appendChild(dlPath);

    dlEl = h('button', { id: 'now-download', className: 'heart-btn now-download', 'aria-label': 'Download track' });
    dlEl.appendChild(dlSvg);
    document.getElementById('now-playing').appendChild(dlEl);
    dlEl.addEventListener('click', async () => {
      const trk = state.queue[state.queueIndex] || (recentlyPlayed && recentlyPlayed[0]);
      if (!trk || !trk.id) { toast('No track to download', 'error'); return; }
      if (trk.is_local) { toast('Already in your library', 'success'); return; }
      dlEl.classList.add('downloading');
      try {
        await apiTidal('/download', { method: 'POST', body: { track_ids: [trk.id] } });
        toast('Downloading ' + (trk.name || 'track'));
      } catch (_) {
        toast('Download failed', 'error');
      }
      setTimeout(() => dlEl.classList.remove('downloading'), 2000);
    });
  }

  // Hide both buttons only when player is truly idle (no track info showing)
  const hasTrack = current || nowTitle.textContent.trim();
  if (!hasTrack) {
    heartEl.style.display = 'none';
    dlEl.style.display = 'none';
    return;
  }

  heartEl.style.display = '';
  if (current) {
    const key = current.path || (current.id ? 'tidal:' + current.id : null);
    heartEl.classList.toggle('hearted', !!(key && _favCache[key]));
    dlEl.style.display = current.is_local ? 'none' : '';
  } else {
    // No queue context — check recent + audio src for download eligibility
    const recent = recentlyPlayed && recentlyPlayed[0];
    const audioSrc = document.getElementById('audio').src || '';
    const isStream = audioSrc.includes('/playback/stream/');
    const isLocal = recent ? recent.is_local : !isStream;
    dlEl.style.display = isLocal ? 'none' : '';
  }
}

// ---- PLAY COUNT (30-second actual-playback threshold) ----
let _playCountLogged = false;
let _playCountElapsed = 0;       // seconds of real playback accumulated
let _playCountLastTime = null;   // last audio.currentTime seen in timeupdate
let _playCountTrack = null;      // track being counted

function _logPlayEvent(track) {
  if (_playCountLogged) return;
  _playCountLogged = true;
  fetch('/api/home/play', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN },
    body: JSON.stringify({
      path: (track.is_local && track.local_path) ? track.local_path : (track.path || null),
      artist: track.artist || null,
      genre: track.genre || null,
      duration: track.duration || null,
    }),
  }).catch(() => {});
}

function _resetPlayCount(track) {
  _playCountLogged = false;
  _playCountElapsed = 0;
  _playCountLastTime = null;
  _playCountTrack = track;
}

function _tickPlayCount() {
  // Called on timeupdate — accumulate real playback delta
  if (_playCountLogged || !_playCountTrack) return;
  const ct = audio.currentTime;
  if (_playCountLastTime !== null) {
    const delta = ct - _playCountLastTime;
    // Only count forward playback between 0–2s delta (filters seeks and stalls)
    if (delta > 0 && delta < 2) {
      _playCountElapsed += delta;
    }
  }
  _playCountLastTime = ct;
  if (_playCountElapsed >= 30) {
    _logPlayEvent(_playCountTrack);
  }
}

function _recordRecentlyPlayed(track) {
  const key = _trackKey(track);
  const idx = recentlyPlayed.findIndex(t => {
    if (key === '') return false;
    if (track.isrc && t.isrc && track.isrc === t.isrc) return true;
    return _trackKey(t) === key;
  });
  if (idx !== -1) recentlyPlayed.splice(idx, 1);
  const entry = Object.assign({}, track, { played_at: Date.now() });
  recentlyPlayed.unshift(entry);
  if (recentlyPlayed.length > MAX_RECENT) recentlyPlayed.pop();
  _saveRecent();
}

function playTrack(track) {
  if (!track) return;

  // Play count: fires after 30s of actual playback (or on ended for short tracks)
  _resetPlayCount(track);

  // Stop current playback — mute to prevent bleed during source switch
  audio.pause();
  audio.muted = true;

  if (track.is_local && track.local_path) {
    audio.src = '/api/playback/local?path=' + encodeURIComponent(track.local_path);
  } else {
    audio.src = '/api/playback/stream/' + track.id;
  }

  // Wait for enough data before playing — prevents buffer underrun artifacts
  audio.addEventListener('canplay', function _onReady() {
    // Guard: if another tab sent 'pause' while we were loading, honour it
    if (!state.playing) { audio.muted = false; return; }
    audio.play().then(() => {
      audio.muted = false;
      // Only record to recently played after audio actually starts
      _recordRecentlyPlayed(track);
    }).catch(() => {
      audio.muted = false;
      toast('Unable to play track', 'error');
    });
  }, { once: true });
  state.playing = true;
  updatePlayButton();
  updateNowPlaying(track);
  handleLyricsTrackChange(track);
  _updateMediaSession(track);
  _fetchWaveform(track);
  highlightPlayingTrack();
  updatePlayerHeart();
  _saveQueue();
}

function updateNowPlaying(track) {
  const info = document.querySelector('.now-info');

  // Crossfade: dim out, update, dim back in
  if (info) info.classList.add('changing');

  setTimeout(() => {
    nowTitle.classList.remove('idle-clickable');
    nowTitle.removeAttribute('onclick');
    nowTitle.removeAttribute('title');
    // Clickable title → album
    nowTitle.textContent = track.name || 'Unknown';
    nowTitle.className = 'now-title now-link';
    nowTitle.onclick = () => {
      if (track.album_id) {
        navigateAlbum(track.album_id);
      } else if (track.album && track.artist) {
        navigate('localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album));
      }
    };

    // Clickable artist + album sub-line
    nowSub.textContent = '';
    const artistSpan = h('span', { className: 'now-link' });
    artistSpan.textContent = track.artist || '';
    artistSpan.onclick = (e) => {
      e.stopPropagation();
      if (track.artist) navigate('artist:' + encodeURIComponent(track.artist));
    };
    nowSub.appendChild(artistSpan);
    if (track.album) {
      nowSub.appendChild(document.createTextNode(' \u2014 '));
      const albumSpan = h('span', { className: 'now-link' });
      albumSpan.textContent = track.album;
      albumSpan.onclick = (e) => {
        e.stopPropagation();
        if (track.album_id) {
          navigateAlbum(track.album_id);
        } else if (track.artist) {
          navigate('localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album));
        }
      };
      nowSub.appendChild(albumSpan);
    }

    // Quality badge
    const nowQuality = document.getElementById('now-quality');
    if (nowQuality) {
      const q = track.quality || track.format || '';
      if (q) {
        nowQuality.textContent = qualityLabel(q);
        nowQuality.title = qualityTitle(q);
        nowQuality.className = 'quality-tag ' + qualityClass(q);
        nowQuality.style.display = '';
      } else {
        nowQuality.style.display = 'none';
      }
    }

    nowArt.classList.remove('idle-art');
    nowArt.classList.add('now-link-art');
    nowArt.setAttribute('aria-label', 'Open album');
    nowArt.onclick = () => {
      if (track.album_id) {
        navigateAlbum(track.album_id);
      } else if (track.album && track.artist) {
        navigate('localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album));
      }
    };
    const btnLyrics = document.getElementById('btn-lyrics');
    if (btnLyrics) {
      btnLyrics.disabled = !(track.is_local && (track.local_path || track.path));
    }
    while (nowArt.firstChild) nowArt.removeChild(nowArt.firstChild);
    if (track.cover_url) {
      nowArt.appendChild(h('img', { className: 'now-art-img', src: track.cover_url, alt: '' }));
    } else {
      nowArt.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(track.id) } }));
    }

    if (info) info.classList.remove('changing');
  }, 150);

  if (queuePanel.classList.contains('open')) renderQueue();
}

function updatePlayButton() {
  // SVG child elements need the SVG namespace to render
  while (playIcon.firstChild) playIcon.removeChild(playIcon.firstChild);
  const tmp = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  // SAFE: ICONS.pause and ICONS.play are hardcoded static SVG markup
  tmp.innerHTML = state.playing ? ICONS.pause : ICONS.play; // eslint-disable-line -- static SVG
  while (tmp.firstChild) playIcon.appendChild(tmp.firstChild);
}

function highlightPlayingTrack() {
  // Restore numbers on previously playing tracks
  document.querySelectorAll('.track.playing').forEach(t => {
    t.classList.remove('playing');
    const numCell = t.querySelector('.track-num');
    if (numCell) {
      const num = numCell.getAttribute('data-num') || '';
      while (numCell.firstChild) numCell.removeChild(numCell.firstChild);
      numCell.textContent = num;
    }
  });

  const currentTrack = state.queue[state.queueIndex];
  if (!currentTrack) return;
  const trackId = String(currentTrack.id);

  document.querySelectorAll('.track[data-track-id]').forEach(t => {
    if (t.getAttribute('data-track-id') === trackId) {
      t.classList.add('playing');
      const numCell = t.querySelector('.track-num');
      if (numCell) {
        while (numCell.firstChild) numCell.removeChild(numCell.firstChild);
        const bars = h('div', { className: 'eq-bars' + (state.playing ? '' : ' paused') });
        for (let i = 0; i < 4; i++) bars.appendChild(h('div', { className: 'eq-bar' }));
        numCell.appendChild(bars);
      }
    }
  });
}

// Transport controls
btnPlay.addEventListener('click', () => {
  if (!audio.src || audio.src === location.href) return;
  if (state.playing) {
    audio.pause();
    state.playing = false;
  } else {
    audio.play().catch(() => {});
    state.playing = true;
  }
  updatePlayButton();
});

btnNext.addEventListener('click', () => {
  if (state.queue.length === 0) return;
  state.queueIndex = (state.queueIndex + 1) % state.queue.length;
  playTrack(state.queue[state.queueIndex]);
});

btnPrev.addEventListener('click', () => {
  if (state.queue.length === 0) return;
  if (audio.currentTime > 3) {
    audio.currentTime = 0;
    return;
  }
  state.queueIndex = (state.queueIndex - 1 + state.queue.length) % state.queue.length;
  playTrack(state.queue[state.queueIndex]);
});

btnShuffle.addEventListener('click', () => {
  if (!state.queue.length) {
    state.shuffle = !state.shuffle;
    btnShuffle.classList.toggle('active', state.shuffle);
    _savePlayerPrefs();
    return;
  }
  if (state.shuffle) _restoreOriginalQueueOrder();
  else _reshuffleCurrentQueue();
  _savePlayerPrefs();
});

btnRepeat.addEventListener('click', () => {
  if (state.repeat === 'off') state.repeat = 'all';
  else if (state.repeat === 'all') state.repeat = 'one';
  else state.repeat = 'off';
  btnRepeat.classList.toggle('active', state.repeat !== 'off');
  _updateRepeatIcon(btnRepeat);
  // Repeat-one: collapse queue to just the current track
  if (state.repeat === 'one' && state.queue.length > 0) {
    const current = state.queue[state.queueIndex];
    if (current) {
      state.queue = [current];
      state.queueIndex = 0;
    }
  }
  _saveQueue();
  _savePlayerPrefs();
});

function _updateRepeatIcon(btn) {
  const badge = btn.querySelector('.repeat-one-badge');
  if (state.repeat === 'one') {
    if (!badge) {
      const b = document.createElement('span');
      b.className = 'repeat-one-badge';
      b.textContent = '1';
      btn.appendChild(b);
    }
  } else if (badge) {
    badge.remove();
  }
  btn.title = state.repeat === 'off' ? 'Repeat' : state.repeat === 'all' ? 'Repeat All' : 'Repeat One';
}

// Progress
audio.addEventListener('timeupdate', () => {
  if (!audio.duration) return;
  _tickPlayCount();
  // Skip UI updates while user is dragging the progress bar — _seekFromEvent
  // handles the display directly and the browser's currentTime lags behind.
  if (_seeking) return;
  const pct = (audio.currentTime / audio.duration) * 100;
  progressFill.style.width = pct + '%';
  timeElapsed.textContent = formatTime(audio.currentTime);
  timeTotal.textContent = formatTime(audio.duration);
});

audio.addEventListener('ended', () => {
  // Log play for short tracks that ended before 30s threshold
  const current = state.queue[state.queueIndex];
  if (current) _logPlayEvent(current);

  if (state.repeat === 'one') {
    // Re-trigger via playTrack for a clean source reload — currentTime=0 + play() is unreliable after 'ended'
    playTrack(current || state.queue[state.queueIndex]);
    return;
  }
  const hasNext = state.queueIndex < state.queue.length - 1;
  if (hasNext) {
    btnNext.click();
  } else if (state.repeat === 'all') {
    state.queueIndex = 0;
    playTrack(state.queue[0]);
  } else {
    state.playing = false;
    updatePlayButton();
    progressFill.style.width = '0%';
    timeElapsed.textContent = '0:00';
  }
});

audio.addEventListener('pause', () => {
  state.playing = false;
  updatePlayButton();
  setWaveformPlaying(false);
  document.querySelectorAll('.eq-bars').forEach(b => b.classList.add('paused'));
  // Freeze play count accumulation — resumes on next timeupdate after play
  _playCountLastTime = null;
});

let _consecutiveErrors = 0;

audio.addEventListener('error', () => {
  state.playing = false;
  updatePlayButton();
  setWaveformPlaying(false);
  _consecutiveErrors++;
  const current = state.queue[state.queueIndex];
  const label = current ? (current.name || 'Track') : 'Track';
  if (_consecutiveErrors >= 3) {
    toast('Multiple tracks failed \u2014 check your Tidal session', 'error');
    return;
  }
  const canAutoSkip = current && state.queueIndex < state.queue.length - 1;
  toast(label + ' unavailable', 'error');
  if (canAutoSkip) {
    setTimeout(() => { state.queueIndex++; playTrack(state.queue[state.queueIndex]); }, 800);
  }
});

audio.addEventListener('play', () => {
  _consecutiveErrors = 0;
  state.playing = true;
  updatePlayButton();
  setWaveformPlaying(true);
  document.querySelectorAll('.eq-bars').forEach(b => b.classList.remove('paused'));
  // Resume play count accumulation — timeupdate will pick it up automatically
  _playCountLastTime = audio.currentTime;
});

// Seek
let _seeking = false;

function _seekFromEvent(e) {
  if (!audio.duration) return;
  const rect = progressBar.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  audio.currentTime = pct * audio.duration;
  // Update UI immediately during seek so counter stays in sync
  progressFill.style.width = (pct * 100) + '%';
  timeElapsed.textContent = formatTime(pct * audio.duration);
}

progressBar.addEventListener('mousedown', (e) => {
  e.preventDefault();
  _seeking = true;
  _seekFromEvent(e);
  const onMove = (ev) => _seekFromEvent(ev);
  const onUp = () => {
    _seeking = false;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
});

progressBar.addEventListener('touchstart', (e) => {
  e.preventDefault();
  _seekFromEvent(e.touches[0]);
  const onMove = (ev) => _seekFromEvent(ev.touches[0]);
  const onEnd = () => {
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onEnd);
  };
  document.addEventListener('touchmove', onMove);
  document.addEventListener('touchend', onEnd);
}, { passive: false });

// Volume
const btnVol = document.getElementById('btn-vol');
let _volBeforeMute = 0.7;

function setVolume(pct) {
  state.volume = pct;
  audio.volume = pct;
  volFill.style.width = (pct * 100) + '%';
  btnVol.classList.toggle('muted', pct === 0);
  _savePlayerPrefs();
}

function _volFromEvent(e) {
  const rect = volSlider.getBoundingClientRect();
  return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
}

volSlider.addEventListener('click', (e) => {
  const pct = _volFromEvent(e);
  _volBeforeMute = pct || _volBeforeMute;
  setVolume(pct);
});

volSlider.addEventListener('mousedown', (e) => {
  e.preventDefault();
  volSlider.classList.add('dragging');
  setVolume(_volFromEvent(e));
  const onMove = (ev) => setVolume(_volFromEvent(ev));
  const onUp = () => {
    volSlider.classList.remove('dragging');
    _volBeforeMute = state.volume || _volBeforeMute;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
});

volSlider.addEventListener('touchstart', (e) => {
  e.preventDefault();
  volSlider.classList.add('dragging');
  setVolume(_volFromEvent(e.touches[0]));
  const onMove = (ev) => setVolume(_volFromEvent(ev.touches[0]));
  const onEnd = () => {
    volSlider.classList.remove('dragging');
    _volBeforeMute = state.volume || _volBeforeMute;
    document.removeEventListener('touchmove', onMove);
    document.removeEventListener('touchend', onEnd);
  };
  document.addEventListener('touchmove', onMove);
  document.addEventListener('touchend', onEnd);
}, { passive: false });

// Mute/unmute on icon click
btnVol.addEventListener('click', (e) => {
  e.stopPropagation();
  if (state.volume > 0) {
    _volBeforeMute = state.volume;
    setVolume(0);
  } else {
    setVolume(_volBeforeMute || 0.7);
  }
});

function _isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function _focusSearchShortcut() {
  navigate('search');
  setTimeout(() => {
    const input = document.querySelector('.search-input');
    if (input) input.focus();
  }, 100);
}

// Keyboard shortcuts (YouTube-style)
document.addEventListener('keydown', (e) => {
  if (_isTypingTarget(e.target)) return;
  if (e.code === 'Escape' && _lyricsOpen()) {
    e.preventDefault();
    closeLyricsPanel({ restoreFocus: true });
    return;
  }
  // Skip arrow/letter keys when card inspect overlay is open
  if (_inspect.isOpen()) return;
  if (e.altKey) return;

  const mod = e.metaKey || e.ctrlKey;
  if (mod) {
    if (e.code === 'KeyK') {
      e.preventDefault();
      _focusSearchShortcut();
      return;
    }
    if (e.code === 'KeyL') {
      const lyricsBtn = document.getElementById('btn-lyrics');
      if (lyricsBtn && !lyricsBtn.disabled) {
        e.preventDefault();
        lyricsBtn.click();
      }
      return;
    }
    if (e.shiftKey && e.code === 'KeyQ') {
      e.preventDefault();
      toggleQueue();
      return;
    }
    return;
  }

  // Shift combos
  if (e.shiftKey) {
    switch (e.code) {
      case 'KeyN': btnNext.click(); return;           // Shift+N — next track
      case 'KeyP': btnPrev.click(); return;           // Shift+P — previous track
      case 'Slash': toggleShortcutsHelp(); return;       // ? (Shift+/) — shortcuts help
      case 'Period':                                    // Shift+> — not applicable (no speed)
      case 'Comma': return;                             // Shift+< — not applicable
    }
  }

  switch (e.code) {
    case 'Space':                                       // Space — play/pause
    case 'KeyK':                                        // K — play/pause
      e.preventDefault();
      btnPlay.click();
      break;
    case 'KeyJ':                                        // J — rewind 10s
      audio.currentTime = Math.max(0, audio.currentTime - 10);
      break;
    case 'KeyL':                                        // L — forward 10s
      if (audio.duration) audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
      break;
    case 'ArrowRight':                                  // → — forward 10s
      if (audio.duration) audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
      break;
    case 'ArrowLeft':                                   // ← — rewind 10s
      audio.currentTime = Math.max(0, audio.currentTime - 10);
      break;
    case 'ArrowUp':                                     // ↑ — volume up 5%
      e.preventDefault();
      setVolume(Math.min(1, state.volume + 0.05));
      break;
    case 'ArrowDown':                                   // ↓ — volume down 5%
      e.preventDefault();
      setVolume(Math.max(0, state.volume - 0.05));
      break;
    case 'KeyM':                                        // M — mute/unmute
      btnVol.click();
      break;
    case 'Digit0':                                      // 0 — restart track
    case 'Home':
      audio.currentTime = 0;
      break;
    case 'End':                                         // End — jump to end
      if (audio.duration) audio.currentTime = audio.duration;
      break;
    case 'Slash':                                       // / — focus search
      e.preventDefault();
      _focusSearchShortcut();
      break;
  }

  // 1–9 — jump to 10%–90% of track
  if (e.code >= 'Digit1' && e.code <= 'Digit9' && audio.duration) {
    const pct = parseInt(e.code.replace('Digit', '')) / 10;
    audio.currentTime = audio.duration * pct;
  }
});

// ---- STATUS LIGHTS ----
const _flashed = new Set();
function flashError(el) {
  if (_flashed.has(el.id)) return;
  _flashed.add(el.id);
  el.style.background = 'rgba(224, 96, 96, 0.1)';
  el.style.borderRadius = 'var(--radius-xs)';
  el.style.transition = 'background 2s ease';
  setTimeout(() => { el.style.background = ''; }, 3000);
}
async function refreshStatusLights() {
  // Tidal auth
  const tidalEl = document.getElementById('connection-tidal');
  if (tidalEl) {
    try {
      const data = await api('/auth/status');
      while (tidalEl.firstChild) tidalEl.removeChild(tidalEl.firstChild);
      const dot = h('span', { className: 'connection-dot' + (data.logged_in ? '' : ' disconnected') });
      tidalEl.appendChild(dot);
      if (data.logged_in) {
        tidalEl.appendChild(document.createTextNode('tidal \u00b7 ' + (data.username || 'connected')));
        tidalEl.style.cursor = '';
        tidalEl.onclick = null;
      } else {
        tidalEl.appendChild(document.createTextNode('tidal \u00b7 log in'));
        tidalEl.style.cursor = 'pointer';
        tidalEl.onclick = triggerLogin;
      }
    } catch (_) { /* leave default */ }
  }

  // HiFi servers
  const hifiEl = document.getElementById('connection-hifi');
  if (hifiEl) {
    try {
      const data = await api('/hifi/status');
      while (hifiEl.firstChild) hifiEl.removeChild(hifiEl.firstChild);
      const alive = data.alive || 0;
      const dot = h('span', { className: 'connection-dot' + (alive > 0 ? '' : ' disconnected') });
      hifiEl.appendChild(dot);
      hifiEl.appendChild(document.createTextNode('tidal-servers \u00b7 ' + alive + ' up'));
      if (alive === 0) flashError(hifiEl);
    } catch (err) {
      console.error('[music-dl] hifi status check failed:', err);
    }
  }
}

let _loginPoll = null;

async function _handleLoginSuccess() {
  refreshStatusLights();
  await _checkErrorBanners();
  const authSection = document.getElementById('settings-auth-status');
  if (authSection) await loadAuthStatus(authSection);
  toast('Connected to Tidal', 'success');
}

function _openExternal(url) {
  // Prefer Tauri shell plugin (opens user's default browser), fall back to window.open
  if (_isTauri() && window.__TAURI__?.core?.invoke) {
    window.__TAURI__.core.invoke('plugin:shell|open', { path: url, with: '' })
      .catch(() => window.open(url, '_blank'));
  } else {
    window.open(url, '_blank');
  }
}

function _showDeviceCodeModal(userCode, verificationUri) {
  _dismissDeviceCodeModal();
  const overlay = h('div', { className: 'modal-overlay', id: 'device-code-modal' });
  overlay.addEventListener('click', e => { if (e.target === overlay) _dismissDeviceCodeModal(); });

  const modal = h('div', { className: 'modal device-code-modal' });
  modal.appendChild(textEl('h3', 'Connect to Tidal'));
  modal.appendChild(textEl('p', 'Open the link below and enter this code:', 'device-code-label'));

  const codeEl = h('div', { className: 'code device-code-value' });
  codeEl.textContent = userCode;
  codeEl.title = 'Click to copy';
  codeEl.style.cursor = 'pointer';
  codeEl.addEventListener('click', () => {
    navigator.clipboard.writeText(userCode).then(() => toast('Code copied', 'success'));
  });
  modal.appendChild(codeEl);

  if (verificationUri) {
    const linkEl = h('a', {
      className: 'wizard-link',
      href: verificationUri,
      target: '_blank',
      rel: 'noopener',
    });
    linkEl.textContent = verificationUri;
    linkEl.addEventListener('click', e => { e.preventDefault(); _openExternal(verificationUri); });
    modal.appendChild(linkEl);
  }

  const spinnerRow = h('div', { className: 'wizard-spinner-row' });
  spinnerRow.appendChild(h('div', { className: 'spinner' }));
  spinnerRow.appendChild(textEl('span', 'Waiting for you to confirm in browser...', 'wizard-waiting-text'));
  modal.appendChild(spinnerRow);

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

function _dismissDeviceCodeModal() {
  const existing = document.getElementById('device-code-modal');
  if (existing) existing.remove();
}

async function triggerLogin() {
  const tidalEl = document.getElementById('connection-tidal');
  try {
    const data = await api('/auth/login', { method: 'POST' });
    if (data.status === 'already_logged_in') {
      await _handleLoginSuccess();
      return;
    }

    // Show device code modal so user always has the code + link visible in-app
    if (data.user_code) {
      _showDeviceCodeModal(data.user_code, data.verification_uri);
    }

    // Also try to auto-open the verification URL in the default browser
    if (data.verification_uri) {
      _openExternal(data.verification_uri);
    }

    // Update sidebar light to show waiting state
    if (tidalEl) {
      while (tidalEl.firstChild) tidalEl.removeChild(tidalEl.firstChild);
      const dot = h('span', { className: 'connection-dot disconnected' });
      tidalEl.appendChild(dot);
      tidalEl.appendChild(document.createTextNode('tidal \u00b7 waiting...'));
      tidalEl.onclick = null;
    }
    // Poll until login completes
    if (_loginPoll) clearInterval(_loginPoll);
    _loginPoll = setInterval(async () => {
      try {
        const status = await api('/auth/login/status');
        if (status.status === 'success') {
          clearInterval(_loginPoll);
          _loginPoll = null;
          _dismissDeviceCodeModal();
          await _handleLoginSuccess();
        } else if (status.status === 'failed' || status.status === 'timeout') {
          clearInterval(_loginPoll);
          _loginPoll = null;
          _dismissDeviceCodeModal();
          const msg = status.status === 'timeout'
            ? 'Tidal login timed out — tap the status light to try again'
            : 'Tidal login failed — tap the status light to try again';
          toast(msg, 'error');
          refreshStatusLights();
        }
      } catch (_) {
        clearInterval(_loginPoll);
        _loginPoll = null;
        _dismissDeviceCodeModal();
        toast('Connection lost during login — tap the status light to retry', 'error');
        refreshStatusLights();
      }
    }, 3000);
  } catch (err) {
    console.error('[music-dl] login failed:', err);
    toast('Could not start Tidal login — check your connection', 'error');
    refreshStatusLights();
  }
}

// ---- QUEUE PANEL ----
const queuePanel = document.getElementById('queue-panel');
const queueListEl = document.getElementById('queue-list');
const btnQueueClose = document.getElementById('queue-close');

function toggleQueue() {
  const opening = !queuePanel.classList.contains('open');
  if (opening && _lyricsOpen()) closeLyricsPanel();
  queuePanel.classList.toggle('open');
  if (queuePanel.classList.contains('open')) renderQueue();
}

function renderQueue() {
  while (queueListEl.firstChild) queueListEl.removeChild(queueListEl.firstChild);

  if (!state.queue.length) {
    const empty = h('div', { className: 'queue-item' });
    empty.textContent = 'Queue is empty';
    empty.style.color = 'var(--text-muted)';
    empty.style.justifyContent = 'center';
    queueListEl.appendChild(empty);
    return;
  }

  state.queue.forEach((track, i) => {
    const item = h('div', {
      className: 'queue-item' + (i === state.queueIndex ? ' qi-active' : ''),
    });

    const art = h('img', { className: 'queue-item-art', alt: '' });
    art.src = track.cover_url || '';
    art.onerror = function() { this.style.background = 'var(--surface)'; this.removeAttribute('src'); };

    const info = h('div', { className: 'queue-item-info' });
    info.appendChild(textEl('div', track.name || 'Unknown', 'queue-item-title'));
    info.appendChild(textEl('div', track.artist || '', 'queue-item-artist'));

    const remove = h('button', {
      className: 'queue-item-remove',
      'aria-label': 'Remove from queue',
    });
    remove.textContent = '\u00d7';
    remove.addEventListener('click', (e) => {
      e.stopPropagation();
      const removedTrack = state.queue[i];
      state.queue.splice(i, 1);
      const originalIdx = _findTrackIndex(state.queueOriginal, removedTrack);
      if (originalIdx !== -1) state.queueOriginal.splice(originalIdx, 1);
      if (i < state.queueIndex) state.queueIndex--;
      else if (i === state.queueIndex && state.queue.length === 0) {
        state.queueIndex = -1;
      } else if (i === state.queueIndex && state.queueIndex >= state.queue.length) {
        state.queueIndex = state.queue.length - 1;
      }
      renderQueue();
      _saveQueue();
    });

    item.addEventListener('click', () => {
      state.queueIndex = i;
      playTrack(state.queue[i]);
      renderQueue();
    });

    item.appendChild(art);
    item.appendChild(info);
    item.appendChild(remove);
    queueListEl.appendChild(item);
  });
}

document.getElementById('btn-queue').addEventListener('click', toggleQueue);
btnQueueClose.addEventListener('click', toggleQueue);

const btnLyricsToggle = document.getElementById('btn-lyrics');
if (btnLyricsToggle) {
  btnLyricsToggle.addEventListener('click', () => {
    if (btnLyricsToggle.disabled) return;
    if (_lyricsOpen()) {
      closeLyricsPanel({ restoreFocus: true });
    } else {
      openLyricsPanel({ focusReturnEl: btnLyricsToggle });
    }
  });
}

// Close queue panel on click outside
document.addEventListener('click', (e) => {
  if (!queuePanel.classList.contains('open')) return;
  if (queuePanel.contains(e.target)) return;
  // Don't close if clicking the queue toggle button itself
  if (document.getElementById('btn-queue').contains(e.target)) return;
  toggleQueue();
});

// ---- UPGRADE SCANNER ----

async function renderUpgradeScanner(container) {
  const wrapper = h('div', { className: 'upgrade-scanner-view' });
  container.appendChild(wrapper);

  wrapper.appendChild(breadcrumb([{ label: 'Library', view: 'library' }, { label: 'Quality Upgrades' }]));

  const header = h('div', { className: 'upgrade-scanner-header' });
  header.appendChild(textEl('h2', 'Quality Upgrade Scanner', 'section-title'));

  const statusEl = h('div', { className: 'upgrade-scanner-status' });
  statusEl.textContent = 'Scan your library for tracks available at higher quality on Tidal.';
  header.appendChild(statusEl);

  const controls = h('div', { className: 'upgrade-scanner-controls' });
  const scanBtn = h('button', { className: 'pill active' });
  scanBtn.textContent = 'Start Scan';
  const cancelBtn = h('button', { className: 'pill' });
  cancelBtn.textContent = 'Cancel';
  cancelBtn.style.display = 'none';
  const purgeBtn = h('button', { className: 'pill' });
  purgeBtn.textContent = 'Clear Probe Cache';
  purgeBtn.title = 'Purge cached Tidal quality probes so the next scan re-probes all tracks fresh';
  purgeBtn.onclick = async () => {
    purgeBtn.disabled = true;
    purgeBtn.textContent = 'Clearing...';
    try {
      const res = await api('/upgrade/probes', { method: 'DELETE' });
      toast((res.deleted || 0) + ' cached probes cleared', 'success');
    } catch (_) {
      toast('Failed to clear probes', 'error');
    }
    purgeBtn.disabled = false;
    purgeBtn.textContent = 'Clear Probe Cache';
  };
  controls.appendChild(scanBtn);
  controls.appendChild(cancelBtn);
  controls.appendChild(purgeBtn);
  header.appendChild(controls);
  wrapper.appendChild(header);

  const progressBar = h('div', { className: 'upgrade-progress-bar' });
  const progressFill = h('div', { className: 'upgrade-progress-fill' });
  progressBar.appendChild(progressFill);
  progressBar.style.display = 'none';
  wrapper.appendChild(progressBar);

  const resultsEl = h('div', { className: 'upgrade-results' });
  wrapper.appendChild(resultsEl);

  let eventSource = null;

  function _scanProgressText(d) {
    if (d.phase) return d.phase;
    return 'Checked ' + d.checked + ' / ' + d.total + ' \u2014 ' + d.upgradeable + ' upgradeable' + (d.skipped_no_isrc ? ' \u2014 ' + d.skipped_no_isrc + ' skipped (no ISRC)' : '');
  }
  function _scanDoneText(d) {
    return 'Done: ' + d.upgradeable + ' upgradeable of ' + d.checked + ' checked' + (d.skipped_no_isrc ? ' (' + d.skipped_no_isrc + ' skipped, no ISRC)' : '');
  }

  function _handleScanEvent(data) {
    if (data.type === 'scan_progress') {
      const pct = data.total > 0 ? Math.round((data.checked / data.total) * 100) : 0;
      progressFill.style.width = pct + '%';
      statusEl.textContent = _scanProgressText(data);
    } else if (data.type === 'scan_complete') {
      progressFill.style.width = '100%';
      statusEl.textContent = _scanDoneText(data);
      scanBtn.disabled = false;
      scanBtn.textContent = 'Scan Again';
      cancelBtn.style.display = 'none';
      if (eventSource) { eventSource.close(); eventSource = null; }
      _renderScanResults(resultsEl, data.results || []);
    } else if (data.type === 'scan_error') {
      statusEl.textContent = 'Error: ' + data.error;
      scanBtn.disabled = false;
      scanBtn.textContent = 'Retry';
      cancelBtn.style.display = 'none';
      if (eventSource) { eventSource.close(); eventSource = null; }
    } else if (data.type === 'scan_cancelled') {
      statusEl.textContent = 'Scan cancelled.';
      scanBtn.disabled = false;
      scanBtn.textContent = 'Start Scan';
      cancelBtn.style.display = 'none';
      if (eventSource) { eventSource.close(); eventSource = null; }
    }
  }

  function _connectSSE() {
    if (eventSource) { eventSource.close(); }
    eventSource = new EventSource('/api/upgrade/scan');
    eventSource.onmessage = (e) => _handleScanEvent(JSON.parse(e.data));
    eventSource.onerror = () => {
      statusEl.textContent = 'Connection lost.';
      scanBtn.disabled = false;
      scanBtn.textContent = 'Retry';
      cancelBtn.style.display = 'none';
    };
  }

  function _startScan() {
    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';
    cancelBtn.style.display = '';
    progressBar.style.display = '';
    while (resultsEl.firstChild) resultsEl.removeChild(resultsEl.firstChild);
    _connectSSE();
  }

  scanBtn.addEventListener('click', _startScan);

  cancelBtn.addEventListener('click', async () => {
    if (eventSource) { eventSource.close(); eventSource = null; }
    try { await api('/upgrade/scan/cancel', { method: 'POST' }); } catch (_) {}
    cancelBtn.style.display = 'none';
    scanBtn.disabled = false;
    scanBtn.textContent = 'Start Scan';
  });

  // Restore state from backend on mount (lightweight — no results payload)
  try {
    const cached = await api('/upgrade/scan/status');
    if (cached.status === 'running') {
      scanBtn.disabled = true;
      scanBtn.textContent = 'Scanning...';
      cancelBtn.style.display = '';
      progressBar.style.display = '';
      if (cached.total > 0) {
        const pct = Math.round((cached.checked / cached.total) * 100);
        progressFill.style.width = pct + '%';
        statusEl.textContent = _scanProgressText(cached);
      } else {
        statusEl.textContent = 'Scan in progress\u2026';
      }
      _connectSSE();
    } else if (cached.status === 'complete') {
      progressBar.style.display = '';
      progressFill.style.width = '100%';
      statusEl.textContent = _scanDoneText(cached);
      scanBtn.textContent = 'Scan Again';
      // Fetch full results separately (can be 600KB+)
      api('/upgrade/scan/status?include_results=true').then(full => {
        _renderScanResults(resultsEl, full.results || []);
      }).catch(() => {
        statusEl.textContent = _scanDoneText(cached) + ' (failed to load results — scan again)';
      });
    } else if (cached.status === 'error') {
      statusEl.textContent = 'Error: ' + (cached.error || 'Unknown error');
      scanBtn.textContent = 'Retry';
    }
  } catch (_) {
    // Status endpoint unavailable — fall through to default idle state
  }

  // Register cleanup so navigate() closes the EventSource before tearing down DOM
  viewEl._viewCleanup = () => { if (eventSource) { eventSource.close(); eventSource = null; } };
}

function _renderScanResults(container, results) {
  if (!results.length) {
    container.appendChild(textEl('div', 'All tracks are at their best available quality.', 'upgrade-empty'));
    return;
  }

  // Group by quality jump
  const groups = {};
  results.forEach(r => {
    const key = qualityLabel(r.current_quality) + ' \u2192 ' + qualityLabel(r.available_quality);
    if (!groups[key]) groups[key] = [];
    groups[key].push(r);
  });

  // "Upgrade All" button
  const upgradeAllBtn = h('button', { className: 'pill active upgrade-all-btn' });
  upgradeAllBtn.textContent = 'Upgrade All (' + results.length + ' tracks)';
  upgradeAllBtn.addEventListener('click', async () => {
    upgradeAllBtn.disabled = true;
    upgradeAllBtn.textContent = 'Upgrading...';
    const tracks = results.map(r => ({ path: r.path, tidal_track_id: r.tidal_track_id || null }));
    try {
      const resp = await api('/upgrade/start', { method: 'POST', body: { tracks } });
      if (resp.count > 0) { updateDlBadge(resp.count); _ensureGlobalSSE(); }
      toast('Upgrade started for ' + resp.count + ' tracks', 'success');
    } catch (err) {
      toast('Upgrade failed', 'error');
      upgradeAllBtn.disabled = false;
      upgradeAllBtn.textContent = 'Upgrade All (' + results.length + ' tracks)';
    }
  });
  container.appendChild(upgradeAllBtn);

  Object.entries(groups).forEach(([label, tracks]) => {
    const groupEl = h('div', { className: 'upgrade-group' });
    const groupHeader = h('div', { className: 'upgrade-group-header' });
    groupHeader.textContent = label + ' (' + tracks.length + ' tracks)';
    groupEl.appendChild(groupHeader);

    tracks.forEach(t => {
      const row = h('div', { className: 'upgrade-row' });
      row.appendChild(textEl('span', t.title || '', 'upgrade-row-title'));
      row.appendChild(textEl('span', t.artist || '', 'upgrade-row-artist'));
      row.appendChild(textEl('span', qualityLabel(t.current_quality) + ' \u2192 ' + qualityLabel(t.available_quality), 'upgrade-row-quality'));
      const upBtn = h('button', { className: 'pill small' });
      upBtn.textContent = 'Upgrade';
      upBtn.addEventListener('click', async () => {
        upBtn.disabled = true;
        upBtn.textContent = 'Queued';
        try {
          const resp = await api('/upgrade/start', { method: 'POST', body: {
            tracks: [{ path: t.path, tidal_track_id: t.tidal_track_id || null }]
          }});
          if (resp.count > 0) { updateDlBadge(resp.count); _ensureGlobalSSE(); }
          else if (resp.errors && resp.errors.length) { throw new Error(resp.errors[0]); }
        } catch (err) {
          toast('Upgrade failed: ' + (err.message || 'unknown'), 'error');
          upBtn.disabled = false;
          upBtn.textContent = 'Retry';
        }
      });
      row.dataset.trackPath = t.path;
      row.appendChild(upBtn);
      groupEl.appendChild(row);
    });

    container.appendChild(groupEl);
  });
}

// ---- SETUP WIZARD ----

async function _checkSetup() {
  try {
    const resp = await fetch('/api/setup/status');
    const data = await resp.json();
    // Allow app access if at least one source is configured:
    // - Tidal login for streaming, OR
    // - Local scan paths for offline playback
    // Only block with wizard if NOTHING is configured.
    const hasAnySource = data.logged_in || data.scan_paths_configured;
    if (!hasAnySource) {
      _renderWizard(data);
      return true;
    }
  } catch (e) {
    console.error('Setup check failed:', e);
  }
  return false;
}

function _renderWizard(setupData) {
  // Hide sidebar + player, show wizard fullscreen
  const appEl = document.querySelector('.app');
  const playerEl = document.querySelector('.player');
  if (appEl) appEl.style.display = 'none';
  if (playerEl) playerEl.style.display = 'none';

  // Remove any existing wizard
  const existing = document.querySelector('.setup-wizard');
  if (existing) existing.remove();

  const wizard = h('div', { className: 'setup-wizard' });
  document.body.appendChild(wizard);

  if (!setupData.logged_in && !setupData.scan_paths_configured) {
    _wizardStepLogin(wizard, setupData);
  } else if (!setupData.scan_paths_configured) {
    _wizardStepPaths(wizard);
  } else if (!setupData.logged_in) {
    // Has local paths but no Tidal - show login with skip option
    _wizardStepLogin(wizard, setupData);
  }
}

function _teardownWizard() {
  const wizard = document.querySelector('.setup-wizard');
  if (wizard) wizard.remove();
  const appEl = document.querySelector('.app');
  const playerEl = document.querySelector('.player');
  if (appEl) appEl.style.display = '';
  if (playerEl) playerEl.style.display = '';
}

function _wizardStepLogin(wizard, setupData) {
  while (wizard.firstChild) wizard.removeChild(wizard.firstChild);

  // Check if we can at least access local music (offline mode)
  const canPlayOffline = setupData.scan_paths_configured;

  const card = h('div', { className: 'wizard-card' });

  // Show offline-capable banner if applicable
  if (canPlayOffline && !setupData.logged_in) {
    const offlineBanner = h('div', { className: 'wizard-offline-banner' });
    offlineBanner.innerHTML = '<strong>Offline mode available</strong><br>Your local music library is ready. Connect Tidal to stream online.';
    card.appendChild(offlineBanner);
  }

  // Step indicator
  card.appendChild(textEl('div', 'Connect Tidal for streaming (optional if you have local music)', 'wizard-step-label'));
  card.appendChild(textEl('h2', 'Connect your Tidal account', 'wizard-title'));
  card.appendChild(textEl('p', 'Sign in to stream and download from Tidal. You\'ll be given a code to enter on Tidal\'s website.', 'wizard-desc'));

  const connectBtn = textEl('button', 'Connect to Tidal', 'wizard-btn');
  const statusArea = h('div', { className: 'wizard-status' });

  connectBtn.addEventListener('click', async () => {
    connectBtn.disabled = true;
    connectBtn.textContent = 'Starting...';
    statusArea.textContent = '';

    try {
      const data = await api('/auth/login', { method: 'POST' });

      if (data.status === 'already_logged_in') {
        // Re-check setup and advance
        const fresh = await fetch('/api/setup/status').then(r => r.json());
        if (fresh.setup_complete) {
          _teardownWizard();
          _initApp();
        } else {
          _renderWizard(fresh);
        }
        return;
      }

      // Show device code
      while (statusArea.firstChild) statusArea.removeChild(statusArea.firstChild);

      const codeBox = h('div', { className: 'device-code' });
      codeBox.appendChild(textEl('div', 'Go to the link below and enter this code:', 'device-code-label'));

      const codeEl = h('div', { className: 'code' });
      codeEl.textContent = data.user_code || '';
      codeBox.appendChild(codeEl);

      if (data.verification_uri) {
        const linkEl = h('a', {
          className: 'wizard-link',
          href: data.verification_uri,
          target: '_blank',
          rel: 'noopener',
        });
        linkEl.textContent = data.verification_uri;
        linkEl.addEventListener('click', e => { e.preventDefault(); _openExternal(data.verification_uri); });
        codeBox.appendChild(linkEl);

        // Also auto-open in browser
        _openExternal(data.verification_uri);
      }

      statusArea.appendChild(codeBox);

      const spinnerRow = h('div', { className: 'wizard-spinner-row' });
      spinnerRow.appendChild(h('div', { className: 'spinner' }));
      spinnerRow.appendChild(textEl('span', 'Waiting for you to confirm in browser...', 'wizard-waiting-text'));
      statusArea.appendChild(spinnerRow);

      connectBtn.textContent = 'Waiting...';

      // Poll login status
      const poll = setInterval(async () => {
        try {
          const status = await api('/auth/login/status');
          if (status.status === 'success') {
            clearInterval(poll);
            // Re-check setup and advance
            const fresh = await fetch('/api/setup/status').then(r => r.json());
            if (fresh.setup_complete) {
              _teardownWizard();
              _initApp();
            } else {
              _renderWizard(fresh);
            }
          } else if (status.status === 'failed' || status.status === 'timeout') {
            clearInterval(poll);
            while (statusArea.firstChild) statusArea.removeChild(statusArea.firstChild);
            const errMsg = status.status === 'timeout'
              ? 'Login timed out. Please try again.'
              : 'Login failed. Please try again.';
            statusArea.appendChild(textEl('div', errMsg, 'wizard-error'));
            connectBtn.disabled = false;
            connectBtn.textContent = 'Retry';
          }
        } catch (_) {
          clearInterval(poll);
          statusArea.appendChild(textEl('div', 'Connection lost. Please try again.', 'wizard-error'));
          connectBtn.disabled = false;
          connectBtn.textContent = 'Retry';
        }
      }, 2000);

    } catch (err) {
      statusArea.appendChild(textEl('div', 'Failed to start login: ' + err.message, 'wizard-error'));
      connectBtn.disabled = false;
      connectBtn.textContent = 'Retry';
    }
  });

  card.appendChild(connectBtn);
  card.appendChild(statusArea);

  // Add skip button for offline users
  if (canPlayOffline) {
    const skipBtn = textEl('button', 'Skip and use local library only', 'wizard-btn wizard-btn-secondary');
    skipBtn.addEventListener('click', () => {
      _teardownWizard();
      _initApp();
    });
    card.appendChild(skipBtn);
  }

  wizard.appendChild(card);
}

function _wizardStepPaths(wizard) {
  while (wizard.firstChild) wizard.removeChild(wizard.firstChild);

  const card = h('div', { className: 'wizard-card' });
  const paths = [];

  // Step indicator
  card.appendChild(textEl('div', 'Step 2 of 2', 'wizard-step-label'));
  card.appendChild(textEl('h2', 'Where\'s your music?', 'wizard-title'));
  card.appendChild(textEl('p', 'Tell us where to find your existing music files. You can add multiple folders.', 'wizard-desc'));

  // Path input row
  const inputRow = h('div', { className: 'path-input-row' });
  const pathInput = h('input', { className: 'settings-input wizard-path-input', type: 'text', placeholder: '/path/to/your/music' });
  inputRow.appendChild(pathInput);

  const browseBtn = textEl('button', 'Browse', 'wizard-btn-sm');
  browseBtn.addEventListener('click', async () => {
    browseBtn.textContent = '...';
    try {
      const result = await api('/browse-directory', { method: 'POST' });
      if (result.path) {
        pathInput.value = result.path;
      }
    } catch (err) {
      if (!err.message.includes('No directory selected')) {
        toast('Browse failed: ' + err.message, 'error');
      }
    }
    browseBtn.textContent = 'Browse';
  });
  inputRow.appendChild(browseBtn);

  const addBtn = textEl('button', 'Add', 'wizard-btn-sm');
  addBtn.addEventListener('click', async () => {
    const val = pathInput.value.trim();
    if (!val) return;
    if (paths.includes(val)) {
      toast('Path already added', 'error');
      return;
    }

    // Validate path
    addBtn.disabled = true;
    addBtn.textContent = '...';
    try {
      const check = await api('/setup/validate-path', { method: 'POST', body: { path: val } });
      if (!check.valid) {
        toast(check.error || 'Invalid path', 'error');
        addBtn.disabled = false;
        addBtn.textContent = 'Add';
        return;
      }
    } catch (err) {
      toast('Validation failed: ' + err.message, 'error');
      addBtn.disabled = false;
      addBtn.textContent = 'Add';
      return;
    }

    paths.push(val);
    pathInput.value = '';
    addBtn.disabled = false;
    addBtn.textContent = 'Add';
    _renderPathList();
  });
  inputRow.appendChild(addBtn);

  card.appendChild(inputRow);

  // Path list
  const pathListEl = h('div', { className: 'wizard-paths' });
  card.appendChild(pathListEl);

  function _renderPathList() {
    while (pathListEl.firstChild) pathListEl.removeChild(pathListEl.firstChild);
    paths.forEach((p, i) => {
      const row = h('div', { className: 'wizard-path-row' });
      const pathText = textEl('span', p, 'wizard-path-text');
      row.appendChild(pathText);
      const removeBtn = textEl('button', '\u00d7', 'wizard-path-remove');
      removeBtn.addEventListener('click', () => {
        paths.splice(i, 1);
        _renderPathList();
      });
      row.appendChild(removeBtn);
      pathListEl.appendChild(row);
    });
    continueBtn.disabled = paths.length === 0;
  }

  // Continue button
  const statusArea = h('div', { className: 'wizard-status' });
  const continueBtn = textEl('button', 'Continue', 'wizard-btn');
  continueBtn.disabled = true;

  continueBtn.addEventListener('click', async () => {
    if (paths.length === 0) return;
    continueBtn.disabled = true;
    continueBtn.textContent = 'Saving...';

    try {
      // Save scan_paths + set download path to first scan path
      await api('/settings', { method: 'PATCH', body: { scan_paths: paths.join(','), download_base_path: paths[0] } });

      // Start initial scan
      continueBtn.textContent = 'Starting library scan...';
      await api('/library/scan', { method: 'POST' }).catch(() => {});

      // Done — launch the app
      _teardownWizard();
      _initApp();
    } catch (err) {
      statusArea.appendChild(textEl('div', 'Failed to save: ' + err.message, 'wizard-error'));
      continueBtn.disabled = false;
      continueBtn.textContent = 'Continue';
    }
  });

  card.appendChild(continueBtn);
  card.appendChild(statusArea);
  wizard.appendChild(card);
}

// ---- ERROR BANNERS ----

async function _checkErrorBanners() {
  // Remove existing banners
  document.querySelectorAll('.error-banner').forEach(b => b.remove());

  // Check auth status
  try {
    const auth = await api('/auth/status');
    if (!auth.logged_in) {
      const banner = h('div', { className: 'error-banner' });
      banner.appendChild(textEl('span', 'Tidal session expired.'));
      const reloginBtn = textEl('button', 'Re-connect', 'banner-action');
      reloginBtn.addEventListener('click', () => triggerLogin());
      banner.appendChild(reloginBtn);
      const mainEl = document.querySelector('.main');
      if (mainEl) mainEl.insertBefore(banner, mainEl.firstChild);
    }
  } catch (_) { /* silent */ }

  // Library views: check scan_paths
  if (state.view === 'library' || state.view === 'recent-added') {
    try {
      const settings = state.settings || await api('/settings');
      const scanPaths = (settings.scan_paths || '').trim();
      if (!scanPaths) {
        const banner = h('div', { className: 'error-banner' });
        banner.appendChild(textEl('span', 'No music directories configured.'));
        const settingsBtn = textEl('button', 'Set up', 'banner-action');
        settingsBtn.addEventListener('click', () => navigate('settings'));
        banner.appendChild(settingsBtn);
        const mainEl = document.querySelector('.main');
        if (mainEl) mainEl.insertBefore(banner, mainEl.firstChild);
      }
    } catch (_) { /* silent */ }
  }
}

// ---- INIT ----

// ── Media Session API — OS media controls (headphones, lock screen, menu bar) ──

function _updateMediaSession(track) {
  if (!('mediaSession' in navigator)) return;
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.name || 'Unknown',
    artist: track.artist || '',
    album: track.album || '',
    artwork: track.cover_url ? [{ src: track.cover_url, sizes: '320x320', type: 'image/jpeg' }] : [],
  });
}

if ('mediaSession' in navigator) {
  navigator.mediaSession.setActionHandler('play', () => { if (!state.playing) btnPlay.click(); });
  navigator.mediaSession.setActionHandler('pause', () => { if (state.playing) btnPlay.click(); });
  navigator.mediaSession.setActionHandler('previoustrack', () => btnPrev.click());
  navigator.mediaSession.setActionHandler('nexttrack', () => btnNext.click());
  navigator.mediaSession.setActionHandler('seekto', (d) => { if (d.seekTime != null) audio.currentTime = d.seekTime; });
  navigator.mediaSession.setActionHandler('seekbackward', (d) => { audio.currentTime = Math.max(0, audio.currentTime - (d.seekOffset || 10)); });
  navigator.mediaSession.setActionHandler('seekforward', (d) => { if (audio.duration) audio.currentTime = Math.min(audio.duration, audio.currentTime + (d.seekOffset || 10)); });
}

// ── Gapless Playback — preload next track so no gap on transition ──

const _preloadAudio = document.getElementById('audio-preload');
let _preloadedSrc = '';

function _preloadNext() {
  if (state.queue.length === 0 || state.repeat === 'one') return;
  const nextIdx = (state.queueIndex + 1) % state.queue.length;
  const next = state.queue[nextIdx];
  if (!next) return;
  const src = (next.is_local && next.local_path)
    ? '/api/playback/local?path=' + encodeURIComponent(next.local_path)
    : '/api/playback/stream/' + next.id;
  if (_preloadedSrc === src) return;  // already preloaded
  _preloadedSrc = src;
  _preloadAudio.src = src;
  _preloadAudio.load();
}

// Trigger preload once we have enough of the current track
audio.addEventListener('canplaythrough', () => _preloadNext());

// ── Queue Persistence — survive page reloads ──

function _savePlayerPrefs() {
  try {
    localStorage.setItem('playerPrefs', JSON.stringify({
      volume: state.volume,
      shuffle: state.shuffle,
      repeat: state.repeat,
      smartShuffle: state.smartShuffle,
    }));
  } catch (_) {}
}

function _restorePlayerPrefs() {
  try {
    const raw = localStorage.getItem('playerPrefs');
    if (!raw) return;
    const prefs = JSON.parse(raw);
    if (typeof prefs.volume === 'number') {
      state.volume = Math.max(0, Math.min(1, prefs.volume));
      audio.volume = state.volume;
      volFill.style.width = (state.volume * 100) + '%';
      btnVol.classList.toggle('muted', state.volume === 0);
    }
    if (typeof prefs.shuffle === 'boolean') {
      state.shuffle = prefs.shuffle;
      btnShuffle.classList.toggle('active', state.shuffle);
    }
    if (['off', 'all', 'one'].includes(prefs.repeat)) {
      state.repeat = prefs.repeat;
      btnRepeat.classList.toggle('active', state.repeat !== 'off');
      _updateRepeatIcon(btnRepeat);
    }
    state.smartShuffle = !!prefs.smartShuffle;
  } catch (_) {}
}

function _saveQueue() {
  try {
    const data = { queue: state.queue, queueOriginal: state.queueOriginal, queueIndex: state.queueIndex, shuffle: state.shuffle, repeat: state.repeat };
    localStorage.setItem('playerQueue', JSON.stringify(data));
  } catch (_) { /* quota exceeded — ignore */ }
}

function _restoreQueue() {
  try {
    const raw = localStorage.getItem('playerQueue');
    if (!raw) return;
    const data = JSON.parse(raw);
    if (data.queue && data.queue.length > 0) {
      state.queue = data.queue;
      state.queueOriginal = (data.queueOriginal && data.queueOriginal.length > 0) ? data.queueOriginal : data.queue.slice();
      state.queueIndex = typeof data.queueIndex === 'number' ? data.queueIndex : 0;
      state.shuffle = !!data.shuffle;
      state.repeat = data.repeat || 'off';
      btnShuffle.classList.toggle('active', state.shuffle);
      btnRepeat.classList.toggle('active', state.repeat !== 'off');
      _updateRepeatIcon(btnRepeat);
      // Show now-playing info without auto-playing
      const current = state.queue[state.queueIndex];
      if (current) updateNowPlaying(current);
    }
  } catch (_) {}
}

// ── Resume Playback Position — pick up where you left off ──

function _savePosition() {
  const current = state.queue[state.queueIndex];
  if (!current || !audio.currentTime) return;
  try {
    localStorage.setItem('playerPosition', JSON.stringify({
      time: audio.currentTime,
      key: _trackKey(current),
    }));
  } catch (_) {}
}

function _restorePosition() {
  try {
    const raw = localStorage.getItem('playerPosition');
    if (!raw) return;
    const data = JSON.parse(raw);
    const current = state.queue[state.queueIndex];
    if (current && data.key === _trackKey(current) && data.time > 0) {
      // Set source and seek to saved position without auto-playing
      const src = (current.is_local && current.local_path)
        ? '/api/playback/local?path=' + encodeURIComponent(current.local_path)
        : '/api/playback/stream/' + current.id;
      audio.src = src;
      audio.addEventListener('loadedmetadata', function _onMeta() {
        audio.currentTime = data.time;
        timeElapsed.textContent = formatTime(data.time);
        if (audio.duration) {
          timeTotal.textContent = formatTime(audio.duration);
          progressFill.style.width = ((data.time / audio.duration) * 100) + '%';
        }
      }, { once: true });
      _fetchWaveform(current);
    }
  } catch (_) {}
}

// Save on pause, on track change, and on page unload
audio.addEventListener('pause', _savePosition);
audio.addEventListener('pause', _saveQueue);
window.addEventListener('beforeunload', () => { _savePosition(); _saveQueue(); });

// ── Loading / Buffer Indicator ──

audio.addEventListener('waiting', () => {
  progressBar.classList.add('buffering');
});
audio.addEventListener('canplay', () => {
  progressBar.classList.remove('buffering');
});
audio.addEventListener('playing', () => {
  progressBar.classList.remove('buffering');
});

// ── Sleep Timer ──

let _sleepTimerId = null;
let _sleepEnd = null;
const SLEEP_OPTIONS = [15, 30, 45, 60, 90];  // minutes
let _sleepOptionIdx = -1;  // -1 = off

const btnSleep = document.getElementById('btn-sleep');
btnSleep.addEventListener('click', () => {
  _sleepOptionIdx++;
  if (_sleepOptionIdx >= SLEEP_OPTIONS.length) {
    // Cancel
    _sleepOptionIdx = -1;
    if (_sleepTimerId) { clearTimeout(_sleepTimerId); _sleepTimerId = null; }
    _sleepEnd = null;
    btnSleep.classList.remove('active');
    btnSleep.title = 'Sleep timer';
    toast('Sleep timer off');
    return;
  }
  const mins = SLEEP_OPTIONS[_sleepOptionIdx];
  if (_sleepTimerId) clearTimeout(_sleepTimerId);
  _sleepEnd = Date.now() + mins * 60000;
  _sleepTimerId = setTimeout(() => {
    audio.pause();
    state.playing = false;
    updatePlayButton();
    toast('Sleep timer — goodnight');
    btnSleep.classList.remove('active');
    btnSleep.title = 'Sleep timer';
    _sleepTimerId = null;
    _sleepEnd = null;
    _sleepOptionIdx = -1;
  }, mins * 60000);
  btnSleep.classList.add('active');
  btnSleep.title = 'Sleep: ' + mins + 'min';
  toast('Sleep in ' + mins + ' minutes');
});

// ── Sidecar / Server lifecycle ────────────────────────────────────────────────

const _sidecar = { status: 'unknown', pollTimer: null, reloadTimer: null, el: null };

function _pollSidecarHealth() {
  fetch('/api/server/health', { method: 'GET' })
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(() => { _setSidecarStatus('running'); })
    .catch(() => { _setSidecarStatus('stopped'); });
}

function _setSidecarStatus(status) {
  const changed = _sidecar.status !== status;
  _sidecar.status = status;
  if (changed && _sidecar.el) _renderSidecarSection(_sidecar.el);
}

function _startSidecarPoll() {
  if (_sidecar.pollTimer) return;
  _pollSidecarHealth();
  _sidecar.pollTimer = setInterval(_pollSidecarHealth, 5000);
}

function _stopSidecarPoll() {
  if (_sidecar.pollTimer) {
    clearInterval(_sidecar.pollTimer);
    _sidecar.pollTimer = null;
  }
  if (_sidecar.reloadTimer) {
    clearTimeout(_sidecar.reloadTimer);
    _sidecar.reloadTimer = null;
  }
}

function _renderSidecarSection(container) {
  while (container.firstChild) container.removeChild(container.firstChild);

  const wrap = h('div', { className: 'sidecar-settings' });

  // Title row with live status
  const titleRow = h('div', { className: 'sidecar-title-row' });
  titleRow.appendChild(textEl('div', 'Server', 'sidecar-settings-title'));

  const isRunning = _sidecar.status === 'running';
  const dotClass = 'connection-dot' + (isRunning ? '' : ' disconnected');
  const statusRow = h('div', { className: 'connection', style: { padding: '0' } },
    h('span', { className: dotClass }),
    document.createTextNode(isRunning ? 'Running' : 'Stopped')
  );
  titleRow.appendChild(statusRow);
  wrap.appendChild(titleRow);

  // Action buttons
  const btnRow = h('div', { className: 'sidecar-btn-row' });

  if (_isTauri()) {
    if (isRunning) {
      const stopBtn = textEl('button', 'Stop', 'sidecar-btn sidecar-btn--danger');
      stopBtn.onclick = () => _sidecarTauriAction('stop');
      btnRow.appendChild(stopBtn);

      const restartBtn = textEl('button', 'Restart', 'sidecar-btn');
      restartBtn.onclick = () => _sidecarTauriAction('restart');
      btnRow.appendChild(restartBtn);
    } else {
      const startBtn = textEl('button', 'Start', 'sidecar-btn sidecar-btn--primary');
      startBtn.onclick = () => _sidecarTauriAction('start');
      btnRow.appendChild(startBtn);
    }
  } else {
    // Browser mode — restart only, and only when running
    if (isRunning) {
      const restartBtn = textEl('button', 'Restart', 'sidecar-btn');
      restartBtn.onclick = _sidecarBrowserRestart;
      btnRow.appendChild(restartBtn);
    }
  }

  wrap.appendChild(btnRow);
  container.appendChild(wrap);
}

function _sidecarDisableButtons() {
  const row = document.querySelector('.sidecar-btn-row');
  if (row) row.querySelectorAll('button').forEach(b => { b.disabled = true; });
}

function _sidecarTauriAction(action) {
  _sidecarDisableButtons();
  _tauriInvoke(action + '_sidecar').then(() => {
    if (action === 'stop') {
      _setSidecarStatus('stopped');
    } else {
      // start or restart — poll until the server is ready, then reload
      _setSidecarStatus('stopped');
      _sidecarWaitThenReload();
    }
  }).catch(e => {
    toast('Server ' + action + ' failed: ' + e, 'error');
    _pollSidecarHealth();
  });
}

function _sidecarBrowserRestart() {
  _sidecarDisableButtons();
  api('/server/restart', { method: 'POST' }).then(() => {
    _setSidecarStatus('stopped');
    _sidecarWaitThenReload();
  }).catch(e => {
    toast('Restart failed: ' + e, 'error');
    _pollSidecarHealth();
  });
}

/** Poll /api/server/health until it responds, then reload the page. */
function _sidecarWaitThenReload() {
  const maxWait = 30000;
  const interval = 500;
  const start = Date.now();

  const poll = () => {
    if (Date.now() - start > maxWait) {
      _sidecar.reloadTimer = null;
      _setSidecarStatus('stopped');
      toast('Server did not come back within 30 seconds', 'error');
      return;
    }
    fetch('/api/server/health', { method: 'GET' })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(() => { _sidecar.reloadTimer = null; window.location.reload(); })
      .catch(() => { _sidecar.reloadTimer = setTimeout(poll, interval); });
  };

  // Wait a beat for the old server to finish dying
  _sidecar.reloadTimer = setTimeout(poll, 1000);
}

// ── Updater ──────────────────────────────────────────────────────────────────

const _updater = { state: null, dismissed: false, settingsEl: null, webUpdate: null };

function _isTauri() {
  return !!(window.__TAURI__ || window.__TAURI_INTERNALS__);
}

function _tauriInvoke(cmd) {
  return window.__TAURI__.core.invoke(cmd);
}

function _onUpdaterState(us) {
  _updater.state = us;
  renderUpdaterBanner(us);
  if (_updater.settingsEl) renderUpdaterSettings(_updater.settingsEl, us);
}

function initUpdater() {
  if (!_isTauri()) return;
  window.__TAURI__.event.listen('updater-state-changed', ev => {
    _onUpdaterState(ev.payload);
  });
  _tauriInvoke('get_updater_state').then(_onUpdaterState).catch(() => {});
}

function checkForUpdates() {
  if (!_isTauri()) return;
  _tauriInvoke('check_for_updates').then(_onUpdaterState).catch(e => {
    toast('Update check failed: ' + e, 'error');
  });
}

function installUpdate() {
  if (!_isTauri()) return;
  _tauriInvoke('install_update').then(_onUpdaterState).catch(e => {
    toast('Install failed: ' + e, 'error');
  });
}

function renderUpdaterBanner(us) {
  const existing = document.getElementById('updater-banner');
  if (existing) existing.remove();

  if (!us) return;
  if (_updater.dismissed && us.status !== 'downloading') return;

  if (us.status === 'downloading') {
    const pct = us.progress_pct || 0;
    const ver = us.available_version || '';
    const banner = h('div', { id: 'updater-banner', className: 'updater-banner' },
      textEl('span', 'Downloading v' + ver + '… ' + pct + '%', 'updater-banner-text'),
      h('div', { className: 'updater-progress-wrap' },
        h('div', { className: 'updater-progress-bar', style: { width: pct + '%' } })
      )
    );
    _insertBanner(banner);
  } else if (us.status === 'ready_to_install') {
    const ver = us.available_version || '';
    const btnInstall = h('button', { className: 'updater-btn-install' }, document.createTextNode('Restart & Install'));
    btnInstall.onclick = () => installUpdate();
    const btnLater = h('button', { className: 'updater-btn-later' }, document.createTextNode('Later'));
    btnLater.onclick = () => { _updater.dismissed = true; const b = document.getElementById('updater-banner'); if (b) b.remove(); };
    const banner = h('div', { id: 'updater-banner', className: 'updater-banner' },
      textEl('span', 'Update v' + ver + ' ready', 'updater-banner-text'),
      btnInstall,
      btnLater
    );
    _insertBanner(banner);
  }
}

function _insertBanner(banner) {
  const nav = document.querySelector('.bottom-nav') || document.querySelector('nav');
  if (nav && nav.parentNode) {
    nav.parentNode.insertBefore(banner, nav.nextSibling);
  } else {
    document.body.prepend(banner);
  }
}

function renderUpdaterSettings(container, us) {
  while (container.firstChild) container.removeChild(container.firstChild);
  if (!us) return;

  const wrap = h('div', { className: 'updater-settings' });
  wrap.appendChild(textEl('div', 'About / Updates', 'updater-settings-title'));
  wrap.appendChild(textEl('div', 'Current version: ' + (us.current_version || '—'), 'updater-version'));

  // Status text
  let statusText = '';
  let statusClass = 'updater-status';
  switch (us.status) {
    case 'idle': statusText = ''; break;
    case 'checking': statusText = 'Checking for updates…'; break;
    case 'up_to_date': statusText = 'You are on the latest version.'; statusClass += ' updater-status--success'; break;
    case 'update_available': statusText = 'Update v' + (us.available_version || '') + ' is available.'; break;
    case 'downloading': statusText = 'Downloading… ' + (us.progress_pct || 0) + '%'; break;
    case 'ready_to_install': statusText = 'v' + (us.available_version || '') + ' is ready to install.'; statusClass += ' updater-status--success'; break;
    case 'installing': statusText = 'Installing…'; break;
    case 'error': statusText = us.error_message || 'An error occurred.'; statusClass += ' updater-status--error'; break;
    case 'unsupported_install_context': statusText = 'Auto-update only works after you move music-dl.app into Applications.'; statusClass += ' updater-status--error'; break;
  }
  if (statusText) {
    const sEl = textEl('div', statusText, '');
    sEl.className = statusClass;
    wrap.appendChild(sEl);
  }

  // Check button
  const busy = us.status === 'checking' || us.status === 'downloading' || us.status === 'installing';
  const btn = h('button', { className: 'updater-btn-check', disabled: busy },
    document.createTextNode(busy ? 'Please wait…' : 'Check for Updates')
  );
  btn.onclick = () => { if (!busy) checkForUpdates(); };
  wrap.appendChild(btn);

  container.appendChild(wrap);
}

function _renderWebUpdaterPanel(container) {
  while (container.firstChild) container.removeChild(container.firstChild);
  const data = _updater.webUpdate;
  const wrap = h('div', { className: 'updater-settings' });
  wrap.appendChild(textEl('div', 'About / Updates', 'updater-settings-title'));
  wrap.appendChild(textEl('div', 'Current version: v' + (data ? data.current_version : '…'), 'updater-version'));
  if (data && !data.update_available) {
    wrap.appendChild(textEl('div', 'You are on the latest version.', 'updater-status updater-status--success'));
  }
  const btn = h('button', { className: 'updater-btn-check' });
  btn.textContent = 'Check for Updates';
  btn.onclick = () => {
    btn.disabled = true;
    btn.textContent = 'Checking…';
    api('/settings/update-check').then(d => {
      _updater.webUpdate = d;
      _renderWebUpdaterPanel(container);
      if (d.update_available) _renderWebUpdaterSettings(container);
    }).catch(() => {
      btn.disabled = false;
      btn.textContent = 'Check for Updates';
      toast('Update check failed', 'error');
    });
  };
  wrap.appendChild(btn);
  container.appendChild(wrap);
}

function _checkWebUpdate() {
  api('/settings/update-check').then(data => {
    if (!data.update_available) return;
    _updater.webUpdate = data;

    // Badge on Settings nav
    const settingsNav = document.querySelector('[data-view="settings"]');
    if (settingsNav && !settingsNav.querySelector('.nav-badge')) {
      const dot = h('span', { className: 'nav-badge' });
      dot.textContent = '1';
      settingsNav.appendChild(dot);
    }

    // Persistent toast with dismiss
    const t = h('div', { className: 'toast toast-update' });
    t.appendChild(textEl('span', 'v' + data.latest_version + ' is available', ''));
    const viewBtn = h('a', {
      className: 'toast-update-link',
      href: data.release_url,
      target: '_blank',
      rel: 'noopener',
    });
    viewBtn.textContent = 'View';
    viewBtn.addEventListener('click', e => e.stopPropagation());
    t.appendChild(viewBtn);
    const dismissBtn = h('button', { className: 'toast-update-dismiss' });
    dismissBtn.textContent = '\u00d7';
    dismissBtn.addEventListener('click', () => t.remove());
    t.appendChild(dismissBtn);
    toastSticky(t);

    // Refresh settings panel if open
    if (_updater.settingsEl) _renderWebUpdaterSettings(_updater.settingsEl);
  }).catch(() => {});
}

function _renderWebUpdaterSettings(container) {
  const data = _updater.webUpdate;
  // Remove any previous web-update card
  const prev = container.querySelector('.update-notification');
  if (prev) prev.remove();
  if (!data) return;

  const card = h('div', { className: 'update-notification' });
  const header = h('div', { className: 'update-notification-header' });
  header.appendChild(textEl('span', 'Update Available', 'update-notification-title'));
  header.appendChild(textEl('span', 'v' + data.latest_version, 'update-notification-version'));
  card.appendChild(header);
  if (data.release_notes) {
    const notes = data.release_notes.length > 200
      ? data.release_notes.slice(0, 200) + '…'
      : data.release_notes;
    card.appendChild(textEl('div', notes, 'update-notification-notes'));
  }
  const actions = h('div', { className: 'update-notification-actions' });
  const dlBtn = h('a', {
    className: 'update-notification-btn',
    href: data.release_url,
    target: '_blank',
    rel: 'noopener',
  });
  dlBtn.textContent = 'Download from GitHub';
  actions.appendChild(dlBtn);
  card.appendChild(actions);
  container.prepend(card);
}

// ---- TOKEN KEEPALIVE ----
// Pings /auth/keepalive every 10 min while the window is visible so the token
// never expires silently during idle periods.  Stops when the tab is hidden
// and fires immediately + restarts the interval when it becomes visible again.
let _keepaliveTimer = null;
const _KEEPALIVE_MS = 10 * 60 * 1000; // 10 minutes

function _keepaliveTick() {
  api('/auth/keepalive', { method: 'POST' }).catch(() => {});
}

function _startKeepalive() {
  if (_keepaliveTimer) return;
  _keepaliveTick(); // immediate tick on visibility restore
  _keepaliveTimer = setInterval(_keepaliveTick, _KEEPALIVE_MS);
}

function _stopKeepalive() {
  if (_keepaliveTimer) { clearInterval(_keepaliveTimer); _keepaliveTimer = null; }
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) _stopKeepalive(); else _startKeepalive();
});

function _initApp() {
  // Load settings into state for upgrade quality checks
  api('/settings').then(s => { state.settings = s; }).catch(() => {});
  refreshStatusLights();
  _restorePlayerPrefs();
  _restoreQueue();
  _restorePosition();
  initUpdater();
  _checkWebUpdate();
  _startKeepalive();
  navigate(normalizeView(location.hash.slice(1) || 'home'));
}

// Setup check on load — wizard or normal app
(async () => {
  const needsSetup = await _checkSetup();
  if (!needsSetup) {
    _initApp();
  }
})();
