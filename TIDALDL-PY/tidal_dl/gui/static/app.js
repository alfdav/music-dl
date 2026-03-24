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

function formatTime(seconds) {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + ':' + String(s).padStart(2, '0');
}

// RPG-tier quality system
function _qualityTier(q) {
  if (!q) return { tier: 'Common', cls: 'quality-common', desc: 'Unknown quality' };
  const ql = q.toUpperCase();

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

function qualityClass(q) { return _qualityTier(q).cls; }
function qualityLabel(q) { return _qualityTier(q).tier; }
function qualityTitle(q) { return _qualityTier(q).desc; }

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
  repeat: false,
  volume: 0.7,
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
    throw new Error(detail.detail || 'API error ' + resp.status);
  }

  return resp.json();
}

// ---- TOAST ----
let toastContainer;

function toast(message, type) {
  if (!toastContainer) {
    toastContainer = h('div', { className: 'toast-container' });
    document.body.appendChild(toastContainer);
  }
  const t = textEl('div', message, 'toast' + (type ? ' ' + type : ''));
  toastContainer.appendChild(t);
  setTimeout(() => { t.remove(); }, 3000);
}

// ---- ROUTER ----
const viewEl = document.getElementById('view');
const navItems = document.querySelectorAll('.nav-item[data-view]');

let _lastNavHash = '';

function navigate(view) {
  if (!view) view = 'home';
  state.view = view;
  _lastNavHash = view;
  location.hash = view;

  navItems.forEach(n => {
    n.classList.toggle('active', n.dataset.view === view);
  });

  // Clear view safely
  while (viewEl.firstChild) viewEl.removeChild(viewEl.firstChild);

  const container = h('div', { className: 'view-enter' });

  switch (view) {
    case 'home': renderHome(container); break;
    case 'search': renderSearch(container); break;
    case 'library': renderLibrary(container); break;
    case 'recent': renderRecentlyPlayed(container); break;
    case 'playlists': renderPlaylists(container); break;
    case 'downloads': renderDownloads(container); break;
    case 'settings': renderSettings(container); break;
    case 'djai': renderDjai(container); break;
    default:
      if (view.startsWith('album:')) {
        renderAlbumDetail(container, view.split(':')[1]);
      } else {
        renderPlaceholder(container, 'Not Found', 'This view does not exist.');
      }
  }

  viewEl.appendChild(container);
}

navItems.forEach(n => {
  n.addEventListener('click', () => navigate(n.dataset.view));
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

    // Check library size first — confirm on large libraries
    try {
      const data = await api('/library?limit=1&offset=0');
      const total = data.total || 0;
      if (total > 500) {
        if (!confirm('Your library has ' + total.toLocaleString() + ' tracks. Syncing will re-scan your music folder which may take a while.\n\nContinue?')) return;
      }
    } catch (_) { /* proceed anyway if check fails */ }

    triggerScan(navSyncBtn, resultsArea, true);
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

  if (data.top_artist && data.top_artist.play_count >= 5) {
    grid.appendChild(_artistTile(data.top_artist, true));
  }
  if (data.most_replayed && data.most_replayed.play_count >= 10) {
    grid.appendChild(_replayedTile(data.most_replayed));
  }

  if (data.genre_breakdown && data.genre_breakdown.length > 0) {
    grid.appendChild(_genreTile(data.top_genre, data.genre_breakdown));
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    grid.appendChild(_listeningTimeTile(data.listening_time_hours, data.weekly_activity));
  }

  const extraArtists = (data.top_artists || []).slice(1, 3);
  for (const a of extraArtists) {
    if (a.play_count >= 3) {
      grid.appendChild(_artistTile(a, false));
    }
  }

  if (established || data.track_count > 0) {
    grid.appendChild(_tracksTile(data.track_count, data.track_genres));
  }
  if (established || data.album_count > 0) {
    grid.appendChild(_albumsTile(data.album_count, data.album_artists));
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
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View artist', 'bento-hint'));
  tile.addEventListener('click', () => {
    navigate('library');
    setTimeout(() => {
      const input = document.querySelector('.lib-search');
      if (input) { input.value = artist.name; input.dispatchEvent(new Event('input')); }
    }, 100);
  });
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
  return tile;
}

// Build an insight line: text with one gold keyword
function _insight(before, keyword, after) {
  const el = h('div', { className: 'bento-insight' });
  if (before) el.appendChild(document.createTextNode(before));
  el.appendChild(h('span', { className: 'insight-gold' }, keyword));
  if (after) el.appendChild(document.createTextNode(after));
  return el;
}

function _genreInsight(topGenre, breakdown) {
  if (breakdown.length >= 2) {
    const pct = Math.round((breakdown[0].count / breakdown.reduce((s, g) => s + g.count, 0)) * 100);
    return _insight(pct + '% of your plays are ', topGenre, '');
  }
  return _insight('Your world revolves around ', topGenre, '');
}

function _listeningInsight(weekly) {
  const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const maxIdx = weekly.indexOf(Math.max(...weekly));
  if (Math.max(...weekly) === 0) return null;
  return _insight('You love listening on ', days[maxIdx], ' the most');
}

function _tracksInsight(count) {
  if (count >= 10000) return _insight('', count.toLocaleString(), ' tracks — that\'s a serious collection');
  if (count >= 1000) return _insight('', count.toLocaleString(), ' tracks and counting');
  return _insight('Your library has ', count.toLocaleString(), ' tracks so far');
}

function _albumsInsight(count, artists) {
  if (artists && artists.length > 0) {
    return _insight('', artists[0].artist, ' dominates your shelf with ' + artists[0].count + ' albums');
  }
  return _insight('', count.toLocaleString(), ' albums in your collection');
}

function _genreTile(topGenre, breakdown) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
  body.appendChild(textEl('div', 'Top genre', 'bento-stat-label'));
  body.appendChild(_genreInsight(topGenre, breakdown));
  body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View stats', 'bento-hint'));
  tile.addEventListener('click', () => toast('Stats detail coming soon'));
  return tile;
}

function _listeningTimeTile(hours, weekly) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', Math.round(hours) + 'h', 'bento-label'));
  body.appendChild(textEl('div', 'Listening time', 'bento-stat-label'));
  const ins = _listeningInsight(weekly);
  if (ins) body.appendChild(ins);
  body.appendChild(_weeklyChart(weekly));
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View stats', 'bento-hint'));
  tile.addEventListener('click', () => toast('Stats detail coming soon'));
  return tile;
}

function _tracksTile(count, genres) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', count.toLocaleString(), 'bento-label'));
  body.appendChild(textEl('div', 'Tracks', 'bento-stat-label'));
  body.appendChild(_tracksInsight(count));
  if (genres && genres.length > 0) {
    body.appendChild(_barChart(genres.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  }
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View stats', 'bento-hint'));
  tile.addEventListener('click', () => toast('Stats detail coming soon'));
  return tile;
}

function _albumsTile(count, artists) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', count.toLocaleString(), 'bento-label'));
  body.appendChild(textEl('div', 'Albums', 'bento-stat-label'));
  body.appendChild(_albumsInsight(count, artists));
  if (artists && artists.length > 0) {
    body.appendChild(_barChart(artists.slice(0, 4).map(a => ({ label: a.artist, value: a.count }))));
  }
  tile.appendChild(body);
  tile.appendChild(textEl('span', 'View stats', 'bento-hint'));
  tile.addEventListener('click', () => toast('Stats detail coming soon'));
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
  const statsBtn = h('div', { className: 'pill pill-sm stats-link', onClick: () => toast('Stats detail coming soon') });
  const statsSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  statsSvg.setAttribute('viewBox', '0 0 24 24');
  statsSvg.setAttribute('fill', 'none');
  statsSvg.setAttribute('stroke', 'currentColor');
  statsSvg.setAttribute('stroke-width', '2');
  statsSvg.style.cssText = 'width:14px;height:14px;';
  // SAFE: static SVG paths, no user data
  statsSvg.innerHTML = '<path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/>'; // eslint-disable-line
  statsBtn.appendChild(statsSvg);
  statsBtn.appendChild(document.createTextNode('Check my stats'));
  rightBtns.appendChild(statsBtn);
  labelRow.appendChild(rightBtns);
  section.appendChild(labelRow);

  const strip = h('div', { className: 'recent-strip' });
  for (const track of recentlyPlayed) {
    const card = h('div', { className: 'recent-card' });
    if (track.cover_url) {
      card.appendChild(h('img', { className: 'recent-card-art', src: track.cover_url, alt: '' }));
    } else {
      const artPlaceholder = h('div', { className: 'recent-card-art' });
      artPlaceholder.style.background = artGradient(track.id);
      card.appendChild(artPlaceholder);
    }
    card.appendChild(textEl('div', track.name || 'Unknown', 'recent-card-name'));
    const artistEl = textEl('div', track.artist || '', 'recent-card-artist');
    artistEl.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!track.artist) return;
      navigate('library');
      setTimeout(() => {
        const input = document.querySelector('.lib-search');
        if (input) { input.value = track.artist; input.dispatchEvent(new Event('input')); }
      }, 100);
    });
    card.appendChild(artistEl);
    card.addEventListener('click', () => {
      if (track.is_local && track.local_path) playTrack(track);
      else if (track.id) playTrack(track);
    });
    strip.appendChild(card);
  }
  section.appendChild(strip);
  container.appendChild(section);
}

// ---- SEARCH VIEW ----
let searchDebounce = null;

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
  input.addEventListener('input', () => {
    state.searchQuery = input.value;
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => doSearch(resultsArea), 300);
  });
  searchField.appendChild(input);
  searchRow.appendChild(searchField);
  searchArea.appendChild(searchRow);

  // Filter pills
  const pills = h('div', { className: 'filter-pills' });
  for (const type of ['tracks', 'albums', 'artists', 'playlists']) {
    const pill = textEl('div', type.charAt(0).toUpperCase() + type.slice(1),
      'pill' + (state.searchType === type ? ' active' : ''));
    pill.style.cursor = 'pointer';
    pill.addEventListener('click', () => {
      state.searchType = type;
      pills.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      if (state.searchQuery) doSearch(resultsArea);
    });
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

  renderSearchSkeleton(resultsArea);

  try {
    const data = await api('/search?q=' + encodeURIComponent(q) + '&type=' + state.searchType + '&limit=50');
    state.searchResults = data;
    renderSearchResults(resultsArea, data);
    refreshStatusLights();
  } catch (err) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Search failed', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
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
    const colHeader = h('div', { className: 'track-header' },
      textEl('div', '#', 'col-label center'),
      h('div'),
      textEl('div', 'Title', 'col-label'),
      textEl('div', 'Album', 'col-label'),
      textEl('div', 'Quality', 'col-label center'),
      textEl('div', 'Time', 'col-label right'),
      h('div')
    );
    container.appendChild(colHeader);

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
        artDiv.appendChild(img);
      } else {
        artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(item.id) } }));
      }
      grid.appendChild(h('div', { className: 'album-card' },
        artDiv,
        textEl('div', item.name || '', 'album-card-name')
      ));
    });
    container.appendChild(grid);
  }
}

function renderTrackRow(track, num, allTracks) {
  const isPlaying = state.queue[state.queueIndex]?.id === track.id && state.playing;
  const row = h('div', { className: 'track' + (isPlaying ? ' playing' : ''), 'data-track-id': String(track.id) });

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
    artCell.appendChild(h('img', { className: 'track-art-img', src: track.cover_url, loading: 'lazy', alt: '' }));
  } else {
    artCell.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(track.id) } }));
  }
  row.appendChild(artCell);

  // Meta — user data via textContent only
  row.appendChild(h('div', { className: 'track-meta' },
    textEl('div', track.name || '', 'track-name'),
    textEl('div', track.artist || '', 'track-artist')
  ));

  // Album — clickable if album_id is present
  const albumCell = textEl('div', track.album || '', 'track-album');
  if (track.album_id) {
    albumCell.addEventListener('click', (e) => {
      e.stopPropagation();
      navigateAlbum(track.album_id);
    });
  }
  row.appendChild(albumCell);

  // Quality
  const qTag = textEl('div', qualityLabel(track.quality), 'quality-tag ' + qualityClass(track.quality));
  qTag.title = qualityTitle(track.quality);
  row.appendChild(qTag);

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

  // Click to play
  row.addEventListener('click', () => {
    state.queue = allTracks.slice();
    state.queueIndex = allTracks.indexOf(track);
    playTrack(track);
  });

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
    header.appendChild(headerMeta);
    resultsArea.appendChild(header);

    resultsArea.appendChild(h('div', { className: 'track-header' },
      textEl('div', '#', 'col-label center'),
      h('div'),
      textEl('div', 'Title', 'col-label'),
      textEl('div', 'Album', 'col-label'),
      textEl('div', 'Quality', 'col-label center'),
      textEl('div', 'Time', 'col-label right'),
      h('div')
    ));

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

  const libInput = h('input', {
    type: 'text', className: 'search-input',
    placeholder: 'Search your library...', value: libraryQuery,
  });
  searchArea.appendChild(libInput);

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
      loadLibrary(resultsArea);
    });
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
      loadLibrary(resultsArea);
    }, 300);
  });

  // Load cached results — user clicks Sync Library to scan
  loadLibrary(resultsArea, false);
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
      textNode.textContent = ' Scanning... ' + status.scanned;
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

      resultsArea.appendChild(h('div', { className: 'track-header' },
        textEl('div', '#', 'col-label center'),
        h('div'),
        textEl('div', 'Title', 'col-label'),
        textEl('div', 'Album', 'col-label'),
        textEl('div', 'Format', 'col-label center'),
        textEl('div', 'Time', 'col-label right'),
        h('div')
      ));

      const trackList = h('div', { className: 'tracks', id: 'library-tracks' });
      resultsArea.appendChild(trackList);
    }

    const trackList = document.getElementById('library-tracks') ||
      resultsArea.querySelector('.tracks');
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

// ---- RECENTLY PLAYED VIEW ----
function renderRecentlyPlayed(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  resultsArea.appendChild(h('div', { className: 'results-header' },
    textEl('div', 'Recently Played', 'results-title'),
    textEl('div', recentlyPlayed.length + ' tracks', 'results-count')
  ));

  if (recentlyPlayed.length === 0) {
    resultsArea.appendChild(h('div', { className: 'empty-state' },
      svgIcon(ICONS.music),
      textEl('div', 'Nothing played yet', 'empty-state-title'),
      textEl('div', 'Tracks you play will show up here.', 'empty-state-sub')
    ));
    return;
  }

  resultsArea.appendChild(h('div', { className: 'track-header' },
    textEl('div', '#', 'col-label center'),
    h('div'),
    textEl('div', 'Title', 'col-label'),
    textEl('div', 'Album', 'col-label'),
    textEl('div', 'Quality', 'col-label center'),
    textEl('div', 'Time', 'col-label right'),
    h('div')
  ));

  const trackList = h('div', { className: 'tracks' });
  recentlyPlayed.forEach((track, i) => {
    trackList.appendChild(renderTrackRow(track, i + 1, recentlyPlayed));
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

    const grid = h('div', { className: 'album-grid' });
    playlists.forEach(pl => {
      const artDiv = h('div', { className: 'album-card-art' });
      if (pl.cover_url) {
        artDiv.appendChild(h('img', { src: pl.cover_url, loading: 'lazy', alt: '' }));
      } else {
        artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(pl.id.charCodeAt(0) || 0) } }));
      }
      const card = h('div', { className: 'album-card' },
        artDiv,
        textEl('div', pl.name || '', 'album-card-name'),
        textEl('div', (pl.num_tracks || 0) + ' tracks', 'album-card-artist')
      );
      card.addEventListener('click', () => loadPlaylistTracks(resultsArea, pl));
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
  renderSearchSkeleton(resultsArea);
  try {
    const data = await api('/playlists/' + encodeURIComponent(pl.id) + '/tracks');
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    const tracks = data.tracks || [];

    const header = h('div', { className: 'results-header' });
    const backBtn = textEl('span', '\u2190 Playlists', 'pill');
    backBtn.style.cursor = 'pointer';
    backBtn.addEventListener('click', () => loadPlaylists(resultsArea));
    header.appendChild(backBtn);
    header.appendChild(textEl('div', pl.name || '', 'results-title'));
    header.appendChild(textEl('div', tracks.length + ' tracks', 'results-count'));
    resultsArea.appendChild(header);

    // Sync button
    const syncBtn = textEl('button', 'Download Missing', 'pill active');
    syncBtn.style.cursor = 'pointer';
    syncBtn.style.marginBottom = '16px';
    syncBtn.addEventListener('click', async () => {
      syncBtn.textContent = 'Syncing...';
      syncBtn.style.pointerEvents = 'none';
      try {
        const result = await api('/playlists/' + encodeURIComponent(pl.id) + '/sync', { method: 'POST' });
        if (result.status === 'up_to_date') {
          toast('All tracks are already local', 'success');
        } else {
          toast('Downloading ' + result.missing + ' missing tracks', 'success');
        }
      } catch (err) {
        toast('Sync failed: ' + err.message, 'error');
      }
      syncBtn.textContent = 'Download Missing';
      syncBtn.style.pointerEvents = '';
    });
    resultsArea.appendChild(syncBtn);

    resultsArea.appendChild(h('div', { className: 'track-header' },
      textEl('div', '#', 'col-label center'),
      h('div'),
      textEl('div', 'Title', 'col-label'),
      textEl('div', 'Album', 'col-label'),
      textEl('div', 'Quality', 'col-label center'),
      textEl('div', 'Time', 'col-label right'),
      h('div')
    ));

    const trackList = h('div', { className: 'tracks' });
    tracks.forEach((track, i) => {
      trackList.appendChild(renderTrackRow(track, i + 1, tracks));
    });
    resultsArea.appendChild(trackList);
  } catch (err) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'empty-state' },
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

// ---- DOWNLOADS VIEW ----
function renderDownloads(container) {
  const resultsArea = h('div', { className: 'results' });
  container.appendChild(resultsArea);

  resultsArea.appendChild(h('div', { className: 'results-header' },
    textEl('div', 'Downloads', 'results-title')
  ));

  const activeSection = h('div', { id: 'dl-active' });
  resultsArea.appendChild(textEl('div', 'Active', 'col-label'));
  resultsArea.appendChild(activeSection);

  resultsArea.appendChild(h('div', { style: { height: '24px' } }));
  resultsArea.appendChild(textEl('div', 'History', 'col-label'));
  const historySection = h('div', { id: 'dl-history' });
  resultsArea.appendChild(historySection);

  // Use global SSE — it updates #dl-active automatically
  _ensureGlobalSSE();

  // Load history
  loadDownloadHistory(historySection);
}

function updateActiveDownload(container, data) {
  let row = container.querySelector('[data-dl-id="' + data.track_id + '"]');
  if (data.type === 'complete' || data.type === 'error') {
    if (row) row.remove();
    return;
  }
  if (!row) {
    row = h('div', { 'data-dl-id': String(data.track_id), style: { padding: '8px 0' } });
    container.appendChild(row);
  }
  while (row.firstChild) row.removeChild(row.firstChild);
  row.appendChild(textEl('span', data.name || 'Track ' + data.track_id, ''));
  row.appendChild(textEl('span', ' \u2014 ' + (data.status || ''), 'track-artist'));
}

async function loadDownloadHistory(container) {
  try {
    const data = await api('/downloads/history');
    const downloads = data.downloads || [];
    if (downloads.length === 0) {
      container.appendChild(textEl('div', 'Your downloaded tracks will appear here.', 'track-artist'));
      return;
    }
    downloads.forEach(dl => {
      container.appendChild(h('div', { style: { padding: '4px 0' } },
        textEl('span', dl.name || 'Track ' + dl.track_id, ''),
        textEl('span', ' \u2014 ' + (dl.status || ''), 'track-artist')
      ));
    });
  } catch (_) {
    container.appendChild(textEl('div', 'Failed to load history.', 'track-artist'));
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

    const fields = [
      { key: 'download_base_path', label: 'Download Path', type: 'path' },
      { key: 'quality_audio', label: 'Audio Quality', type: 'select', options: ['HI_RES_LOSSLESS', 'HI_RES', 'LOSSLESS', 'HIGH', 'LOW'] },
      { key: 'skip_existing', label: 'Skip Existing', type: 'toggle' },
      { key: 'metadata_cover_embed', label: 'Embed Cover Art', type: 'toggle' },
      { key: 'lyrics_embed', label: 'Embed Lyrics', type: 'toggle' },
      { key: 'lyrics_file', label: 'Save Lyrics File', type: 'toggle' },
      { key: 'cover_album_file', label: 'Save Album Cover', type: 'toggle' },
      { key: 'downloads_concurrent_max', label: 'Max Concurrent Downloads', type: 'number' },
    ];

    fields.forEach(field => {
      const row = h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid var(--glass-border)' } });
      row.appendChild(textEl('label', field.label, ''));

      if (field.type === 'path') {
        const wrapper = h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } });
        const input = h('input', { className: 'search-input', type: 'text', style: { width: '260px', borderRadius: '8px', padding: '8px 12px' } });
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
        const input = h('input', { className: 'search-input', type: 'text', style: { width: '300px', borderRadius: '8px', padding: '8px 12px' } });
        input.value = data[field.key] || '';
        input.addEventListener('blur', () => saveSetting(field.key, input.value));
        row.appendChild(input);
      } else if (field.type === 'number') {
        const input = h('input', { className: 'search-input', type: 'number', style: { width: '80px', borderRadius: '8px', padding: '8px 12px' } });
        input.value = data[field.key] || 3;
        input.addEventListener('blur', () => saveSetting(field.key, parseInt(input.value, 10)));
        row.appendChild(input);
      } else if (field.type === 'select') {
        const select = h('select', { className: 'search-input', style: { width: '200px', borderRadius: '8px', padding: '8px 12px', background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--glass-border)' } });
        field.options.forEach(opt => {
          const option = h('option', { value: opt });
          option.textContent = opt;
          if (data[field.key] === opt) option.selected = true;
          select.appendChild(option);
        });
        select.addEventListener('change', () => saveSetting(field.key, select.value));
        row.appendChild(select);
      } else if (field.type === 'toggle') {
        const btn = textEl('button', data[field.key] ? 'On' : 'Off',
          'pill' + (data[field.key] ? ' active' : ''));
        btn.style.cursor = 'pointer';
        let val = !!data[field.key];
        btn.addEventListener('click', () => {
          val = !val;
          btn.textContent = val ? 'On' : 'Off';
          btn.className = 'pill' + (val ? ' active' : '');
          saveSetting(field.key, val);
        });
        row.appendChild(btn);
      }

      container.appendChild(row);
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

// ── Web Audio API: real-time frequency-reactive waveform ──
const WF_BARS = 80;
let _audioCtx = null;
let _analyser = null;
let _freqData = null;
let _wfAnimId = null;
let _wfBars = [];

function _ensureAudioContext() {
  if (_audioCtx) return;
  _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = _audioCtx.createMediaElementSource(audio);
  _analyser = _audioCtx.createAnalyser();
  _analyser.fftSize = 256; // 128 frequency bins
  _analyser.smoothingTimeConstant = 0.8;
  _freqData = new Uint8Array(_analyser.frequencyBinCount);
  src.connect(_analyser);
  _analyser.connect(_audioCtx.destination);
}

function generateWaveform() {
  while (waveform.firstChild) waveform.removeChild(waveform.firstChild);
  _wfBars = [];
  for (let i = 0; i < WF_BARS; i++) {
    const bar = h('div', { className: 'wf-bar' });
    // Static random heights as idle visual — Web Audio overwrites on play
    bar.style.transform = 'scaleY(' + (0.15 + Math.random() * 0.6).toFixed(2) + ')';
    waveform.appendChild(bar);
    _wfBars.push(bar);
  }
}
generateWaveform();

function _wfLoop() {
  if (!_analyser) { _wfAnimId = requestAnimationFrame(_wfLoop); return; }
  _analyser.getByteFrequencyData(_freqData);
  const bins = _freqData.length; // 128
  const step = bins / WF_BARS;
  // Progress percentage for yellow sweep
  const pct = audio.duration ? (audio.currentTime / audio.duration) : 0;
  for (let i = 0; i < WF_BARS; i++) {
    // Map bar index to frequency bin (logarithmic-ish grouping for bass emphasis)
    const binIdx = Math.min(Math.floor(i * step), bins - 1);
    const val = _freqData[binIdx] / 255; // 0..1
    const scale = 0.05 + val * 0.95; // min 5% height
    _wfBars[i].style.transform = `scaleY(${scale})`;
    // Yellow sweep: bars behind playhead get accent color
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
    _ensureAudioContext();
    if (_audioCtx.state === 'suspended') _audioCtx.resume();
    if (!_wfAnimId) _wfAnimId = requestAnimationFrame(_wfLoop);
  } else {
    if (_wfAnimId) { cancelAnimationFrame(_wfAnimId); _wfAnimId = null; }
  }
}

// Set initial volume
audio.volume = state.volume;
volFill.style.width = (state.volume * 100) + '%';

const MAX_RECENT = 50;
const recentlyPlayed = (() => {
  try {
    return JSON.parse(localStorage.getItem('recentlyPlayed') || '[]').slice(0, MAX_RECENT);
  } catch (_) { return []; }
})();

function _saveRecent() {
  try { localStorage.setItem('recentlyPlayed', JSON.stringify(recentlyPlayed)); } catch (_) {}
}

function playTrack(track) {
  if (!track) return;

  // Track history — dedupe by id, most recent first
  const idx = recentlyPlayed.findIndex(t => t.id === track.id);
  if (idx !== -1) recentlyPlayed.splice(idx, 1);
  recentlyPlayed.unshift(track);
  if (recentlyPlayed.length > MAX_RECENT) recentlyPlayed.pop();
  _saveRecent();

  // Log play event for Home view stats (fire-and-forget)
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

  // Tell other tabs to stop
  _playerChannel.postMessage('pause');

  if (track.is_local && track.local_path) {
    audio.src = '/api/playback/local?path=' + encodeURIComponent(track.local_path);
  } else {
    audio.src = '/api/playback/stream/' + track.id;
  }

  audio.play().catch(() => {
    toast('Unable to play track', 'error');
  });
  state.playing = true;
  updatePlayButton();
  updateNowPlaying(track);
  generateWaveform();
  highlightPlayingTrack();
}

function updateNowPlaying(track) {
  const info = document.querySelector('.now-info');

  // Crossfade: dim out, update, dim back in
  if (info) info.classList.add('changing');

  setTimeout(() => {
    nowTitle.classList.remove('idle-clickable');
    nowTitle.removeAttribute('onclick');
    nowTitle.removeAttribute('title');
    nowTitle.textContent = track.name || 'Unknown';
    nowSub.textContent = (track.artist || '') + (track.album ? ' \u2014 ' + track.album : '');

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
    while (nowArt.firstChild) nowArt.removeChild(nowArt.firstChild);
    if (track.cover_url) {
      nowArt.appendChild(h('img', { className: 'now-art-img', src: track.cover_url, alt: '' }));
    } else {
      nowArt.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(track.id) } }));
    }

    if (info) info.classList.remove('changing');
  }, 150);
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
  state.repeat = !state.repeat;
  btnRepeat.classList.toggle('active', state.repeat);
});

// Progress
audio.addEventListener('timeupdate', () => {
  if (!audio.duration) return;
  const pct = (audio.currentTime / audio.duration) * 100;
  progressFill.style.width = pct + '%';
  timeElapsed.textContent = formatTime(audio.currentTime);
  timeTotal.textContent = formatTime(audio.duration);
});

audio.addEventListener('ended', () => {
  if (state.repeat) {
    audio.currentTime = 0;
    audio.play().catch(() => {});
    return;
  }
  if (state.queueIndex < state.queue.length - 1 || state.shuffle) {
    btnNext.click();
  } else {
    state.playing = false;
    updatePlayButton();
  }
});

audio.addEventListener('pause', () => {
  state.playing = false;
  updatePlayButton();
  setWaveformPlaying(false);
  document.querySelectorAll('.eq-bars').forEach(b => b.classList.add('paused'));
});

audio.addEventListener('play', () => {
  state.playing = true;
  updatePlayButton();
  setWaveformPlaying(true);
  document.querySelectorAll('.eq-bars').forEach(b => b.classList.remove('paused'));
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

// Mute/unmute on icon click
btnVol.addEventListener('click', () => {
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

// ---- INIT ----
refreshStatusLights();
navigate(location.hash.slice(1) || 'home');
