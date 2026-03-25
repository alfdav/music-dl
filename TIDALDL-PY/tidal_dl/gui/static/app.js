/* music-dl — SPA core: router, state, player, views */
/* Security: All user-supplied data (track names, artist names, etc.) goes
   through textContent or the textEl() helper. innerHTML is ONLY used for
   static SVG icons and structural layout scaffolding — never with user data. */
'use strict';

// ---- CSRF ----
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

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
  queueIndex: -1,
  playing: false,
  shuffle: false,
  repeat: 'off',  // 'off' | 'all' | 'one'
  volume: 0.7,
};

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

  try {
    const res = await api('/library/favorites/toggle', {
      method: 'POST',
      body,
    });

    const key = track.path || (track.id ? 'tidal:' + track.id : null);
    if (key) _favCache[key] = res.favorited;

    btn.classList.toggle('hearted', res.favorited);
    updatePlayerHeart();
  } catch (err) {
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
    throw new Error(detail.detail || 'API error ' + resp.status);
  }

  return resp.json();
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
      ['\u2190', 'Back 5s'],
      ['\u2192', 'Forward 5s'],
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
  if (!view) view = 'home';

  // Save outgoing view state
  if (state.view && viewEl.firstChild) {
    const scrollEl = document.querySelector('.main');
    _viewState[state.view] = {
      scrollY: scrollEl ? scrollEl.scrollTop : 0,
    };
  }

  state.view = view;
  _lastNavHash = view;
  location.hash = view;

  navItems.forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });

  // Deep-linked views: highlight parent nav item
  if (!document.querySelector('.nav-item.active')) {
    const parent = view.startsWith('artist:') ? 'home'
      : view.startsWith('localalbum:') ? 'library'
      : view.startsWith('album:') ? 'search'
      : null;
    if (parent) {
      navItems.forEach(n => { if (n.dataset.view === parent) n.classList.add('active'); });
    }
  }

  // Clear view safely
  while (viewEl.firstChild) viewEl.removeChild(viewEl.firstChild);

  const container = h('div', { className: 'view-enter' });

  switch (view) {
    case 'home': renderHome(container); break;
    case 'search': renderSearch(container); break;
    case 'library': renderLibrary(container); break;
    case 'recent': renderRecentlyPlayed(container); break;
    case 'playlists': renderPlaylists(container); break;
    case 'favorites': renderFavorites(container); break;
    case 'downloads': renderDownloads(container); break;
    case 'settings': renderSettings(container); break;
    case 'djai': renderDjai(container); break;
    case 'upgrades': renderUpgradeScanner(container); break;
    default:
      if (view.startsWith('localalbum:')) {
        const parts = view.substring(11).split(':');
        renderLocalAlbumDetail(container, decodeURIComponent(parts[0]), decodeURIComponent(parts.slice(1).join(':')));
      } else if (view.startsWith('artist:')) {
        renderArtistGallery(container, decodeURIComponent(view.substring(7)));
      } else if (view.startsWith('album:')) {
        renderAlbumDetail(container, view.split(':')[1]);
      } else {
        renderPlaceholder(container, 'Not Found', 'This view does not exist.');
      }
  }

  viewEl.appendChild(container);

  // Restore saved scroll position or reset to top
  const scrollEl = document.querySelector('.main');
  if (scrollEl) {
    const saved = _viewState[view];
    if (saved && saved.scrollY) {
      requestAnimationFrame(() => { scrollEl.scrollTop = saved.scrollY; });
    } else {
      scrollEl.scrollTop = 0;
    }
  }
}

navItems.forEach(n => {
  n.addEventListener('click', () => navigate(n.dataset.view));
  a11yClick(n);
});

window.addEventListener('hashchange', () => {
  const hash = location.hash.slice(1) || 'home';
  if (hash === _lastNavHash) return; // already handled by navigate()
  navigate(hash);
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
  const wrap = h('div', { className: 'home-wrap' });

  let data;
  try {
    data = await api('/home');
  } catch (_) {
    data = { total_plays: 0, weekly_activity: [0,0,0,0,0,0,0] };
  }

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

  const header = h('div', { className: 'home-header' });
  const title = h('h1', { className: 'home-title' });
  title.appendChild(document.createTextNode(_greeting() + ' welcome to '));
  title.appendChild(h('em', { className: 'home-your' }, 'your'));
  title.appendChild(document.createTextNode(' library'));
  header.appendChild(title);
  wrap.appendChild(header);

  if (data.volume_available === false) {
    const banner = h('div', { className: 'volume-offline-banner' });
    banner.textContent = 'Your music drive is offline — showing what we remember';
    wrap.appendChild(banner);
  }

  if (totalPlays === 0) {
    _renderHomeCold(wrap);
  } else {
    _renderHomeGrid(wrap, data, totalPlays);
  }

  if (recentlyPlayed.length > 0) {
    _renderRecentStrip(wrap);
  }

  container.appendChild(wrap);
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
  const grid = h('div', { className: 'home-grid' });

  // Adaptive column count + density classes via ResizeObserver
  new ResizeObserver(entries => {
    for (const e of entries) {
      const w = e.contentRect.width;
      const cols = Math.max(2, Math.min(6, Math.floor(w / 280)));
      e.target.style.setProperty('--cols', cols);
      e.target.classList.toggle('density-compact', cols <= 2);
    }
  }).observe(grid);

  // Helper: tag a tile with a priority tier for adaptive hiding
  function _t(tile, tier) { tile.dataset.tier = tier; return tile; }

  // === Core tiles (always visible) ===
  if (data.top_artist && data.top_artist.play_count >= 5) {
    grid.appendChild(_artistTile(data.top_artist, true));
  }
  if (data.most_replayed && data.most_replayed.play_count >= 10) {
    grid.appendChild(_replayedTile(data.most_replayed));
  }

  // Genre tile: show what you LISTEN to (play_events), not what you HAVE (library)
  // Fall back to library genres only if no play history exists
  const hasPlayGenres = data.genre_breakdown && data.genre_breakdown.length > 0;
  const genreSource = hasPlayGenres ? data.genre_breakdown : (data.track_genres || []);
  const genreLabel = genreSource.length > 0 ? genreSource[0].genre : null;
  if (genreSource.length > 0) {
    grid.appendChild(_genreTile(genreLabel, genreSource, !hasPlayGenres));
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    grid.appendChild(_listeningTimeTile(data.listening_time_hours, data.weekly_activity, data));
  }

  // === Secondary tiles (tier 1 — hidden on compact) ===
  const extraArtists = (data.top_artists || []).slice(1, 3);
  for (const a of extraArtists) {
    if (a.play_count >= 3) {
      grid.appendChild(_t(_artistTile(a, false), 1));
    }
  }

  // === Library tiles (tier 2 — hidden on compact) ===
  if (established || data.track_count > 0) {
    grid.appendChild(_t(_tracksTile(data.track_count, data.track_genres || [], data), 2));
  }
  if (established || data.album_count > 0) {
    grid.appendChild(_t(_albumsTile(data.album_count, data.album_artists, data), 2));
  }

  container.appendChild(grid);
}


function _artistTile(artist, hero) {
  const tile = h('div', { className: 'bento-tile bento-artist' + (hero ? ' bento-hero' : '') });
  if (artist.cover_url) {
    tile.appendChild(h('img', { className: 'bento-bg-art', src: artist.cover_url, alt: '' }));
  }
  tile.appendChild(h('div', { className: 'bento-overlay' }));
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', artist.name, 'bento-label'));
  body.appendChild(textEl('div', artist.play_count + ' plays', 'bento-sub'));
  // Per-artist stats
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
  // Lazy-load artist photo from Tidal (cached on backend)
  fetch('/api/home/artist-image?name=' + encodeURIComponent(artist.name))
    .then(r => r.json())
    .then(data => {
      if (data.image_url) {
        const img = tile.querySelector('.bento-bg-art');
        if (img) { img.src = data.image_url; }
        else { tile.prepend(h('img', { className: 'bento-bg-art', src: data.image_url, alt: '' })); }
      }
    })
    .catch(() => {});
  return tile;
}

function _replayedTile(track) {
  const tile = h('div', { className: 'bento-tile bento-replayed bento-hero' });
  if (track.cover_url) {
    tile.appendChild(h('img', { className: 'bento-bg-art', src: track.cover_url, alt: '' }));
  }
  tile.appendChild(h('div', { className: 'bento-overlay bento-overlay-purple' }));
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', 'Most Replayed', 'bento-eyebrow'));
  body.appendChild(textEl('div', track.name, 'bento-label'));
  body.appendChild(textEl('div', track.artist + ' \u2014 ' + track.album, 'bento-sub'));
  body.appendChild(textEl('div', track.play_count + ' plays', 'bento-stat'));
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'Play', 'bento-hint'));
  tile.addEventListener('click', () => {
    const t = { ...track, local_path: track.path, is_local: true };
    playTrack(t);
  });
  a11yClick(tile);
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

function _expandToggle(tile) {
  tile.addEventListener('click', () => tile.classList.toggle('bento-expanded'));
  a11yClick(tile);
  tile.appendChild(textEl('span', 'More', 'bento-hint'));
  tile.appendChild(textEl('span', '\u25BE', 'bento-chevron'));
}

function _detailBlock(items) {
  const block = h('div', { className: 'bento-detail' });
  items.forEach((item, i) => {
    const row = h('div', { className: 'bento-detail-row' });
    row.style.transitionDelay = (i * 40) + 'ms';
    row.appendChild(textEl('span', item.label, 'bento-detail-key'));
    row.appendChild(textEl('span', item.value, 'bento-detail-val'));
    block.appendChild(row);
  });
  return block;
}

function _genreTile(topGenre, breakdown, fromLibrary) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
  body.appendChild(textEl('div', fromLibrary ? 'Top genre' : 'Recent genre', 'bento-stat-label'));
  body.appendChild(_genreInsight(topGenre, breakdown, fromLibrary));
  body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  // Detail: full genre breakdown beyond top 4
  const allGenres = breakdown.map(g => ({
    label: g.genre,
    value: g.count + (fromLibrary ? ' tracks' : ' plays')
  }));
  if (allGenres.length > 4) {
    body.appendChild(_detailBlock(allGenres.slice(4)));
  }
  tile.appendChild(body);
  if (allGenres.length > 4) _expandToggle(tile);
  return tile;
}

function _listeningTimeTile(hours, weekly, data) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', Math.round(hours) + 'h', 'bento-label'));
  body.appendChild(textEl('div', 'Listening time', 'bento-stat-label'));
  const ins = _listeningInsight(hours, weekly);
  if (ins) body.appendChild(ins);
  body.appendChild(_weeklyChart(weekly));
  // Detail: deeper listening habits
  const details = [];
  if (data.peak_hour !== undefined) {
    const h12 = data.peak_hour % 12 || 12;
    const ampm = data.peak_hour < 12 ? 'am' : 'pm';
    details.push({ label: 'You listen most around', value: h12 + ampm });
  }
  if (data.streak > 0) details.push({ label: 'Current streak', value: data.streak + ' day' + (data.streak !== 1 ? 's' : '') });
  if (data.week_vs_last) {
    const diff = data.week_vs_last.this_week - data.week_vs_last.last_week;
    details.push({ label: 'This week', value: Math.round(data.week_vs_last.this_week) + ' min' });
    if (data.week_vs_last.last_week > 0) {
      const pct = Math.round((diff / data.week_vs_last.last_week) * 100);
      details.push({ label: 'vs last week', value: (pct >= 0 ? '+' : '') + pct + '%' });
    }
  }
  if (data.total_plays) details.push({ label: 'Lifetime plays', value: data.total_plays.toLocaleString() });
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
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
  // Detail: how your library is stored
  const details = [];
  if (data.format_breakdown && data.format_breakdown.length > 0) {
    for (const f of data.format_breakdown) {
      const pct = Math.round((f.count / count) * 100);
      details.push({ label: f.format, value: f.count.toLocaleString() + ' (' + pct + '%)' });
    }
  }
  if (data.unplayed_count > 0) {
    const pct = Math.round((data.unplayed_count / count) * 100);
    details.push({ label: 'Never played', value: data.unplayed_count.toLocaleString() + ' (' + pct + '%)' });
  }
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
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
  // Detail: what you keep coming back to
  const details = [];
  if (data.top_album) {
    details.push({ label: 'Most played album', value: data.top_album.album });
    details.push({ label: 'Artist', value: data.top_album.artist });
    if (data.top_album.play_count) details.push({ label: 'Plays', value: data.top_album.play_count.toLocaleString() });
  }
  if (data.favorites_count > 0) details.push({ label: 'Favorited', value: data.favorites_count.toLocaleString() + ' tracks' });
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
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
      if (track.is_local && track.local_path) playTrack(track);
      else if (track.id) playTrack(track);
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
    renderSearchResults(resultsArea, state.searchResults);
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
    tidalData = await api('/search?q=' + encodeURIComponent(q) + '&type=' + state.searchType + '&limit=50');
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
  const artistEl = textEl('div', track.artist || '', 'track-artist');
  if (track.artist) {
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
  const albumCell = textEl('div', track.album || '', 'track-album');
  if (track.album_id) {
    albumCell.style.cursor = 'pointer';
    albumCell.addEventListener('click', (e) => {
      e.stopPropagation();
      navigateAlbum(track.album_id);
    });
  } else if (track.album && track.artist) {
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

  // Right-click context menu (local tracks only)
  const localPath = track.local_path || track.path;
  if (localPath) {
    row.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const trackName = track.name || track.title || 'this track';
      showContextMenu(e, [
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

                // Remove from queue if present
                state.queue = state.queue.filter(t => _trackKey(t) !== _trackKey(track));

                toast('Track deleted', 'success');
              } catch (err) {
                toast('Failed to delete track', 'error');
              }
            });
          }
        }
      ]);
    });
  }

  // Click to play
  row.addEventListener('click', () => {
    state.queue = allTracks.slice();
    state.queueIndex = allTracks.indexOf(track);
    playTrack(track);
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
      span.addEventListener('click', () => navigate(c.view));
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
        navigate('localalbum:' + encodeURIComponent(artistName) + ':' + encodeURIComponent(album.name));
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
  artistLink.addEventListener('click', () => navigate('artist:' + encodeURIComponent(artistName)));
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
        state.queue = tracks.slice();
        state.queueIndex = 0;
        state.shuffle = false;
        btnShuffle.classList.remove('active');
        playTrack(tracks[0]);
      });
      shuffleBtn.addEventListener('click', () => {
        const shuffled = tracks.slice().sort(() => Math.random() - 0.5);
        state.queue = shuffled;
        state.queueIndex = 0;
        state.shuffle = true;
        btnShuffle.classList.add('active');
        playTrack(shuffled[0]);
      });

      // Upgrade check — show button if any tracks might be upgradeable
      const upgradeableTracks = tracks.filter(t => {
        if (!t.isrc) return false;
        const tier = _qualityTier(t.quality, t.format);
        const tierRanks = { 'Common': 0, 'Uncommon': 1, 'Rare': 2, 'Epic': 3, 'Legendary': 4, 'Mythic': 5 };
        const targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
        return (tierRanks[tier.tier] || 0) < targetRank;
      });
      if (upgradeableTracks.length > 0) {
        upgradeBtn.style.display = '';
        upgradeBtn.addEventListener('click', async () => {
          upgradeBtn.disabled = true;
          upgradeBtn.textContent = 'Checking...';
          try {
            const isrcs = upgradeableTracks.map(t => t.isrc);
            const probeData = await api('/upgrade/probe', { method: 'POST', body: { isrcs: isrcs } });
            const results = probeData.results || [];
            const upgradeable = results.filter(r => r.upgradeable);

            // Mark rows with upgrade badges
            results.forEach(r => {
              const matchTrack = tracks.find(t => t.isrc === r.isrc);
              if (!matchTrack) return;
              const row = trackList.querySelector('[data-track-id="' + _trackKey(matchTrack) + '"]');
              if (!row) return;
              const existing = row.querySelector('.upgrade-badge');
              if (existing) existing.remove();
              if (r.upgradeable) {
                const badge = h('span', { className: 'upgrade-badge' });
                badge.textContent = '\u2B06 ' + qualityLabel(r.max_quality);
                badge.title = 'Upgrade available: ' + (r.max_quality || '');
                const metaCell = row.querySelector('.track-artist');
                if (metaCell && metaCell.parentElement) metaCell.parentElement.appendChild(badge);
              }
            });

            // Tracks without ISRC get "No ISRC" indicator
            tracks.forEach(t => {
              if (t.isrc) return;
              const row = trackList.querySelector('[data-track-id="' + _trackKey(t) + '"]');
              if (!row || row.querySelector('.upgrade-badge')) return;
              const badge = h('span', { className: 'upgrade-badge', style: { opacity: '0.5' } });
              badge.textContent = 'No ISRC';
              const metaCell = row.querySelector('.track-artist');
              if (metaCell && metaCell.parentElement) metaCell.parentElement.appendChild(badge);
            });

            if (upgradeable.length === 0) {
              toast('All tracks at best available quality', 'success');
              upgradeBtn.textContent = 'All Best Quality';
            } else {
              upgradeBtn.textContent = 'Upgrade ' + upgradeable.length + ' Tracks';
              upgradeBtn.disabled = false;
              upgradeBtn.onclick = async () => {
                upgradeBtn.disabled = true;
                upgradeBtn.textContent = 'Upgrading...';
                const paths = upgradeable.map(r => {
                  const t = tracks.find(tr => tr.isrc === r.isrc);
                  return t ? (t.local_path || t.path) : null;
                }).filter(Boolean);
                try {
                  await api('/upgrade/start', { method: 'POST', body: { track_paths: paths } });
                  toast('Upgrade started for ' + paths.length + ' tracks', 'success');
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
              await api('/download', {
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
  navigate('album:' + albumId);
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
      state.queue = playable.slice();
      state.queueIndex = 0;
      playTrack(playable[0]);
    });

    const shuffleBtn = h('button', { className: 'pill' });
    shuffleBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>Shuffle';
    shuffleBtn.addEventListener('click', () => {
      const playable = tracks.filter(t => t.is_local);
      if (!playable.length) { toast('No local tracks to play', 'info'); return; }
      const shuffled = playable.slice().sort(() => Math.random() - 0.5);
      state.queue = shuffled;
      state.queueIndex = 0;
      state.shuffle = true;
      btnShuffle.classList.add('active');
      playTrack(shuffled[0]);
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
        await api('/download', {
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
let libraryOffset = 0;
let libraryTotal = 0;
let _libSearchTimer = null;
let _libRequestId = 0;

function renderLibrary(container) {
  libraryOffset = 0;
  libraryQuery = '';
  const searchArea = h('div', { className: 'search-area' });

  const searchRow = h('div', { className: 'search-row' });
  const searchField = h('div', { className: 'search-field' });
  searchField.appendChild(svgIcon(ICONS.search));
  const libInput = h('input', {
    type: 'text', className: 'search-input',
    placeholder: 'Search your library...', value: libraryQuery,
  });
  searchField.appendChild(libInput);
  searchRow.appendChild(searchField);
  searchArea.appendChild(searchRow);

  const pills = h('div', { className: 'filter-pills' });
  for (const sort of ['artist', 'album', 'title']) {
    const pill = textEl('div', sort.charAt(0).toUpperCase() + sort.slice(1),
      'pill' + (librarySort === sort ? ' active' : ''));
    pill.style.cursor = 'pointer';
    pill.addEventListener('click', () => {
      librarySort = sort;
      libraryOffset = 0;
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

  searchArea.appendChild(pills);
  container.appendChild(searchArea);

  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  // Debounced search
  libInput.addEventListener('input', () => {
    clearTimeout(_libSearchTimer);
    _libSearchTimer = setTimeout(() => {
      libraryQuery = libInput.value.trim();
      libraryOffset = 0;
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
  while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
  resultsArea.appendChild(h('div', { className: 'skeleton-row' }));

  try {
    const data = await api('/library/albums' + (query ? '?q=' + encodeURIComponent(query) : ''));
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
      const sub = [album.artist || 'Unknown'];
      sub.push(album.track_count + ' track' + (album.track_count !== 1 ? 's' : ''));
      meta.appendChild(textEl('div', sub.join(' · '), 'album-card-sub'));
      card.appendChild(meta);

      card.addEventListener('click', () => {
        navigate('localalbum:' + encodeURIComponent(album.artist) + ':' + encodeURIComponent(album.name));
      });
      a11yClick(card);

      grid.appendChild(card);
    });
    resultsArea.appendChild(grid);
  } catch (err) {
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
    // Fetch all tracks sorted by artist (large limit for grouping)
    const data = await api('/library?sort=artist&limit=200&offset=0' +
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

function renderRecentlyPlayed(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  const headerRow = h('div', { className: 'results-header' },
    textEl('div', 'Recently Played', 'results-title'),
    textEl('div', recentlyPlayed.length + ' tracks', 'results-count')
  );
  if (recentlyPlayed.length > 0) {
    const clearBtn = h('button', { className: 'recent-page-clear-btn' }, 'Clear history');
    clearBtn.addEventListener('click', () => _clearRecentHistory());
    headerRow.appendChild(clearBtn);
  }
  resultsArea.appendChild(headerRow);

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

  const trackList = h('div', { className: 'tracks' });
  let currentGroup = null;
  let num = 0;
  recentlyPlayed.forEach((track, i) => {
    // Group dividers
    const group = _recentTimeGroup(track.played_at);
    if (group !== currentGroup) {
      currentGroup = group;
      trackList.appendChild(textEl('div', group, 'recent-page-divider'));
    }

    num++;
    const row = renderTrackRow(track, num, recentlyPlayed);

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

  actions.appendChild(playBtn);
  actions.appendChild(shuffleBtn);
  actions.appendChild(dlBtn);
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
        state.queue = tracks.slice();
        state.queueIndex = 0;
        state.shuffle = false;
        btnShuffle.classList.remove('active');
        playTrack(tracks[0]);
      });
      shuffleBtn.addEventListener('click', () => {
        const shuffled = tracks.slice().sort(() => Math.random() - 0.5);
        state.queue = shuffled;
        state.queueIndex = 0;
        state.shuffle = true;
        btnShuffle.classList.add('active');
        playTrack(shuffled[0]);
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
    await api('/download', {
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
      if (data.type === 'complete') _dlComplete(data.track_id, true);
      else if (data.type === 'error') {
        toast('Download failed: ' + (data.error || 'unknown'), 'error');
        _dlComplete(data.track_id, false);
      }
      // Also update the downloads view if visible
      const activeEl = document.getElementById('dl-active');
      if (activeEl) updateActiveDownload(activeEl, data);
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

  // Active section
  const activeLabel = textEl('div', 'Active', 'dl-section-label');
  resultsArea.appendChild(activeLabel);
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

  // Show initial empty state for active section
  _showActiveEmpty(activeSection);

  // Use global SSE — it updates #dl-active automatically
  _ensureGlobalSSE();

  // Load history
  loadDownloadHistory(historySection);
}

function updateActiveDownload(container, data) {
  let card = container.querySelector('[data-dl-id="' + data.track_id + '"]');

  if (data.type === 'complete' || data.type === 'error') {
    if (card) card.remove();
    // Check if active section is now empty
    if (!container.children.length) {
      _showActiveEmpty(container);
    }
    // Refresh history to show the new entry
    const histEl = document.getElementById('dl-history');
    if (histEl) loadDownloadHistory(histEl);
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
          state.queue = [track];
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
            await api('/download', { method: 'POST', body: { track_ids: [dl.track_id] } });
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

  // Auth status
  const authSection = h('div', { style: { marginBottom: '24px' } });
  resultsArea.appendChild(authSection);
  loadAuthStatus(authSection);

  // Settings form
  const formSection = h('div');
  resultsArea.appendChild(formSection);
  loadSettingsForm(formSection);
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
      container.appendChild(h('div', { className: 'connection', style: { padding: '0 0 16px' } },
        dot,
        document.createTextNode('Not logged in \u2014 run music-dl login in terminal')
      ));
    }
  } catch (_) {
    container.appendChild(textEl('div', 'Could not check auth status', 'track-artist'));
  }
}

async function loadSettingsForm(container) {
  try {
    const data = await api('/settings');
    while (container.firstChild) container.removeChild(container.firstChild);

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
          input.addEventListener('blur', () => saveSetting(field.key, input.value));
          wrapper.appendChild(input);
          const browseBtn = textEl('button', 'Browse', 'pill active');
          browseBtn.style.cursor = 'pointer';
          browseBtn.style.whiteSpace = 'nowrap';
          browseBtn.addEventListener('click', async () => {
            browseBtn.textContent = '...';
            try {
              const result = await api('/browse-directory', { method: 'POST' });
              if (result.path) {
                input.value = result.path;
                saveSetting(field.key, result.path);
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
          input.addEventListener('blur', () => saveSetting(field.key, input.value));
          row.appendChild(input);
        } else if (field.type === 'number') {
          const input = h('input', { className: 'settings-input', type: 'number' });
          input.style.width = '80px';
          input.min = '1';
          input.max = '10';
          input.value = data[field.key] || 3;
          input.addEventListener('blur', () => {
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
  } catch (err) {
    container.appendChild(textEl('div', 'Failed to load settings: ' + err.message, 'track-artist'));
  }
}

async function saveSetting(key, value) {
  try {
    const body = {};
    body[key] = value;
    await api('/settings', { method: 'PATCH', body });
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

// ---- SINGLE-TAB PLAYBACK (pause other tabs when this one plays) ----
const _playerChannel = new BroadcastChannel('music-dl-player');
_playerChannel.onmessage = (e) => {
  if (e.data === 'pause') {
    audio.pause();
    state.playing = false;
    updatePlayButton();
    setWaveformPlaying(false);
  }
};

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

// ── Waveform visualization (no Web Audio API — audio path stays untouched) ──
const WF_BARS = 80;
let _wfAnimId = null;
let _wfBars = [];

function generateWaveform() {
  while (waveform.firstChild) waveform.removeChild(waveform.firstChild);
  _wfBars = [];
  for (let i = 0; i < WF_BARS; i++) {
    const bar = h('div', { className: 'wf-bar' });
    bar.style.transform = 'scaleY(' + (0.15 + Math.random() * 0.6).toFixed(2) + ')';
    waveform.appendChild(bar);
    _wfBars.push(bar);
  }
}
generateWaveform();

// Decorative waveform: static random heights + yellow sweep following playhead.
// No frequency analysis — we refuse to touch the audio signal path.
function _wfLoop() {
  const pct = audio.duration ? (audio.currentTime / audio.duration) : 0;
  for (let i = 0; i < WF_BARS; i++) {
    const barPct = (i + 1) / WF_BARS;
    if (barPct <= pct) {
      _wfBars[i].classList.add('wf-played');
    } else {
      _wfBars[i].classList.remove('wf-played');
    }
  }
  _wfAnimId = requestAnimationFrame(_wfLoop);
}

function setWaveformPlaying(playing) {
  waveform.classList.toggle('playing', playing);
  waveform.classList.toggle('paused', !playing);
  if (playing) {
    // Regenerate random bar heights each track for visual variety
    for (let i = 0; i < WF_BARS; i++) {
      _wfBars[i].style.transform = 'scaleY(' + (0.15 + Math.random() * 0.6).toFixed(2) + ')';
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
        await api('/download', { method: 'POST', body: { track_ids: [trk.id] } });
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

// ---- PLAY COUNT (30-second threshold) ----
let _playCountTimer = null;
let _playCountLogged = false;

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

function _schedulePlayCount(track) {
  // Cancel any pending timer from previous track
  if (_playCountTimer) { clearTimeout(_playCountTimer); _playCountTimer = null; }
  _playCountLogged = false;

  // Schedule at 30s of playback — for short tracks, 'ended' event handles it
  _playCountTimer = setTimeout(() => { _logPlayEvent(track); }, 30000);
}

function playTrack(track) {
  if (!track) return;

  // Track history — dedupe by ISRC first, then by _trackKey, most recent first
  const key = _trackKey(track);
  const idx = recentlyPlayed.findIndex(t => {
    if (key === '') return false;
    // Check ISRC match first (catches same song from different file paths)
    if (track.isrc && t.isrc && track.isrc === t.isrc) return true;
    return _trackKey(t) === key;
  });
  if (idx !== -1) recentlyPlayed.splice(idx, 1);
  const entry = Object.assign({}, track, { played_at: Date.now() });
  recentlyPlayed.unshift(entry);
  if (recentlyPlayed.length > MAX_RECENT) recentlyPlayed.pop();
  _saveRecent();

  // Play count: fires after 30s of playback (or on ended for short tracks)
  _schedulePlayCount(track);

  // Tell other tabs to stop
  _playerChannel.postMessage('pause');

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
    }).catch(() => {
      audio.muted = false;
      toast('Unable to play track', 'error');
    });
  }, { once: true });
  state.playing = true;
  updatePlayButton();
  updateNowPlaying(track);
  generateWaveform();
  highlightPlayingTrack();
  updatePlayerHeart();
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
    nowArt.onclick = () => {
      if (track.album_id) {
        navigateAlbum(track.album_id);
      } else if (track.album && track.artist) {
        navigate('localalbum:' + encodeURIComponent(track.artist) + ':' + encodeURIComponent(track.album));
      }
    };
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
    // Tell other tabs to stop before resuming here
    _playerChannel.postMessage('pause');
    audio.play().catch(() => {});
    state.playing = true;
  }
  updatePlayButton();
});

btnNext.addEventListener('click', () => {
  if (state.queue.length === 0) return;
  if (state.shuffle) {
    state.queueIndex = Math.floor(Math.random() * state.queue.length);
  } else {
    state.queueIndex = (state.queueIndex + 1) % state.queue.length;
  }
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
  state.shuffle = !state.shuffle;
  btnShuffle.classList.toggle('active', state.shuffle);
});

btnRepeat.addEventListener('click', () => {
  if (state.repeat === 'off') state.repeat = 'all';
  else if (state.repeat === 'all') state.repeat = 'one';
  else state.repeat = 'off';
  btnRepeat.classList.toggle('active', state.repeat !== 'off');
  _updateRepeatIcon(btnRepeat);
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
    audio.currentTime = 0;
    audio.play().catch(() => {});
    return;
  }
  if (state.queueIndex < state.queue.length - 1 || state.shuffle) {
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
  // Pause the play count timer — resumes on play
  if (_playCountTimer) { clearTimeout(_playCountTimer); _playCountTimer = null; }
});

audio.addEventListener('error', () => {
  state.playing = false;
  updatePlayButton();
  setWaveformPlaying(false);
  const current = state.queue[state.queueIndex];
  const label = current ? (current.name || 'Track') : 'Track';
  toast(label + ' unavailable — skipping', 'error');
  // Auto-skip to next track after a brief pause
  if (state.queueIndex < state.queue.length - 1) {
    setTimeout(() => { state.queueIndex++; playTrack(state.queue[state.queueIndex]); }, 800);
  }
});

audio.addEventListener('play', () => {
  state.playing = true;
  updatePlayButton();
  setWaveformPlaying(true);
  document.querySelectorAll('.eq-bars').forEach(b => b.classList.remove('paused'));
  // Resume play count timer if not yet logged
  if (!_playCountLogged && !_playCountTimer) {
    const remaining = Math.max(0, 30 - (audio.currentTime || 0)) * 1000;
    const current = state.queue[state.queueIndex];
    if (current && remaining > 0) {
      _playCountTimer = setTimeout(() => { _logPlayEvent(current); }, remaining);
    } else if (current) {
      _logPlayEvent(current);
    }
  }
});

// Seek
function _seekFromEvent(e) {
  if (!audio.duration) return;
  const rect = progressBar.getBoundingClientRect();
  const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  audio.currentTime = pct * audio.duration;
}

progressBar.addEventListener('click', _seekFromEvent);

progressBar.addEventListener('mousedown', (e) => {
  e.preventDefault();
  _seekFromEvent(e);
  const onMove = (ev) => _seekFromEvent(ev);
  const onUp = () => {
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

// Keyboard shortcuts (YouTube-style)
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

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
    case 'ArrowRight':                                  // → — forward 5s
      if (audio.duration) audio.currentTime = Math.min(audio.duration, audio.currentTime + 5);
      break;
    case 'ArrowLeft':                                   // ← — rewind 5s
      audio.currentTime = Math.max(0, audio.currentTime - 5);
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
      navigate('search');
      setTimeout(() => {
        const input = document.querySelector('.search-input');
        if (input) input.focus();
      }, 100);
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

async function triggerLogin() {
  const tidalEl = document.getElementById('connection-tidal');
  try {
    const data = await api('/auth/login', { method: 'POST' });
    if (data.status === 'already_logged_in') {
      refreshStatusLights();
      return;
    }
    if (data.verification_uri) {
      window.open(data.verification_uri, '_blank');
    }
    // Update light to show waiting state
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
          refreshStatusLights();
        } else if (status.status === 'failed') {
          clearInterval(_loginPoll);
          _loginPoll = null;
          refreshStatusLights();
        }
      } catch (_) {
        clearInterval(_loginPoll);
        _loginPoll = null;
      }
    }, 3000);
  } catch (err) {
    console.error('[music-dl] login failed:', err);
  }
}

// ---- QUEUE PANEL ----
const queuePanel = document.getElementById('queue-panel');
const queueListEl = document.getElementById('queue-list');
const btnQueueClose = document.getElementById('queue-close');

function toggleQueue() {
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
      state.queue.splice(i, 1);
      if (i < state.queueIndex) state.queueIndex--;
      else if (i === state.queueIndex && state.queue.length === 0) {
        state.queueIndex = -1;
      } else if (i === state.queueIndex && state.queueIndex >= state.queue.length) {
        state.queueIndex = state.queue.length - 1;
      }
      renderQueue();
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
  controls.appendChild(scanBtn);
  controls.appendChild(cancelBtn);
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

  scanBtn.addEventListener('click', () => {
    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';
    cancelBtn.style.display = '';
    progressBar.style.display = '';
    while (resultsEl.firstChild) resultsEl.removeChild(resultsEl.firstChild);

    eventSource = new EventSource('/api/upgrade/scan');
    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      if (data.type === 'scan_progress') {
        const pct = data.total > 0 ? Math.round((data.checked / data.total) * 100) : 0;
        progressFill.style.width = pct + '%';
        statusEl.textContent = 'Checked ' + data.checked + ' / ' + data.total + ' \u2014 ' + data.upgradeable + ' upgradeable' + (data.skipped_no_isrc ? ' \u2014 ' + data.skipped_no_isrc + ' skipped (no ISRC)' : '');
      } else if (data.type === 'scan_complete') {
        progressFill.style.width = '100%';
        statusEl.textContent = 'Done: ' + data.upgradeable + ' upgradeable of ' + data.checked + ' checked' + (data.skipped_no_isrc ? ' (' + data.skipped_no_isrc + ' skipped, no ISRC)' : '');
        scanBtn.disabled = false;
        scanBtn.textContent = 'Scan Again';
        cancelBtn.style.display = 'none';
        eventSource.close();
        _renderScanResults(resultsEl, data.results || []);
      } else if (data.type === 'scan_error') {
        statusEl.textContent = 'Error: ' + data.error;
        scanBtn.disabled = false;
        scanBtn.textContent = 'Retry';
        cancelBtn.style.display = 'none';
        eventSource.close();
      } else if (data.type === 'scan_cancelled') {
        statusEl.textContent = 'Scan cancelled.';
        scanBtn.disabled = false;
        scanBtn.textContent = 'Start Scan';
        cancelBtn.style.display = 'none';
        eventSource.close();
      }
    };
    eventSource.onerror = () => {
      statusEl.textContent = 'Connection lost.';
      scanBtn.disabled = false;
      scanBtn.textContent = 'Retry';
      cancelBtn.style.display = 'none';
    };
  });

  cancelBtn.addEventListener('click', async () => {
    if (eventSource) eventSource.close();
    try { await api('/upgrade/scan/cancel', { method: 'POST' }); } catch (_) {}
    cancelBtn.style.display = 'none';
    scanBtn.disabled = false;
    scanBtn.textContent = 'Start Scan';
  });
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
    const paths = results.map(r => r.path);
    try {
      await api('/upgrade/start', { method: 'POST', body: { track_paths: paths } });
      toast('Upgrade started for ' + paths.length + ' tracks', 'success');
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
          await api('/upgrade/start', { method: 'POST', body: { track_paths: [t.path] } });
        } catch (_) {
          upBtn.disabled = false;
          upBtn.textContent = 'Retry';
        }
      });
      row.appendChild(upBtn);
      groupEl.appendChild(row);
    });

    container.appendChild(groupEl);
  });
}

// ---- INIT ----
// Load settings into state for upgrade quality checks
api('/settings').then(s => { state.settings = s; }).catch(() => {});
refreshStatusLights();
navigate(location.hash.slice(1) || 'home');
