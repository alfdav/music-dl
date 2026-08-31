const { describe, expect, test } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const viewsSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/views.js'),
  'utf8',
);

function classListFor(node) {
  return {
    add(...names) {
      const set = new Set(String(node.className || '').split(/\s+/).filter(Boolean));
      names.forEach(name => set.add(name));
      node.className = [...set].join(' ');
    },
    remove(...names) {
      const set = new Set(String(node.className || '').split(/\s+/).filter(Boolean));
      names.forEach(name => set.delete(name));
      node.className = [...set].join(' ');
    },
  };
}

function createNode(tag) {
  const node = {
    tag,
    className: '',
    children: [],
    parentNode: null,
    isConnected: false,
    style: {},
    classList: null,
    appendChild(child) {
      if (child.parentNode) child.parentNode.removeChild(child);
      child.parentNode = node;
      child.isConnected = node.isConnected;
      node.children.push(child);
      return child;
    },
    removeChild(child) {
      node.children = node.children.filter(existing => existing !== child);
      child.parentNode = null;
      child.isConnected = false;
      return child;
    },
    replaceWith(next) {
      const parent = node.parentNode;
      if (!parent) return;
      const index = parent.children.indexOf(node);
      next.parentNode = parent;
      next.isConnected = parent.isConnected;
      parent.children[index] = next;
      node.parentNode = null;
      node.isConnected = false;
    },
    remove() {
      if (node.parentNode) node.parentNode.removeChild(node);
    },
    querySelector(selector) {
      return node.querySelectorAll(selector)[0] || null;
    },
    querySelectorAll(selector) {
      const wanted = selector.startsWith('.') ? selector.slice(1) : selector;
      const matches = [];
      const visit = (child) => {
        const classes = String(child.className || '').split(/\s+/);
        if (classes.includes(wanted)) matches.push(child);
        (child.children || []).forEach(visit);
      };
      node.children.forEach(visit);
      return matches;
    },
    addEventListener() {},
    setAttribute() {},
    set textContent(value) { this._text = String(value); this.children = []; },
    get textContent() { return (this._text || '') + this.children.map(child => child.textContent).join(''); },
  };
  node.classList = classListFor(node);
  return node;
}

function createConnectedContainer() {
  const container = createNode('div');
  container.isConnected = true;
  return container;
}

function createH() {
  const h = (tag, props = {}, ...children) => {
    const node = createNode(tag);
    Object.assign(node, props);
    if (!node.classList || typeof node.classList.add !== 'function') {
      node.classList = classListFor(node);
    }
    children.forEach(child => node.appendChild(child));
    return node;
  };
  const textEl = (tag, value, className) => h(tag, { textContent: value, className });
  return { h, textEl };
}

function loadHomeRenderer(api, extras = {}) {
  const functionBody = viewsSource
    .split('async function renderHome(container) {')[1]
    ?.split('\nfunction _getContinueListeningState')[0];
  if (!functionBody) throw new Error('Home renderer not found');

  const { h, textEl } = createH();
  return new Function(
    'api', 'h', 'textEl', 'document', '_greeting', '_renderContinueListening',
    '_renderHomeCold', '_renderHomeGrid', '_renderRecentStrip', 'recentlyPlayed',
    `async function renderHome(container) {${functionBody}\nreturn renderHome;`,
  )(
    api, h, textEl, { createTextNode: value => h('span', { textContent: value }) },
    extras._greeting || (() => 'Good afternoon,'),
    extras._renderContinueListening || (() => {}),
    extras._renderHomeCold || (() => {}),
    extras._renderHomeGrid || (() => {}),
    extras._renderRecentStrip || (() => {}),
    extras.recentlyPlayed || [],
  );
}

function loadContinueListeningRenderer(state, store) {
  const start = viewsSource.indexOf('function _getContinueListeningState() {');
  const end = viewsSource.indexOf('function _renderHomeCold(');
  const block = start >= 0 && end > start ? viewsSource.slice(start, end) : '';
  if (!block.includes('function _renderContinueListening')) {
    throw new Error('continue listening helpers not found');
  }

  const { h, textEl } = createH();
  const localStorage = {
    getItem: (key) => (Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null),
    setItem: (key, value) => { store[key] = value; },
    removeItem: (key) => { delete store[key]; },
  };

  return new Function(
    'state', 'localStorage', '_trackKey', 'formatTime', 'h', 'textEl',
    'artGradient', 'a11yClick', 'audio', '_findTrackIndex', 'playTrack',
    `${block}\nreturn { _renderContinueListening, _getContinueListeningState };`,
  )(
    state,
    localStorage,
    (track) => String(track.id),
    (seconds) => {
      const m = Math.floor(seconds / 60);
      const s = Math.floor(seconds % 60);
      return `${m}:${String(s).padStart(2, '0')}`;
    },
    h,
    textEl,
    () => 'gradient',
    () => {},
    { addEventListener() {} },
    () => 0,
    () => {},
  );
}

function loadRecentStripRenderer(recentlyPlayed) {
  const start = viewsSource.indexOf('function _renderRecentStrip(container) {');
  const end = viewsSource.indexOf('// ---- SEARCH VIEW ----');
  const block = start >= 0 && end > start ? viewsSource.slice(start, end) : '';
  if (!block.includes('function _renderRecentStrip')) {
    throw new Error('recent strip renderer not found');
  }

  const { h, textEl } = createH();
  return new Function(
    'h', 'textEl', 'recentlyPlayed', 'feelingLucky', 'artGradient',
    'a11yClick', 'navigate', 'startPlaybackFromList',
    `${block}\nreturn _renderRecentStrip;`,
  )(h, textEl, recentlyPlayed, () => {}, () => 'gradient', () => {}, () => {}, () => {});
}

function huelepegaResume(time) {
  const track = {
    id: 'huelepega',
    name: 'Huelepega / Sandy',
    artist: 'PAPO — Otra Vez',
    duration: 0,
  };
  const store = {
    playerPosition: JSON.stringify({ key: 'huelepega', time }),
  };
  const continueListening = loadContinueListeningRenderer(
    { queue: [track], queueIndex: 0 },
    store,
  );
  const recentlyPlayed = [track];
  return {
    store,
    continueListening,
    recentlyPlayed,
    renderRecentStrip: loadRecentStripRenderer(recentlyPlayed),
  };
}

function offlineHomePayload() {
  return {
    total_plays: 0,
    track_count: 0,
    album_count: 0,
    volume_available: false,
  };
}

function delayedHomeApi() {
  const pending = [];
  return {
    api: () => new Promise((resolve) => { pending.push(resolve); }),
    resolveNext(data) {
      const resolve = pending.shift();
      if (!resolve) throw new Error('no pending /home');
      resolve(data);
    },
  };
}

describe('Home view decisions', () => {
  test('shows an honest error instead of an empty-library state when Home fails', async () => {
    const renderHome = loadHomeRenderer(async () => { throw new Error('HTTP 500'); });
    const container = createConnectedContainer();

    await renderHome(container);

    const text = container.children[0].textContent;
    expect(text).toContain('Could not load Home');
    expect(text).toContain('could not load your library summary');
    expect(text).not.toContain("I'm feeling lucky");
  });

  test('a second Home paint cannot leave two resume tiles or two recent strips', async () => {
    const { store, continueListening, recentlyPlayed, renderRecentStrip } = huelepegaResume(118);
    const renderHome = loadHomeRenderer(async () => offlineHomePayload(), {
      _renderContinueListening: continueListening._renderContinueListening,
      _renderRecentStrip: renderRecentStrip,
      recentlyPlayed,
    });
    const container = createConnectedContainer();

    await renderHome(container);
    store.playerPosition = JSON.stringify({ key: 'huelepega', time: 119 });
    await renderHome(container);

    expect(container.querySelectorAll('.home-wrap')).toHaveLength(1);
    expect(container.querySelectorAll('.continue-card')).toHaveLength(1);
    expect(container.querySelectorAll('.home-recent-section')).toHaveLength(1);
    expect(container.querySelectorAll('.volume-offline-banner')).toHaveLength(1);
    expect(container.textContent).toContain('Your music drive is offline — showing what we remember');
    expect(container.textContent).toContain('Continue Listening');
    expect(container.textContent).toContain('Resume at 1:59');
    expect(container.textContent).not.toContain('Resume at 1:58');
    expect(container.textContent).not.toContain('Now Playing');

    const wrap = container.querySelector('.home-wrap');
    continueListening._renderContinueListening(wrap);
    renderRecentStrip(wrap);
    expect(wrap.querySelectorAll('.continue-card')).toHaveLength(1);
    expect(wrap.querySelectorAll('.home-recent-section')).toHaveLength(1);
  });

  test('a delayed offline /home cannot stack a second resume tile', async () => {
    const { store, continueListening, recentlyPlayed, renderRecentStrip } = huelepegaResume(118);
    const home = delayedHomeApi();
    const renderHome = loadHomeRenderer(home.api, {
      _renderContinueListening: continueListening._renderContinueListening,
      _renderRecentStrip: renderRecentStrip,
      recentlyPlayed,
    });
    const container = createConnectedContainer();

    const firstPaint = renderHome(container);
    const secondPaint = renderHome(container);
    expect(container.querySelectorAll('.home-wrap')).toHaveLength(1);

    home.resolveNext(offlineHomePayload());
    await firstPaint;
    expect(container.querySelectorAll('.continue-card')).toHaveLength(0);

    store.playerPosition = JSON.stringify({ key: 'huelepega', time: 119 });
    home.resolveNext(offlineHomePayload());
    await secondPaint;

    expect(container.querySelectorAll('.home-wrap')).toHaveLength(1);
    expect(container.querySelectorAll('.continue-card')).toHaveLength(1);
    expect(container.querySelectorAll('.home-recent-section')).toHaveLength(1);
    expect(container.querySelectorAll('.volume-offline-banner')).toHaveLength(1);
    expect(container.textContent).toContain('Your music drive is offline — showing what we remember');
    expect(container.textContent).toContain('Continue Listening');
    expect(container.textContent).toContain('Resume at 1:59');
    expect(container.textContent).not.toContain('Resume at 1:58');
  });
});

function loadGroupingDecisionPayload() {
  const helperSource = viewsSource.match(
    /function _groupingDecisionPayload\(assessment, decision, canonicalTitle\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('grouping decision helper not found');
  return new Function(`${helperSource[0]}\nreturn _groupingDecisionPayload;`)();
}

function loadDownloadHistoryRenderer(api) {
  const rendererSource = viewsSource.match(
    /async function loadDownloadHistory\(container\) \{[\s\S]*?\n\}\n\n\/\/ ---- SETTINGS VIEW ----/,
  );
  if (!rendererSource) throw new Error('download history renderer not found');

  function element(tag) {
    return {
      tag,
      children: [],
      style: {},
      classList: { add() {}, remove() {} },
      appendChild(child) { this.children.push(child); return child; },
      removeChild(child) { this.children.splice(this.children.indexOf(child), 1); },
      addEventListener() {},
      set textContent(value) { this._text = String(value); this.children = []; },
      get textContent() { return (this._text || '') + this.children.map(child => child.textContent).join(''); },
      get firstChild() { return this.children[0] || null; },
    };
  }

  const h = (tag, props = {}) => {
    const node = element(tag);
    Object.assign(node, props);
    return node;
  };
  const textEl = (tag, text, className) => {
    const node = element(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };

  return new Function(
    'api',
    'h',
    'textEl',
    '_dlArtThumb',
    `const ICONS = {};
${rendererSource[0]}
return loadDownloadHistory;`,
  )(api, h, textEl, () => element('div'));
}

describe('album grouping review decisions', () => {
  test('keeps signatures and includes title only when grouping', () => {
    const payload = loadGroupingDecisionPayload();
    const assessment = { left_signature: 'left', right_signature: 'right' };

    expect(payload(assessment, 'group_together', 'Album')).toEqual({
      left_signature: 'left',
      right_signature: 'right',
      decision: 'group_together',
      canonical_title: 'Album',
    });
    expect(payload(assessment, 'keep_separate', 'Album')).toEqual({
      left_signature: 'left',
      right_signature: 'right',
      decision: 'keep_separate',
      canonical_title: null,
    });
  });
});

describe('download history decisions', () => {
  test('failed download history visibly renders persisted error reason', async () => {
    const reason = 'Quality mismatch: requested HI_RES_LOSSLESS but received HIGH with codec aac.';
    const loadDownloadHistory = loadDownloadHistoryRenderer(async () => ({
      downloads: [{ track_id: 118, name: 'Song', status: 'error', error: reason }],
    }));
    const container = { children: [], appendChild(child) { this.children.push(child); }, get firstChild() { return this.children[0] || null; }, removeChild() {} };

    await loadDownloadHistory(container);

    expect(container.children[0].textContent).toContain(reason);
    expect(container.children[0].textContent).toContain('Failed');
    expect(container.children[0].textContent).toContain('Retry');
  });

  test('failed download history without a reason retains retry controls', async () => {
    const loadDownloadHistory = loadDownloadHistoryRenderer(async () => ({
      downloads: [{ track_id: 118, name: 'Song', status: 'error', error: '' }],
    }));
    const container = { children: [], appendChild(child) { this.children.push(child); }, get firstChild() { return this.children[0] || null; }, removeChild() {} };

    await loadDownloadHistory(container);

    expect(container.children[0].textContent).toBe('SongFailedRetry');
  });
});

function loadArtistGroupingHelper() {
  const functionBody = viewsSource
    .split('function _groupArtistTracks(tracks) {')[1]
    ?.split('\nasync function loadLibraryArtistGrouped')[0];

  if (!functionBody) throw new Error('artist grouping helper not found');

  return new Function(
    `function _groupArtistTracks(tracks) {${functionBody}\nreturn _groupArtistTracks;`,
  )();
}

function loadTidalResetHelpers(deps = {}) {
  const helperSource = viewsSource.match(
    /function _authStateCanReset\(authState\) \{[\s\S]*?\n\}\n\nasync function _resetTidalConnection\(container\) \{[\s\S]*?\n\}/,
  );

  if (!helperSource) throw new Error('Tidal reset helpers not found');

  return new Function(
    'api',
    'clearInterval',
    '_dismissDeviceCodeModal',
    'loadAuthStatus',
    'refreshStatusLights',
    'toast',
    '_setRemotePlaybackUnavailable',
    'initialPoll',
    `let _loginPoll = initialPoll;
${helperSource[0]}
return { _authStateCanReset, _resetTidalConnection, getLoginPoll: () => _loginPoll };`,
  )(
    deps.api || (async () => ({})),
    deps.clearInterval || (() => {}),
    deps.dismiss || (() => {}),
    deps.loadAuthStatus || (async () => {}),
    deps.refreshStatusLights || (async () => {}),
    deps.toast || (() => {}),
    deps.clearRemote || (() => {}),
    deps.initialPoll === undefined ? 42 : deps.initialPoll,
  );
}

function wireTidalResetButton(deps = {}) {
  const block = viewsSource.match(
    /if \(_authStateCanReset\(data\.auth_state\)\) \{[\s\S]*?row\.appendChild\(resetBtn\);\n    \}/,
  );
  if (!block) throw new Error('Tidal reset button wiring not found');

  const listeners = [];
  const button = {
    addEventListener(type, listener) {
      if (type === 'click') listeners.push(listener);
    },
    click() {
      listeners.forEach(listener => listener());
    },
  };
  const row = { appendChild() {} };

  new Function(
    'data',
    '_authStateCanReset',
    'textEl',
    'inlineConfirm',
    '_resetTidalConnection',
    'container',
    'row',
    block[0],
  )(
    { auth_state: 'expired' },
    () => true,
    () => button,
    deps.inlineConfirm,
    deps.reset,
    {},
    row,
  );

  return button;
}

function loadAlbumFilterHelper() {
  const helperSource = viewsSource.match(
    /function _filterTidalAlbums\(items, qualityFilter, ratingFilter\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('album filter helper not found');
  return new Function(`${helperSource[0]}\nreturn _filterTidalAlbums;`)();
}

function loadRecentViewHelpers(recentlyPlayed, now) {
  const functionBody = viewsSource
    .split('function _recentFilterKey(playedAt) {')[1]
    ?.split('\nfunction renderRecentlyPlayed')[0];

  if (!functionBody) throw new Error('recent view helpers not found');

  return new Function(
    'recentlyPlayed',
    'Date',
    '_saveRecent',
    'navigate',
    'localStorage',
    `function _recentFilterKey(playedAt) {${functionBody}\nreturn { _recentFilterKey, _recentFilterCounts, _clearRecentOlderThan30Days };`,
  )(
    recentlyPlayed,
    { now: () => now },
    () => {},
    () => {},
    { getItem: () => null, setItem: () => {} },
  );
}

function loadRecentSync(recentlyPlayed, api) {
  const playerSource = readFileSync(join(import.meta.dir, '../tidal_dl/gui/static/player.js'), 'utf8');
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

describe('library view decisions', () => {
  test('keeps artists grouped when a later page crosses an artist boundary', () => {
    const groupArtistTracks = loadArtistGroupingHelper();
    const firstPage = [
      { artist: '*NSYNC', album: 'Hits', track_number: 1 },
      { artist: 'Adele', album: '19', track_number: 1 },
    ];
    const nextPage = [
      { artist: 'Adele', album: '21', track_number: 1 },
      { artist: 'Agnes Fredenberg', album: 'Solitude', track_number: 1 },
    ];

    const groups = groupArtistTracks(firstPage.concat(nextPage));

    expect(groups.map(group => group.artist)).toEqual([
      '*NSYNC',
      'Adele',
      'Agnes Fredenberg',
    ]);
    expect(groups[1].tracks).toHaveLength(2);
  });
});

describe('Tidal connection reset decisions', () => {
  test('shows reset only for existing or unhealthy credentials', () => {
    const { _authStateCanReset } = loadTidalResetHelpers();

    expect(_authStateCanReset('connected')).toBe(true);
    expect(_authStateCanReset('credentials_ready')).toBe(true);
    expect(_authStateCanReset('expired')).toBe(true);
    expect(_authStateCanReset('unavailable')).toBe(true);
    expect(_authStateCanReset('not_configured')).toBe(false);
  });

  test('waits for in-page confirmation before invoking reset', () => {
    let resetCalls = 0;
    let confirmation;
    const button = wireTidalResetButton({
      inlineConfirm: (message, onYes) => { confirmation = { message, onYes }; },
      reset: () => { resetCalls += 1; },
    });

    button.click();

    expect(resetCalls).toBe(0);
    expect(confirmation.message).toBe(
      'Reset the saved Tidal connection? You will need to log in again.',
    );
    confirmation.onYes();
    expect(resetCalls).toBe(1);
    expect(viewsSource).not.toContain("window.confirm('Reset the saved Tidal connection?");
  });

  test('confirm resets once without starting login and refreshes both auth surfaces', async () => {
    const calls = [];
    const container = { marker: 'connected' };
    const helpers = loadTidalResetHelpers({
      api: async (path, options) => { calls.push(['api', path, options]); },
      clearInterval: value => calls.push(['clearInterval', value]),
      dismiss: () => calls.push(['dismiss']),
      loadAuthStatus: async value => calls.push(['loadAuthStatus', value]),
      refreshStatusLights: async () => calls.push(['refreshStatusLights']),
      toast: (message, kind) => calls.push(['toast', message, kind]),
      clearRemote: value => calls.push(['clearRemote', value]),
    });

    const result = await helpers._resetTidalConnection(container);

    expect(result).toBe(true);
    expect(calls.filter(call => call[0] === 'api')).toEqual([
      ['api', '/auth/reset', { method: 'POST' }],
    ]);
    expect(calls).toContainEqual(['clearInterval', 42]);
    expect(calls).toContainEqual(['dismiss']);
    expect(calls).toContainEqual(['clearRemote', false]);
    expect(calls).toContainEqual(['loadAuthStatus', container]);
    expect(calls).toContainEqual(['refreshStatusLights']);
    expect(calls).toContainEqual(['toast', 'Tidal connection reset', 'success']);
    expect(helpers.getLoginPoll()).toBe(null);
  });

  test('failure keeps rendered status and reports error', async () => {
    const calls = [];
    const container = { marker: 'connected' };
    const helpers = loadTidalResetHelpers({
      api: async () => { throw new Error('local failure'); },
      loadAuthStatus: async () => calls.push(['loadAuthStatus']),
      refreshStatusLights: async () => calls.push(['refreshStatusLights']),
      toast: (message, kind) => calls.push(['toast', message, kind]),
    });

    const result = await helpers._resetTidalConnection(container);

    expect(result).toBe(false);
    expect(container.marker).toBe('connected');
    expect(calls).toEqual([['toast', 'Could not reset Tidal connection', 'error']]);
    expect(helpers.getLoginPoll()).toBe(42);
  });
});

describe('track source decisions', () => {
  test('shows local or Tidal source while leaving unknown remote format blank', () => {
    expect(viewsSource).toContain("track.is_local ? 'local' : 'tidal'");
    expect(viewsSource).toContain("className: 'source-tag ' + (track.is_local ? 'local-tag' : 'tidal-tag')");
    expect(viewsSource).toContain("if (track.format) return track.format.toUpperCase();\n  return '';");
  });
});

describe('recent history view decisions', () => {
  test('classifies a normalized current server play as Today', async () => {
    const now = 1_700_000_000_000;
    const recentlyPlayed = [];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [{ id: 'today', played_at: Math.floor(now / 1000) }],
    }));
    const views = loadRecentViewHelpers(recentlyPlayed, now);

    await syncRecentFromServer();

    expect(views._recentFilterKey(recentlyPlayed[0].played_at)).toBe('today');
    expect(views._recentFilterCounts()).toEqual({ all: 1, today: 1, week: 0, older: 0 });
  });

  test('classifies normalized weekly and older server plays', async () => {
    const now = 1_700_000_000_000;
    const recentlyPlayed = [];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [
        { id: 'week', played_at: Math.floor((now - 2 * 24 * 60 * 60 * 1000) / 1000) },
        { id: 'older', played_at: Math.floor((now - 31 * 24 * 60 * 60 * 1000) / 1000) },
      ],
    }));
    const views = loadRecentViewHelpers(recentlyPlayed, now);

    await syncRecentFromServer();

    expect(views._recentFilterCounts()).toEqual({ all: 2, today: 0, week: 1, older: 1 });
  });

  test('clears only server entries older than 30 days after normalization', async () => {
    const now = 1_700_000_000_000;
    const recentlyPlayed = [];
    const syncRecentFromServer = loadRecentSync(recentlyPlayed, async () => ({
      tracks: [
        { id: 'recent', played_at: Math.floor((now - 2 * 24 * 60 * 60 * 1000) / 1000) },
        { id: 'old', played_at: Math.floor((now - 31 * 24 * 60 * 60 * 1000) / 1000) },
      ],
    }));
    const views = loadRecentViewHelpers(recentlyPlayed, now);

    await syncRecentFromServer();
    views._clearRecentOlderThan30Days();

    expect(recentlyPlayed).toEqual([
      { id: 'recent', played_at: now - 2 * 24 * 60 * 60 * 1000 },
    ]);
  });
});

function loadApplyQueueCountsFromEvent() {
  const helperSource = viewsSource.match(
    /function applyQueueCountsFromEvent\(data\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('applyQueueCountsFromEvent not found');

  const summary = {
    className: 'dl-card dl-batch-summary',
    removed: false,
    children: [],
    querySelector(sel) {
      if (sel === '.dl-card-status') {
        return this.children.find(child => String(child.className || '').includes('dl-card-status'));
      }
      if (sel === '.dl-card-name') {
        return this.children.find(child => String(child.className || '').includes('dl-card-name'));
      }
      return null;
    },
    remove() {
      this.removed = true;
      activeEl.children = activeEl.children.filter(child => child !== this);
    },
  };
  const running = { className: 'dl-card', 'data-dl-id': '1' };
  const activeEl = {
    children: [summary, running],
    querySelector(sel) {
      if (sel === '.dl-batch-summary') {
        return this.children.find(child => String(child.className || '').includes('dl-batch-summary')) || null;
      }
      return null;
    },
    prepend(node) {
      this.children.unshift(node);
    },
  };
  const badge = { textContent: '2', style: { display: '' } };
  const h = (tag, props = {}) => ({ tag, ...props, children: [], appendChild(child) { this.children.push(child); return child; } });
  const textEl = (tag, value, className) => ({ tag, textContent: value, className });
  const fn = new Function(
    'document',
    'h',
    'textEl',
    'setDlBadge',
    '_setQueuePaused',
    '_queuedLabel',
    `${helperSource[0]}\nreturn applyQueueCountsFromEvent;`,
  )(
    { getElementById: id => (id === 'dl-active' ? activeEl : null) },
    h,
    textEl,
    count => {
      badge.textContent = count;
      badge.style.display = count > 0 ? '' : 'none';
    },
    () => {},
    count => count + (count === 1 ? ' track queued' : ' tracks queued'),
  );

  return { fn, dom: { summary, activeEl, badge } };
}

describe('download badge and requeue decisions', () => {
  test('badge is an absolute count from queue-state, not a local delta', () => {
    expect(viewsSource).toContain('function refreshDlBadge()');
    expect(viewsSource).toContain("api('/downloads/queue-state')");
    expect(viewsSource).toContain('setDlBadge(qs.active_count || 0)');
    expect(viewsSource).not.toMatch(/updateDlBadge\(\s*1\s*\)/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(\s*-1\s*\)/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(data\.count/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(result\.missing\)/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(missingTracks\.length\)/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(nonLocal\.length\)/);
    expect(viewsSource).not.toMatch(/updateDlBadge\(resp\.count\)/);
  });

  test('clear history buttons refresh the Downloads badge', () => {
    const clearBlock = viewsSource.split("['Failed', 'Done', 'All'].forEach(label => {")[1];
    expect(clearBlock).toBeTruthy();
    expect(clearBlock).toContain("await api('/downloads/history' + qs, { method: 'DELETE' })");
    expect(clearBlock).toContain('refreshDlBadge()');
  });

  test('Cancel All clears the queued summary without waiting for SSE', () => {
    const cancelBlock = viewsSource.split("cancelBtn.textContent = 'Cancel All';")[1];
    expect(cancelBlock).toBeTruthy();
    expect(cancelBlock).toContain("await api('/downloads/cancel', { method: 'POST' })");
    expect(cancelBlock).toContain('refreshActiveDownloads()');
    expect(viewsSource).toContain('function refreshActiveDownloads()');
    expect(viewsSource).toContain('function applyActiveSnapshot(');
    expect(viewsSource).toContain("api('/downloads/active/snapshot')");
    expect(viewsSource).toContain("data.type === 'cancelled'");
    expect(viewsSource).toContain("count === 1 ? ' track queued' : ' tracks queued'");
  });

  test('Active downloads render from snapshot, not leftover SSE cards', () => {
    expect(viewsSource).toContain('refreshActiveDownloads()');
    expect(viewsSource).toContain("if (data.type === 'upgrade_progress') {");
    expect(viewsSource).toContain("if (data.type !== 'progress') refreshActiveDownloads();");
  });

  test('progress events apply queue counts so the waiting card does not linger', () => {
    const handler = viewsSource.split('_globalSSE.onmessage = (event) => {')[1];
    expect(handler).toBeTruthy();
    expect(handler).toContain("if (data.type === 'progress')");
    expect(handler).toContain('updateActiveDownload(activeEl, data)');
    expect(handler).toContain('applyQueueCountsFromEvent(data)');
    expect(viewsSource).toContain('function applyQueueCountsFromEvent(');
  });

  test('applyQueueCountsFromEvent removes the queued summary when a claim lowers queued_count', () => {
    const apply = loadApplyQueueCountsFromEvent();
    const { summary, activeEl, badge } = apply.dom;

    apply.fn({
      type: 'progress',
      queued_count: 0,
      active_count: 1,
      paused: false,
    });

    expect(summary.removed).toBe(true);
    expect(activeEl.children).not.toContain(summary);
    expect(badge.textContent).toBe(1);
    expect(badge.style.display).toBe('');
  });

  test('active download card shows Indexing... during post-processing', () => {
    const card = viewsSource.split('function updateActiveDownload(container, data) {')[1];
    expect(card).toBeTruthy();
    expect(card).toContain("data.status === 'indexing'");
    expect(card).toContain('Indexing...');
    expect(card).not.toMatch(/data\.status === 'queued' \? 'Waiting\.\.\.' : 'Downloading'/);
  });

  test('single-track download can be requeued after a missed terminal event', () => {
    const downloadTrack = viewsSource.split('async function downloadTrack(track, btn) {')[1];
    expect(downloadTrack).toBeTruthy();
    expect(downloadTrack).not.toContain('if (_downloading.has(track.id)) return;');
    expect(downloadTrack).toContain('refreshDlBadge()');
    expect(viewsSource).toContain('function _reconcileDownloadUi()');
    expect(viewsSource).toContain('_reconcileDownloadUi()');
    expect(viewsSource).toContain('refreshActiveDownloads()');
    expect(viewsSource).toContain('setTimeout(_reconcileDownloadUi, 1500)');
  });
});

describe('Tidal album filter decisions', () => {
  test('filters albums by quality and rating', () => {
    const filterTidalAlbums = loadAlbumFilterHelper();
    const albums = [
      { id: 1, quality: 'HI_RES_LOSSLESS', explicit: true },
      { id: 2, quality: 'HI_RES', explicit: false },
      { id: 3, quality: 'LOSSLESS', explicit: false },
      { id: 4, quality: 'HIGH', explicit: true },
      { id: 5, quality: 'UNKNOWN', explicit: null, atmos: true },
    ];

    expect(filterTidalAlbums(albums, 'all', 'all')).toEqual(albums);
    expect(filterTidalAlbums(albums, 'max', 'all').map(album => album.id)).toEqual([1, 2]);
    expect(filterTidalAlbums(albums, 'lossless', 'all').map(album => album.id)).toEqual([3]);
    expect(filterTidalAlbums(albums, 'lossless', 'clean').map(album => album.id)).toEqual([3]);
    expect(filterTidalAlbums(albums, 'all', 'clean').map(album => album.id)).toEqual([2, 3]);
    expect(filterTidalAlbums(albums, 'high', 'explicit').map(album => album.id)).toEqual([4]);
    expect(filterTidalAlbums(albums, 'max', 'all').some(album => album.id === 5)).toBe(false);
    expect(filterTidalAlbums([{ id: 6, quality: 'MAX', explicit: false }], 'max', 'all')).toEqual([]);
    expect(filterTidalAlbums([{ id: 7, quality: 'HIGH', explicit: 'true' }], 'all', 'explicit')).toEqual([]);
  });
});

function loadArtistTile() {
  const helperSource = viewsSource.match(
    /function _artistTile\(artist, hero\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('artist tile helper not found');
  return new Function(
    'h',
    'textEl',
    'navigate',
    'a11yClick',
    'fetch',
    `${helperSource[0]}\nreturn _artistTile;`,
  )(
    (tag, props = {}, ...children) => {
      const node = {
        tag,
        ...props,
        children: [],
        appendChild(child) { this.children.push(child); return child; },
        addEventListener() {},
        textContent: props.textContent || '',
      };
      children.forEach(child => node.appendChild(child));
      return node;
    },
    (tag, value, className) => ({ tag, textContent: value, className, children: [] }),
    () => {},
    () => {},
    () => Promise.resolve({ json: async () => ({}) }),
  );
}

describe('artist album count copy', () => {
  test('hero tile singularizes one album', () => {
    const tile = loadArtistTile()({ name: 'Sandy, PAPO', play_count: 4, album_count: 1, track_count: 9 }, true);
    const text = JSON.stringify(tile);
    expect(text).toContain('1 album');
    expect(text).not.toContain('1 albums');
  });

  test('hero tile keeps plural albums', () => {
    const tile = loadArtistTile()({ name: 'Artist', play_count: 4, album_count: 2, track_count: 9 }, true);
    expect(JSON.stringify(tile)).toContain('2 albums');
  });
});

describe('local album detail cover fetch', () => {
  test('skips artist albums when prefetched data already has cover_url', () => {
    const coverBlock = viewsSource
      .split('async function renderLocalAlbumDetail(container, artistName, albumName, prefetchedData) {')[1]
      ?.split('// Album header')[0];
    if (!coverBlock) throw new Error('album detail cover block not found');
    expect(coverBlock).toMatch(/prefetchedData(?: &&|\.)cover_url|'cover_url' in prefetchedData/);
    expect(coverBlock).toMatch(/if \(!coverUrl\b/);
  });
});

describe('artist and album loading state', () => {
  test('artist gallery uses a visible loading hint instead of skeleton-row', () => {
    const gallery = viewsSource
      .split('async function renderArtistGallery(')[1]
      ?.split('// ---- LOCAL ALBUM DETAIL')[0];
    if (!gallery) throw new Error('artist gallery not found');
    expect(gallery).not.toContain('skeleton-row');
    expect(gallery).toMatch(/Loading albums|home-loading-hint|skeleton-track/);
  });

  test('artist gallery is hybrid local plus Tidal, not library-only', () => {
    const gallery = artistGallerySource();
    expect(gallery).toContain('/library/artist/');
    expect(gallery).toMatch(/\/artists\/|tidalArtistId/);
    const results = viewsSource
      .split('function renderSearchResults(')[1]
      ?.split('function _trackKey(')[0] || '';
    expect(results).toContain('buildArtistView(item.name, item.id)');
  });

  test('recent-search chips give query text a truncating class', () => {
    const recent = viewsSource
      .split('function _renderRecentSearches(')[1]
      ?.split('function _filterTidalAlbums(')[0] || '';
    expect(recent).toContain('recent-chip-query');
    expect(recent).toContain('recent-chip-x');
    expect(recent).toContain('recent-chip-type');
  });

  test('local-empty plus Tidal-pending keeps the skeleton', () => {
    const search = viewsSource
      .split('async function doSearch(resultsArea) {')[1]
      ?.split('function renderTidalSearchAuthPanel(')[0] || '';
    expect(search).toContain('_searchStillWaitingForTidal');
    expect(search).toContain('renderSearchSkeleton(resultsArea)');
    expect(search).toContain('tidalSettled');

    const helperStart = viewsSource.indexOf('function _searchStillWaitingForTidal(');
    expect(helperStart).toBeGreaterThan(-1);
    const helperBody = viewsSource.slice(helperStart).split('\nfunction ')[0];
    const waiting = new Function(`${helperBody}\nreturn _searchStillWaitingForTidal;`)();
    expect(waiting(null, 'tracks', false, false)).toBe(true);
    expect(waiting({ tracks: [] }, 'tracks', false, false)).toBe(true);
    expect(waiting({ tracks: [{ id: 1 }] }, 'tracks', false, false)).toBe(false);
    expect(waiting({ tracks: [] }, 'tracks', true, false)).toBe(false);
    expect(waiting({ tracks: [] }, 'tracks', false, true)).toBe(false);
  });

  test('album search does not skip the local/Tidal divider', () => {
    const source = viewsSource
      .split('function renderUnifiedSearchResults(')[1]
      ?.split('function renderSearchResults(')[0] || '';
    expect(source).toContain("className: 'search-divider'");
    expect(source).not.toContain("type !== 'albums' && localItems.length > 0");
    expect(source).toMatch(/localItems\.length > 0 && [\s\S]*tidal/);
  });

  test('album detail uses a visible loading hint instead of skeleton-row', () => {
    const detail = viewsSource
      .split('async function renderLocalAlbumDetail(container, artistName, albumName, prefetchedData) {')[1]
      ?.split('\nasync function ')[0];
    if (!detail) throw new Error('album detail not found');
    expect(detail).not.toContain('skeleton-row');
    expect(detail).toMatch(/Loading tracks|home-loading-hint|skeleton-track/);
  });
});

function loadRecentAlbumsExpanded(fetchPage) {
  const functionBody = viewsSource
    .split('async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {')[1]
    ?.split('\nfunction renderLibrary(container) {')[0];
  if (!functionBody) throw new Error('recent albums loader not found');

  function element(tag) {
    return {
      tag,
      children: [],
      style: {},
      classList: {
        add() {},
        remove() {},
        contains() { return false; },
      },
      appendChild(child) { this.children.push(child); return child; },
      remove() {},
      querySelector(selector) {
        return this.children.find(child =>
          selector.split('.').every(part => !part || (child.className || '').split(/\s+/).includes(part))
        ) || null;
      },
      set textContent(value) { this._text = String(value); this.children = []; },
      get textContent() {
        return (this._text || '') + this.children.map(child => child.textContent).join('');
      },
    };
  }
  const h = (tag, props = {}, ...children) => {
    const node = element(tag);
    Object.assign(node, props);
    children.forEach(child => child && node.appendChild(child));
    return node;
  };
  const textEl = (tag, value, className) => h(tag, { textContent: value, className });
  const renderRecentAlbumRow = (album) => textEl('div', album.name || 'album', 'recent-album-row');

  return new Function(
    'loadLibraryRecentAlbumsPage',
    'LIBRARY_PAGE_SIZE',
    'h',
    'textEl',
    'renderRecentAlbumRow',
    '_recentTimeGroup',
    'toast',
    'document',
    `let libraryOffset = 0;
     let libraryTotal = 0;
     async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {${functionBody}
     return loadLibraryRecentAlbumsExpanded;`,
  )(
    fetchPage,
    12,
    h,
    textEl,
    renderRecentAlbumRow,
    () => 'Today',
    () => {},
    { getElementById() { return null; } },
  );
}

describe('recently added loading state', () => {
  test('paints a home-loading-hint before the recent-albums request resolves', async () => {
    const source = viewsSource
      .split('async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {')[1]
      ?.split('\nfunction renderLibrary(container) {')[0];
    if (!source) throw new Error('recent albums loader not found');
    const beforeAwait = source.split('await loadLibraryRecentAlbumsPage')[0];
    expect(beforeAwait).toContain('home-loading-hint');
    expect(beforeAwait).toMatch(/Loading albums/);
    expect(source).not.toContain('skeleton-row');

    let resolvePage;
    const pendingPage = new Promise(resolve => { resolvePage = resolve; });
    const load = loadRecentAlbumsExpanded(() => pendingPage);
    const resultsArea = {
      children: [],
      firstChild: null,
      appendChild(child) {
        this.children.push(child);
        this.firstChild = this.children[0];
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter(item => item !== child);
        this.firstChild = this.children[0] || null;
        return child;
      },
      querySelector() { return null; },
      get textContent() { return this.children.map(child => child.textContent).join(''); },
    };

    const pending = load(resultsArea, false);
    expect(resultsArea.textContent).toContain('Loading albums');
    expect(resultsArea.children.some(child => child.className === 'home-loading-hint')).toBe(true);

    resolvePage({ albums: [{ name: 'Otra Vez', artist: 'Sandy, PAPO', track_count: 9, recent_at: 1 }], total: 1 });
    await pending;
    expect(resultsArea.textContent).not.toContain('Loading albums');
    expect(resultsArea.textContent).toContain('Otra Vez');
  });

  test('replaces the hint with an error state when recent albums fail', async () => {
    const load = loadRecentAlbumsExpanded(async () => { throw new Error('HTTP 500'); });
    const resultsArea = {
      children: [],
      firstChild: null,
      appendChild(child) {
        this.children.push(child);
        this.firstChild = this.children[0];
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter(item => item !== child);
        this.firstChild = this.children[0] || null;
        return child;
      },
      querySelector() { return null; },
      get textContent() { return this.children.map(child => child.textContent).join(''); },
    };

    await load(resultsArea, false);

    expect(resultsArea.textContent).toContain('Could not load recently added albums');
    expect(resultsArea.textContent).toContain('HTTP 500');
    expect(resultsArea.textContent).not.toContain('Loading albums');
    expect(resultsArea.children.some(child => child.className === 'empty-state')).toBe(true);
  });
});

function searchCardElement(tag) {
  return {
    tag,
    children: [],
    style: {},
    className: '',
    alt: '',
    src: '',
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {},
    set textContent(value) { this._text = String(value); this.children = []; },
    get textContent() {
      return (this._text || '') + this.children.map(child => child.textContent).join('');
    },
  };
}

function searchCardH(tag, props = {}, ...children) {
  const node = searchCardElement(tag);
  Object.assign(node, props);
  children.forEach(child => child && node.appendChild(child));
  return node;
}

function searchCardTextEl(tag, value, className) {
  return searchCardH(tag, { textContent: value, className });
}

function walkSearchNode(node, visit) {
  if (!node || typeof node !== 'object') return;
  visit(node);
  (node.children || []).forEach(child => walkSearchNode(child, visit));
}

function findSearchNodes(root, predicate) {
  const matches = [];
  walkSearchNode(root, node => { if (predicate(node)) matches.push(node); });
  return matches;
}

function loadSearchResultsRenderer(searchType) {
  const functionBody = viewsSource
    .split('function renderSearchResults(container, data, showHeader = true) {')[1]
    ?.split('\nfunction _trackKey(')[0];
  if (!functionBody) throw new Error('renderSearchResults not found');

  return new Function(
    'state',
    'h',
    'textEl',
    'artGradient',
    'a11yClick',
    'navigateAlbum',
    'navigate',
    'loadPlaylistTracks',
    `function renderSearchResults(container, data, showHeader = true) {${functionBody}
     return renderSearchResults;`,
  )(
    { searchType },
    searchCardH,
    searchCardTextEl,
    () => 'gradient',
    () => {},
    () => {},
    () => {},
    () => {},
  );
}

function loadLocalArtistSearchRenderer() {
  const block = viewsSource.match(
    /\} else if \(type === 'artists'\) \{[\s\S]*?container\.appendChild\(grid\);\n    \}/,
  );
  if (!block) throw new Error('local artist search cards not found');
  const body = block[0]
    .replace("} else if (type === 'artists') {", '')
    .replace(/\n    \}$/, '');
  return new Function(
    'h',
    'textEl',
    'artGradient',
    'a11yClick',
    'navigate',
    'localItems',
    'container',
    body,
  );
}

function renderSearchContainer() {
  return {
    children: [],
    get firstChild() { return this.children[0] || null; },
    removeChild(child) {
      this.children = this.children.filter(item => item !== child);
      return child;
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
  };
}

describe('artist search card captions', () => {
  test('Tidal artist tiles show the name as visible title text and img alt', () => {
    const renderSearchResults = loadSearchResultsRenderer('artists');
    const container = renderSearchContainer();
    const name = 'Tetrarch (David Diaz)';

    renderSearchResults(container, {
      artists: [{ id: 1, name, cover_url: 'https://example.test/tetrarch.jpg', roles: 'Artist' }],
    }, false);

    const titles = findSearchNodes(container, node => node.className === 'album-card-title');
    const images = findSearchNodes(container, node => node.tag === 'img');
    expect(titles.map(node => node.textContent)).toEqual([name]);
    expect(images.map(node => node.alt)).toEqual([name]);
    expect(container.children.map(child => child.textContent).join('')).toContain(name);
  });

  test('local artist tiles show the name as visible title text', () => {
    const renderLocalArtists = loadLocalArtistSearchRenderer();
    const container = renderSearchContainer();
    const name = 'Tetrarch (David Diaz)';

    renderLocalArtists(
      searchCardH,
      searchCardTextEl,
      () => 'gradient',
      () => {},
      () => {},
      [{ name, cover_url: '/library/cover/1', track_count: 12 }],
      container,
    );

    const titles = findSearchNodes(container, node => node.className === 'album-card-title');
    const images = findSearchNodes(container, node => node.tag === 'img');
    expect(titles.map(node => node.textContent)).toEqual([name]);
    expect(images.map(node => node.alt)).toEqual([name]);
    expect(container.children[0].textContent).toContain(name);
  });

  test('album and playlist search cards keep a visible title', () => {
    const albums = loadSearchResultsRenderer('albums');
    const playlists = loadSearchResultsRenderer('playlists');
    const albumContainer = renderSearchContainer();
    const playlistContainer = renderSearchContainer();

    albums(albumContainer, {
      albums: [{
        id: 9,
        name: 'Unstable',
        artist: 'Tetrarch',
        cover_url: 'https://example.test/u.jpg',
        quality: 'LOSSLESS',
      }],
    }, false);
    playlists(playlistContainer, {
      playlists: [{
        id: 3,
        name: 'Metal Mix',
        cover_url: 'https://example.test/p.jpg',
        num_tracks: 20,
      }],
    }, false);

    expect(
      findSearchNodes(albumContainer, node => node.className === 'album-card-title')
        .map(node => node.textContent),
    ).toEqual(['Unstable']);
    expect(
      findSearchNodes(playlistContainer, node => node.className === 'album-card-title')
        .map(node => node.textContent),
    ).toEqual(['Metal Mix']);
  });

  test('card CSS does not stretch cover art over the caption', () => {
    const css = readFileSync(
      join(import.meta.dir, '../tidal_dl/gui/static/style.css'),
      'utf8',
    );
    const rule = (selector) => {
      const matches = [...css.matchAll(new RegExp(
        `^${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([^}]*)\\}`,
        'gm',
      ))];
      return matches.map(match => match[1]);
    };

    expect(rule('.album-card-art').some(body => body.includes('height: 100%'))).toBe(false);
    expect(rule('.album-card-art').some(body => body.includes('aspect-ratio: 1'))).toBe(true);
    expect(rule('.album-card-art-wrap .album-card-art').some(body =>
      body.includes('height: 100%') && body.includes('object-fit: cover'),
    )).toBe(true);
    expect(rule('.album-grid').some(body => body.includes('align-items: start'))).toBe(true);
    expect(rule('.album-gallery').some(body => body.includes('align-items: start'))).toBe(true);
  });
});

function loadUnifiedSearchRenderer(searchType) {
  const functionBody = viewsSource
    .split('function renderUnifiedSearchResults(container, localData, tidalData, tidalAuthRequired) {')[1]
    ?.split('\nfunction renderSearchResults(')[0];
  if (!functionBody) throw new Error('renderUnifiedSearchResults not found');
  const renderSearchResults = loadSearchResultsRenderer(searchType);
  return new Function(
    'state',
    'h',
    'textEl',
    'artGradient',
    'a11yClick',
    'navigate',
    'buildLocalReleaseView',
    'buildLocalAlbumView',
    'buildArtistView',
    '_appendGroupingBadge',
    '_filterTidalAlbums',
    'renderSearchResults',
    'renderTidalSearchAuthPanel',
    `function renderUnifiedSearchResults(container, localData, tidalData, tidalAuthRequired) {${functionBody}
     return renderUnifiedSearchResults;`,
  )(
    {
      searchType,
      albumQualityFilter: 'all',
      albumRatingFilter: 'all',
    },
    searchCardH,
    searchCardTextEl,
    () => 'gradient',
    () => {},
    () => {},
    () => 'local-release',
    () => 'local-album',
    () => 'artist',
    () => {},
    (items) => items,
    renderSearchResults,
    () => {},
  );
}

describe('unified album search sections', () => {
  test('separates the local gallery from the Tidal Albums header', () => {
    const render = loadUnifiedSearchRenderer('albums');
    const container = renderSearchContainer();
    const tidalAlbums = Array.from({ length: 50 }, (_, i) => ({
      id: i + 1,
      name: 'Album ' + i,
      artist: 'Tidal Artist',
    }));

    render(
      container,
      { albums: [{ id: 'local-1', name: 'Los Grandes Del Vallenato', artist: 'Various Artists' }] },
      { albums: tidalAlbums },
      false,
    );

    const classes = container.children.map(child => child.className);
    const galleryAt = classes.indexOf('album-gallery');
    const dividerAt = classes.indexOf('search-divider');
    const headers = container.children.filter(child => child.className === 'results-header');

    expect(galleryAt).toBeGreaterThan(-1);
    expect(dividerAt).toBeGreaterThan(galleryAt);
    expect(headers).toHaveLength(2);
    expect(headers[0].textContent).toContain('Your Library');
    expect(headers[0].textContent).toContain('1 result');
    expect(headers[0].textContent).not.toContain('1 results');
    expect(headers[1].textContent).toContain('Tidal Albums');
    expect(headers[1].textContent).toContain('50 albums');
    expect(container.children.indexOf(headers[1])).toBeGreaterThan(dividerAt);
  });

  test('search result headers vertically center the count with the title', () => {
    const css = readFileSync(
      join(import.meta.dir, '../tidal_dl/gui/static/style.css'),
      'utf8',
    );
    const headerRules = [...css.matchAll(/^\.results-header \{([^}]*)\}/gm)].map(match => match[1]);
    expect(headerRules.some(body => body.includes('align-items: center'))).toBe(true);
    expect(headerRules.some(body => body.includes('align-items: baseline'))).toBe(false);
    const galleryBreak = [...css.matchAll(/^\.album-gallery \+ \.search-divider \{([^}]*)\}/gm)]
      .map(match => match[1]);
    expect(galleryBreak.some(body => /padding-top:\s*\d+px/.test(body))).toBe(true);
  });
});

function loadNavStackHelpers() {
  const start = viewsSource.indexOf('// ---- NAV STACK ----');
  const end = viewsSource.indexOf('// ---- /NAV STACK ----');
  const block = start >= 0 && end > start ? viewsSource.slice(start, end) : '';
  if (!block.includes('function _isTopLevelView')) {
    throw new Error('nav stack helpers not found');
  }
  return new Function(
    `${block}\nreturn {\n  _isTopLevelView, _isDrillInView, _shouldShowNavBack,\n  _snapshotOutgoing, _pushNav, _popNav, _restoreLibrary,\n  _navMode, _hashchangeNavOpts,\n};`,
  )();
}

function artistGallerySource() {
  return viewsSource
    .split('async function renderArtistGallery(')[1]
    ?.split('// ---- LOCAL ALBUM DETAIL')[0] || '';
}

function localAlbumDetailSource() {
  return viewsSource
    .split('async function renderLocalAlbumDetail(container, artistName, albumName, prefetchedData) {')[1]
    ?.split('\nasync function ')[0] || '';
}

function tidalAlbumDetailSource() {
  return viewsSource
    .split('async function renderAlbumDetail(container, albumId) {')[1]
    ?.split('\nfunction ')[0] || '';
}

function libraryMountSource() {
  return viewsSource
    .split('function renderLibrary(container) {')[1]
    ?.split('\nasync function _showDuplicatePreview')[0] || '';
}

describe('navigation stack', () => {
  test('back from a Plays album restores library sort, query, and scroll', () => {
    const nav = loadNavStackHelpers();
    const stack = [];
    const library = { librarySort: 'plays', libraryQuery: 'tetrarch' };
    const outgoing = nav._snapshotOutgoing('library', library.librarySort, library.libraryQuery, 240);

    expect(nav._navMode({})).toBe('push');
    nav._pushNav(stack, outgoing);
    expect(stack).toHaveLength(1);

    library.librarySort = 'artist';
    library.libraryQuery = '';
    const restored = nav._popNav(stack);
    nav._restoreLibrary(restored, library);

    expect(nav._navMode({ back: true })).toBe('back');
    expect(restored.view).toBe('library');
    expect(library.librarySort).toBe('plays');
    expect(library.libraryQuery).toBe('tetrarch');
    expect(restored.scrollY).toBe(240);
    expect(stack).toHaveLength(0);
  });

  test('top-level views do not show the back control', () => {
    const nav = loadNavStackHelpers();
    const topLevel = [
      'home', 'search', 'library', 'recent', 'playlists', 'favorites',
      'downloads', 'settings', 'djai', 'upgrades', 'recent-added',
    ];

    topLevel.forEach(view => {
      expect(nav._isTopLevelView(view)).toBe(true);
      expect(nav._isDrillInView(view)).toBe(false);
      expect(nav._shouldShowNavBack(view, 0)).toBe(false);
      expect(nav._shouldShowNavBack(view, 2)).toBe(false);
    });
    expect(nav._shouldShowNavBack('localalbum:A:B', 0)).toBe(false);
  });

  test('drill-in with a non-empty stack shows the back control', () => {
    const nav = loadNavStackHelpers();
    ['artist:Tetrarch', 'localalbum:Tetrarch:Unstable', 'localrelease:abc123', 'album:99'].forEach(view => {
      expect(nav._isDrillInView(view)).toBe(true);
      expect(nav._isTopLevelView(view)).toBe(false);
      expect(nav._shouldShowNavBack(view, 1)).toBe(true);
    });

    expect(artistGallerySource()).toContain('_navBackControl()');
    expect(localAlbumDetailSource()).toContain('_navBackControl()');
    expect(tidalAlbumDetailSource()).toContain('_navBackControl()');
    expect(viewsSource).toContain("className: 'nav-back'");
    expect(viewsSource).toContain("aria-label', 'Back'");
  });

  test('sidebar jump to library clears the stack instead of walking artist then album', () => {
    const nav = loadNavStackHelpers();
    const stack = [];
    nav._pushNav(stack, nav._snapshotOutgoing('home', 'artist', '', 0));
    nav._pushNav(stack, nav._snapshotOutgoing('artist:Tetrarch', 'artist', '', 0));
    expect(stack.map(entry => entry.view)).toEqual(['home', 'artist:Tetrarch']);

    expect(nav._navMode({ jump: true })).toBe('jump');
    expect(nav._navMode({ replace: true })).toBe('jump');
    stack.length = 0;
    expect(stack).toEqual([]);
    expect(nav._shouldShowNavBack('library', stack.length)).toBe(false);

    expect(viewsSource).toMatch(/n\.addEventListener\('click', \(\) => navigate\(n\.dataset\.view,\s*\{\s*jump:\s*true\s*\}\)\)/);
    expect(viewsSource).toMatch(/navigate\('library',\s*\{\s*jump:\s*true\s*\}\)/);
    expect(viewsSource).toContain('function navigate(view, opts)');
  });

  test('Home → artist → album pops album, then artist, then home', () => {
    const nav = loadNavStackHelpers();
    const stack = [];
    nav._pushNav(stack, nav._snapshotOutgoing('home', 'artist', '', 0));
    nav._pushNav(stack, nav._snapshotOutgoing('artist:Tetrarch', 'artist', '', 12));

    const fromAlbum = nav._popNav(stack);
    expect(fromAlbum.view).toBe('artist:Tetrarch');
    expect(nav._shouldShowNavBack(fromAlbum.view, stack.length)).toBe(true);

    const fromArtist = nav._popNav(stack);
    expect(fromArtist.view).toBe('home');
    expect(nav._shouldShowNavBack(fromArtist.view, stack.length)).toBe(false);
    expect(stack).toHaveLength(0);
  });

  test('hashchange pops when it matches the previous stack entry, otherwise jumps', () => {
    const nav = loadNavStackHelpers();
    expect(nav._hashchangeNavOpts('library', 'library', 'library')).toBe(null);
    expect(nav._hashchangeNavOpts('library', 'localalbum:A:B', 'library')).toEqual({ back: true });
    expect(nav._hashchangeNavOpts('search', 'localalbum:A:B', 'library')).toEqual({ jump: true });
  });

  test('library remount keeps the current sort and query instead of wiping search', () => {
    const mount = libraryMountSource();
    expect(mount).toBeTruthy();
    expect(mount).not.toMatch(/^\s*libraryQuery = '';/m);
    expect(mount).toContain('loadLibraryAlbums(resultsArea, libraryQuery)');
    expect(mount).toContain('loadLibraryArtistGrouped(resultsArea, libraryQuery)');
  });
});

function clickableNode(tag) {
  const listeners = {};
  const node = {
    tag,
    className: '',
    children: [],
    parentNode: null,
    style: {},
    dataset: {},
    attributes: {},
    _homeData: null,
    listeners,
    classList: null,
    appendChild(child) {
      child.parentNode = node;
      node.children.push(child);
      return child;
    },
    removeChild(child) {
      node.children = node.children.filter(existing => existing !== child);
      child.parentNode = null;
      return child;
    },
    remove() {
      if (node.parentNode) node.parentNode.removeChild(node);
    },
    querySelector(selector) {
      return node.querySelectorAll(selector)[0] || null;
    },
    querySelectorAll(selector) {
      const wanted = selector.startsWith('.') ? selector.slice(1) : selector;
      const matches = [];
      const visit = (child) => {
        const classes = String(child.className || '').split(/\s+/);
        if (classes.includes(wanted) || child.id === wanted || child.tag === wanted) {
          matches.push(child);
        }
        (child.children || []).forEach(visit);
      };
      node.children.forEach(visit);
      return matches;
    },
    addEventListener(type, listener) {
      listeners[type] = listeners[type] || [];
      listeners[type].push(listener);
    },
    removeEventListener(type, listener) {
      listeners[type] = (listeners[type] || []).filter(fn => fn !== listener);
    },
    dispatchEvent(event) {
      (listeners[event.type] || []).forEach(fn => fn(event));
    },
    click() {
      node.dispatchEvent({
        type: 'click',
        target: node,
        currentTarget: node,
        stopPropagation() {},
        preventDefault() {},
      });
    },
    setAttribute(name, value) { node.attributes[name] = value; },
    getAttribute(name) { return node.attributes[name]; },
    closest(selector) {
      const wanted = selector.startsWith('.') ? selector.slice(1) : selector;
      let current = node;
      while (current) {
        const classes = String(current.className || '').split(/\s+/);
        if (classes.includes(wanted) || current.tag === wanted) return current;
        current = current.parentNode;
      }
      return null;
    },
    set textContent(value) { this._text = String(value); this.children = []; },
    get textContent() {
      return (this._text || '') + node.children.map(child => child.textContent).join('');
    },
    get firstChild() { return node.children[0] || null; },
    focus() {},
  };
  node.classList = classListFor(node);
  return node;
}

function clickableH(tag, props = {}, ...children) {
  const node = clickableNode(tag);
  Object.assign(node, props);
  if (!node.classList || typeof node.classList.add !== 'function') {
    node.classList = classListFor(node);
  }
  children.forEach(child => child && node.appendChild(child));
  return node;
}

function clickableTextEl(tag, value, className) {
  return clickableH(tag, { textContent: value, className });
}

function loadHomeInsightCards() {
  const factsStart = viewsSource.indexOf('const HOME_FAN_WEEKDAYS');
  const cardsStart = viewsSource.indexOf('function _homeInsightCards(data)');
  const cardsEnd = viewsSource.indexOf('\nfunction _homeFanLayout(');
  if (factsStart < 0 || cardsStart < factsStart || cardsEnd < cardsStart) {
    throw new Error('home insight cards helper not found');
  }
  return new Function(`${viewsSource.slice(factsStart, cardsEnd)}\nreturn _homeInsightCards;`)();
}

function loadHomeInsightFan(options = {}) {
  const start = viewsSource.indexOf('// ---- HOME INSIGHT FAN ----');
  const end = viewsSource.indexOf('// ---- HOME INSIGHT FAN END ----');
  if (start < 0 || end < start) throw new Error('home insight fan block not found');
  const block = viewsSource.slice(start, end);
  const host = options.host || clickableNode('main');
  host.className = 'main';
  const docListeners = {};
  const documentMock = {
    body: host,
    querySelector(selector) {
      if (selector === '.main') return host;
      if (selector === '.home-fan-overlay') return host.querySelector(selector);
      return host.querySelector(selector);
    },
    querySelectorAll(selector) {
      return host.querySelectorAll(selector);
    },
    addEventListener(type, listener) {
      docListeners[type] = docListeners[type] || [];
      docListeners[type].push(listener);
    },
    removeEventListener(type, listener) {
      docListeners[type] = (docListeners[type] || []).filter(fn => fn !== listener);
    },
    dispatchKey(key) {
      (docListeners.keydown || []).forEach(fn => fn({ key, preventDefault() {} }));
    },
  };
  const matchMedia = (query) => ({
    matches: Boolean(options.reducedMotion && String(query).includes('prefers-reduced-motion')),
  });
  const loaded = new Function(
    'h',
    'textEl',
    'document',
    'window',
    'a11yClick',
    'svgIcon',
    'ICONS',
    '_barChart',
    '_weeklyChart',
    `${block}\nreturn { _homeInsightCards, _homeFanLayout, _homePrefersReducedMotion, _bindHomeDataFan, _openHomeInsightFan, _closeHomeInsightFan, _cycleHomeInsightFan };`,
  )(
    clickableH,
    clickableTextEl,
    documentMock,
    { matchMedia, requestAnimationFrame: (fn) => fn(0) },
    (el) => { el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); },
    () => clickableH('svg'),
    { chevronLeft: '', chevronRight: '' },
    (items) => clickableH('div', { className: 'mini-bar-chart', textContent: (items || []).map(i => i.label).join(' ') }),
    () => clickableH('div', { className: 'mini-weekly-chart' }),
  );
  loaded.dispatchKey = (key) => documentMock.dispatchKey(key);
  return loaded;
}

function richHomePayload() {
  return {
    total_plays: 847,
    listening_time_hours: 11.4,
    streak: 6,
    top_artist: {
      name: 'Tetrarch',
      play_count: 40,
      genre: 'Metal',
      album_count: 2,
      track_count: 9,
    },
    top_artists: [
      {
        name: 'Tetrarch',
        play_count: 40,
        genre: 'Metal',
        album_count: 2,
        track_count: 9,
      },
      {
        name: 'Deftones',
        play_count: 12,
        genre: 'Alt Rock',
        album_count: 3,
        track_count: 14,
      },
    ],
    most_replayed: { name: 'Unstable', play_count: 18 },
    track_count: 11974,
    album_count: 1565,
    genre_breakdown: [
      { genre: 'Metal', count: 40 },
      { genre: 'Alt Rock', count: 12 },
    ],
    weekly_activity: [0, 1.2, 0, 0, 2.4, 0, 0],
    this_week: {
      total_plays: 8,
      top_artist: { name: 'Deftones', play_count: 8 },
      most_replayed: { name: 'Change', play_count: 8 },
      genre_breakdown: [{ genre: 'Alt Rock', count: 8 }],
    },
    recent_albums: [{ album: 'Unstable' }, { album: 'Otra Vez' }],
  };
}

describe('Home insight fan decisions', () => {
  test('skips empty insights and does not invent stats', () => {
    const cards = loadHomeInsightCards()({
      total_plays: 0,
      listening_time_hours: 0,
      top_artist: null,
      top_artists: [],
      most_replayed: null,
      track_count: 0,
      album_count: 0,
      genre_breakdown: [],
      weekly_activity: [0, 0, 0, 0, 0, 0, 0],
      this_week: { total_plays: 0 },
    });

    expect(cards).toEqual([]);
    expect(cards.some(card => card.id === 'recent_albums')).toBe(false);
  });

  test('total_plays, top_artist, and this_week cards render supporting facts from the fixture', () => {
    const payload = richHomePayload();
    const cards = loadHomeInsightCards()(payload);
    const byId = Object.fromEntries(cards.map(card => [card.id, card]));

    expect(byId.total_plays.facts).toEqual([
      '6-day streak',
      'Unstable on repeat — 18 plays',
      '11,974 tracks · 1,565 albums',
    ]);
    expect(byId.top_artist.facts).toEqual([
      'Metal',
      '2 albums · 9 tracks',
    ]);
    expect(byId.this_week.facts).toEqual([
      'Change on repeat — 8 plays',
      'Alt Rock',
    ]);
    expect(byId.listening_time_hours.facts).toEqual([
      'Friday was the peak this week',
      '3.6h this week of 11h all-time',
    ]);
    expect(byId.weekly_activity.facts).toEqual(['Peak Friday']);
    expect(byId['top_artists:Deftones'].facts).toEqual([
      'Alt Rock',
      '3 albums · 14 tracks',
    ]);

    const host = clickableNode('main');
    host.className = 'main';
    const fan = loadHomeInsightFan({ host, reducedMotion: true });
    fan._openHomeInsightFan(payload);
    const center = host.querySelector('.is-center');
    expect(center.querySelectorAll('.home-fan-fact').map(node => node.textContent)).toEqual([
      '6-day streak',
      'Unstable on repeat — 18 plays',
      '11,974 tracks · 1,565 albums',
    ]);
    expect(center.textContent).toContain('Total plays');
  });

  test('empty or sparse home does not invent insight facts', () => {
    const empty = loadHomeInsightCards()({
      total_plays: 0,
      listening_time_hours: 0,
      streak: 0,
      top_artist: null,
      top_artists: [],
      most_replayed: null,
      track_count: 0,
      album_count: 0,
      genre_breakdown: [],
      weekly_activity: [0, 0, 0, 0, 0, 0, 0],
      this_week: { total_plays: 0, most_replayed: null, genre_breakdown: [] },
    });
    expect(empty).toEqual([]);

    const playsOnly = loadHomeInsightCards()({ total_plays: 859 });
    expect(playsOnly).toHaveLength(1);
    expect(playsOnly[0].id).toBe('total_plays');
    expect(playsOnly[0].facts).toEqual([]);
    expect(JSON.stringify(playsOnly)).not.toMatch(/0-day|0 genre|0 plays per|0 albums/);

    const artistOnly = loadHomeInsightCards()({
      top_artist: { name: 'Daft Punk', play_count: 133 },
    });
    expect(artistOnly[0].facts).toEqual([]);
    expect(artistOnly[0].facts.join(' ')).not.toMatch(/0 genre|0 album|0 track/);

    const weekOnly = loadHomeInsightCards()({
      this_week: { total_plays: 3, top_artist: { name: 'Sister Sledge' } },
    });
    expect(weekOnly[0].detail).toBe('Sister Sledge');
    expect(weekOnly[0].facts).toEqual([]);
  });

  test('builds local cards only from already-loaded /home fields', () => {
    const cards = loadHomeInsightCards()(richHomePayload());
    const ids = cards.map(card => card.id);

    expect(ids).toContain('total_plays');
    expect(ids).toContain('listening_time_hours');
    expect(ids).toContain('top_artist');
    expect(ids).toContain('top_artists:Deftones');
    expect(ids).toContain('most_replayed');
    expect(ids).toContain('track_count');
    expect(ids).toContain('album_count');
    expect(ids).toContain('genre_breakdown');
    expect(ids).toContain('weekly_activity');
    expect(ids).toContain('this_week');
    expect(ids).toContain('recent_albums');
    expect(ids.filter(id => id === 'top_artist' || id === 'top_artists:Tetrarch')).toHaveLength(1);
    expect(cards.find(card => card.id === 'recent_albums').names).toEqual(['Unstable', 'Otra Vez']);
    expect(viewsSource).not.toMatch(/api\('\/home\/insights/);
    expect(viewsSource).not.toContain('unsplash');
  });

  test('data tiles open the overlay and artist tiles still navigate to artist:', () => {
    const host = clickableNode('main');
    host.className = 'main';
    const fan = loadHomeInsightFan({ host, reducedMotion: true });
    const navigated = [];
    const artistTile = loadArtistTileWithClicks((view) => { navigated.push(view); });
    const dataTile = clickableH('div', { className: 'bento-tile bento-stat-tile' });

    fan._bindHomeDataFan(dataTile, richHomePayload());
    dataTile.click();

    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(1);
    expect(host.textContent).toContain('Total plays');
    expect(navigated).toEqual([]);

    artistTile.click();
    expect(navigated).toEqual(['artist:' + encodeURIComponent('Tetrarch')]);
    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(1);
    expect(viewsSource).toContain("navigate('artist:' + encodeURIComponent(artist.name))");
    expect(viewsSource).toContain('_closeHomeInsightFan()');
    expect(viewsSource).toContain('function navigate(view, opts)');
    expect(viewsSource).toContain('const _navStack = []');
    expect(viewsSource.split('function navigate(view, opts) {')[1].split('\nfunction ')[0]).toContain('_closeHomeInsightFan()');
    expect(viewsSource.split('function navigate(view, opts) {')[1].split('\nfunction ')[0]).not.toContain('function navigate(view) {');
    expect(viewsSource).toContain('_bindHomeDataFan(genreTile');
    expect(viewsSource).toContain('_bindHomeDataFan(ltTile');
    expect(viewsSource).toContain('_bindHomeDataFan(tTile');
    expect(viewsSource).toContain('_bindHomeDataFan(aTile');
  });

  test('reduced motion skips the elastic fan and overlay dismisses', () => {
    const host = clickableNode('main');
    host.className = 'main';
    const fan = loadHomeInsightFan({ host, reducedMotion: true });

    fan._openHomeInsightFan(richHomePayload());
    const overlay = host.querySelector('.home-fan-overlay');
    expect(overlay.className.split(/\s+/)).toContain('home-fan-reduced');
    expect(overlay.className.split(/\s+/)).not.toContain('home-fan-spring');
    expect(overlay.querySelectorAll('.home-fan-card')).toHaveLength(1);
    const css = readFileSync(join(import.meta.dir, '../tidal_dl/gui/static/style.css'), 'utf8');
    expect(css).toContain('.home-fan-overlay');
    expect(css).toContain('.home-fan-reduced');
    expect(css).toContain('home-fan-spring-in');
    expect(css).toContain('.home-fan-facts');
    expect(css).toContain('.home-fan-fact');

    overlay.click();
    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(0);

    fan._openHomeInsightFan(richHomePayload());
    host.querySelector('.home-fan-back').click();
    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(0);
  });

  test('chevrons rotate the centered insight', () => {
    const host = clickableNode('main');
    const fan = loadHomeInsightFan({ host, reducedMotion: true });
    fan._openHomeInsightFan(richHomePayload());
    const before = host.querySelector('.is-center').textContent;
    fan._cycleHomeInsightFan(1);
    expect(host.querySelector('.is-center').textContent).not.toBe(before);
  });

  test('spring mode fans visible cards instead of a single static center', () => {
    const host = clickableNode('main');
    const fan = loadHomeInsightFan({ host, reducedMotion: false });
    fan._openHomeInsightFan(richHomePayload());
    const overlay = host.querySelector('.home-fan-overlay');
    expect(overlay.className.split(/\s+/)).toContain('home-fan-spring');
    expect(overlay.querySelectorAll('.home-fan-card').length).toBeGreaterThan(1);
    expect(overlay.querySelectorAll('.home-fan-card').length).toBeLessThanOrEqual(7);
  });

  test('Escape dismisses the open fan', () => {
    const host = clickableNode('main');
    const fan = loadHomeInsightFan({ host, reducedMotion: true });
    fan._openHomeInsightFan(richHomePayload());
    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(1);

    fan.dispatchKey('Escape');
    expect(host.querySelectorAll('.home-fan-overlay')).toHaveLength(0);
  });
});

function loadArtistTileWithClicks(navigate) {
  const helperSource = viewsSource.match(
    /function _artistTile\(artist, hero\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('artist tile helper not found');
  return new Function(
    'h',
    'textEl',
    'navigate',
    'a11yClick',
    'fetch',
    `${helperSource[0]}\nreturn _artistTile;`,
  )(
    clickableH,
    clickableTextEl,
    navigate,
    (el) => { el.setAttribute('tabindex', '0'); el.setAttribute('role', 'button'); },
    () => Promise.resolve({ json: async () => ({}) }),
  )({ name: 'Tetrarch', play_count: 40, album_count: 2, track_count: 9 }, true);
}
