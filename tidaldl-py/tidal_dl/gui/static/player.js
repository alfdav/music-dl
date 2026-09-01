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
const _REMOTE_PLAYBACK_UNAVAILABLE_KEY = 'remotePlaybackUnavailable';

function _remotePlaybackUnavailable() {
  try {
    return sessionStorage.getItem(_REMOTE_PLAYBACK_UNAVAILABLE_KEY) === 'true';
  } catch (_) {
    return false;
  }
}

function _setRemotePlaybackUnavailable(unavailable) {
  try {
    if (unavailable) sessionStorage.setItem(_REMOTE_PLAYBACK_UNAVAILABLE_KEY, 'true');
    else sessionStorage.removeItem(_REMOTE_PLAYBACK_UNAVAILABLE_KEY);
  } catch (_) {}
}

function _tidalStatusPresentation(data) {
  if (data.auth_state === 'expired') return { label: 'connection expired', dot: 'disconnected' };
  if (data.auth_state === 'unavailable') return { label: 'connection unavailable', dot: 'disconnected' };
  if (data.auth_state === 'not_configured') return { label: 'log in', dot: 'disconnected' };
  if (_remotePlaybackUnavailable() && (data.auth_state === 'credentials_ready' || data.logged_in)) {
    return { label: 'playback unavailable', dot: 'disconnected' };
  }
  if (data.logged_in || data.auth_state === 'credentials_ready') {
    return { label: data.username || 'connected', dot: '' };
  }
  return { label: 'log in', dot: 'disconnected' };
}

function _refreshTidalStatus() {
  refreshStatusLights();
  const authSection = document.getElementById('settings-auth-status');
  if (authSection) loadAuthStatus(authSection);
}

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
  lyricsViewportEl: null,
  lyricsFollow: true,
  lyricsProgrammaticGen: 0,
  lyricsUserScrollPending: false,
  lyricsFollowScrollTop: null,
  lyricsReflowScheduled: false,
};
let _lyricsResizeObserver = null;
const _lyricsReduceMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

function _currentTrack() {
  return state.queue[state.queueIndex] || null;
}

function _currentTrackLocalPath(track) {
  if (!track) return null;
  return track.local_path || track.path || null;
}

function _lyricsRequestKey(track) {
  if (!track) return null;
  const localPath = _currentTrackLocalPath(track);
  if (localPath) return localPath;
  const tid = track.tidal_track_id || track.id;
  if (tid) return 'tidal:' + tid;
  if (track.isrc) return 'isrc:' + String(track.isrc).toUpperCase();
  return null;
}

function _lyricsTrackOpenable(track) {
  return !!_lyricsRequestKey(track);
}

function _lyricsCanSave(track, payload) {
  if (!_currentTrackLocalPath(track) || !payload) return false;
  return payload.source === 'tidal-synced' || payload.source === 'tidal-unsynced';
}

function _syncLyricsSaveButton() {
  const btn = document.getElementById('lyrics-save');
  if (!btn) return;
  const can = _lyricsOpen() && _lyricsCanSave(_currentTrack(), lyricsState.lyricsData);
  btn.hidden = !can;
  btn.disabled = !can;
}

function _lyricsQuery(track) {
  const params = new URLSearchParams();
  const localPath = _currentTrackLocalPath(track);
  if (localPath) params.set('path', localPath);
  const tid = track.tidal_track_id || track.id;
  if (tid) params.set('tidal_track_id', String(tid));
  if (track.isrc) params.set('isrc', String(track.isrc));
  if (track.name || track.title) params.set('title', String(track.name || track.title));
  if (track.artist) params.set('artist', String(track.artist));
  if (track.duration) params.set('duration', String(track.duration));
  return params.toString();
}

function _nowPlayingDownloadHidden(track, audioSrc) {
  if (track && (track.is_local || track.local_path || track.path)) return true;
  return String(audioSrc || '').includes('/playback/local');
}

function _nowPlayingSource(track, audioSrc) {
  const src = String(audioSrc || '');
  if (src.includes('/playback/local')) return 'local';
  if (src.includes('/playback/stream/')) return 'tidal';
  if (!track) return null;
  if (track.is_local || track.local_path || track.path) return 'local';
  if (track.id) return 'tidal';
  return null;
}

function _updateNowPlayingSourceChip(track, audioSrc) {
  const el = document.getElementById('now-source');
  if (!el) return;
  const source = _nowPlayingSource(track, audioSrc);
  if (!source) {
    el.textContent = '';
    el.style.display = 'none';
    return;
  }
  el.textContent = source;
  el.className = 'source-tag ' + (source === 'local' ? 'local-tag' : 'tidal-tag');
  el.style.display = '';
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

function _lyricsScrollTarget(lineOffsetTop, lineHeight, viewportHeight, contentHeight) {
  const raw = lineOffsetTop + (lineHeight / 2) - (viewportHeight / 2);
  const max = Math.max(0, contentHeight - viewportHeight);
  return Math.min(Math.max(0, raw), max);
}

function _lyricsEdgeSpacerPx(viewportHeight, lineHeight) {
  return Math.max(0, (viewportHeight - lineHeight) / 2);
}

function _lyricsMeasureLineHeight(list) {
  if (!list || !list.firstElementChild) return 0;
  const el = list.firstElementChild;
  if (typeof el.getBoundingClientRect === 'function') {
    const rect = el.getBoundingClientRect();
    if (rect && rect.height) return rect.height;
  }
  return el.offsetHeight || 0;
}

function _lyricsApplyListSpacer(viewport, list) {
  if (!viewport || !list) return 0;
  const lineHeight = _lyricsMeasureLineHeight(list) || 73.5;
  const pad = _lyricsEdgeSpacerPx(viewport.clientHeight, lineHeight);
  list.style.paddingTop = pad + 'px';
  list.style.paddingBottom = pad + 'px';
  return pad;
}

function _lyricsScrollBehavior(reduceMotion) {
  return reduceMotion ? 'instant' : 'smooth';
}

function _lyricsUserScrollKey(key) {
  return key === 'ArrowUp' || key === 'ArrowDown' || key === 'PageUp'
    || key === 'PageDown' || key === 'Home' || key === 'End';
}

function _lyricsSyncButtonVisible(panelState, follow) {
  return panelState === 'synced' && follow === false;
}

function _lyricsDetachFollow(state) {
  state.lyricsFollow = false;
}

function _lyricsAttachFollow(state) {
  state.lyricsFollow = true;
}

function _lyricsMarkUserScrollIntent(state) {
  state.lyricsUserScrollPending = true;
}

function _lyricsOnViewportScroll(state, viewport) {
  if (!state.lyricsFollow || !viewport) return;
  if (state.lyricsProgrammaticGen > 0) {
    if (Math.abs(viewport.scrollTop - state.lyricsFollowScrollTop) < 2) {
      state.lyricsProgrammaticGen = 0;
    }
    return;
  }
  if (state.lyricsUserScrollPending) {
    state.lyricsUserScrollPending = false;
    _lyricsDetachFollow(state);
  }
}

function _lyricsWriteScrollTop(viewport, target, reduceMotion, state, force) {
  if (!viewport) return false;
  const atTarget = Math.abs(viewport.scrollTop - target) < 1;
  if (atTarget) {
    state.lyricsFollowScrollTop = target;
    state.lyricsProgrammaticGen = 0;
    return false;
  }
  if (!force && state.lyricsProgrammaticGen > 0 && state.lyricsFollowScrollTop === target) {
    return false;
  }
  state.lyricsFollowScrollTop = target;
  state.lyricsProgrammaticGen = (state.lyricsProgrammaticGen || 0) + 1;
  const behavior = _lyricsScrollBehavior(reduceMotion);
  if (typeof viewport.scrollTo === 'function') {
    viewport.scrollTo({ top: target, behavior: behavior });
  } else {
    viewport.scrollTop = target;
  }
  if (behavior === 'instant') state.lyricsProgrammaticGen = 0;
  return true;
}

function _lyricsLineCenterError(viewport, lineEl) {
  if (!viewport || !lineEl) return 0;
  return (lineEl.offsetTop + lineEl.offsetHeight / 2)
    - (viewport.scrollTop + viewport.clientHeight / 2);
}

function _lyricsFollowActiveLine(state, viewport, activeEl, reduceMotion, force) {
  if (!state.lyricsFollow || !viewport || !activeEl) return false;
  const target = _lyricsScrollTarget(
    activeEl.offsetTop,
    activeEl.offsetHeight,
    viewport.clientHeight,
    viewport.scrollHeight,
  );
  return _lyricsWriteScrollTop(viewport, target, reduceMotion, state, force);
}

function _lyricsResyncFollow(state, viewport, activeEl, reduceMotion) {
  _lyricsAttachFollow(state);
  state.lyricsFollowScrollTop = null;
  return _lyricsFollowActiveLine(state, viewport, activeEl, reduceMotion);
}

function _lyricsApplyActiveClasses(lineEls, activeIndex) {
  if (!lineEls) return;
  lineEls.forEach((lineEl, index) => lineEl.classList.toggle('active', index === activeIndex));
}

function _lyricsActiveIndexAt(lines, currentTimeMs) {
  let activeIndex = -1;
  if (!lines) return activeIndex;
  lines.forEach((line, index) => {
    if (line.start_ms <= currentTimeMs && currentTimeMs < line.end_ms) activeIndex = index;
  });
  return activeIndex;
}

function _lyricsTickActive(state, lineEls, lines, currentTimeMs, viewport, reduceMotion) {
  const activeIndex = _lyricsActiveIndexAt(lines, currentTimeMs);
  _lyricsApplyActiveClasses(lineEls, activeIndex);
  const activeEl = activeIndex >= 0 && lineEls ? lineEls[activeIndex] : null;
  _lyricsFollowActiveLine(state, viewport, activeEl, reduceMotion);
  return activeIndex;
}

function _lyricsReadingAnchor(viewport, lineEls) {
  if (!viewport || !lineEls || !lineEls.length) return null;
  const viewMid = viewport.scrollTop + viewport.clientHeight / 2;
  let index = 0;
  let best = Infinity;
  lineEls.forEach((el, i) => {
    if (!el) return;
    const mid = el.offsetTop + (el.offsetHeight || 0) / 2;
    const dist = Math.abs(mid - viewMid);
    if (dist < best) {
      best = dist;
      index = i;
    }
  });
  const el = lineEls[index];
  return { index: index, viewOffset: el.offsetTop - viewport.scrollTop };
}

function _lyricsRestoreReadingAnchor(viewport, lineEls, anchor, state) {
  if (!viewport || !anchor || !lineEls || !lineEls[anchor.index]) return false;
  const el = lineEls[anchor.index];
  const raw = el.offsetTop - anchor.viewOffset;
  const max = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
  const target = Math.min(Math.max(0, raw), max);
  return _lyricsWriteScrollTop(viewport, target, true, state, true);
}

function _lyricsAfterLayout(fn, schedule) {
  const go = typeof schedule === 'function'
    ? schedule
    : (typeof requestAnimationFrame === 'function' ? requestAnimationFrame : function (cb) { cb(); });
  go(function () { go(fn); });
}

function _lyricsReflowViewport(state, viewport, list, lineEls, lines, currentTimeMs, reduceMotion, schedule) {
  const anchor = state.lyricsFollow ? null : _lyricsReadingAnchor(viewport, lineEls);
  _lyricsApplyListSpacer(viewport, list);
  state.lyricsFollowScrollTop = null;
  const settle = function () {
    if (state.lyricsFollow) {
      const activeIndex = _lyricsActiveIndexAt(lines, currentTimeMs);
      const activeEl = activeIndex >= 0 && lineEls ? lineEls[activeIndex] : null;
      _lyricsFollowActiveLine(state, viewport, activeEl, true, true);
      return;
    }
    if (anchor) _lyricsRestoreReadingAnchor(viewport, lineEls, anchor, state);
  };
  settle();
  if (state.lyricsReflowScheduled) return;
  state.lyricsReflowScheduled = true;
  _lyricsAfterLayout(function () {
    state.lyricsReflowScheduled = false;
    settle();
  }, schedule);
}

function _lyricsReflowAttachedViewport(state, viewport, list, lineEls, lines, currentTimeMs, reduceMotion, schedule) {
  _lyricsReflowViewport(state, viewport, list, lineEls, lines, currentTimeMs, reduceMotion, schedule);
}

function _lyricsResetFollowState() {
  lyricsState.lyricsFollow = true;
  lyricsState.lyricsProgrammaticGen = 0;
  lyricsState.lyricsUserScrollPending = false;
  lyricsState.lyricsFollowScrollTop = null;
  lyricsState.lyricsReflowScheduled = false;
}

function _syncLyricsSyncButton() {
  const btn = document.getElementById('lyrics-sync');
  if (!btn) return;
  const show = _lyricsOpen() && _lyricsSyncButtonVisible(lyricsState.lyricsPanelState, lyricsState.lyricsFollow);
  const hadFocus = document.activeElement === btn;
  btn.hidden = !show;
  btn.disabled = !show;
  const live = document.getElementById('lyrics-sync-status');
  if (live) {
    if (show) live.textContent = 'Lyrics auto-scroll paused. Press Sync lyrics to re-center.';
    else if (_lyricsOpen() && lyricsState.lyricsPanelState === 'synced' && lyricsState.lyricsFollow) {
      live.textContent = 'Lyrics following playback.';
    } else {
      live.textContent = '';
    }
  }
  if (!show && hadFocus) {
    const closeBtn = document.getElementById('lyrics-close');
    if (closeBtn && closeBtn.focus) closeBtn.focus();
    else if (lyricsBody && lyricsBody.focus) lyricsBody.focus();
  }
}

function _disconnectLyricsViewportObserver() {
  if (_lyricsResizeObserver) {
    _lyricsResizeObserver.disconnect();
    _lyricsResizeObserver = null;
  }
}

function _bindLyricsViewport(viewport, list) {
  lyricsState.lyricsViewportEl = viewport;
  viewport.tabIndex = 0;
  _lyricsApplyListSpacer(viewport, list);
  _disconnectLyricsViewportObserver();
  const detachFromUser = () => {
    if (!lyricsState.lyricsFollow) return;
    _lyricsDetachFollow(lyricsState);
    lyricsState.lyricsUserScrollPending = false;
    _syncLyricsSyncButton();
  };
  viewport.addEventListener('wheel', detachFromUser, { passive: true });
  viewport.addEventListener('touchstart', detachFromUser, { passive: true });
  viewport.addEventListener('touchmove', detachFromUser, { passive: true });
  viewport.addEventListener('pointerdown', detachFromUser);
  viewport.addEventListener('keydown', (e) => {
    if (!_lyricsUserScrollKey(e.key)) return;
    _lyricsMarkUserScrollIntent(lyricsState);
    detachFromUser();
  });
  viewport.addEventListener('scroll', () => {
    const wasFollow = lyricsState.lyricsFollow;
    _lyricsOnViewportScroll(lyricsState, viewport);
    if (wasFollow !== lyricsState.lyricsFollow) _syncLyricsSyncButton();
  });
  if (typeof ResizeObserver !== 'undefined') {
    _lyricsResizeObserver = new ResizeObserver(() => {
      if (!_lyricsOpen() || lyricsState.lyricsPanelState !== 'synced' || !lyricsState.lyricsData) return;
      _lyricsReflowViewport(
        lyricsState,
        viewport,
        list,
        lyricsState.lyricsLineEls,
        lyricsState.lyricsData.lines,
        Math.floor(audio.currentTime * 1000),
        _lyricsReduceMotionQuery.matches,
      );
    });
    _lyricsResizeObserver.observe(viewport);
  }
}

function renderSyncedLyrics(payload) {
  _clearLyricsBody();
  _lyricsResetFollowState();
  const shell = h('div', { className: 'lyrics-shell lyrics-shell-synced' });
  const viewport = h('div', { className: 'lyrics-synced-viewport' });
  const list = h('div', { className: 'lyrics-synced-list' });
  lyricsState.lyricsLineEls = payload.lines.map((line) => textEl('div', line.text, 'lyrics-synced-line'));
  lyricsState.lyricsLineEls.forEach((lineEl) => list.appendChild(lineEl));
  viewport.appendChild(list);
  shell.appendChild(viewport);
  lyricsBody.appendChild(shell);
  lyricsState.lyricsListEl = list;
  _bindLyricsViewport(viewport, list);
  _syncLyricsSyncButton();
  if (_lyricsAnimId) cancelAnimationFrame(_lyricsAnimId);
  _lyricsAnimId = requestAnimationFrame(syncActiveLyricLine);
}

function syncActiveLyricLine() {
  if (!_lyricsOpen() || lyricsState.lyricsPanelState !== 'synced' || !lyricsState.lyricsData || !lyricsState.lyricsListEl) {
    _lyricsAnimId = null;
    return;
  }
  const currentTimeMs = Math.floor(audio.currentTime * 1000);
  const reduceMotion = _lyricsReduceMotionQuery.matches;
  _lyricsTickActive(
    lyricsState,
    lyricsState.lyricsLineEls,
    lyricsState.lyricsData.lines,
    currentTimeMs,
    lyricsState.lyricsViewportEl,
    reduceMotion,
  );
  _lyricsAnimId = requestAnimationFrame(syncActiveLyricLine);
}

function validateLyricsPayload(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('Invalid lyrics payload');
  if (!['synced', 'unsynced', 'none'].includes(payload.mode)) throw new Error('Invalid lyrics mode');
  if (typeof payload.track_path !== 'string' || !payload.track_path.trim()) throw new Error('Missing track_path');
  if (!Object.prototype.hasOwnProperty.call(payload, 'source')) throw new Error('Missing lyrics source');
  if (!Array.isArray(payload.lines) || typeof payload.text !== 'string') throw new Error('Invalid lyrics shape');
  const sourceByMode = {
    synced: ['lrc-synced', 'embedded-synced', 'tidal-synced'],
    unsynced: ['lrc-unsynced', 'embedded-unsynced', 'tidal-unsynced'],
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
  _syncLyricsSaveButton();
  _syncLyricsSyncButton();
  if (lyricsState.lyricsPanelState === 'loading') {
    _renderLyricsShell('lyrics-shell-loading', 'Loading lyrics…', '');
    return;
  }
  if (lyricsState.lyricsPanelState === 'error') {
    _renderLyricsShell('lyrics-shell-error', 'Could not load lyrics', 'Try again while playback continues.');
    return;
  }
  if (lyricsState.lyricsPanelState === 'empty') {
    _renderLyricsShell('lyrics-shell-empty', 'Lyrics not available', 'No lyrics available for this track.');
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
  if (payload.mode !== 'none') {
    if (requestPath) lyricsState.lyricsCache[requestPath] = payload;
    if (payload.track_path) lyricsState.lyricsCache[payload.track_path] = payload;
  }
  if (payload.mode === 'synced') lyricsState.lyricsPanelState = 'synced';
  else if (payload.mode === 'unsynced') lyricsState.lyricsPanelState = 'unsynced';
  else lyricsState.lyricsPanelState = 'empty';
  renderLyricsPanel();
}

async function loadLyricsForCurrentTrack(trackOverride) {
  const track = trackOverride || _currentTrack();
  const requestKey = _lyricsRequestKey(track);
  if (!track || !_lyricsTrackOpenable(track) || !requestKey) return;

  const requestToken = ++lyricsState.lyricsRequestToken;
  lyricsState.lyricsRequestPath = requestKey;

  try {
    const cached = lyricsState.lyricsCache[requestKey];
    const payload = cached || validateLyricsPayload(await api('/lyrics?' + _lyricsQuery(track)));
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
    _applyLyricsPayload(payload, requestKey);
  } catch (err) {
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
    lyricsState.lyricsData = null;
    lyricsState.lyricsError = err.message || String(err);
    lyricsState.lyricsPanelState = 'error';
    renderLyricsPanel();
  }
}

async function saveLyricsForCurrentTrack() {
  const track = _currentTrack();
  const localPath = _currentTrackLocalPath(track);
  const payload = lyricsState.lyricsData;
  if (!track || !localPath || !_lyricsCanSave(track, payload)) return;

  const requestToken = ++lyricsState.lyricsRequestToken;
  try {
    const saved = validateLyricsPayload(await api('/lyrics/save', {
      method: 'POST',
      body: {
        path: localPath,
        lines: payload.lines || [],
        text: payload.text || '',
        tidal_track_id: track.tidal_track_id || track.id || null,
        isrc: track.isrc || null,
      },
    }));
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
    delete lyricsState.lyricsCache[localPath];
    if (payload.track_path) delete lyricsState.lyricsCache[payload.track_path];
    _applyLyricsPayload(saved, localPath);
  } catch (err) {
    if (requestToken !== lyricsState.lyricsRequestToken || !_lyricsOpen()) return;
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
  lyricsState.lyricsViewportEl = null;
  _disconnectLyricsViewportObserver();
  _lyricsResetFollowState();
  if (_lyricsAnimId) { cancelAnimationFrame(_lyricsAnimId); _lyricsAnimId = null; }
  _setLyricsPanelOpen(false);
  _syncLyricsSaveButton();
  _syncLyricsSyncButton();
  if (options.restoreFocus && lyricsState.lyricsFocusReturnEl && lyricsState.lyricsFocusReturnEl.focus) {
    lyricsState.lyricsFocusReturnEl.focus();
  }
}

function openLyricsPanel(opts) {
  const options = opts || {};
  const track = options.track || _currentTrack();
  const requestKey = _lyricsRequestKey(track);
  if (!track || !_lyricsTrackOpenable(track) || !requestKey) return;

  if (queuePanel.classList.contains('open')) toggleQueue();
  lyricsState.lyricsFocusReturnEl = options.focusReturnEl || document.activeElement || nowArt;
  _lyricsResetFollowState();
  _setLyricsPanelOpen(true);

  if (lyricsState.lyricsCache[requestKey]) {
    _applyLyricsPayload(lyricsState.lyricsCache[requestKey], requestKey);
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
  if (!track || !_lyricsTrackOpenable(track)) {
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
    _lyricsResetFollowState();
    renderLyricsPanel();
    loadLyricsForCurrentTrack(track);
  }
}

if (btnLyricsClose) {
  btnLyricsClose.addEventListener('click', () => closeLyricsPanel({ restoreFocus: true }));
}
const btnLyricsSave = document.getElementById('lyrics-save');
if (btnLyricsSave) {
  btnLyricsSave.addEventListener('click', () => {
    if (btnLyricsSave.disabled || btnLyricsSave.hidden) return;
    saveLyricsForCurrentTrack();
  });
}
const btnLyricsSync = document.getElementById('lyrics-sync');
if (btnLyricsSync) {
  btnLyricsSync.addEventListener('click', () => {
    if (btnLyricsSync.disabled || btnLyricsSync.hidden) return;
    const currentTimeMs = Math.floor(audio.currentTime * 1000);
    const lines = lyricsState.lyricsData && lyricsState.lyricsData.lines;
    const activeIndex = _lyricsActiveIndexAt(lines, currentTimeMs);
    const activeEl = activeIndex >= 0 && lyricsState.lyricsLineEls
      ? lyricsState.lyricsLineEls[activeIndex]
      : null;
    _lyricsResyncFollow(
      lyricsState,
      lyricsState.lyricsViewportEl,
      activeEl,
      _lyricsReduceMotionQuery.matches,
    );
    _syncLyricsSyncButton();
  });
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

async function _syncRecentFromServer() {
  try {
    const data = await api('/home/recent?limit=' + MAX_RECENT);
    const serverTracks = Array.isArray(data.tracks) ? data.tracks : [];
    if (serverTracks.length === 0) return;
    const normalizedServerTracks = serverTracks.map(track => {
      const playedAt = Number(track?.played_at);
      return playedAt > 0 && playedAt < 10_000_000_000
        ? { ...track, played_at: playedAt * 1000 }
        : track;
    });

    const merged = [];
    const seen = new Set();
    normalizedServerTracks.concat(recentlyPlayed)
      .filter(t => t && _trackKey(t))
      .sort((a, b) => (b.played_at || 0) - (a.played_at || 0))
      .forEach(track => {
        const key = _trackKey(track);
        if (seen.has(key)) return;
        seen.add(key);
        merged.push(track);
      });

    recentlyPlayed.length = 0;
    recentlyPlayed.push(...merged.slice(0, MAX_RECENT));
    _saveRecent();
  } catch (err) {
    console.warn('[music-dl] recent memory sync failed:', err);
  }
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
      const audioSrc = (document.getElementById('audio') || {}).src || '';
      if (_nowPlayingDownloadHidden(trk, audioSrc)) { toast('Already in your library', 'success'); return; }
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
    _updateNowPlayingSourceChip(null, '');
    return;
  }

  heartEl.style.display = '';
  const recent = recentlyPlayed && recentlyPlayed[0];
  const audioSrc = (document.getElementById('audio') || {}).src || '';
  if (current) {
    const key = current.path || (current.id ? 'tidal:' + current.id : null);
    heartEl.classList.toggle('hearted', !!(key && _favCache[key]));
  }
  const downloadTrack = current || recent || null;
  dlEl.style.display = _nowPlayingDownloadHidden(downloadTrack, audioSrc) ? 'none' : '';
  _updateNowPlayingSourceChip(downloadTrack, audioSrc);
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
  const localPath = _currentTrackLocalPath(track);
  if (track.is_local && !localPath) {
    toast('Local file unavailable', 'error');
    return;
  }

  // Play count: fires after 30s of actual playback (or on ended for short tracks)
  _resetPlayCount(track);

  // Stop current playback — mute to prevent bleed during source switch
  audio.pause();
  audio.muted = true;

  if (localPath) {
    audio.src = '/api/playback/local?path=' + encodeURIComponent(localPath);
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
  audio.load();
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

    _updateNowPlayingSourceChip(track, (document.getElementById('audio') || {}).src || '');

    // Quality badge
    const nowQuality = document.getElementById('now-quality');
    if (nowQuality) {
      const q = track.quality || '';
      if (q || track.codec) {
        nowQuality.textContent = qualityLabel(track.quality, track.format, track.codec);
        nowQuality.title = qualityTitle(track.quality, track.format, track.codec);
        nowQuality.className = 'quality-tag ' + qualityClass(track.quality, track.format, track.codec);
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
      btnLyrics.disabled = !_lyricsTrackOpenable(track);
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
  if (!audio.src || audio.src === location.href) {
    const current = state.queue[state.queueIndex];
    if (current) playTrack(current);
    return;
  }
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
    try { localStorage.removeItem('playerPosition'); } catch (_) {}
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
let _localHealInFlight = false;
let _localHealToken = 0;
let _localHealTrackKey = null;
let _localHealAttempted = null;

function _trackHealKey(track) {
  return _currentTrackLocalPath(track) || '';
}

function _sameQueueTrack(track) {
  const current = state.queue[state.queueIndex];
  return !!(current && track && _trackHealKey(current) && _trackHealKey(current) === _trackHealKey(track));
}

async function _waitForReconcileIdle(token, track) {
  const started = Date.now();
  while (Date.now() - started < 30000) {
    if (token !== _localHealToken || !_sameQueueTrack(track)) return false;
    try {
      const status = await api('/library/reconcile/status');
      if (status.done || !status.reconciling) return true;
    } catch (_) { /* keep polling */ }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

async function _probeLocalPlaybackStatus(track) {
  const localPath = _currentTrackLocalPath(track);
  if (!localPath) return 0;
  const url = '/api/playback/local?path=' + encodeURIComponent(localPath);
  const resp = await fetch(url, { cache: 'no-store', headers: { Range: 'bytes=0-1' } });
  return resp.status;
}

async function _retryLocalPlaybackAfterHeal(track) {
  const key = _trackHealKey(track);
  if (!key) return false;
  if (_localHealInFlight) return key === _localHealTrackKey;
  if (_localHealAttempted === key) return false;

  _localHealInFlight = true;
  _localHealTrackKey = key;
  const token = ++_localHealToken;
  try {
    let status = 0;
    try {
      status = await _probeLocalPlaybackStatus(track);
    } catch (_) {
      return false;
    }
    if (status === 202 || status === 409) {
      await _waitForReconcileIdle(token, track);
      if (token !== _localHealToken || !_sameQueueTrack(track)) return true;
      try {
        status = await _probeLocalPlaybackStatus(track);
      } catch (_) {
        return false;
      }
    }
    if (token !== _localHealToken || !_sameQueueTrack(track)) return true;
    if (status === 200 || status === 206) {
      _localHealAttempted = key;
      playTrack(track);
      return true;
    }
    return false;
  } finally {
    if (token === _localHealToken) {
      _localHealInFlight = false;
      _localHealTrackKey = null;
    }
  }
}

audio.addEventListener('error', () => {
  state.playing = false;
  updatePlayButton();
  setWaveformPlaying(false);
  const current = state.queue[state.queueIndex];
  if (_localHealInFlight && current && _trackHealKey(current) !== _localHealTrackKey) {
    _localHealToken++;
    _localHealInFlight = false;
    _localHealTrackKey = null;
  }
  if (!current || !current.is_local) {
    if (current) {
      _setRemotePlaybackUnavailable(true);
      _refreshTidalStatus();
    }
    _consecutiveErrors = 0;
    toast('Tidal stream unavailable \u2014 try again later', 'error');
    return;
  }
  void (async () => {
    if (await _retryLocalPlaybackAfterHeal(current)) return;
    _consecutiveErrors++;
    const label = current.name || 'Track';
    if (_consecutiveErrors >= 3) {
      toast('Multiple local files failed \u2014 check file access', 'error');
      return;
    }
    const canAutoSkip = state.queueIndex < state.queue.length - 1;
    toast(label + ' unavailable', 'error');
    if (canAutoSkip) {
      setTimeout(() => { state.queueIndex++; playTrack(state.queue[state.queueIndex]); }, 800);
    }
  })();
});

audio.addEventListener('play', () => {
  const current = state.queue[state.queueIndex];
  if (current && !current.is_local) {
    _setRemotePlaybackUnavailable(false);
    _refreshTidalStatus();
  }
  _consecutiveErrors = 0;
  _localHealAttempted = null;
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
  if (
    _lyricsOpen()
    && lyricsState.lyricsViewportEl
    && lyricsState.lyricsViewportEl.contains(e.target)
    && _lyricsUserScrollKey(e.key)
  ) {
    return;
  }
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
function _renderAccountQualityChip(accountEl, quality) {
  while (accountEl.firstChild) accountEl.removeChild(accountEl.firstChild);
  if (!quality) {
    accountEl.hidden = true;
    accountEl.className = 'connection connection-account';
    accountEl.removeAttribute('title');
    return;
  }
  const tier = _qualityTier(quality);
  accountEl.hidden = false;
  accountEl.className = 'connection connection-account ' + tier.cls;
  accountEl.title = tier.desc;
  accountEl.appendChild(document.createTextNode(tier.tier));
}

async function refreshStatusLights() {
  // Tidal auth
  const tidalEl = document.getElementById('connection-tidal');
  const accountEl = document.getElementById('connection-account');
  if (tidalEl) {
    try {
      const data = await api('/auth/status');
      while (tidalEl.firstChild) tidalEl.removeChild(tidalEl.firstChild);
      const presentation = _tidalStatusPresentation(data);
      const dot = h('span', { className: 'connection-dot' + (presentation.dot ? ' ' + presentation.dot : '') });
      tidalEl.appendChild(dot);
      tidalEl.appendChild(document.createTextNode('tidal \u00b7 ' + presentation.label));
      if (data.logged_in) {
        tidalEl.style.cursor = '';
        tidalEl.onclick = null;
      } else {
        tidalEl.style.cursor = 'pointer';
        tidalEl.onclick = triggerLogin;
      }
      if (accountEl) {
        if (!data.logged_in) {
          _renderAccountQualityChip(accountEl, null);
        } else if (data.account_quality) {
          _renderAccountQualityChip(accountEl, data.account_quality);
        } else {
          try {
            const account = await api('/auth/account');
            _renderAccountQualityChip(accountEl, account.account_quality);
          } catch (_) {
            _renderAccountQualityChip(accountEl, null);
          }
        }
      }
    } catch (_) { /* leave default */ }
  } else if (accountEl) {
    _renderAccountQualityChip(accountEl, null);
  }
}

let _loginPoll = null;

async function _refreshSearchAfterLogin() {
  if (!state.searchResults?.tidalAuthRequired) return;

  state.searchResults = null;
  if (state.view !== 'search' || !state.searchQuery.trim()) return;

  const resultsArea = document.querySelector('.results');
  if (resultsArea) await doSearch(resultsArea);
}

async function _handleLoginSuccess() {
  _setRemotePlaybackUnavailable(false);
  refreshStatusLights();
  await _checkErrorBanners();
  await _refreshSearchAfterLogin();
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

function _fallbackCopyText(text) {
  const el = h('textarea', { style: { position: 'fixed', left: '-9999px', top: '0' } });
  el.value = text;
  document.body.appendChild(el);
  el.focus();
  el.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    el.remove();
  }
}

function _copyText(text, successMessage) {
  const onFallback = () => {
    if (_fallbackCopyText(text)) toast(successMessage, 'success');
    else toast('Copy failed', 'error');
  };

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => toast(successMessage, 'success'))
      .catch(onFallback);
    return;
  }

  onFallback();
}

function _updateInstallCommands() {
  return {
    unix: 'curl -fsSL https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.sh | bash',
    windows: 'irm https://raw.githubusercontent.com/alfdav/music-dl/master/scripts/install.ps1 | iex',
  };
}

function _preferredUpdateInstallCommand() {
  const platform = (navigator.userAgentData?.platform || navigator.platform || '').toLowerCase();
  return platform.includes('win') ? _updateInstallCommands().windows : _updateInstallCommands().unix;
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
    if (data.status === 'expired') {
      toast('Tidal session could not be refreshed. Try again in a moment.', 'error');
      refreshStatusLights();
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
            ? 'Tidal login timed out. Try Connect Tidal again.'
            : 'Tidal login failed. Try Connect Tidal again.';
          toast(msg, 'error');
          refreshStatusLights();
        }
      } catch (_) {
        clearInterval(_loginPoll);
        _loginPoll = null;
        _dismissDeviceCodeModal();
        toast('Connection lost during login. Try Connect Tidal again.', 'error');
        refreshStatusLights();
      }
    }, 3000);
  } catch (err) {
    console.error('[music-dl] login failed:', err);
    toast('Could not start Tidal login. Try Connect Tidal again.', 'error');
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
    remove.disabled = i === state.queueIndex;
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

function _upgradeQualityJump(result) {
  return qualityTitle(result.current_quality, result.current_format, result.current_codec)
    + ' \u2192 ' + qualityTitle(result.available_quality);
}

function _renderScanResults(container, results) {
  if (!results.length) {
    container.appendChild(textEl('div', 'All tracks are at their best available quality.', 'upgrade-empty'));
    return;
  }

  // Group by quality jump
  const groups = {};
  results.forEach(r => {
    const key = _upgradeQualityJump(r);
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
      if (resp.count > 0) { refreshDlBadge(); _ensureGlobalSSE(); }
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
      row.appendChild(textEl('span', _upgradeQualityJump(t), 'upgrade-row-quality'));
      const upBtn = h('button', { className: 'pill small' });
      upBtn.textContent = 'Upgrade';
      upBtn.addEventListener('click', async () => {
        upBtn.disabled = true;
        upBtn.textContent = 'Queued';
        try {
          const resp = await api('/upgrade/start', { method: 'POST', body: {
            tracks: [{ path: t.path, tidal_track_id: t.tidal_track_id || null }]
          }});
          if (resp.count > 0) { refreshDlBadge(); _ensureGlobalSSE(); }
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

function _setupMustBlock(setupData) {
  return !setupData.scan_paths_configured;
}

function _authStateNeedsExpiredBanner(authState) {
  return authState === 'expired';
}

async function _checkSetup() {
  try {
    const resp = await fetch('/api/setup/status');
    const data = await resp.json();
    if (_setupMustBlock(data)) {
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

  if (!setupData.scan_paths_configured) {
    _wizardStepPaths(wizard);
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

function _wizardStepPaths(wizard) {
  while (wizard.firstChild) wizard.removeChild(wizard.firstChild);

  const card = h('div', { className: 'wizard-card' });
  const paths = [];

  // Step indicator
  card.appendChild(textEl('div', 'Set up your local library', 'wizard-step-label'));
  card.appendChild(textEl('h2', 'Select your music folders', 'wizard-title'));
  card.appendChild(textEl('p', 'Choose folders containing music on this device. Tidal is optional. Connect it later for catalog search, streaming, and downloads.', 'wizard-desc'));

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

  const connectTidalBtn = textEl('button', 'Connect Tidal', 'wizard-btn wizard-btn-secondary');
  connectTidalBtn.addEventListener('click', () => triggerLogin());
  card.appendChild(connectTidalBtn);

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
    if (_authStateNeedsExpiredBanner(auth.auth_state)) {
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
  const localPath = _currentTrackLocalPath(next);
  const src = (next.is_local && localPath)
    ? '/api/playback/local?path=' + encodeURIComponent(localPath)
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
    if (!_isResumePositionUsable(current, audio.currentTime, audio.duration)) {
      localStorage.removeItem('playerPosition');
      return;
    }
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
    if (current && data.key === _trackKey(current) && _isResumePositionUsable(current, data.time)) {
      // Set source and seek to saved position without auto-playing
      const localPath = _currentTrackLocalPath(current);
      const src = (current.is_local && localPath)
        ? '/api/playback/local?path=' + encodeURIComponent(localPath)
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

function _hasTauriApi() {
  return !!(window.__TAURI__?.core?.invoke && window.__TAURI__?.event?.listen);
}

function _tauriInvoke(cmd) {
  return window.__TAURI__.core.invoke(cmd);
}

function _currentAppVersionLabel() {
  const chip = document.getElementById('app-version-chip')?.textContent?.trim();
  return chip || null;
}

function _normalizeUpdaterState(us) {
  if (!us) return us;
  return {
    ...us,
    status: us.status || us.phase || 'idle',
    current_version: us.current_version || _currentAppVersionLabel(),
    available_version: us.available_version || us.version || '',
    error_message: us.error_message || us.error || '',
    progress_pct: us.progress_pct || 0,
  };
}

function _onUpdaterState(us) {
  const normalized = _normalizeUpdaterState(us);
  _updater.state = normalized;
  renderUpdaterBanner(normalized);
  if (_updater.settingsEl) renderUpdaterSettings(_updater.settingsEl, normalized);
}

function initUpdater() {
  if (!_hasTauriApi()) return;
  window.__TAURI__.event.listen('updater-state-changed', ev => {
    _onUpdaterState(ev.payload);
  });
  _tauriInvoke('get_updater_state').then(_onUpdaterState).catch(() => {});
}

function checkForUpdates() {
  if (!_hasTauriApi()) return;
  _tauriInvoke('check_for_updates').then(_onUpdaterState).catch(e => {
    toast('Update check failed: ' + e, 'error');
  });
}

function installUpdate() {
  if (!_hasTauriApi()) return;
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
  const actions = h('div', { className: 'updater-settings-actions' });
  const btn = h('button', { className: 'updater-btn-check', type: 'button', disabled: busy },
    document.createTextNode(busy ? 'Please wait…' : 'Check for Updates')
  );
  btn.onclick = () => { if (!busy) checkForUpdates(); };
  actions.appendChild(btn);

  if (us.status === 'ready_to_install') {
    const installBtn = h('button', { className: 'updater-btn-install', type: 'button' }, 'Restart & Install');
    installBtn.onclick = () => installUpdate();
    actions.appendChild(installBtn);
  }
  wrap.appendChild(actions);

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
  return api('/settings/update-check').then(data => {
    _updater.webUpdate = data;
    if (!data.update_available) {
      if (_updater.settingsEl && !_isTauri()) {
        _renderWebUpdaterPanel(_updater.settingsEl);
      }
      return;
    }

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
    const viewBtn = h('button', {
      className: 'toast-update-link',
      type: 'button',
    });
    viewBtn.textContent = 'View';
    viewBtn.addEventListener('click', e => {
      e.stopPropagation();
      _openExternal(data.release_url);
    });
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
  const commands = _updateInstallCommands();
  const command = _preferredUpdateInstallCommand();
  const commandBox = h('code', { className: 'update-install-command' }, command);
  card.appendChild(commandBox);

  const copyBtn = h('button', {
    className: 'update-notification-btn',
    type: 'button',
  });
  copyBtn.textContent = 'Copy install command';
  copyBtn.addEventListener('click', () => _copyText(command, 'Install command copied'));
  actions.appendChild(copyBtn);

  const dlBtn = h('button', {
    className: 'update-notification-btn',
    type: 'button',
  });
  dlBtn.textContent = 'Open release';
  dlBtn.addEventListener('click', () => _openExternal(data.release_url));
  actions.appendChild(dlBtn);

  const otherCommand = command === commands.windows ? commands.unix : commands.windows;
  const otherLabel = command === commands.windows ? 'Copy macOS/Linux command' : 'Copy Windows command';
  const otherBtn = h('button', {
    className: 'update-notification-btn update-notification-btn-secondary',
    type: 'button',
  });
  otherBtn.textContent = otherLabel;
  otherBtn.addEventListener('click', () => _copyText(otherCommand, 'Install command copied'));
  actions.appendChild(otherBtn);

  card.appendChild(actions);
  container.prepend(card);
}

async function _initApp() {
  // Load settings into state for upgrade quality checks
  api('/settings').then(s => { state.settings = s; }).catch(() => {});
  refreshStatusLights();
  _restorePlayerPrefs();
  _restoreQueue();
  _restorePosition();
  initUpdater();
  _checkWebUpdate();
  const recentPromise = _syncRecentFromServer();
  navigate(normalizeView(location.hash.slice(1) || 'home'));
  recentPromise.then(() => {
    if (recentlyPlayed.length === 0) return;
    const wrap = document.querySelector('.home-wrap');
    if (!wrap || wrap.querySelector('.home-recent-section')) return;
    if (typeof _renderRecentStrip === 'function') _renderRecentStrip(wrap);
  }).catch(() => {});
}

// Setup check on load — wizard or normal app
(async () => {
  const needsSetup = await _checkSetup();
  if (!needsSetup) {
    _initApp();
  }
})();
