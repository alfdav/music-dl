const { describe, expect, test } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const playerSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/player.js'),
  'utf8',
);

function loadDecisionHelpers() {
  const helperSource = playerSource.match(
    /function _setupMustBlock\(setupData\) \{[\s\S]*?\n\}\n\nfunction _authStateNeedsExpiredBanner\(authState\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('Player decision helpers not found');

  return new Function(`${helperSource[0]}\nreturn { _setupMustBlock, _authStateNeedsExpiredBanner };`)();
}

function loadNowPlayingDownloadHidden() {
  const helperSource = playerSource.match(
    /function _nowPlayingDownloadHidden\(track, audioSrc\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('now-playing download helper not found');

  return new Function(`${helperSource[0]}\nreturn _nowPlayingDownloadHidden;`)();
}

function loadNowPlayingSource() {
  const helperSource = playerSource.match(
    /function _nowPlayingSource\(track, audioSrc\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('now-playing source helper not found');

  return new Function(`${helperSource[0]}\nreturn _nowPlayingSource;`)();
}

function loadSearchRefreshHelper(state, document, doSearch) {
  const helperSource = playerSource.match(
    /async function _refreshSearchAfterLogin\(\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('Search refresh helper not found');

  return new Function(
    'state',
    'document',
    'doSearch',
    `${helperSource[0]}\nreturn _refreshSearchAfterLogin;`,
  )(state, document, doSearch);
}

function loadPlayTrack(audio, state) {
  const functionSource = playerSource.split('function playTrack(track) {')[1]
    .split('\nfunction updateNowPlaying(track) {')[0];

  if (!functionSource) throw new Error('playTrack function not found');

  const noop = () => {};
  return new Function(
    'audio',
    'state',
    '_currentTrackLocalPath',
    '_resetPlayCount',
    '_recordRecentlyPlayed',
    'toast',
    'updatePlayButton',
    'updateNowPlaying',
    'handleLyricsTrackChange',
    '_updateMediaSession',
    '_fetchWaveform',
    'highlightPlayingTrack',
    'updatePlayerHeart',
    '_saveQueue',
    `function playTrack(track) {${functionSource}\nreturn playTrack;`,
  )(audio, state, track => track?.local_path || track?.path || null, noop, noop, noop, noop, noop, noop, noop, noop, noop, noop, noop);
}

function loadPreloadNext(state) {
  const functionSource = playerSource.split('function _preloadNext() {')[1]
    .split('\n// Trigger preload')[0];
  if (!functionSource) throw new Error('preload function not found');

  const preloadAudio = { src: '', load: () => {} };
  const preloadNext = new Function(
    'state',
    '_preloadAudio',
    '_currentTrackLocalPath',
    `let _preloadedSrc = '';\nfunction _preloadNext() {${functionSource}\nreturn _preloadNext;`,
  )(state, preloadAudio, track => track?.local_path || track?.path || null);
  return { preloadAudio, preloadNext };
}

function loadRestorePosition(state, savedPosition) {
  const functionSource = playerSource.split('function _restorePosition() {')[1]
    .split('\n// Save on pause')[0];
  if (!functionSource) throw new Error('restore position function not found');

  const audio = { src: '', addEventListener: () => {} };
  const restorePosition = new Function(
    'state', 'localStorage', '_trackKey', '_isResumePositionUsable',
    '_currentTrackLocalPath', 'audio', 'timeElapsed', 'formatTime',
    'timeTotal', 'progressFill', '_fetchWaveform',
    `function _restorePosition() {${functionSource}\nreturn _restorePosition;`,
  )(
    state,
    { getItem: () => JSON.stringify(savedPosition) },
    track => track.key,
    () => true,
    track => track?.local_path || track?.path || null,
    audio,
    {},
    value => String(value),
    {},
    { style: {} },
    () => {},
  );
  return { audio, restorePosition };
}

function loadRepeatHandler(state) {
  const section = playerSource
    .split("btnRepeat.addEventListener('click', () => {")[1]
    .split('\nfunction _updateRepeatIcon')[0];
  const handlerBody = section.slice(0, section.lastIndexOf('});'));

  if (!handlerBody) throw new Error('repeat handler not found');

  const noop = () => {};
  const btnRepeat = {
    classList: { toggle: noop },
    querySelector: () => null,
    title: '',
  };
  return new Function(
    'state',
    'btnRepeat',
    '_updateRepeatIcon',
    '_saveQueue',
    '_savePlayerPrefs',
    `return () => {${handlerBody}};`,
  )(state, btnRepeat, noop, noop, noop);
}

function loadPlayButtonHandler(audio, state, playTrack) {
  const section = playerSource
    .split("btnPlay.addEventListener('click', () => {")[1]
    .split("\nbtnNext.addEventListener('click', () => {")[0];
  const handlerBody = section.slice(0, section.lastIndexOf('});'));

  if (!handlerBody) throw new Error('play button handler not found');

  return new Function(
    'audio',
    'state',
    'location',
    'playTrack',
    'updatePlayButton',
    `return () => {${handlerBody}};`,
  )(audio, state, { href: 'http://localhost/' }, playTrack, () => {});
}

function loadUpgradeQualityJump(qualityTitle) {
  const helperSource = playerSource.match(
    /function _upgradeQualityJump\(result\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('upgrade quality label helper not found');

  return new Function(
    'qualityTitle',
    `${helperSource[0]}\nreturn _upgradeQualityJump;`,
  )(qualityTitle);
}

function loadWebUpdateCheck(updater, response, renderPanel) {
  const helperSource = playerSource.match(
    /function _checkWebUpdate\(\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('Web update check helper not found');

  const noop = () => {};
  return new Function(
    '_updater',
    'api',
    'document',
    '_isTauri',
    '_renderWebUpdaterPanel',
    '_renderWebUpdaterSettings',
    'h',
    'textEl',
    '_openExternal',
    'toastSticky',
    `${helperSource[0]}\nreturn _checkWebUpdate;`,
  )(
    updater,
    () => Promise.resolve(response),
    { querySelector: () => null },
    () => false,
    renderPanel,
    noop,
    noop,
    noop,
    noop,
    noop,
  );
}

function loadTidalStatusHelpers(sessionStorage) {
  const helperSource = playerSource.match(
    /const _REMOTE_PLAYBACK_UNAVAILABLE_KEY = 'remotePlaybackUnavailable';[\s\S]*?\n\}\n\n\/\/ Idle player title/,
  );

  if (!helperSource) throw new Error('Tidal status helpers not found');

  return new Function(
    'sessionStorage',
    helperSource[0].replace('\n\n// Idle player title', '\nreturn { _remotePlaybackUnavailable, _setRemotePlaybackUnavailable, _tidalStatusPresentation };'),
  )(sessionStorage);
}

function loadPlaybackStatusEvents(state, sessionStorage, refreshTidalStatus, extras = {}) {
  const sessionSource = playerSource.match(
    /const _REMOTE_PLAYBACK_UNAVAILABLE_KEY = 'remotePlaybackUnavailable';[\s\S]*?\n\}\n\nfunction _tidalStatusPresentation/,
  );
  const eventSource = playerSource.match(
    /let _consecutiveErrors = 0;[\s\S]*?\n\n\/\/ Seek/,
  );

  if (!sessionSource || !eventSource) throw new Error('Playback status events not found');
  const sessionHelpers = sessionSource[0].replace('\n\nfunction _tidalStatusPresentation', '');

  const audio = {
    handlers: {},
    addEventListener(name, handler) { this.handlers[name] = handler; },
  };
  const document = { querySelectorAll: () => [] };
  const playTrack = extras.playTrack || (() => { throw new Error('remote failure must not auto-skip'); });
  const api = extras.api || (async () => ({ done: true, reconciling: false }));
  const fetchFn = extras.fetch || (async () => ({ status: 403 }));
  const localPath = extras.localPath || (track => track?.local_path || track?.path || null);
  new Function(
    'audio',
    'state',
    'document',
    'sessionStorage',
    '_refreshTidalStatus',
    'toast',
    'updatePlayButton',
    'setWaveformPlaying',
    'playTrack',
    'setTimeout',
    'api',
    'fetch',
    '_currentTrackLocalPath',
    `${sessionHelpers}\n${eventSource[0]}\nreturn audio.handlers;`,
  )(
    audio, state, document, sessionStorage, refreshTidalStatus,
    extras.toast || (() => {}), () => {}, () => {}, playTrack, extras.setTimeout || (() => {}),
    api, fetchFn, localPath,
  );

  return { events: audio.handlers };
}

function loadTidalStatusRefresh(document, refreshStatusLights, loadAuthStatus) {
  const helperSource = playerSource.match(
    /function _refreshTidalStatus\(\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) return null;

  return new Function(
    'document',
    'refreshStatusLights',
    'loadAuthStatus',
    `${helperSource[0]}\nreturn _refreshTidalStatus;`,
  )(document, refreshStatusLights, loadAuthStatus);
}

function loadLoginSuccessHandler(deps = {}) {
  const helperSource = playerSource.match(
    /async function _handleLoginSuccess\(\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('Login success helper not found');

  return new Function(
    '_setRemotePlaybackUnavailable',
    'refreshStatusLights',
    '_checkErrorBanners',
    '_refreshSearchAfterLogin',
    'document',
    'loadAuthStatus',
    'toast',
    `${helperSource[0]}\nreturn _handleLoginSuccess;`,
  )(
    deps.clearRemote || (() => {}),
    deps.refreshStatusLights || (() => {}),
    deps.checkBanners || (async () => {}),
    deps.refreshSearch || (async () => {}),
    deps.document || { getElementById: () => null },
    deps.loadAuthStatus || (async () => {}),
    deps.toast || (() => {}),
  );
}

function loadInitApp(deps) {
  const functionBody = playerSource
    .split('async function _initApp() {')[1]
    ?.split('\n// Setup check on load')[0];
  if (!functionBody) throw new Error('_initApp not found');

  return new Function(
    'api',
    'state',
    'refreshStatusLights',
    '_restorePlayerPrefs',
    '_restoreQueue',
    '_restorePosition',
    'initUpdater',
    '_checkWebUpdate',
    '_syncRecentFromServer',
    'navigate',
    'normalizeView',
    'location',
    `async function _initApp() {${functionBody}\nreturn _initApp;`,
  )(
    deps.api || (async () => ({})),
    deps.state || {},
    deps.refreshStatusLights || (() => {}),
    deps._restorePlayerPrefs || (() => {}),
    deps._restoreQueue || (() => {}),
    deps._restorePosition || (() => {}),
    deps.initUpdater || (() => {}),
    deps._checkWebUpdate || (() => {}),
    deps._syncRecentFromServer,
    deps.navigate,
    deps.normalizeView || ((view) => view || 'home'),
    deps.location || { hash: '' },
  );
}

function loadRecentSync(recentlyPlayed, api) {
  const functionBody = playerSource
    .split('async function _syncRecentFromServer() {')[1]
    ?.split('\nfunction updatePlayerHeart()')[0];

  if (!functionBody) throw new Error('recent sync helper not found');

  return new Function(
    'api',
    'recentlyPlayed',
    'MAX_RECENT',
    '_trackKey',
    '_saveRecent',
    'console',
    `async function _syncRecentFromServer() {${functionBody}\nreturn _syncRecentFromServer;`,
  )(
    api,
    recentlyPlayed,
    50,
    track => track.id || track.path || track.local_path || '',
    () => {},
    { warn: () => {} },
  );
}

describe('player onboarding decisions', () => {
  test('blocks only when scan paths are missing', () => {
    const { _setupMustBlock } = loadDecisionHelpers();

    expect(_setupMustBlock({ logged_in: true, scan_paths_configured: false })).toBe(true);
    expect(_setupMustBlock({ logged_in: false, scan_paths_configured: true })).toBe(false);
  });

  test('shows expired banner only for an expired auth state', () => {
    const { _authStateNeedsExpiredBanner } = loadDecisionHelpers();

    expect(_authStateNeedsExpiredBanner('not_configured')).toBe(false);
    expect(_authStateNeedsExpiredBanner('expired')).toBe(true);
  });

  test('clears cached Tidal auth state and reruns the active search after login', async () => {
    const state = {
      view: 'search',
      searchQuery: 'coast',
      searchResults: { local: { tracks: [] }, tidal: null, tidalAuthRequired: true },
    };
    const resultsArea = { id: 'search-results' };
    const doSearch = async area => {
      expect(area).toBe(resultsArea);
      expect(state.searchResults).toBeNull();
      state.searchResults = { local: { tracks: [] }, tidal: { tracks: [{ id: '1' }] }, tidalAuthRequired: false };
    };
    const refreshSearch = loadSearchRefreshHelper(state, {
      querySelector: selector => selector === '.results' ? resultsArea : null,
    }, doSearch);

    await refreshSearch();

    expect(state.searchResults.tidalAuthRequired).toBe(false);
    expect(state.searchResults.tidal.tracks).toHaveLength(1);
  });

  test('clears a stale auth-required result without rerunning an inactive search', async () => {
    const state = {
      view: 'library',
      searchQuery: 'coast',
      searchResults: { local: { tracks: [] }, tidal: null, tidalAuthRequired: true },
    };
    const doSearch = async () => {
      throw new Error('inactive search should not rerun');
    };
    const refreshSearch = loadSearchRefreshHelper(state, {
      querySelector: () => ({ id: 'search-results' }),
    }, doSearch);

    await refreshSearch();

    expect(state.searchResults).toBeNull();
  });
});

describe('web update decisions', () => {
  test('keeps automatic no-update response so Settings shows current version', async () => {
    const settingsEl = { id: 'settings-updater' };
    const updater = { settingsEl, webUpdate: null };
    const response = {
      current_version: '1.6.9',
      latest_version: '1.6.8',
      update_available: false,
    };
    let renderedWith = null;
    const check = loadWebUpdateCheck(updater, response, container => {
      renderedWith = container;
    });

    await check();

    expect(updater.webUpdate).toBe(response);
    expect(renderedWith).toBe(settingsEl);
  });
});

describe('now-playing download visibility', () => {
  test('hides Download for a local library track', () => {
    const hidden = loadNowPlayingDownloadHidden();

    expect(hidden({ is_local: true, name: 'Huelepega' }, '')).toBe(true);
  });

  test('shows Download for a Tidal-only queue item', () => {
    const hidden = loadNowPlayingDownloadHidden();

    expect(hidden({ id: 42, name: 'Huelepega', artist: 'Sandy, PAPO', is_local: false }, '/api/playback/stream/42')).toBe(false);
  });

  test('hides Download when a Tidal item is already stamped local', () => {
    const hidden = loadNowPlayingDownloadHidden();

    expect(hidden({
      id: 42,
      is_local: true,
      local_path: '/music/Sandy, PAPO/Otra Vez/Huelepega.flac',
    }, '/api/playback/stream/42')).toBe(true);
    expect(hidden({
      id: 42,
      is_local: false,
      local_path: '/music/Sandy, PAPO/Otra Vez/Huelepega.flac',
    }, '/api/playback/stream/42')).toBe(true);
    expect(hidden({
      id: 42,
      path: '/music/Sandy, PAPO/Otra Vez/Huelepega.flac',
    }, '/api/playback/stream/42')).toBe(true);
  });

  test('hides Download when audio is already a local playback URL', () => {
    const hidden = loadNowPlayingDownloadHidden();

    expect(hidden(
      { id: 42, is_local: false },
      '/api/playback/local?path=%2Fmusic%2FHuelepega.flac',
    )).toBe(true);
  });
});

describe('now-playing source chip', () => {
  test('matches the audio src over queue flags', () => {
    const source = loadNowPlayingSource();

    expect(source(
      { id: 42, is_local: false },
      '/api/playback/local?path=%2Fmusic%2FHuelepega.flac',
    )).toBe('local');
    expect(source(
      { id: 42, is_local: true, local_path: '/music/Huelepega.flac' },
      '/api/playback/stream/42',
    )).toBe('tidal');
  });

  test('falls back to on-disk vs Tidal id when src is empty', () => {
    const source = loadNowPlayingSource();

    expect(source({ is_local: true, name: 'Huelepega' }, '')).toBe('local');
    expect(source({ path: '/music/Huelepega.flac' }, '')).toBe('local');
    expect(source({ local_path: '/music/Huelepega.flac' }, '')).toBe('local');
    expect(source({ id: 42, name: 'Huelepega' }, '')).toBe('tidal');
  });

  test('hides when idle and pairs source with the download hide rule', () => {
    const source = loadNowPlayingSource();
    const hidden = loadNowPlayingDownloadHidden();

    expect(source(null, '')).toBe(null);

    const localSrc = '/api/playback/local?path=%2Fmusic%2FHuelepega.flac';
    const localTrack = {
      id: 42,
      is_local: true,
      local_path: '/music/Sandy, PAPO/Otra Vez/Huelepega.flac',
    };
    expect(source(localTrack, localSrc)).toBe('local');
    expect(hidden(localTrack, localSrc)).toBe(true);

    const streamTrack = { id: 99, name: 'Huelepega', is_local: false };
    const streamSrc = '/api/playback/stream/99';
    expect(source(streamTrack, streamSrc)).toBe('tidal');
    expect(hidden(streamTrack, streamSrc)).toBe(false);
  });

  test('paints a text source-tag in the now-sub-row', () => {
    const html = readFileSync(
      join(import.meta.dir, '../tidal_dl/gui/static/index.html'),
      'utf8',
    );

    expect(html).toContain('id="now-source"');
    expect(html).toMatch(/now-sub-row[\s\S]*id="now-source"/);
    expect(playerSource).toContain("el.className = 'source-tag ' + (source === 'local' ? 'local-tag' : 'tidal-tag')");
    expect(playerSource).toContain('el.textContent = source');
  });
});

describe('local playback decisions', () => {
  test('uses either local path key and streams only remote tracks', () => {
    const makeAudio = () => ({
      src: '',
      muted: false,
      pause: () => {},
      addEventListener: () => {},
      load: () => {},
    });
    const localPathAudio = makeAudio();
    const pathAudio = makeAudio();
    const remoteAudio = makeAudio();
    const invalidLocalAudio = makeAudio();

    loadPlayTrack(localPathAudio, { playing: false })({
      id: 1,
      is_local: true,
      local_path: '/music/local path.flac',
    });
    loadPlayTrack(pathAudio, { playing: false })({
      id: 2,
      is_local: true,
      path: '/music/favorite.flac',
    });
    loadPlayTrack(remoteAudio, { playing: false })({ id: 3, is_local: false });
    loadPlayTrack(invalidLocalAudio, { playing: false })({ is_local: true });

    expect(localPathAudio.src).toBe('/api/playback/local?path=%2Fmusic%2Flocal%20path.flac');
    expect(pathAudio.src).toBe('/api/playback/local?path=%2Fmusic%2Ffavorite.flac');
    expect(remoteAudio.src).toBe('/api/playback/stream/3');
    expect(pathAudio.src).not.toContain('null');
    expect(pathAudio.src).not.toContain('undefined');
    expect(invalidLocalAudio.src).toBe('');
  });

  test('plays a Tidal item from disk when a local path is stamped', () => {
    const audio = {
      src: '',
      muted: false,
      pause: () => {},
      addEventListener: () => {},
      load: () => {},
    };

    loadPlayTrack(audio, { playing: false })({
      id: 42,
      is_local: false,
      local_path: '/music/Huelepega.flac',
    });

    expect(audio.src).toBe('/api/playback/local?path=%2Fmusic%2FHuelepega.flac');
  });

  test('loads a selected local source after installing the readiness listener', () => {
    const calls = [];
    const state = { playing: false };
    const audio = {
      src: '',
      muted: false,
      pause: () => calls.push('pause'),
      addEventListener: eventName => calls.push(eventName),
      load: () => {
        expect(state.playing).toBe(true);
        calls.push('load');
      },
      play: () => Promise.resolve(),
    };
    const playTrack = loadPlayTrack(audio, state);

    playTrack({ is_local: true, local_path: '/music/local track.flac' });

    expect(audio.src).toBe('/api/playback/local?path=%2Fmusic%2Flocal%20track.flac');
    expect(calls).toEqual(['pause', 'canplay', 'load']);
  });

  test('preloads a path-only local queue entry without a Tidal stream', () => {
    const state = {
      queue: [{ id: 1 }, { id: 2, is_local: true, path: '/music/preload.flac' }],
      queueIndex: 0,
      repeat: 'off',
    };
    const { preloadAudio, preloadNext } = loadPreloadNext(state);

    preloadNext();

    expect(preloadAudio.src).toBe('/api/playback/local?path=%2Fmusic%2Fpreload.flac');
  });

  test('restores a path-only local track without a Tidal stream', () => {
    const current = { id: 3, key: 'favorite', is_local: true, path: '/music/resume.flac' };
    const { audio, restorePosition } = loadRestorePosition(
      { queue: [current], queueIndex: 0 },
      { key: 'favorite', time: 42 },
    );

    restorePosition();

    expect(audio.src).toBe('/api/playback/local?path=%2Fmusic%2Fresume.flac');
  });

  test('repeat one preserves the current queue and position', () => {
    const queue = [{ name: 'First' }, { name: 'Current' }, { name: 'Last' }];
    const state = { repeat: 'all', queue, queueIndex: 1 };
    const toggleRepeat = loadRepeatHandler(state);

    toggleRepeat();

    expect(state.repeat).toBe('one');
    expect(state.queue).toEqual(queue);
    expect(state.queueIndex).toBe(1);
  });

  test('play starts a restored queue when no resume position supplied a source', () => {
    const current = { name: 'Restored track', is_local: true };
    const state = { playing: false, queue: [current], queueIndex: 0 };
    const audio = {
      src: '',
      paused: true,
      play: () => Promise.resolve(),
      pause: () => {},
    };
    let startedTrack = null;
    const clickPlay = loadPlayButtonHandler(audio, state, track => {
      startedTrack = track;
    });

    clickPlay();

    expect(startedTrack).toBe(current);
  });

  test('queue prevents removing the active track', () => {
    expect(playerSource).toContain('remove.disabled = i === state.queueIndex;');
  });

  test('upgrade results keep distinct high-resolution quality descriptions', () => {
    const qualityDescriptions = {
      '44100Hz/24bit': '44100Hz/24bit · Hi-Res',
      HI_RES_LOSSLESS: 'Hi-Res Lossless · 24-bit FLAC',
    };
    const qualityJump = loadUpgradeQualityJump(quality => qualityDescriptions[quality]);

    expect(qualityJump({
      current_quality: '44100Hz/24bit',
      available_quality: 'HI_RES_LOSSLESS',
    })).toBe('44100Hz/24bit · Hi-Res → Hi-Res Lossless · 24-bit FLAC');
  });

  test('presents a connected Tidal session as ready', () => {
    const storage = new Map();
    const helpers = loadTidalStatusHelpers({
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    });

    expect(helpers._tidalStatusPresentation({
      logged_in: true,
      auth_state: 'credentials_ready',
    })).toEqual({ label: 'connected', dot: '' });
    expect(helpers._tidalStatusPresentation({
      logged_in: true,
      auth_state: 'credentials_ready',
      username: 'Ada',
    })).toEqual({ label: 'Ada', dot: '' });

    helpers._setRemotePlaybackUnavailable(true);
    expect(helpers._tidalStatusPresentation({ logged_in: false, auth_state: 'expired' }))
      .toEqual({ label: 'connection expired', dot: 'disconnected' });
    expect(helpers._tidalStatusPresentation({ logged_in: false, auth_state: 'not_configured' }))
      .toEqual({ label: 'log in', dot: 'disconnected' });
    expect(helpers._tidalStatusPresentation({ logged_in: false, auth_state: 'unavailable' }))
      .toEqual({ label: 'connection unavailable', dot: 'disconnected' });
  });

  test('clears stale remote playback state after login succeeds', async () => {
    const calls = [];
    const handleLoginSuccess = loadLoginSuccessHandler({
      clearRemote: value => calls.push(['clearRemote', value]),
      refreshStatusLights: () => calls.push(['refreshStatusLights']),
      checkBanners: async () => calls.push(['checkBanners']),
      refreshSearch: async () => calls.push(['refreshSearch']),
      toast: (message, kind) => calls.push(['toast', message, kind]),
    });

    await handleLoginSuccess();

    expect(calls[0]).toEqual(['clearRemote', false]);
  });

  test('refresh helper updates sidebar and open settings auth status', () => {
    const settingsAuth = { id: 'settings-auth-status' };
    const calls = [];
    const refresh = loadTidalStatusRefresh(
      { getElementById: id => id === 'settings-auth-status' ? settingsAuth : null },
      () => calls.push('sidebar'),
      element => calls.push(element),
    );

    expect(refresh).not.toBeNull();
    if (!refresh) return;
    refresh();

    expect(calls).toEqual(['sidebar', settingsAuth]);
  });

  test('remote media events refresh status while local events leave it unchanged', () => {
    const storage = new Map();
    const sessionStorage = {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    };
    const remoteState = { playing: true, queue: [{ id: 1, is_local: false }], queueIndex: 0 };
    const refreshCalls = [];
    const remote = loadPlaybackStatusEvents(remoteState, sessionStorage, () => refreshCalls.push('refresh'));

    remote.events.error();
    expect(storage.get('remotePlaybackUnavailable')).toBe('true');
    expect(refreshCalls).toEqual(['refresh']);
    expect(loadTidalStatusHelpers(sessionStorage)._tidalStatusPresentation({
      logged_in: true,
      auth_state: 'credentials_ready',
    })).toEqual({ label: 'playback unavailable', dot: 'disconnected' });

    remote.events.play();
    expect(storage.has('remotePlaybackUnavailable')).toBe(false);
    expect(refreshCalls).toEqual(['refresh', 'refresh']);
    expect(loadTidalStatusHelpers(sessionStorage)._tidalStatusPresentation({
      logged_in: true,
      auth_state: 'credentials_ready',
    })).toEqual({ label: 'connected', dot: '' });

    storage.set('remotePlaybackUnavailable', 'true');
    const localState = { playing: true, queue: [{ id: 2, is_local: true, name: 'Local' }], queueIndex: 0 };
    const localRefreshCalls = [];
    const local = loadPlaybackStatusEvents(localState, sessionStorage, () => localRefreshCalls.push('refresh'));
    local.events.error();
    local.events.play();

    expect(storage.get('remotePlaybackUnavailable')).toBe('true');
    expect(localRefreshCalls).toEqual([]);
  });

  test('reports aggregate local failures as local file access failures', () => {
    expect(playerSource).toContain("toast('Multiple local files failed \\u2014 check file access', 'error');");
  });

  test('202 and 409 poll reconcile then retry the same local track', async () => {
    const storage = new Map();
    const sessionStorage = {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    };
    const track = { is_local: true, name: 'Song', local_path: '/music/song.wav' };
    const state = { playing: true, queue: [track, { is_local: true, name: 'Next' }], queueIndex: 0 };
    const playCalls = [];
    const polls = [];
    const toasts = [];
    const skips = [];
    const { events } = loadPlaybackStatusEvents(state, sessionStorage, () => {}, {
      playTrack: (item) => playCalls.push(item),
      api: async (path) => {
        polls.push(path);
        return { done: true, reconciling: false };
      },
      fetch: async () => ({ status: 202 }),
      toast: (msg) => toasts.push(msg),
      setTimeout: (fn) => skips.push(fn),
    });

    events.error();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(playCalls).toEqual([track]);
    expect(polls).toContain('/library/reconcile/status');
    expect(state.queueIndex).toBe(0);
    expect(skips).toEqual([]);
    expect(toasts).toEqual([]);
  });

  test('403 after a completed heal may skip the local track', async () => {
    const storage = new Map();
    const sessionStorage = {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    };
    const track = { is_local: true, name: 'Gone', local_path: '/music/gone.wav' };
    const next = { is_local: true, name: 'Next' };
    const state = { playing: true, queue: [track, next], queueIndex: 0 };
    const playCalls = [];
    const toasts = [];
    const { events } = loadPlaybackStatusEvents(state, sessionStorage, () => {}, {
      playTrack: (item) => playCalls.push(item),
      fetch: async () => ({ status: 403 }),
      toast: (msg) => toasts.push(msg),
      setTimeout: (fn) => fn(),
    });

    events.error();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(playCalls).toEqual([next]);
    expect(state.queueIndex).toBe(1);
    expect(toasts.some((msg) => String(msg).includes('unavailable'))).toBe(true);
  });
});

describe('recent history sync decisions', () => {
  test('normalizes positive server epoch seconds to browser milliseconds', async () => {
    const recentlyPlayed = [];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [{ id: 'server-seconds', played_at: 1_700_000_000 }],
    }));

    await syncRecentFromServer();

    expect(recentlyPlayed[0].played_at).toBe(1_700_000_000_000);
  });

  test('leaves server millisecond timestamps at the boundary unchanged', async () => {
    const recentlyPlayed = [];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [{ id: 'server-milliseconds', played_at: 10_000_000_000 }],
    }));

    await syncRecentFromServer();

    expect(recentlyPlayed[0].played_at).toBe(10_000_000_000);
  });

  test('Home navigation is not gated on /home/recent', async () => {
    let navigated = null;
    let resolveRecent;
    const recentHang = new Promise((resolve) => {
      resolveRecent = resolve;
    });

    const initApp = loadInitApp({
      _syncRecentFromServer: () => recentHang,
      navigate: (view) => {
        navigated = view;
      },
    });

    const pending = initApp();
    await Promise.resolve();
    await Promise.resolve();

    expect(navigated).toBe('home');

    resolveRecent();
    await pending;
  });

  test('keeps the actually newer duplicate after normalizing server timestamps', async () => {
    const recentlyPlayed = [{ id: 'duplicate', source: 'browser', played_at: 1_699_999_900_000 }];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [{ id: 'duplicate', source: 'server', played_at: 1_700_000_000 }],
    }));

    await syncRecentFromServer();

    expect(recentlyPlayed).toEqual([
      { id: 'duplicate', source: 'server', played_at: 1_700_000_000_000 },
    ]);
  });
});
