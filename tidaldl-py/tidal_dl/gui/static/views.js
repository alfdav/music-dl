// ---- ROUTER ----
const viewEl = document.getElementById('view');
const navItems = document.querySelectorAll('.nav-item[data-view]');

let _lastNavHash = '';
const _viewState = {};
const _navStack = [];

// ---- NAV STACK ----
function _isTopLevelView(view) {
  return view === 'home' || view === 'search' || view === 'library'
    || view === 'recent' || view === 'playlists' || view === 'favorites'
    || view === 'downloads' || view === 'settings' || view === 'djai'
    || view === 'upgrades' || view === 'recent-added';
}

function _isDrillInView(view) {
  const name = String(view || '');
  return name.startsWith('artist:') || name.startsWith('localalbum:')
    || name.startsWith('localrelease:') || name.startsWith('album:');
}

function _shouldShowNavBack(view, stackLen) {
  return stackLen > 0 && _isDrillInView(view) && !_isTopLevelView(view);
}

function _snapshotOutgoing(view, sort, query, scrollY) {
  return {
    view: view || '',
    librarySort: sort || 'artist',
    libraryQuery: query || '',
    scrollY: scrollY || 0,
  };
}

function _pushNav(stack, snapshot) {
  if (!stack || !snapshot || !snapshot.view) return stack;
  stack.push(snapshot);
  return stack;
}

function _popNav(stack) {
  if (!stack || !stack.length) return null;
  return stack.pop();
}

function _restoreLibrary(snapshot, target) {
  if (!snapshot || !target) return target;
  if (snapshot.librarySort != null) target.librarySort = snapshot.librarySort;
  if (snapshot.libraryQuery != null) target.libraryQuery = snapshot.libraryQuery;
  return target;
}

function _navMode(opts) {
  if (opts && opts.back) return 'back';
  if (opts && (opts.jump || opts.replace)) return 'jump';
  return 'push';
}

function _hashchangeNavOpts(hash, lastNavHash, stackTopView) {
  if (hash === lastNavHash) return null;
  if (stackTopView && hash === stackTopView) return { back: true };
  return { jump: true };
}
// ---- /NAV STACK ----

function _navBackControl() {
  if (!_shouldShowNavBack(state.view, _navStack.length)) return null;
  const btn = h('button', { type: 'button', className: 'nav-back' });
  btn.setAttribute('aria-label', 'Back');
  btn.appendChild(svgIcon(ICONS.back));
  btn.addEventListener('click', () => navigate(null, { back: true }));
  return btn;
}

function navigate(view, opts) {
  _closeHomeInsightFan();
  const mode = _navMode(opts);
  let restore = null;
  if (mode === 'back') {
    restore = _popNav(_navStack);
    view = (restore && restore.view) || view || 'home';
  }

  const safeView = normalizeView(view);

  // Save outgoing view state
  if (state.view && viewEl.firstChild) {
    const scrollEl = document.querySelector('.main');
    _viewState[state.view] = {
      scrollY: scrollEl ? scrollEl.scrollTop : 0,
    };
  }

  if (mode === 'jump') {
    _navStack.length = 0;
  } else if (mode === 'push' && state.view && state.view !== safeView) {
    const saved = _viewState[state.view];
    _pushNav(_navStack, _snapshotOutgoing(
      state.view,
      librarySort,
      libraryQuery,
      saved ? saved.scrollY : 0,
    ));
  }

  if (restore) {
    const next = _restoreLibrary(restore, { librarySort, libraryQuery });
    librarySort = next.librarySort;
    libraryQuery = next.libraryQuery;
    _viewState[restore.view] = { scrollY: restore.scrollY || 0 };
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
      : (safeView.startsWith('localalbum:') || safeView.startsWith('localrelease:')) ? 'library'
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
      } else if (safeView.startsWith('localrelease:')) {
        renderLocalReleaseDetail(container, safeView.substring(13));
      } else if (safeView.startsWith('artist:')) {
        const parsed = parseArtistView(safeView);
        renderArtistGallery(container, parsed.name, parsed.tidalId);
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
  n.addEventListener('click', () => navigate(n.dataset.view, { jump: true }));
  a11yClick(n);
});

window.addEventListener('hashchange', () => {
  const hash = normalizeView(location.hash.slice(1) || 'home');
  const top = _navStack.length ? _navStack[_navStack.length - 1].view : '';
  const hashOpts = _hashchangeNavOpts(hash, _lastNavHash, top);
  if (!hashOpts) return; // already handled by navigate()
  navigate(hash, hashOpts);
});

// Sidebar Sync Library button
const navSyncBtn = document.getElementById('nav-sync-library');
if (navSyncBtn) {
  navSyncBtn.addEventListener('click', async () => {
    navigate('library', { jump: true });
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
  container.querySelectorAll('.home-wrap').forEach(old => old.remove());
  container.appendChild(wrap);

  let data;
  try {
    data = await api('/home');
  } catch (_) {
    if (!wrap.isConnected) return;
    wrap.classList.remove('home-loading');
    loadingHint.remove();
    wrap.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load Home', 'empty-state-title'),
      textEl('div', 'Home could not load your library summary. Try again in a moment.', 'empty-state-sub')
    ));
    return;
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
    if (!saved || saved.key !== _trackKey(current)) return null;
    if (!_isResumePositionUsable(current, saved.time)) {
      localStorage.removeItem('playerPosition');
      return null;
    }
    return { track: current, time: saved.time };
  } catch (_) {
    return null;
  }
}

function _isResumePositionUsable(track, time, durationOverride) {
  const resumeAt = Number(time || 0);
  if (!(resumeAt > 0)) return false;
  const duration = Number(durationOverride || track.duration || 0);
  if (!duration) return true;
  return resumeAt < Math.max(1, duration - 5);
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
  container.querySelectorAll('.continue-card').forEach(old => old.remove());
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
    _bindHomeDataFan(genreTile, data);
    // For split tiles, also set on the genre half
    if (onRepeatTrack) {
      const genreHalf = genreTile.querySelector('.bento-half:not(.bento-on-repeat)');
      if (genreHalf) genreHalf._homeData = data;
    }
    grid.appendChild(genreTile);
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    const ltTile = _listeningTimeTile(data.listening_time_hours, data.weekly_activity, data);
    _bindHomeDataFan(ltTile, data);
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
    _bindHomeDataFan(tTile, data);
    grid.appendChild(_t(tTile, 2));
  }
  if (established || data.album_count > 0) {
    const aTile = _albumsTile(data.album_count, data.album_artists, data);
    _bindHomeDataFan(aTile, data);
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
  if (artist.album_count) stats.push(artist.album_count + ' album' + (artist.album_count !== 1 ? 's' : ''));
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

function _listeningTimeTile(hours, weekly, data) {
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', Math.round(hours) + 'h', 'bento-label'));
  body.appendChild(textEl('div', 'Listening time', 'bento-stat-label'));
  const ins = _listeningInsight(hours, weekly);
  if (ins) body.appendChild(ins);
  body.appendChild(_weeklyChart(weekly));
  tile.appendChild(body);
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
      navigate(buildArtistView(track.artist, track.artist_id));
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
  container.querySelectorAll('.home-recent-section').forEach(old => old.remove());
  container.appendChild(section);
}

// ---- HOME INSIGHT FAN ----
const HOME_FAN_MAX_VISIBLE = 7;
const HOME_FAN_POSITIONS = [
  { rot: -21, scale: 0.7756, x: -30, y: 7.3, z: 1 },
  { rot: -14, scale: 0.8498, x: -22, y: 4.0, z: 2 },
  { rot: -7, scale: 0.9346, x: -11, y: 1.3, z: 3 },
  { rot: 0, scale: 1.0, x: 0, y: 0, z: 10 },
  { rot: 7, scale: 0.9346, x: 11, y: 1.3, z: 3 },
  { rot: 14, scale: 0.8498, x: 22, y: 4.0, z: 2 },
  { rot: 21, scale: 0.7756, x: 30, y: 7.3, z: 1 },
];

let _homeFan = null;

function _homeInsightCards(data) {
  const cards = [];
  if (!data) return cards;

  if (data.total_plays) {
    cards.push({
      id: 'total_plays',
      value: data.total_plays,
      display: Number(data.total_plays).toLocaleString(),
      label: 'Total plays',
    });
  }
  if (data.listening_time_hours) {
    cards.push({
      id: 'listening_time_hours',
      value: data.listening_time_hours,
      display: String(Math.round(data.listening_time_hours)),
      label: 'Listening time',
      unit: 'h',
      weekly: Array.isArray(data.weekly_activity) ? data.weekly_activity : null,
    });
  }

  const top = data.top_artist;
  if (top && top.name) {
    cards.push({
      id: 'top_artist',
      value: top.play_count || 0,
      display: top.name,
      label: 'Top artist',
      detail: top.play_count ? top.play_count + ' plays' : null,
    });
  }
  for (const artist of data.top_artists || []) {
    if (!artist || !artist.name || !artist.play_count) continue;
    if (top && artist.name === top.name) continue;
    cards.push({
      id: 'top_artists:' + artist.name,
      value: artist.play_count,
      display: artist.name,
      label: 'Also playing',
      detail: artist.play_count + ' plays',
    });
  }

  const replayed = data.most_replayed;
  if (replayed && (replayed.name || replayed.play_count)) {
    cards.push({
      id: 'most_replayed',
      value: replayed.play_count || 0,
      display: replayed.name || 'Unknown',
      label: 'Most replayed',
      detail: replayed.play_count ? replayed.play_count + ' plays' : null,
    });
  }
  if (data.track_count) {
    cards.push({
      id: 'track_count',
      value: data.track_count,
      display: Number(data.track_count).toLocaleString(),
      label: 'Tracks',
      bars: (data.track_genres || []).slice(0, 4).map(g => ({ label: g.genre, value: g.count })),
    });
  }
  if (data.album_count) {
    cards.push({
      id: 'album_count',
      value: data.album_count,
      display: Number(data.album_count).toLocaleString(),
      label: 'Albums',
    });
  }
  if (data.genre_breakdown && data.genre_breakdown.length) {
    const lead = data.genre_breakdown[0];
    cards.push({
      id: 'genre_breakdown',
      value: lead.count,
      display: lead.genre,
      label: 'Top genre',
      bars: data.genre_breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count })),
    });
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    const total = data.weekly_activity.reduce((sum, hours) => sum + hours, 0);
    cards.push({
      id: 'weekly_activity',
      value: total,
      display: total.toFixed(1),
      label: 'Weekly activity',
      unit: 'h',
      weekly: data.weekly_activity,
    });
  }
  const week = data.this_week;
  if (week && week.total_plays) {
    cards.push({
      id: 'this_week',
      value: week.total_plays,
      display: String(week.total_plays),
      label: 'This week',
      detail: week.top_artist && week.top_artist.name ? week.top_artist.name : null,
    });
  }
  if (data.recent_albums && data.recent_albums.length) {
    const names = data.recent_albums.map(album => album.album || album.name).filter(Boolean);
    if (names.length) {
      cards.push({
        id: 'recent_albums',
        value: names.length,
        display: String(names.length),
        label: 'Recent albums',
        names,
      });
    }
  }
  return cards;
}

function _homeFanLayout(count, centerIndex) {
  if (count <= 0) return [];
  const visible = Math.min(HOME_FAN_MAX_VISIBLE, count);
  const half = Math.floor((visible - 1) / 2);
  const startSlot = visible === HOME_FAN_MAX_VISIBLE ? 0 : 3 - half;
  const items = [];
  for (let i = 0; i < visible; i++) {
    const cardIndex = ((centerIndex - half + i) % count + count) % count;
    items.push({ cardIndex, slot: startSlot + i });
  }
  return items;
}

function _homeFanWidthScale(widthPx) {
  if (!(widthPx > 0)) return 1;
  return Math.max(0.28, Math.min(1, widthPx / 960));
}

function _homePrefersReducedMotion() {
  try {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  } catch (_) {
    return false;
  }
}

function _homeFanNumeric(card) {
  return card.id === 'total_plays' || card.id === 'listening_time_hours'
    || card.id === 'track_count' || card.id === 'album_count'
    || card.id === 'weekly_activity' || card.id === 'this_week';
}

function _animateHomeFanNumber(el, card, reduced) {
  if (!el) return;
  const formatted = card.display + (card.unit ? card.unit : '');
  const canTime = window.performance && typeof performance.now === 'function';
  if (reduced || !_homeFanNumeric(card) || !Number.isFinite(Number(card.value))
      || !window.requestAnimationFrame || !canTime) {
    el.textContent = formatted;
    return;
  }
  const target = Number(card.value);
  const started = performance.now();
  const duration = 700;
  const tick = (now) => {
    const t = Math.min(1, Math.max(0, (now - started) / duration));
    const eased = 1 - Math.pow(1 - t, 3);
    const current = target * eased;
    if (card.id === 'weekly_activity' || (target < 10 && !Number.isInteger(target))) {
      el.textContent = current.toFixed(1) + (card.unit || '');
    } else {
      el.textContent = Math.round(current).toLocaleString() + (card.unit || '');
    }
    if (t < 1) window.requestAnimationFrame(tick);
    else el.textContent = formatted;
  };
  window.requestAnimationFrame(tick);
}

function _renderHomeFanCard(card, slot, state, motion) {
  const pos = HOME_FAN_POSITIONS[slot] || HOME_FAN_POSITIONS[3];
  const el = h('article', {
    className: 'home-fan-card' + (slot === 3 ? ' is-center' : ''),
    style: {
      transform: 'translateX(' + (pos.x * state.widthScale) + 'rem) translateY(' + pos.y + 'rem) rotate(' + pos.rot + 'deg) scale(' + pos.scale + ')',
      zIndex: String(pos.z),
      animationDelay: (slot * 0.06) + 's',
    },
  });
  if (!state.reduced && motion && motion.enter === 'stack') {
    el.classList.add('home-fan-spring-in');
  } else if (!state.reduced && motion && (motion.enter === 'right' || motion.enter === 'left') && slot !== 3) {
    const edge = motion.enter === 'right' ? 6 : 0;
    if (slot === edge) el.classList.add(motion.enter === 'right' ? 'home-fan-from-right' : 'home-fan-from-left');
  }
  const value = h('div', { className: 'home-fan-value' });
  _animateHomeFanNumber(value, card, state.reduced);
  el.appendChild(value);
  el.appendChild(textEl('div', card.label, 'home-fan-label'));
  if (card.detail) el.appendChild(textEl('div', card.detail, 'home-fan-detail'));
  if (card.names && card.names.length) {
    for (const name of card.names) {
      el.appendChild(textEl('div', name, 'home-fan-name'));
    }
  }
  if (card.bars && card.bars.length) el.appendChild(_barChart(card.bars));
  else if (card.weekly && card.weekly.some(v => v > 0)) el.appendChild(_weeklyChart(card.weekly));
  return el;
}

function _paintHomeFanDots(state) {
  while (state.dots.firstChild) state.dots.removeChild(state.dots.firstChild);
  if (state.cards.length <= HOME_FAN_MAX_VISIBLE) {
    state.dots.hidden = true;
    return;
  }
  state.dots.hidden = false;
  state.cards.forEach((card, index) => {
    const dot = h('button', {
      className: 'home-fan-dot' + (index === state.centerIndex ? ' is-active' : ''),
      type: 'button',
      'aria-label': card.label,
    });
    dot.addEventListener('click', (event) => {
      event.stopPropagation();
      state.centerIndex = index;
      _paintHomeFanDeck(state, { enter: 'stack' });
    });
    state.dots.appendChild(dot);
  });
}

function _paintHomeFanDeck(state, motion) {
  while (state.deck.firstChild) state.deck.removeChild(state.deck.firstChild);
  const layout = state.reduced
    ? [{ cardIndex: state.centerIndex, slot: 3 }]
    : _homeFanLayout(state.cards.length, state.centerIndex);
  for (const item of layout) {
    state.deck.appendChild(_renderHomeFanCard(state.cards[item.cardIndex], item.slot, state, motion));
  }
  _paintHomeFanDots(state);
}

function _onHomeFanKey(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    _closeHomeInsightFan();
  }
}

function _closeHomeInsightFan() {
  if (!_homeFan) return;
  document.removeEventListener('keydown', _onHomeFanKey);
  if (_homeFan.overlay && _homeFan.overlay.parentNode) _homeFan.overlay.remove();
  _homeFan = null;
}

function _cycleHomeInsightFan(delta) {
  if (!_homeFan || _homeFan.cards.length < 2) return;
  const count = _homeFan.cards.length;
  _homeFan.centerIndex = ((_homeFan.centerIndex + delta) % count + count) % count;
  _paintHomeFanDeck(_homeFan, { enter: delta > 0 ? 'right' : 'left' });
}

function _openHomeInsightFan(data) {
  const cards = _homeInsightCards(data);
  if (!cards.length) return;
  _closeHomeInsightFan();
  const host = document.querySelector('.main') || document.body;
  const reduced = _homePrefersReducedMotion();
  const overlay = h('div', {
    className: 'home-fan-overlay' + (reduced ? ' home-fan-reduced' : ' home-fan-spring'),
    role: 'dialog',
    'aria-modal': 'true',
    'aria-label': 'Listening insights',
    tabIndex: '-1',
  });
  const back = h('button', {
    className: 'home-fan-back',
    type: 'button',
    'aria-label': 'Close insights',
  });
  back.appendChild(svgIcon(ICONS.chevronLeft));
  back.addEventListener('click', (event) => {
    event.stopPropagation();
    _closeHomeInsightFan();
  });
  const stage = h('div', { className: 'home-fan-stage' });
  const prev = h('button', {
    className: 'home-fan-chevron home-fan-prev',
    type: 'button',
    'aria-label': 'Previous insight',
  });
  prev.appendChild(svgIcon(ICONS.chevronLeft));
  const next = h('button', {
    className: 'home-fan-chevron home-fan-next',
    type: 'button',
    'aria-label': 'Next insight',
  });
  next.appendChild(svgIcon(ICONS.chevronRight));
  const deck = h('div', { className: 'home-fan-deck' });
  const dots = h('div', { className: 'home-fan-dots' });
  prev.addEventListener('click', (event) => {
    event.stopPropagation();
    _cycleHomeInsightFan(-1);
  });
  next.addEventListener('click', (event) => {
    event.stopPropagation();
    _cycleHomeInsightFan(1);
  });
  if (cards.length < 2) {
    prev.hidden = true;
    next.hidden = true;
  }
  stage.appendChild(prev);
  stage.appendChild(deck);
  stage.appendChild(next);
  overlay.appendChild(back);
  overlay.appendChild(stage);
  overlay.appendChild(dots);
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) _closeHomeInsightFan();
  });
  _homeFan = {
    overlay,
    deck,
    dots,
    cards,
    centerIndex: 0,
    reduced,
    widthScale: _homeFanWidthScale(host.clientWidth || 0),
  };
  _paintHomeFanDeck(_homeFan, { enter: 'stack' });
  host.appendChild(overlay);
  document.addEventListener('keydown', _onHomeFanKey);
  if (overlay.focus) overlay.focus();
}

function _bindHomeDataFan(tile, data) {
  tile._homeData = data;
  tile.addEventListener('click', (event) => {
    const target = event.target;
    if (target && target.closest && target.closest('.bento-on-repeat')) return;
    _openHomeInsightFan(tile._homeData || data);
  });
  a11yClick(tile);
}

// ---- HOME INSIGHT FAN END ----

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
    chip.appendChild(textEl('span', item.query, 'recent-chip-query'));
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
      const albumFilters = input.closest('.search-area')?.querySelector('.album-search-filters');
      if (albumFilters) albumFilters.hidden = state.searchType !== 'albums';
    });
    chips.appendChild(chip);
  }
  recentEl.appendChild(chips);
  recentEl.classList.add('visible');
}

function _filterTidalAlbums(items, qualityFilter, ratingFilter) {
  return (items || []).filter(item => {
    const qualityMatches = qualityFilter === 'all'
      || (qualityFilter === 'max'
        ? ['HI_RES_LOSSLESS', 'HI_RES'].includes(item.quality)
        : item.quality === qualityFilter.toUpperCase());
    const ratingMatches = ratingFilter === 'all'
      || (ratingFilter === 'explicit' ? item.explicit === true : item.explicit === false);
    return qualityMatches && ratingMatches;
  });
}

function _rerenderCachedSearch(resultsArea) {
  const cacheMatches = state.searchResults
    && state.searchResults.query === state.searchQuery.trim()
    && state.searchResults.type === state.searchType;
  if (!cacheMatches) return;
  renderUnifiedSearchResults(
    resultsArea,
    state.searchResults.local,
    state.searchResults.tidal,
    state.searchResults.tidalAuthRequired
  );
}

function _renderAlbumFilterControls(container, resultsArea, focusTarget = null) {
  while (container.firstChild) container.removeChild(container.firstChild);
  container.hidden = state.searchType !== 'albums';

  const groups = [
    ['Quality', 'albumQualityFilter', [['all', 'All'], ['max', 'Max'], ['lossless', 'Lossless'], ['high', 'High']]],
    ['Rating', 'albumRatingFilter', [['all', 'All'], ['explicit', 'Explicit'], ['clean', 'Clean']]],
  ];
  for (const [label, stateKey, options] of groups) {
    const group = h('div', { className: 'filter-pills', role: 'group', 'aria-label': label + ' filter' });
    group.appendChild(textEl('span', label, 'results-count'));
    for (const [value, text] of options) {
      const selected = state[stateKey] === value;
      const button = h('button', {
        className: 'pill' + (selected ? ' active selected' : ''),
        type: 'button',
        'aria-pressed': selected ? 'true' : 'false',
        'data-filter-key': stateKey,
        'data-filter-value': value,
      }, text);
      button.addEventListener('click', () => {
        state[stateKey] = value;
        _renderAlbumFilterControls(container, resultsArea, { key: stateKey, value });
        _rerenderCachedSearch(resultsArea);
      });
      group.appendChild(button);
    }
    container.appendChild(group);
  }

  if (state.albumQualityFilter !== 'all' || state.albumRatingFilter !== 'all') {
    const clearButton = h('button', { className: 'pill', type: 'button' }, 'Clear filters');
    clearButton.addEventListener('click', () => {
      state.albumQualityFilter = 'all';
      state.albumRatingFilter = 'all';
      _renderAlbumFilterControls(container, resultsArea, { key: 'albumQualityFilter', value: 'all' });
      _rerenderCachedSearch(resultsArea);
    });
    container.appendChild(clearButton);
  }

  if (focusTarget) {
    const replacement = container.querySelector(
      '[data-filter-key="' + focusTarget.key + '"][data-filter-value="' + focusTarget.value + '"]'
    );
    if (replacement) replacement.focus();
  }
}

function renderSearch(container) {
  const searchArea = h('div', { className: 'search-area' });
  const resultsArea = h('div', { className: 'results' });

  const searchRow = h('div', { className: 'search-row' });
  const searchField = h('div', { className: 'search-field' });
  searchField.appendChild(svgIcon(ICONS.search));
  const input = h('input', {
    className: 'search-input',
    type: 'text',
    placeholder: 'Search or paste a Tidal URL...',
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
      albumFilters.hidden = state.searchType !== 'albums';
      if (state.searchQuery) doSearch(resultsArea);
      else _renderRecentSearches(recentSearchesEl, input, resultsArea);
    });
    a11yClick(pill);
    pills.appendChild(pill);
  }
  searchArea.appendChild(pills);
  const albumFilters = h('div', { className: 'album-search-filters' });
  _renderAlbumFilterControls(albumFilters, resultsArea);
  searchArea.appendChild(albumFilters);
  container.appendChild(searchArea);

  container.appendChild(resultsArea);

  const cacheMatches = state.searchResults
    && state.searchResults.query === state.searchQuery.trim()
    && state.searchResults.type === state.searchType;
  if (cacheMatches) {
    renderUnifiedSearchResults(
      resultsArea,
      state.searchResults.local,
      state.searchResults.tidal,
      state.searchResults.tidalAuthRequired
    );
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

function _followSearchResolve(resultsArea, tidalData) {
  const resolved = tidalData && tidalData.resolve;
  if (!resolved) return;
  if (resolved.kind === 'album' && resolved.id) {
    navigateAlbum(resolved.id);
    return;
  }
  if (resolved.kind === 'artist') {
    navigate(buildArtistView(resolved.name || '', resolved.id));
    return;
  }
  if (resolved.kind === 'playlist' && resolved.id) {
    loadPlaylistTracks(resultsArea, {
      id: resolved.id,
      name: resolved.name,
      cover_url: resolved.cover_url,
      num_tracks: resolved.num_tracks,
    });
  }
}

async function doSearch(resultsArea) {
  const query = state.searchQuery.trim();
  const type = state.searchType;
  if (!query) {
    state.searchResults = null;
    renderSearchEmpty(resultsArea);
    return;
  }

  _saveRecentSearch(query, type);
  renderSearchSkeleton(resultsArea);

  let localData = null;
  let tidalData = null;
  let tidalAuthRequired = false;
  const isStale = () => state.searchQuery.trim() !== query || state.searchType !== type;
  const paint = () => {
    if (isStale()) return;
    state.searchResults = { query, type, local: localData, tidal: tidalData, tidalAuthRequired };
    renderUnifiedSearchResults(resultsArea, localData, tidalData, tidalAuthRequired);
    refreshStatusLights();
  };

  const localP = api(
    '/library/search?q=' + encodeURIComponent(query) + '&type=' + type + '&limit=20',
    { timeoutMs: 2500 }
  ).then((data) => { localData = data; paint(); }).catch(() => { /* local search optional */ });

  const tidalP = api('/search?q=' + encodeURIComponent(query) + '&type=' + type + '&limit=50')
    .then((data) => { tidalData = data; paint(); })
    .catch((error) => {
      if (_isTidalAuthError(error)) {
        tidalAuthRequired = true;
      }
      paint();
    });

  await Promise.all([localP, tidalP]);
  if (isStale()) return;
  _followSearchResolve(resultsArea, tidalData);
}

function renderTidalSearchAuthPanel(container) {
  const panel = h('div', { className: 'search-tidal-auth-panel' });
  panel.appendChild(textEl('div', 'Connect Tidal to search, stream, and download', 'search-tidal-auth-message'));

  const connectButton = h('button', { className: 'search-tidal-auth-button', type: 'button' });
  connectButton.textContent = 'Connect Tidal';
  connectButton.addEventListener('click', () => triggerLogin());
  panel.appendChild(connectButton);
  container.appendChild(panel);
}

function renderUnifiedSearchResults(container, localData, tidalData, tidalAuthRequired) {
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
        _appendGroupingBadge(meta, a);
        card.appendChild(meta);
        card.addEventListener('click', () => {
          navigate(a.id ? buildLocalReleaseView(a.id) : buildLocalAlbumView(a.artist, a.name));
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
        card.addEventListener('click', () => navigate(buildArtistView(a.name)));
        a11yClick(card);
        grid.appendChild(card);
      });
      container.appendChild(grid);
    }
  }

  // Divider between local and Tidal sections
  const originalTidalItems = tidalData ? (tidalData[type] || []) : [];
  const albumFiltersActive = type === 'albums'
    && (state.albumQualityFilter !== 'all' || state.albumRatingFilter !== 'all');
  const tidalItems = type === 'albums'
    ? _filterTidalAlbums(originalTidalItems, state.albumQualityFilter, state.albumRatingFilter)
    : originalTidalItems;
  const tidalResponse = type === 'albums'
    ? { ...(tidalData || {}), albums: tidalItems, unfiltered_total: originalTidalItems.length }
    : tidalData;
  if (type !== 'albums' && localItems.length > 0 && tidalItems.length > 0) {
    const divider = h('div', { className: 'search-divider' });
    divider.appendChild(textEl('span', 'Tidal', 'search-divider-label'));
    container.appendChild(divider);
  }

  // Tidal results section — delegate to existing renderer via a sub-container
  // to prevent it from clearing the local results we just rendered
  if (type === 'albums' && originalTidalItems.length > 0) {
    const tidalHeader = h('div', { className: 'results-header' });
    tidalHeader.appendChild(textEl('h3', 'Tidal Albums', 'results-section-title'));
    const count = albumFiltersActive
      ? tidalItems.length + ' of ' + originalTidalItems.length + ' albums'
      : originalTidalItems.length + ' albums';
    tidalHeader.appendChild(textEl('span', count, 'results-count'));
    container.appendChild(tidalHeader);

    const tidalWrap = h('div', {});
    container.appendChild(tidalWrap);
    renderSearchResults(tidalWrap, tidalResponse, false);
  } else if (tidalItems.length > 0) {
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

  if (tidalAuthRequired) {
    renderTidalSearchAuthPanel(container);
  }

  if (localItems.length === 0 && tidalItems.length === 0
      && originalTidalItems.length === 0 && !tidalAuthRequired) {
    if (tidalData && tidalData.error) {
      container.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'Could not open that Tidal link', 'empty-state-title'),
        textEl('div', tidalData.error, 'empty-state-sub')
      ));
    } else {
      container.appendChild(textEl('div', 'No results found', 'search-empty-text'));
    }
  }
}

function renderSearchResults(container, data, showHeader = true) {
  while (container.firstChild) container.removeChild(container.firstChild);

  if (state.searchType === 'tracks') {
    const tracks = data.tracks || [];
    if (showHeader) {
      container.appendChild(h('div', { className: 'results-header' },
        textEl('div', 'Search Results', 'results-title'),
        textEl('div', tracks.length + ' tracks', 'results-count')
      ));
    }

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
    if (showHeader) {
      container.appendChild(h('div', { className: 'results-header' },
        textEl('div', 'Search Results', 'results-title'),
        textEl('div', items.length + ' ' + state.searchType, 'results-count')
      ));
    }

    if (items.length === 0) {
      if (state.searchType === 'albums' && data.unfiltered_total > 0) {
        container.appendChild(h('div', { className: 'empty-state' },
          textEl('div', 'No albums match these filters', 'empty-state-title'),
          textEl('div', 'Use Clear filters above to see every album.', 'empty-state-sub')
        ));
        return;
      }
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
        img.alt = item.name || '';
        img.onerror = function() {
          this.style.display = 'none';
          artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(item.id || item.name) } }));
        };
        artDiv.appendChild(img);
      } else {
        artDiv.appendChild(h('div', { className: 'art-gradient', style: { background: artGradient(item.id) } }));
      }
      if (state.searchType === 'albums') {
        const qualityLabel = {
          HI_RES_LOSSLESS: 'MAX',
          HI_RES: 'MAX',
          LOSSLESS: 'LOSSLESS',
          HIGH: 'HIGH',
          LOW: 'LOW',
        }[item.quality] || 'UNKNOWN';
        const badges = h('div', { className: 'album-search-badges' });
        badges.appendChild(textEl('span', qualityLabel, 'album-search-badge'));
        if (item.atmos === true) {
          badges.appendChild(textEl('span', 'ATMOS', 'album-search-badge'));
        }
        if (item.explicit === true) {
          badges.appendChild(textEl('span', 'E', 'album-search-badge'));
        }
        artDiv.appendChild(badges);
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
        card.addEventListener('click', () => navigate(buildArtistView(item.name, item.id)));
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
      navigate(buildArtistView(track.artist, track.artist_id));
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
  const qTag = textEl('div', qualityLabel(track.quality, track.format, track.codec), 'quality-tag ' + qualityClass(track.quality, track.format, track.codec));
  qTag.title = qualityTitle(track.quality, track.format, track.codec);
  row.appendChild(qTag);

  // Format
  row.appendChild(textEl('div', _extractFormat(track), 'track-format'));

  // Plays
  const plays = track.play_count || 0;
  row.appendChild(textEl('div', plays > 0 ? String(plays) : '\u2014', 'track-plays'));

  // Time
  row.appendChild(textEl('div', formatTime(track.duration), 'track-time'));

  // Actions
  const actions = h('div', { className: 'track-actions visible' });
  const sourceTag = h('span', {
    className: 'source-tag ' + (track.is_local ? 'local-tag' : 'tidal-tag'),
  }, track.is_local ? 'local' : 'tidal');
  actions.appendChild(sourceTag);
  if (!track.is_local) {
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
          const targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
          if (qualityRank(track.quality, track.format, track.codec) >= targetRank) return [];
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

function _albumDedupKey(name) {
  return String(name || '').toLowerCase().replace(/[^\w]+/g, ' ').trim();
}

function _mergeArtistAlbums(localAlbums, tidalAlbums) {
  const seen = new Set();
  const merged = [];
  for (const album of localAlbums || []) {
    seen.add(_albumDedupKey(album.name));
    merged.push({ ...album, is_local: true });
  }
  for (const album of tidalAlbums || []) {
    const key = _albumDedupKey(album.name);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push({
      ...album,
      is_local: false,
      tidal_id: album.id,
      track_count: album.track_count || album.num_tracks || 0,
      best_quality: album.best_quality || album.quality || '',
    });
  }
  return merged;
}

async function _tidalArtistAlbums(artistName, tidalArtistId) {
  let id = tidalArtistId;
  if (!id) {
    try {
      const found = await api('/search?q=' + encodeURIComponent(artistName) + '&type=artists&limit=5');
      const artists = found.artists || [];
      const exact = artists.find(a => (a.name || '').toLowerCase() === String(artistName || '').toLowerCase());
      id = (exact || artists[0] || {}).id;
    } catch (_) {
      return [];
    }
  }
  if (!id) return [];
  try {
    const data = await api('/artists/' + id + '/albums');
    return data.albums || [];
  } catch (_) {
    return [];
  }
}

// ---- ARTIST ALBUM GALLERY (local library + Tidal) ----
async function renderArtistGallery(container, artistName, tidalArtistId) {
  const header = h('div', { className: 'artist-gallery-header' });
  const crumbRow = h('div', { className: 'nav-back-row' });
  const back = _navBackControl();
  if (back) crumbRow.appendChild(back);
  crumbRow.appendChild(breadcrumb([
    { label: 'Home', view: 'home' },
    { label: artistName },
  ]));
  header.appendChild(crumbRow);
  const titleRow = h('div', { className: 'artist-gallery-title-row' });
  titleRow.appendChild(textEl('h1', artistName, 'artist-gallery-title'));
  header.appendChild(titleRow);
  container.appendChild(header);

  const grid = h('div', { className: 'album-gallery' });
  container.appendChild(grid);
  grid.appendChild(textEl('p', 'Loading albums…', 'home-loading-hint'));

  try {
    const localP = api('/library/artist/' + encodeURIComponent(artistName) + '/albums')
      .catch(() => ({ albums: [] }));
    const tidalP = _tidalArtistAlbums(artistName, tidalArtistId);
    const [localData, tidalAlbums] = await Promise.all([localP, tidalP]);
    const albums = _mergeArtistAlbums(localData.albums || [], tidalAlbums);
    while (grid.firstChild) grid.removeChild(grid.firstChild);

    if (!albums.length) {
      grid.appendChild(h('div', { className: 'empty-state' },
        textEl('div', 'No albums found', 'empty-state-title'),
        textEl('div', 'Try syncing your library first', 'empty-state-sub')
      ));
      return;
    }

    const countRow = header.querySelector('.artist-gallery-title-row');
    if (countRow) countRow.appendChild(textEl('span', albums.length + ' album' + (albums.length !== 1 ? 's' : ''), 'artist-gallery-count'));

    albums.forEach((album, index) => {
      const card = h('div', { className: 'album-card' });

      const artWrap = h('div', { className: 'album-card-art-wrap' });
      if (album.cover_url) {
        const img = h('img', { className: 'album-card-art', src: album.cover_url, alt: '', loading: index < 6 ? 'eager' : 'lazy' });
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
      _appendGroupingBadge(meta, album);
      card.appendChild(meta);

      card.addEventListener('click', () => {
        if (album.is_local) {
          navigate(album.id ? buildLocalReleaseView(album.id) : buildLocalAlbumView(artistName, album.name));
        } else {
          navigateAlbum(album.tidal_id || album.id);
        }
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
async function renderLocalReleaseDetail(container, releaseHash) {
  container.appendChild(textEl('p', 'Loading tracks…', 'home-loading-hint'));
  try {
    const data = await api('/library/releases/' + encodeURIComponent(releaseHash) + '/tracks');
    while (container.firstChild) container.removeChild(container.firstChild);
    renderLocalAlbumDetail(container, data.artist, data.album, data);
  } catch (err) {
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(h('div', { className: 'empty-state' },
      textEl('div', 'Could not load release', 'empty-state-title'),
      textEl('div', err.message, 'empty-state-sub')
    ));
  }
}

async function renderLocalAlbumDetail(container, artistName, albumName, prefetchedData) {
  const wrapper = h('div', { className: 'album-detail-view' });
  container.appendChild(wrapper);

  const crumbRow = h('div', { className: 'nav-back-row' });
  const back = _navBackControl();
  if (back) crumbRow.appendChild(back);
  crumbRow.appendChild(breadcrumb([
    { label: 'Library', view: 'library' },
    { label: artistName, view: 'artist:' + encodeURIComponent(artistName) },
    { label: albumName },
  ]));
  wrapper.appendChild(crumbRow);

  let coverUrl = (prefetchedData && prefetchedData.cover_url) || '';
  if (!coverUrl && !(prefetchedData && 'cover_url' in prefetchedData)) {
    try {
      const albumsData = await api('/library/artist/' + encodeURIComponent(artistName) + '/albums');
      const match = (albumsData.albums || []).find(a => a.name === albumName);
      if (match) coverUrl = match.cover_url;
    } catch (_) {}
  }

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
  trackList.appendChild(textEl('p', 'Loading tracks…', 'home-loading-hint'));

  try {
    const data = prefetchedData || await api('/library/artist/' + encodeURIComponent(artistName) + '/album/' + encodeURIComponent(albumName) + '/tracks');
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
      const _targetRank = { 'HI_RES': 3, 'HI_RES_LOSSLESS': 4 }[state.settings?.upgrade_target_quality] || 4;
      const belowTarget = tracks.filter(t => qualityRank(t.quality, t.format, t.codec) < _targetRank);
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
                const localRank = qualityRank(mt.quality, mt.format, mt.codec);
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
                const mtLocalRank = qualityRank(mt.quality, mt.format, mt.codec);
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
                  if (resp.count > 0) { refreshDlBadge(); _ensureGlobalSSE(); }
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
              refreshDlBadge();
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
  const back = _navBackControl();
  if (back) container.appendChild(back);
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
        refreshDlBadge();
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

// ---- DJAI VIEW ----
function renderDjai(container) {
  const shell = h('div', { className: 'djai-shell' });
  const header = h('div', { className: 'djai-header' },
    textEl('div', 'DJAI', 'wizard-step-label'),
    textEl('h2', 'DJAI', 'djai-title'),
    textEl('p', 'Music automation modules live here. Discord Bot is the first deployable module.', 'djai-desc')
  );

  const moduleGrid = h('div', { className: 'djai-module-grid' });
  const botCard = h('section', { className: 'djai-module-card djai-discord-card' });
  const botHeader = h('div', { className: 'djai-module-header' },
    h('div', {},
      textEl('div', 'Available now', 'wizard-step-label'),
      textEl('h3', 'Discord Bot', 'djai-module-title')
    ),
    textEl('p', 'Deploy the private voice bot against this music-dl server.', 'djai-module-desc')
  );

  const statusLine = h('div', { className: 'djai-bot-status' },
    textEl('span', 'Checking bot status...', 'djai-bot-pill')
  );

  const fields = [
    ['discord_token', 'Discord Bot Token', 'password'],
    ['discord_application_id', 'Application ID', 'text'],
    ['allowed_guild_id', 'Allowed Guild ID', 'text'],
    ['allowed_channel_id', 'Allowed Channel ID', 'text'],
    ['allowed_user_id', 'Allowed User ID', 'text'],
  ];

  const inputs = {};
  const form = h('form', { className: 'djai-bot-form' });
  fields.forEach(([name, label, type]) => {
    const input = h('input', {
      className: 'settings-input',
      name,
      type,
      autocomplete: 'off',
      spellcheck: 'false',
    });
    inputs[name] = input;
    form.appendChild(h('label', { className: 'djai-bot-field' },
      textEl('span', label, 'settings-label'),
      input
    ));
  });

  const details = h('div', { className: 'djai-bot-details' });
  const saveBtn = h('button', { className: 'wizard-btn', type: 'submit' }, 'Save Bot Config');
  const deployBtn = h('button', { className: 'wizard-btn djai-deploy-btn', type: 'button' }, 'Deploy Discord Bot');
  const restartBtn = h('button', { className: 'wizard-btn-sm', type: 'button' }, 'Restart');
  const shutdownBtn = h('button', { className: 'wizard-btn-sm', type: 'button' }, 'Shutdown');
  const editBtn = h('button', { className: 'wizard-btn-sm', type: 'button' }, 'Edit Config');
  const cancelEditBtn = h('button', { className: 'wizard-btn-sm', type: 'button' }, 'Cancel');
  const refreshBtn = h('button', { className: 'wizard-btn-sm', type: 'button' }, 'Refresh');
  const formActions = h('div', { className: 'djai-bot-actions' }, saveBtn, cancelEditBtn);
  const serviceActions = h('div', { className: 'djai-bot-actions' }, deployBtn, restartBtn, shutdownBtn, editBtn, refreshBtn);
  form.appendChild(formActions);

  shell.appendChild(header);
  botCard.appendChild(botHeader);
  botCard.appendChild(statusLine);
  botCard.appendChild(form);
  botCard.appendChild(serviceActions);
  botCard.appendChild(details);
  moduleGrid.appendChild(botCard);
  shell.appendChild(moduleGrid);
  container.appendChild(shell);

  let lastStatus = null;
  let editingConfig = false;

  function setBusy(busy) {
    saveBtn.disabled = busy;
    deployBtn.disabled = busy || !lastStatus?.configured || lastStatus?.running;
    restartBtn.disabled = busy || !lastStatus?.configured;
    shutdownBtn.disabled = busy || !lastStatus?.running;
    editBtn.disabled = busy;
    cancelEditBtn.disabled = busy;
    refreshBtn.disabled = busy;
  }

  function renderStatus(data) {
    lastStatus = data;
    saveBtn.hidden = data.configured && !editingConfig;
    cancelEditBtn.hidden = !data.configured || !editingConfig;

    while (statusLine.firstChild) statusLine.removeChild(statusLine.firstChild);
    statusLine.appendChild(textEl('span', data.configured ? 'Configured' : 'Needs config', 'djai-bot-pill ' + (data.configured ? 'ok' : 'warn')));
    statusLine.appendChild(textEl('span', data.running ? 'Running' : 'Stopped', 'djai-bot-pill ' + (data.running ? 'ok' : 'warn')));
    deployBtn.textContent = data.running ? 'Bot Running' : (data.configured ? 'Start Discord Bot' : 'Deploy Discord Bot');
    deployBtn.disabled = !data.configured || data.running;
    restartBtn.disabled = !data.configured;
    shutdownBtn.disabled = !data.running;
    editBtn.hidden = !data.configured || editingConfig;

    fields.forEach(([name, , type]) => {
      const input = inputs[name];
      input.disabled = data.configured && !editingConfig;
      input.readOnly = data.configured && !editingConfig;
      input.classList.toggle('djai-ghost-input', data.configured && !editingConfig);

      if (data.configured && !editingConfig) {
        const key = {
          discord_token: 'DISCORD_TOKEN',
          discord_application_id: 'DISCORD_APPLICATION_ID',
          allowed_guild_id: 'ALLOWED_GUILD_ID',
          allowed_channel_id: 'ALLOWED_CHANNEL_ID',
          allowed_user_id: 'ALLOWED_USER_ID',
        }[name];
        const present = data.configured_fields?.includes(key);
        input.type = 'text';
        input.value = present ? (name === 'discord_token' ? 'Saved (hidden)' : (data.saved_labels?.[name] || data.saved_ids?.[name] || 'Saved')) : 'Missing';
        input.classList.toggle('ok', present);
        input.classList.toggle('warn', !present);
      } else {
        input.type = type;
        input.classList.remove('ok', 'warn');
      }
    });

    while (details.firstChild) details.removeChild(details.firstChild);
    if (data.missing_fields?.length) {
      details.appendChild(textEl('div', 'Missing: ' + data.missing_fields.join(', '), 'wizard-desc'));
    }
    if (data.invalid_fields?.length) {
      details.appendChild(textEl('div', 'Invalid Discord IDs: ' + data.invalid_fields.join(', '), 'wizard-desc'));
    } else if (data.configured) {
      details.appendChild(textEl('div', 'Existing config detected. You can deploy or restart without re-entering secrets.', 'wizard-desc'));
    }
    details.appendChild(textEl('div', 'Backend: ' + data.backend_url, 'wizard-desc'));
    details.appendChild(textEl('div', 'Config: ' + data.env_path, 'wizard-desc'));
    details.appendChild(textEl('div', 'Bot app: ' + data.bot_root, 'wizard-desc'));
  }

  async function runBotAction(path, successMessage, failurePrefix) {
    try {
      setBusy(true);
      renderStatus(await api(path, { method: 'POST', body: {} }));
      toast(successMessage, 'success');
    } catch (err) {
      toast(failurePrefix + ': ' + err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function loadStatus() {
    try {
      setBusy(true);
      renderStatus(await api('/bot-control/status'));
    } catch (err) {
      toast('Bot status failed: ' + err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      setBusy(true);
      const payload = {};
      fields.forEach(([name]) => { payload[name] = inputs[name].value.trim(); });
      editingConfig = false;
      renderStatus(await api('/bot-control/configure', { method: 'POST', body: payload }));
      inputs.discord_token.value = '';
      toast('Discord bot config saved', 'success');
    } catch (err) {
      toast('Bot config failed: ' + err.message, 'error');
    } finally {
      setBusy(false);
    }
  });

  deployBtn.addEventListener('click', async () => {
    await runBotAction('/bot-control/start', 'Discord bot started', 'Bot deploy failed');
  });

  restartBtn.addEventListener('click', async () => {
    await runBotAction('/bot-control/restart', 'Discord bot restarted', 'Bot restart failed');
  });

  shutdownBtn.addEventListener('click', async () => {
    await runBotAction('/bot-control/stop', 'Discord bot stopped', 'Bot shutdown failed');
  });

  editBtn.addEventListener('click', () => {
    editingConfig = true;
    fields.forEach(([name]) => { inputs[name].value = ''; });
    if (lastStatus) renderStatus(lastStatus);
  });

  cancelEditBtn.addEventListener('click', () => {
    editingConfig = false;
    fields.forEach(([name]) => { inputs[name].value = ''; });
    if (lastStatus) renderStatus(lastStatus);
  });

  refreshBtn.addEventListener('click', loadStatus);
  loadStatus();
}

// ---- LIBRARY VIEW ----
let librarySort = 'artist';
let libraryQuery = '';
let libraryScanPoll = null;
const LIBRARY_PAGE_SIZE = 50;
const LIBRARY_ALBUM_BATCH_SIZE = 80;
let libraryOffset = 0;
let libraryTotal = 0;
let libraryArtistTracks = [];
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

function _groupingDecisionPayload(assessment, decision, canonicalTitle) {
  return {
    left_signature: assessment.left_signature,
    right_signature: assessment.right_signature,
    decision,
    canonical_title: decision === 'group_together' ? canonicalTitle : null,
  };
}

function _openGroupingReview(album) {
  const assessment = (album.assessments || []).find(
    item => item.outcome === 'review' || item.user_decision_superseded,
  );
  if (!assessment) return;

  const superseded = assessment.user_decision_superseded === true;
  const previousFocus = document.activeElement;
  const overlay = h('div', { className: 'modal-overlay grouping-review-overlay' });
  const dialog = h('section', {
    className: 'modal grouping-review',
    role: 'dialog',
    'aria-modal': 'true',
    'aria-labelledby': 'grouping-review-title',
  });
  dialog.appendChild(textEl(
    'h3',
    superseded ? 'Albums kept separate' : 'Possible duplicate albums',
    'grouping-review-title',
  ));
  dialog.lastChild.id = 'grouping-review-title';
  dialog.appendChild(textEl(
    'p',
    assessment.left_title + '  ↔  ' + assessment.right_title,
    'grouping-review-pair',
  ));
  dialog.appendChild(textEl(
    'p',
    'Confidence ' + assessment.score + '/100 · ' + Math.round((assessment.coverage || 0) * 100) + '% track coverage',
    'grouping-review-score',
  ));

  const evidence = h('ul', { className: 'grouping-review-evidence' });
  (assessment.evidence || []).forEach(item => {
    evidence.appendChild(textEl(
      'li',
      item.explanation + ' (+' + item.points + ', ' + (item.sources || []).join(' + ') + ')',
    ));
  });
  (assessment.vetoes || []).forEach(item => {
    evidence.appendChild(textEl('li', 'Conflict: ' + item.explanation, 'grouping-review-veto'));
  });
  dialog.appendChild(evidence);

  const titleLabel = textEl('label', 'Album title', 'grouping-review-label');
  const titleSelect = h('select', { className: 'grouping-review-select' });
  [assessment.left_title, assessment.right_title].filter(Boolean).forEach(title => {
    titleSelect.appendChild(h('option', { value: title }, title));
  });
  titleLabel.appendChild(titleSelect);
  dialog.appendChild(titleLabel);

  const actions = h('div', { className: 'grouping-review-actions' });
  const keepButton = textEl('button', 'Keep separate', 'pill');
  const groupButton = textEl('button', 'Group together', 'pill active');
  if (superseded) {
    groupButton.disabled = true;
    groupButton.textContent = 'Cannot group';
  }
  let onKeyDown;
  const close = () => {
    if (onKeyDown) document.removeEventListener('keydown', onKeyDown);
    overlay.remove();
    if (previousFocus && previousFocus.focus) previousFocus.focus();
  };
  async function save(decision) {
    try {
      await api('/library/grouping/decision', {
        method: 'POST',
        body: _groupingDecisionPayload(assessment, decision, titleSelect.value),
      });
      close();
      navigate('library');
    } catch (err) {
      toast(err.message, 'error');
    }
  }
  keepButton.addEventListener('click', () => save('keep_separate'));
  groupButton.addEventListener('click', () => save('group_together'));
  actions.appendChild(keepButton);
  actions.appendChild(groupButton);
  dialog.appendChild(actions);
  overlay.appendChild(dialog);
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });
  onKeyDown = event => {
    if (event.key === 'Escape') {
      close();
    } else if (event.key === 'Tab') {
      const focusable = [titleSelect, keepButton, groupButton];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };
  document.addEventListener('keydown', onKeyDown);
  document.body.appendChild(overlay);
  keepButton.focus();
}

function _appendGroupingBadge(parent, album) {
  if (!album.possible_duplicate) return;
  const badge = textEl('button', 'Possible duplicate', 'possible-duplicate-badge');
  badge.type = 'button';
  badge.addEventListener('click', event => {
    event.stopPropagation();
    _openGroupingReview(album);
  });
  parent.appendChild(badge);
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
  _appendGroupingBadge(meta, album);
  card.appendChild(meta);

  card.addEventListener('click', () => {
    navigate(album.id ? buildLocalReleaseView(album.id) : buildLocalAlbumView(album.artist, album.name));
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
  _appendGroupingBadge(meta, album);
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
    navigate(album.id ? buildLocalReleaseView(album.id) : buildLocalAlbumView(album.artist || 'Unknown Artist', album.name || 'Unknown Album'));
  });
  row.style.cursor = 'pointer';
  a11yClick(row);
  return row;
}

async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {
  if (!append) {
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'results-header' },
      textEl('div', 'Recently Added', 'results-title'),
    ));
    resultsArea.appendChild(textEl('p', 'Loading albums…', 'home-loading-hint'));
  }
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

  container.appendChild(resultsArea);

  if (!recentAddedExpanded) {
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
      loadLibraryAlbums(resultsArea, libraryQuery);
    } else if (librarySort === 'artist') {
      loadLibraryArtistGrouped(resultsArea, libraryQuery);
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

function _scanStatusLabel(status) {
  const phase = status && status.phase;
  if (phase === 'error' || (status && status.error)) return ' Sync failed';
  if (phase === 'discovering' && status.scanned > 0) {
    return ' Found ' + Number(status.scanned).toLocaleString();
  }
  if (status && status.total > 0 && status.scanned > 0) {
    return ' ' + status.scanned + '/' + status.total;
  }
  if (phase && phase !== 'done' && phase !== 'idle') {
    return ' ' + phase.charAt(0).toUpperCase() + phase.slice(1) + '...';
  }
  if (status && status.scanned > 0) return ' New: ' + status.scanned;
  if (status && status.total > 0) return ' Checking... ' + Number(status.total).toLocaleString();
  return ' Scanning...';
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
      textNode.textContent = _scanStatusLabel(status);
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
        if (status.phase === 'error' || status.error) {
          toast('Library sync failed — previous library kept', 'error');
        } else {
          toast('Library synced — ' + status.scanned + ' files indexed', 'success');
        }
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

function _groupArtistTracks(tracks) {
  const groups = [];
  let currentArtist = null;
  let currentGroup = null;

  tracks.forEach(track => {
    track.local_path = track.path;
    const artist = track.artist || 'Unknown Artist';
    if (artist !== currentArtist) {
      currentArtist = artist;
      currentGroup = { artist: artist, tracks: [] };
      groups.push(currentGroup);
    }
    currentGroup.tracks.push(track);
  });

  groups.forEach(group => {
    group.tracks.sort((a, b) => {
      const albumCmp = (a.album || '').localeCompare(b.album || '');
      if (albumCmp !== 0) return albumCmp;
      return (a.track_number || 0) - (b.track_number || 0);
    });
  });

  return groups;
}

async function loadLibraryArtistGrouped(resultsArea, query, append) {
  const reqId = ++_libRequestId;
  if (!append) {
    libraryOffset = 0;
    libraryArtistTracks = [];
    while (resultsArea.firstChild) resultsArea.removeChild(resultsArea.firstChild);
    resultsArea.appendChild(h('div', { className: 'skeleton-row' }));
  }

  try {
    // Keep first paint page-sized; rendering many track rows synchronously makes navigation feel stuck.
    const data = await api('/library?sort=artist&limit=' + LIBRARY_PAGE_SIZE + '&offset=' + libraryOffset +
      (query ? '&q=' + encodeURIComponent(query) : ''));
    if (reqId !== _libRequestId) return;
    const pageTracks = data.tracks || [];
    libraryArtistTracks = append ? libraryArtistTracks.concat(pageTracks) : pageTracks;
    const tracks = libraryArtistTracks;

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

    const groups = _groupArtistTracks(tracks);

    // Update header with artist count
    const countEl = resultsArea.querySelector('.results-count');
    if (countEl) countEl.textContent = groups.length + ' artists \u00b7 ' + (data.total || 0) + ' tracks';

    const wrapper = h('div', { className: 'library-artist-groups' });

    let globalNum = 0;
    groups.forEach(g => {
      // Artist header
      const header = h('div', { className: 'artist-group-header' },
        textEl('div', g.artist, 'artist-group-name'),
        textEl('div', g.tracks.length + ' track' + (g.tracks.length !== 1 ? 's' : ''), 'artist-group-count')
      );
      wrapper.appendChild(header);

      // Track list for this group
      const trackList = h('div', { className: 'tracks' });
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
      loadMore.addEventListener('click', () => {
        loadMore.disabled = true;
        libraryOffset = tracks.length;
        loadLibraryArtistGrouped(resultsArea, query, true);
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
            refreshDlBadge();
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
  btn.disabled = true;
  btn.classList.add('downloading');

  try {
    const resp = await apiTidal('/download', {
      method: 'POST',
      body: { track_ids: [track.id] },
    });
    if (resp && resp.status === 'already_queued') {
      toast((track.name || 'Track') + ' already queued', 'info');
    } else {
      toast((track.name || 'Track') + ' queued', 'success');
    }
    _downloading.add(track.id);
    _dlCallbacks[track.id] = { btn };
    _ensureGlobalSSE();
    refreshDlBadge();
    setTimeout(_reconcileDownloadUi, 1500);
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
  refreshDlBadge();
}

// Global SSE for download progress (shared across views)
let _globalSSE = null;
function _ensureGlobalSSE() {
  if (_globalSSE) return;
  _globalSSE = new EventSource('/api/downloads/active');
  refreshActiveDownloads();
  _globalSSE.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'ping') return;
      if (data.type === 'upgrade_progress') {
        _updateUpgradeRow(data.old_path, 'upgrading', data.name);
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
      else if (data.type === 'queue_cancelled') {
        _scheduleHistoryReload();
      }
      else if (data.type === 'upgrade_complete') {
        _updateUpgradeRow(data.old_path, 'done', data.name);
      } else if (data.type === 'upgrade_error') {
        _updateUpgradeRow(data.old_path, 'error', data.error);
      }
      if (data.type === 'progress') {
        const activeEl = document.getElementById('dl-active');
        if (activeEl) updateActiveDownload(activeEl, data);
        applyQueueCountsFromEvent(data);
      }
      if (data.type !== 'progress') refreshActiveDownloads();
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

function setDlBadge(count) {
  const badge = document.getElementById('dl-badge');
  if (!badge) return;
  count = Math.max(0, parseInt(count, 10) || 0);
  badge.textContent = count;
  badge.style.display = count > 0 ? '' : 'none';
}

function refreshDlBadge() {
  api('/downloads/queue-state').then(qs => {
    setDlBadge(qs.active_count || 0);
  }).catch(() => {});
}

function _queuedLabel(count) {
  return count + (count === 1 ? ' track queued' : ' tracks queued');
}

function applyQueueCountsFromEvent(data) {
  if (data.queued_count == null && data.active_count == null) return;
  if (data.active_count != null) setDlBadge(data.active_count);
  if (data.paused != null) _setQueuePaused(!!data.paused);
  const activeEl = document.getElementById('dl-active');
  if (!activeEl) return;
  const queuedCount = data.queued_count || 0;
  let summary = activeEl.querySelector('.dl-batch-summary');
  if (queuedCount > 0) {
    if (!summary) {
      summary = h('div', { className: 'dl-card dl-batch-summary' });
      summary.appendChild(textEl('div', _queuedLabel(queuedCount), 'dl-card-name'));
      summary.appendChild(textEl('div', data.paused ? 'Paused' : 'Waiting to start...', 'dl-card-status dl-status-queued'));
      activeEl.prepend(summary);
    } else {
      const nameEl = summary.querySelector('.dl-card-name');
      if (nameEl) nameEl.textContent = _queuedLabel(queuedCount);
      const statusEl = summary.querySelector('.dl-card-status');
      if (statusEl) statusEl.textContent = data.paused ? 'Paused' : 'Waiting to start...';
    }
  } else if (summary) {
    summary.remove();
  }
}

function applyActiveSnapshot(data, paused) {
  const activeEl = document.getElementById('dl-active');
  if (!activeEl) return;
  const entries = data.active || [];
  const queuedCount = data.queued_count || 0;
  while (activeEl.firstChild) activeEl.removeChild(activeEl.firstChild);
  if (entries.length === 0 && queuedCount === 0) {
    _showActiveEmpty(activeEl);
    Object.keys(_dlCallbacks).forEach(id => {
      const cb = _dlCallbacks[id];
      if (cb && cb.btn) {
        cb.btn.classList.remove('downloading');
        cb.btn.disabled = false;
      }
      delete _dlCallbacks[id];
      _downloading.delete(Number(id) || id);
    });
  } else {
    entries.forEach(e => updateActiveDownload(activeEl, { type: 'progress', ...e }));
    if (queuedCount > 0) {
      const summary = h('div', { className: 'dl-card dl-batch-summary' });
      summary.appendChild(textEl('div', _queuedLabel(queuedCount), 'dl-card-name'));
      summary.appendChild(textEl('div', paused ? 'Paused' : 'Waiting to start...', 'dl-card-status dl-status-queued'));
      activeEl.prepend(summary);
    }
  }
  _setQueuePaused(!!paused);
}

let _activeRefreshTimer = null;
function refreshActiveDownloads() {
  clearTimeout(_activeRefreshTimer);
  _activeRefreshTimer = setTimeout(() => {
    Promise.all([
      api('/downloads/active/snapshot'),
      api('/downloads/queue-state'),
    ]).then(([snap, qs]) => {
      setDlBadge(qs.active_count || 0);
      applyActiveSnapshot(snap, qs.paused);
    }).catch(() => {});
  }, 100);
}

function _clearActiveDownloads() {
  const activeEl = document.getElementById('dl-active');
  if (!activeEl) return;
  _showActiveEmpty(activeEl);
}

function _reconcileDownloadUi() {
  refreshActiveDownloads();
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
        refreshActiveDownloads();
        _scheduleHistoryReload();
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
      refreshDlBadge();
    };
    clearBtns.appendChild(btn);
  });
  historyHeader.appendChild(clearBtns);
  resultsArea.appendChild(historyHeader);
  const historySection = h('div', { id: 'dl-history', className: 'dl-card-list' });
  resultsArea.appendChild(historySection);

  _ensureGlobalSSE();
  refreshActiveDownloads();

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

  if (data.type === 'complete' || data.type === 'error' || data.type === 'cancelled') {
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
  if (data.status === 'downloading' || data.status === 'indexing') {
    barFill.classList.add('dl-progress-active');
    barFill.style.width = (data.progress || 0) + '%';
  } else {
    // queued
    barFill.classList.add('dl-progress-queued');
    barFill.style.width = '0%';
  }
  barWrap.appendChild(barFill);
  info.appendChild(barWrap);

  const statusLabel = data.status === 'queued'
    ? 'Waiting...'
    : data.status === 'indexing'
      ? 'Indexing...'
      : 'Downloading';
  const statusText = textEl('div',
    statusLabel,
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
        if (dl.error) meta.appendChild(textEl('span', dl.error, 'dl-error-text'));
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

function _authStateCanReset(authState) {
  return ['connected', 'credentials_ready', 'expired', 'unavailable'].includes(authState);
}

async function _resetTidalConnection(container) {
  try {
    await api('/auth/reset', { method: 'POST' });
    _setRemotePlaybackUnavailable(false);
    if (_loginPoll) {
      clearInterval(_loginPoll);
      _loginPoll = null;
    }
    _dismissDeviceCodeModal();
    await loadAuthStatus(container);
    await refreshStatusLights();
    toast('Tidal connection reset', 'success');
    return true;
  } catch (_) {
    toast('Could not reset Tidal connection', 'error');
    return false;
  }
}

async function loadAuthStatus(container) {
  try {
    let data = await api('/auth/status');
    if (data.logged_in && !data.account_quality) {
      try { data = await api('/auth/account'); } catch (_) { /* keep cached status */ }
    }
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(textEl('div', 'Tidal Account', 'settings-section-header'));
    const row = h('div', { className: 'connection', style: { padding: '0 0 16px', gap: '12px' } });
    const presentation = _tidalStatusPresentation(data);
    if (data.logged_in) {
      const dot = h('span', { className: 'connection-dot' + (presentation.dot ? ' ' + presentation.dot : '') });
      row.appendChild(dot);
      row.appendChild(document.createTextNode(presentation.label));
      if (data.account_quality) {
        const tier = _qualityTier(data.account_quality);
        const badge = textEl('span', tier.tier, 'quality-tag ' + tier.cls);
        badge.title = tier.desc;
        row.appendChild(badge);
      }
    } else {
      const dot = h('span', { className: 'connection-dot' + (presentation.dot ? ' ' + presentation.dot : '') });
      row.appendChild(dot);
      row.appendChild(document.createTextNode(presentation.label));
      const loginBtn = textEl('button', 'Log in to Tidal', 'banner-action');
      loginBtn.addEventListener('click', () => { triggerLogin(); });
      row.appendChild(loginBtn);
    }
    if (_authStateCanReset(data.auth_state)) {
      const resetBtn = textEl('button', 'Reset Tidal connection', 'banner-action');
      resetBtn.addEventListener('click', () => {
        inlineConfirm('Reset the saved Tidal connection? You will need to log in again.', () => { _resetTidalConnection(container); });
      });
      row.appendChild(resetBtn);
    }
    container.appendChild(row);
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
        { key: 'upgrade_target_quality', label: 'Upgrade Target', type: 'select', options: ['HI_RES_LOSSLESS', 'HI_RES'], helper: 'Preferred cap for upgrade downloads. Better-than-local Tidal quality still upgrades.' },
      ]},
      { title: 'Downloads', fields: [
        { key: 'downloads_concurrent_max', label: 'Max Concurrent Downloads', type: 'number', helper: '1\u201310 recommended for stability' },
        { key: 'download_delay', label: 'Download Delay', type: 'toggle', helper: 'Adds a pause between downloads to avoid rate limits' },
      ]},
      { title: 'Metadata', fields: [
        { key: 'metadata_cover_embed', label: 'Embed Cover Art', type: 'toggle', helper: 'Saves album art inside the audio file' },
        { key: 'lyrics_embed', label: 'Embed Lyrics', type: 'toggle', helper: 'On download, write synced lyrics into the audio file. The player can also Save lyrics on a local file without turning this on for every download.' },
        { key: 'lyrics_file', label: 'Save Lyrics File', type: 'toggle', helper: 'On download, write a sidecar .lrc. The lyrics panel Save lyrics control writes that same sidecar for the current track without enabling this for every download.' },
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
