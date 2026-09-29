const { describe, expect, test } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const viewsSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/views.js'),
  'utf8',
);

const ROW_PX = 66;

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
    toggle(name, force) {
      if (force === true) this.add(name);
      else if (force === false) this.remove(name);
      else if (this.contains(name)) this.remove(name);
      else this.add(name);
    },
    contains(name) {
      return String(node.className || '').split(/\s+/).includes(name);
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
    _listeners: {},
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
    addEventListener(type, fn) {
      (node._listeners[type] ||= []).push(fn);
    },
    removeEventListener(type, fn) {
      node._listeners[type] = (node._listeners[type] || []).filter(existing => existing !== fn);
    },
    click() {
      (node._listeners.click || []).forEach(fn => fn({}));
    },
    focus() {},
    setAttribute() {},
    set textContent(value) {
      this._text = String(value);
      this.children = [];
      if (node._onText) node._onText(this._text);
    },
    get textContent() {
      return (this._text || '') + this.children.map(child => child.textContent).join('');
    },
    get firstChild() { return node.children[0] || null; },
  };
  node.classList = classListFor(node);
  return node;
}

function createH(onText) {
  const h = (tag, props = {}, ...children) => {
    const node = createNode(tag);
    const propsCopy = { ...props };
    const text = propsCopy.textContent;
    delete propsCopy.textContent;
    Object.assign(node, propsCopy);
    if (!node.classList || typeof node.classList.add !== 'function') {
      node.classList = classListFor(node);
    }
    if (text != null) {
      if (onText && String(node.className || '').includes('album-detail-sub')) {
        node._onText = onText;
      }
      node.textContent = text;
    }
    children.forEach(child => {
      if (typeof child === 'string' || typeof child === 'number') {
        const textNode = createNode('#text');
        textNode.textContent = String(child);
        node.appendChild(textNode);
      } else if (child) {
        node.appendChild(child);
      }
    });
    return node;
  };
  const textEl = (tag, value, className) => h(tag, { className, textContent: value });
  return { h, textEl };
}

function sliceBetween(source, startMark, endMark) {
  const start = source.indexOf(startMark);
  const end = source.indexOf(endMark, start + startMark.length);
  if (start < 0 || end < start) throw new Error('missing slice ' + startMark);
  return source.slice(start, end);
}

function loadPlaylistUi(hooks) {
  const nav = sliceBetween(viewsSource, 'function _isTopLevelView(view)', '// ---- /NAV STACK ----');
  const navAndNavigate = sliceBetween(
    viewsSource,
    'function _navBackControl()',
    'navItems.forEach(n => {\n  n.addEventListener',
  );
  const playlist = sliceBetween(
    viewsSource,
    'const PLAYLIST_PAGE_SIZE = 50;',
    '// ---- DOWNLOAD TRIGGER ----',
  );
  const { h, textEl } = createH(hooks.onCountText);
  const viewEl = createNode('div');
  viewEl.id = 'view';
  viewEl.isConnected = true;
  viewEl.scrollTop = 0;
  viewEl.scrollHeight = 4000;
  viewEl.clientHeight = 800;
  const state = {
    view: '',
    queue: [],
    queueOriginal: [],
    queueIndex: 0,
    shuffle: false,
    playing: false,
  };
  const queues = new Map();
  function api(url) {
    const match = String(url).match(/\/playlists\/([^/]+)\/tracks\?[\s\S]*offset=(\d+)/);
    if (!match) return Promise.resolve({});
    const key = decodeURIComponent(match[1]) + ':' + match[2];
    let resolve;
    const promise = new Promise(res => { resolve = res; });
    if (!queues.has(key)) queues.set(key, []);
    queues.get(key).push(resolve);
    return promise;
  }
  function fulfill(id, offset, total, count) {
    const key = id + ':' + offset;
    const pending = queues.get(key) || [];
    const resolve = pending.shift();
    if (!resolve) throw new Error('no waiter for ' + key);
    const tracks = [];
    for (let i = 0; i < count; i++) {
      tracks.push({
        id: id + '-' + (offset + i),
        name: 'Track ' + (offset + i),
        artist: 'Artist',
        album: 'Album',
        duration: 180,
      });
    }
    resolve({ tracks, total, offset });
  }
  const btnShuffle = createNode('button');
  const location = { hash: '' };
  const document = {
    getElementById(id) { return id === 'view' ? viewEl : null; },
    querySelector() { return null; },
    addEventListener() {},
    removeEventListener() {},
  };
  const noop = () => {};
  const ui = new Function(
    'h', 'textEl', 'svgIcon', 'ICONS', 'document', 'location', 'state', 'viewEl', 'navItems',
    'api', 'toast', 'btnShuffle', 'queuePanel', 'renderTrackHeader', 'renderTrackRow', 'breadcrumb',
    'artGradient', '_cloneQueueTrack', '_saveQueue', 'renderQueue', '_setQueueOrder', 'playTrack',
    '_scanPlaylistUpgrades', '_checkErrorBanners', '_closeHomeInsightFan', 'normalizeView',
    'renderHome', 'renderSearch', 'renderLibrary', 'renderRecentlyPlayed', 'renderPlaylists',
    'renderFavorites', 'renderDownloads', 'renderSettings', 'renderDjai', 'renderUpgradeScanner',
    'renderLocalAlbumDetail', 'renderLocalReleaseDetail', 'renderArtistGallery', 'renderAlbumDetail',
    'renderPlaceholder', 'parseArtistView',
    `function requestAnimationFrame() { return 0; }
let librarySort = 'artist';
let libraryQuery = '';
let _lastNavHash = '';
const _viewState = {};
const _navStack = [];
const _playlistMeta = {};
let _queueEntrySeq = 0;
${nav}
${navAndNavigate}
${playlist}
return {
  navigate, playlistViewKey, _rememberPlaylist, _viewState, _playlistMeta,
  PLAYLIST_VIRTUAL_ROW_PX, PLAYLIST_VIRTUAL_THRESHOLD,
  fillTotal: () => _playlistFillTotal,
};
`,
  )(
    h, textEl, () => createNode('svg'), { back: '' }, document, location, state, viewEl, [],
    api, noop, btnShuffle, hooks.queuePanel, 
    () => h('div', { className: 'track-header' }),
    () => h('div', { className: 'track' }),
    () => h('nav', { className: 'breadcrumb' }),
    () => 'grad',
    (track, id) => ({ ...track, _queueEntryId: id }),
    noop,
    hooks.renderQueue || noop,
    noop,
    noop,
    noop,
    noop,
    noop,
    (view) => view || 'home',
    noop, noop, noop, noop, noop, noop, noop, noop, noop, noop,
    noop, noop, noop, noop, noop,
  );
  return {
    ...ui,
    state,
    viewEl,
    fulfill,
    pending(id, offset) { return ((queues.get(id + ':' + offset) || []).length); },
  };
}

function spacerPx(viewEl) {
  const spacer = viewEl.querySelector('.tracks-virtual-spacer');
  if (!spacer || spacer.style.height == null) return null;
  return Number(String(spacer.style.height).replace('px', ''));
}

async function flush() {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

function openKnownPlaylist(ui, id, total) {
  ui.navigate(ui.playlistViewKey(ui._rememberPlaylist({
    id,
    name: id,
    num_tracks: total,
  })));
}

describe('playlist known count is per playlist', () => {
  test('a known playlist length sizes the spacer before the first page', async () => {
    const ui = loadPlaylistUi({});
    openKnownPlaylist(ui, 'only', 555);
    expect(ui.PLAYLIST_VIRTUAL_ROW_PX).toBe(ROW_PX);
    expect(spacerPx(ui.viewEl)).toBe(555 * ROW_PX);
    ui.fulfill('only', 0, 555, 50);
    await flush();
    ui.navigate('playlists');
    ui.navigate(null, { back: true });
    expect(ui.pending('only', 0)).toBe(1);
    expect(spacerPx(ui.viewEl)).toBe(555 * ROW_PX);
  });

  test('a playing playlist does not size the playlist you leave', async () => {
    const aTotal = 555;
    const bTotal = 120;
    let ui;
    let left = false;
    ui = loadPlaylistUi({
      queuePanel: { classList: { contains: () => true } },
      renderQueue() {
        if (ui.openedB) return;
        ui.openedB = true;
        openKnownPlaylist(ui, 'b', bTotal);
      },
      onCountText(value) {
        if (left) return;
        if (!ui || ui.state.view !== 'playlist:b') return;
        if (value !== aTotal + ' tracks') return;
        left = true;
        ui.navigate('playlists');
      },
    });
    openKnownPlaylist(ui, 'a', aTotal);
    expect(spacerPx(ui.viewEl)).toBe(aTotal * ROW_PX);
    ui.fulfill('a', 0, aTotal, 50);
    await flush();
    expect(ui.pending('a', 50)).toBe(1);
    ui.viewEl.querySelector('.album-play-btn').click();
    ui.fulfill('a', 50, aTotal, 50);
    await flush();
    expect(ui.fillTotal()).toBe(aTotal);
    if (ui.pending('b', 0)) {
      ui.fulfill('b', 0, bTotal, 50);
      await flush();
    }
    expect(ui.fillTotal()).toBe(aTotal);
    ui.navigate(null, { back: true });
    expect(ui.pending('b', 0)).toBeGreaterThan(0);
    expect(spacerPx(ui.viewEl)).toBe(bTotal * ROW_PX);
  });

  test('a smaller playing playlist does not shrink the other spacer', async () => {
    const aTotal = 120;
    const bTotal = 555;
    let ui;
    let left = false;
    ui = loadPlaylistUi({
      queuePanel: { classList: { contains: () => true } },
      renderQueue() {
        if (ui.openedB) return;
        ui.openedB = true;
        openKnownPlaylist(ui, 'b', bTotal);
      },
      onCountText(value) {
        if (left) return;
        if (!ui || ui.state.view !== 'playlist:b') return;
        if (value !== aTotal + ' tracks') return;
        left = true;
        ui.navigate('playlists');
      },
    });
    openKnownPlaylist(ui, 'a', aTotal);
    ui.fulfill('a', 0, aTotal, 50);
    await flush();
    ui.viewEl.querySelector('.album-play-btn').click();
    ui.fulfill('a', 50, aTotal, 50);
    await flush();
    expect(ui.fillTotal()).toBe(aTotal);
    const remembered = ui._playlistMeta.b;
    remembered.num_tracks = 0;
    ui.navigate(null, { back: true });
    expect(ui.pending('b', 0)).toBeGreaterThan(0);
    expect(spacerPx(ui.viewEl)).toBe(bTotal * ROW_PX);
  });
});
