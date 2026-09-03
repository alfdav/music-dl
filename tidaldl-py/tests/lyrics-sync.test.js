const { describe, expect, test } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const staticDir = join(import.meta.dir, '../tidal_dl/gui/static');
const playerSource = readFileSync(join(staticDir, 'player.js'), 'utf8');
const cssSource = readFileSync(join(staticDir, 'style.css'), 'utf8');
const htmlSource = readFileSync(join(staticDir, 'index.html'), 'utf8');

const VIEWPORT_H = 620;
const BODY_PADDED_H = 716;
const CONTENT_H = 2757;
const LINE_H = 73.5;
const LINE0_TOP = 18;
const LINE_COUNT = 48;

const PLAYER_BAR_CONTROL_IDS = [
  'now-art',
  'now-title',
  'now-sub',
  'btn-shuffle',
  'btn-prev',
  'btn-play',
  'btn-next',
  'btn-repeat',
  'time-elapsed',
  'progress-bar',
  'time-total',
  'btn-vol',
  'btn-sleep',
  'btn-lyrics',
  'btn-queue',
];

function cssRule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = cssSource.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`CSS rule not found: ${selector}`);
  return match[1];
}

function loadLyricsHelpers() {
  const helperSource = playerSource.match(
    /function _lyricsScrollTarget\(lineOffsetTop, lineHeight, viewportHeight, contentHeight\) \{[\s\S]*?\nfunction _lyricsTickActive\(state, lineEls, lines, currentTimeMs, viewport, reduceMotion\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('lyrics helpers not found');
  return new Function(
    `${helperSource[0]}\nreturn {`
    + ' _lyricsScrollTarget, _lyricsScrollBehavior, _lyricsUserScrollKey,'
    + ' _lyricsSyncButtonVisible, _lyricsDetachFollow, _lyricsAttachFollow,'
    + ' _lyricsOnUserScrollIntent, _lyricsOnViewportScroll,'
    + ' _lyricsBeginProgrammaticScroll, _lyricsEndProgrammaticScroll,'
    + ' _lyricsWriteScrollTop, _lyricsFollowActiveLine, _lyricsResyncFollow,'
    + ' _lyricsApplyActiveClasses, _lyricsActiveIndexAt, _lyricsTickActive'
    + ' };',
  )();
}

function loadSetLyricsPanelOpen(lyricsPanel, documentRef) {
  const helperSource = playerSource.match(
    /function _setLyricsPanelOpen\(open\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('_setLyricsPanelOpen not found');
  return new Function(
    'lyricsPanel',
    'document',
    `${helperSource[0]}\nreturn _setLyricsPanelOpen;`,
  )(lyricsPanel, documentRef);
}

function makeClassList() {
  const classes = new Set();
  return {
    classes,
    toggle(name, on) {
      if (on) classes.add(name);
      else classes.delete(name);
    },
    contains(name) {
      return classes.has(name);
    },
  };
}

function makeState(overrides = {}) {
  return {
    lyricsFollow: true,
    lyricsProgrammaticScroll: false,
    lyricsFollowScrollTop: null,
    lyricsPanelState: 'synced',
    ...overrides,
  };
}

function fakeLine(offsetTop, offsetHeight) {
  const classList = makeClassList();
  return { offsetTop, offsetHeight, classList };
}

function fakeViewport(scrollTop = 0) {
  return {
    clientHeight: VIEWPORT_H,
    scrollHeight: CONTENT_H,
    scrollTop,
    scrollCalls: [],
    scrollTo(opts) {
      this.scrollCalls.push(opts);
      this.scrollTop = opts.top;
    },
  };
}

function lineOffset(index) {
  const last = CONTENT_H - LINE_H;
  return LINE0_TOP + (index / (LINE_COUNT - 1)) * (last - LINE0_TOP);
}

describe('lyrics scroll math', () => {
  test('centers a mid-list line using viewport height', () => {
    const { _lyricsScrollTarget } = loadLyricsHelpers();
    const midTop = lineOffset(22);
    const target = _lyricsScrollTarget(midTop, LINE_H, VIEWPORT_H, CONTENT_H);
    const expected = midTop + (LINE_H / 2) - (VIEWPORT_H / 2);

    expect(target).toBeCloseTo(expected, 5);
    expect(target).toBeGreaterThan(0);
    expect(target).toBeLessThan(CONTENT_H - VIEWPORT_H);
  });

  test('clamps the first lines to 0 and the last lines to max', () => {
    const { _lyricsScrollTarget } = loadLyricsHelpers();
    const max = CONTENT_H - VIEWPORT_H;

    expect(_lyricsScrollTarget(LINE0_TOP, LINE_H, VIEWPORT_H, CONTENT_H)).toBe(0);
    expect(_lyricsScrollTarget(lineOffset(1), LINE_H, VIEWPORT_H, CONTENT_H)).toBe(0);
    expect(_lyricsScrollTarget(CONTENT_H - LINE_H, LINE_H, VIEWPORT_H, CONTENT_H)).toBe(max);
    expect(_lyricsScrollTarget(lineOffset(47), LINE_H, VIEWPORT_H, CONTENT_H)).toBe(max);
  });

  test('RED-GUARD: production uses viewport height, not lyricsBody.clientHeight', () => {
    const { _lyricsScrollTarget } = loadLyricsHelpers();
    const midTop = lineOffset(22);
    const fromViewport = _lyricsScrollTarget(midTop, LINE_H, VIEWPORT_H, CONTENT_H);
    const fromPaddedBody = _lyricsScrollTarget(midTop, LINE_H, BODY_PADDED_H, CONTENT_H);

    expect(fromViewport).not.toBe(fromPaddedBody);
    expect(playerSource).not.toContain('lyricsBody.clientHeight');
    expect(playerSource).toContain('viewport.clientHeight');
    expect(playerSource).toContain('viewport.scrollHeight');
    expect(playerSource).not.toContain(
      'activeEl.offsetTop - ((lyricsBody.clientHeight / 2) - (activeEl.offsetHeight / 2))',
    );
    expect(playerSource).not.toMatch(
      /offsetTop\s*-\s*\(\(.*clientHeight\s*\/\s*2\)\s*-\s*\(.*offsetHeight\s*\/\s*2\)\)/,
    );
  });

  test('keeps every Adele Hello line inside the visible viewport', () => {
    const { _lyricsScrollTarget } = loadLyricsHelpers();

    for (let i = 0; i < LINE_COUNT; i++) {
      const top = lineOffset(i);
      const scrollTop = _lyricsScrollTarget(top, LINE_H, VIEWPORT_H, CONTENT_H);
      expect(top).toBeGreaterThanOrEqual(scrollTop);
      expect(top).toBeLessThanOrEqual(scrollTop + VIEWPORT_H);
    }
  });
});

describe('lyrics follow / detach state machine', () => {
  test('user wheel, touch, and scroll keys detach follow', () => {
    const {
      _lyricsOnUserScrollIntent,
      _lyricsUserScrollKey,
    } = loadLyricsHelpers();
    const state = makeState();

    expect(_lyricsUserScrollKey('ArrowUp')).toBe(true);
    expect(_lyricsUserScrollKey('ArrowDown')).toBe(true);
    expect(_lyricsUserScrollKey('PageUp')).toBe(true);
    expect(_lyricsUserScrollKey('PageDown')).toBe(true);
    expect(_lyricsUserScrollKey('Home')).toBe(true);
    expect(_lyricsUserScrollKey('End')).toBe(true);
    expect(_lyricsUserScrollKey('Escape')).toBe(false);

    _lyricsOnUserScrollIntent(state);
    expect(state.lyricsFollow).toBe(false);
    expect(_lyricsSyncVisibleAfterDetach()).toBe(true);
  });

  test('while detached, a time change updates the active line but not scrollTop', () => {
    const { _lyricsTickActive } = loadLyricsHelpers();
    const state = makeState({ lyricsFollow: false });
    const viewport = fakeViewport(999);
    const lines = [
      { start_ms: 0, end_ms: 1000 },
      { start_ms: 1000, end_ms: 2000 },
    ];
    const lineEls = [fakeLine(18, LINE_H), fakeLine(800, LINE_H)];

    const activeIndex = _lyricsTickActive(state, lineEls, lines, 1500, viewport, false);

    expect(activeIndex).toBe(1);
    expect(lineEls[0].classList.contains('active')).toBe(false);
    expect(lineEls[1].classList.contains('active')).toBe(true);
    expect(viewport.scrollTop).toBe(999);
    expect(viewport.scrollCalls).toEqual([]);
    expect(state.lyricsFollow).toBe(false);
  });

  test('Sync re-centers the current line and re-attaches follow', () => {
    const { _lyricsResyncFollow, _lyricsScrollTarget, _lyricsSyncButtonVisible } = loadLyricsHelpers();
    const state = makeState({ lyricsFollow: false, lyricsFollowScrollTop: 999 });
    const viewport = fakeViewport(999);
    const activeEl = fakeLine(800, LINE_H);
    const expected = _lyricsScrollTarget(800, LINE_H, VIEWPORT_H, CONTENT_H);

    _lyricsResyncFollow(state, viewport, activeEl, false);

    expect(state.lyricsFollow).toBe(true);
    expect(viewport.scrollTop).toBe(expected);
    expect(viewport.scrollCalls[0].behavior).toBe('smooth');
    expect(_lyricsSyncButtonVisible(state.lyricsPanelState, state.lyricsFollow)).toBe(false);
  });

  test('programmatic auto-follow scroll does not self-detach', () => {
    const {
      _lyricsFollowActiveLine,
      _lyricsOnViewportScroll,
    } = loadLyricsHelpers();
    const state = makeState();
    const viewport = fakeViewport(0);
    const activeEl = fakeLine(800, LINE_H);

    _lyricsFollowActiveLine(state, viewport, activeEl, false);
    expect(state.lyricsProgrammaticScroll).toBe(true);
    expect(viewport.scrollCalls).toHaveLength(1);

    _lyricsOnViewportScroll(state);
    expect(state.lyricsFollow).toBe(true);

    _lyricsFollowActiveLine(state, viewport, activeEl, false);
    expect(viewport.scrollCalls).toHaveLength(1);
  });

  test('reduced motion selects instant scroll behaviour', () => {
    const { _lyricsScrollBehavior, _lyricsFollowActiveLine } = loadLyricsHelpers();
    expect(_lyricsScrollBehavior(true)).toBe('instant');
    expect(_lyricsScrollBehavior(false)).toBe('smooth');

    const state = makeState();
    const viewport = fakeViewport(0);
    _lyricsFollowActiveLine(state, viewport, fakeLine(800, LINE_H), true);
    expect(viewport.scrollCalls[0].behavior).toBe('instant');
  });

  test('no active line holds the last scroll position', () => {
    const { _lyricsFollowActiveLine } = loadLyricsHelpers();
    const state = makeState({ lyricsFollowScrollTop: 400 });
    const viewport = fakeViewport(400);

    _lyricsFollowActiveLine(state, viewport, null, false);

    expect(viewport.scrollTop).toBe(400);
    expect(viewport.scrollCalls).toEqual([]);
    expect(state.lyricsFollow).toBe(true);
  });
});

function _lyricsSyncVisibleAfterDetach() {
  const { _lyricsSyncButtonVisible } = loadLyricsHelpers();
  return _lyricsSyncButtonVisible('synced', false);
}

describe('lyrics source and CSS invariants', () => {
  test('style.css no longer hides heart or download when lyrics are open', () => {
    expect(cssSource).not.toMatch(/\.lyrics-open\s+#now-heart/);
    expect(cssSource).not.toMatch(/\.lyrics-open\s+#now-download/);
    expect(cssSource).not.toMatch(/\.lyrics-open[^{]*\{[^}]*display\s*:\s*none/);
  });

  test('player.js no longer blocks the wheel on synced lyrics', () => {
    expect(playerSource).not.toContain("lyricsState.lyricsPanelState === 'synced') e.preventDefault()");
    expect(playerSource).not.toMatch(/lyricsPanelState === 'synced'[\s\S]{0,40}preventDefault/);
  });

  test('player grid items declare min-width 0 and keep equal columns', () => {
    expect(cssRule('.player')).toMatch(/grid-template-columns:\s*1fr 1fr 1fr/);
    expect(cssRule('.now-playing')).toMatch(/min-width:\s*0/);
    expect(cssRule('.transport')).toMatch(/min-width:\s*0/);
    expect(cssRule('.volume-area')).toMatch(/min-width:\s*0/);
  });

  test('index.html contains a real Sync lyrics button', () => {
    expect(htmlSource).toMatch(/<button[^>]*id="lyrics-sync"/);
    expect(htmlSource).toMatch(/id="lyrics-sync"[^>]*type="button"|type="button"[^>]*id="lyrics-sync"/);
    expect(htmlSource).toMatch(/aria-label="Sync lyrics"/);
    expect(htmlSource).toContain('Sync lyrics');
    expect(htmlSource).toMatch(/aria-live="polite"/);
  });

  test('synced viewport is a real scroll container without transform positioning', () => {
    const viewport = cssRule('.lyrics-synced-viewport');
    expect(viewport).toMatch(/overflow-y:\s*auto/);
    expect(viewport).toMatch(/position:\s*relative/);
    expect(viewport).toMatch(/align-items:\s*flex-start/);
    expect(cssRule('.lyrics-synced-list')).toMatch(/padding-block:\s*50%/);
    expect(cssRule('.lyrics-synced-list')).not.toMatch(/will-change:\s*transform/);
    expect(playerSource).not.toMatch(/lyricsListEl\.style\.transform/);
    expect(playerSource).not.toContain("translateY(0px)");
  });
});

describe('player-bar invariance when lyrics open', () => {
  test('static control ids stay in the bar markup', () => {
    for (const id of PLAYER_BAR_CONTROL_IDS) {
      expect(htmlSource).toContain(`id="${id}"`);
    }
    expect(playerSource).toContain("id: 'now-heart'");
    expect(playerSource).toContain("id: 'now-download'");
  });

  test('open and close cycles only toggle the lyrics panel class seam', () => {
    const panel = {
      classList: makeClassList(),
      attrs: {},
      setAttribute(name, value) {
        this.attrs[name] = value;
      },
    };
    const body = { classList: makeClassList() };
    const setOpen = loadSetLyricsPanelOpen(panel, { body });

    setOpen(true);
    setOpen(false);
    setOpen(true);
    setOpen(false);

    expect(panel.classList.contains('open')).toBe(false);
    expect(body.classList.contains('lyrics-open')).toBe(false);
    expect(panel.attrs['aria-hidden']).toBe('true');

    setOpen(true);
    expect(panel.classList.contains('open')).toBe(true);
    expect(body.classList.contains('lyrics-open')).toBe(true);
    expect(panel.attrs['aria-hidden']).toBe('false');

    expect(cssRule('.lyrics-panel')).toMatch(/position:\s*fixed/);
    expect(cssRule('.player')).toMatch(/grid-template-columns:\s*1fr 1fr 1fr/);
    expect(playerSource.match(/function _setLyricsPanelOpen\(open\) \{[\s\S]*?\n\}/)[0])
      .not.toMatch(/now-heart|now-download|display/);
  });
});
