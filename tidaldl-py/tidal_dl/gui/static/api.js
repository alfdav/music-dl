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
      else if (typeof v === 'boolean') {
        if (v) e.setAttribute(k, '');
      }
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

// Semantic quality badges (Lossless / Hi-Res / Lossy)
function _qualityTier(q, fmt, codec) {
  const cl = (codec || '').toLowerCase();
  if (cl === 'aac' || cl === 'mp3' || cl === 'ogg' || cl === 'opus' || cl === 'vorbis')
    return { tier: 'Lossy', cls: 'quality-lossy', desc: (codec || fmt || q) + ' · Lossy', rank: 1 };
  if (cl === 'flac' || cl === 'alac' || cl === 'pcm') {
    const ql = (q || '').toUpperCase();
    if (ql.includes('24BIT') || ql.includes('/24')) {
      const hz = parseInt(ql);
      return { tier: 'Hi-Res', cls: 'quality-hires', desc: q + ' · Hi-Res', rank: hz > 48000 ? 4 : 3 };
    }
    return { tier: 'Lossless', cls: 'quality-lossless', desc: (q || codec) + ' · Lossless', rank: 2 };
  }
  if (!q) return { tier: 'Unknown', cls: 'quality-unknown', desc: 'Unknown quality', rank: 0 };
  const ql = q.toUpperCase();

  if (ql === 'DOLBY_ATMOS' || ql.includes('ATMOS') || ql.includes('DOLBY'))
    return { tier: 'Hi-Res', cls: 'quality-hires', desc: 'Dolby Atmos · Spatial Audio', rank: 5 };
  if (ql === 'HI_RES_LOSSLESS')
    return { tier: 'Hi-Res', cls: 'quality-hires', desc: 'Hi-Res Lossless · 24-bit FLAC', rank: 4 };
  if (ql === 'HI_RES' || ql === 'MQA' || ql.includes('MASTER'))
    return { tier: 'Hi-Res', cls: 'quality-hires', desc: 'Hi-Res · MQA', rank: 3 };
  if (ql === 'LOSSLESS')
    return { tier: 'Lossless', cls: 'quality-lossless', desc: 'Lossless · CD 16-bit', rank: 2 };
  if (ql === 'HIGH')
    return { tier: 'Lossy', cls: 'quality-lossy', desc: 'HIGH · 320 kbps', rank: 1 };
  if (ql === 'LOW')
    return { tier: 'Lossy', cls: 'quality-lossy', desc: 'LOW · 96 kbps', rank: 0 };

  if (ql === 'FLAC' || ql === 'WAV')
    return { tier: 'Lossless', cls: 'quality-lossless', desc: q + ' · Lossless', rank: 2 };
  if (ql === 'MP3' || ql === 'AAC' || ql === 'OGG')
    return { tier: 'Lossy', cls: 'quality-lossy', desc: q + ' · Lossy', rank: 1 };
  if ((fmt || '').toLowerCase() === 'm4a')
    return { tier: 'Unknown', cls: 'quality-unknown', desc: 'M4A · Unknown', rank: 0 };

  return { tier: 'Unknown', cls: 'quality-unknown', desc: q || fmt || 'Unknown quality', rank: 0 };
}

function qualityClass(q, fmt, codec) { return _qualityTier(q, fmt, codec).cls; }
function qualityLabel(q, fmt, codec) { return _qualityTier(q, fmt, codec).tier; }
function qualityTitle(q, fmt, codec) { return _qualityTier(q, fmt, codec).desc; }
function qualityRank(q, fmt, codec) { return _qualityTier(q, fmt, codec).rank; }

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
  chevronLeft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="15 18 9 12 15 6"/></svg>',
  chevronRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="9 18 15 12 9 6"/></svg>',
  play: '<polygon points="5 3 19 12 5 21 5 3"/>',
  pause: '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="15 18 9 12 15 6"/></svg>',
};

// ---- STATE ----
const state = {
  view: 'home',
  searchQuery: '',
  searchType: 'tracks',
  searchResults: null,
  albumQualityFilter: 'all',
  albumRatingFilter: 'all',
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
  const targetRank = _playlistUpgradeTargetRank();
  return (tracks || []).filter(t => {
    if (!t || !t.is_local || !t.isrc) return false;
    return qualityRank(t.quality, t.format, t.codec) < targetRank;
  });
}

function _setPlaylistUpgradeBadge(trackList, track, maxQuality) {
  const row = trackList.querySelector('[data-track-id="' + _trackKey(track) + '"]');
  if (!row) return false;
  const ex = row.querySelector('.upgrade-badge');
  if (ex) ex.remove();

  const probeRanks = { 'LOW': 0, 'HIGH': 1, 'LOSSLESS': 2, 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 };
  const localRank = qualityRank(track.quality, track.format, track.codec);
  const probeRank = probeRanks[maxQuality] || 0;
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
      if (resp.count > 0) { refreshDlBadge(); _ensureGlobalSSE(); }
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
    const raw = args[0];
    const url = typeof raw === 'string' ? raw : (raw && raw.url) || '';
    if (!String(url).includes('/api/playback/local')) {
      const data = await resp.clone().json().catch(() => null);
      toast(data?.detail || 'Operation in progress \u2014 try again shortly.', 'error');
    }
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

  const controller = opts.timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), opts.timeoutMs) : null;
  let resp;
  try {
    resp = await fetch('/api' + path, {
      method,
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controller ? controller.signal : undefined,
    });
  } finally {
    if (timer) clearTimeout(timer);
  }

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
