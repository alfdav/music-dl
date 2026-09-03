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
const LINE_STEP = LINE_H + 36;

const VIEWPORT_PROFILES = [
  { label: '700x1400 narrow', height: 1281, width: 380 },
  { label: '1100 normal', height: 620, width: 700 },
  { label: '1280 normal', height: 620, width: 780 },
  { label: '1440 normal', height: 620, width: 780 },
];

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
    /function _lyricsScrollTarget\(lineOffsetTop, lineHeight, viewportHeight, contentHeight\) \{[\s\S]*?\nfunction _lyricsReflowAttachedViewport\(state, viewport, list, lineEls, lines, currentTimeMs, reduceMotion, schedule\) \{[\s\S]*?\n\}/,
  );
  if (!helperSource) throw new Error('lyrics helpers not found');
  return new Function(
    `${helperSource[0]}\nreturn {`
    + ' _lyricsScrollTarget, _lyricsEdgeSpacerPx, _lyricsApplyListSpacer, _lyricsScrollBehavior,'
    + ' _lyricsUserScrollKey, _lyricsSyncButtonVisible, _lyricsDetachFollow, _lyricsAttachFollow,'
    + ' _lyricsMarkUserScrollIntent, _lyricsOnViewportScroll, _lyricsWriteScrollTop,'
    + ' _lyricsLineCenterError, _lyricsFollowActiveLine, _lyricsResyncFollow,'
    + ' _lyricsReadingAnchor, _lyricsRestoreReadingAnchor, _lyricsAfterLayout,'
    + ' _lyricsReflowViewport, _lyricsReflowAttachedViewport,'
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
    lyricsProgrammaticGen: 0,
    lyricsUserScrollPending: false,
    lyricsFollowScrollTop: null,
    lyricsReflowScheduled: false,
    lyricsPanelState: 'synced',
    ...overrides,
  };
}

function makeFrameScheduler() {
  const frames = [];
  const schedule = (cb) => { frames.push(cb); };
  schedule.flushOne = () => {
    const cb = frames.shift();
    if (cb) cb();
  };
  schedule.flush = (n = 2) => {
    for (let i = 0; i < n; i++) schedule.flushOne();
  };
  schedule.pending = () => frames.length;
  return schedule;
}

function fakeLine(offsetTop, offsetHeight) {
  const classList = makeClassList();
  return { offsetTop, offsetHeight, classList };
}

function fakeList(lineHeight = LINE_H) {
  return {
    style: {},
    firstElementChild: {
      offsetHeight: lineHeight,
      getBoundingClientRect: () => ({ height: lineHeight }),
    },
  };
}

function fakeViewport(scrollTop = 0, clientHeight = VIEWPORT_H, scrollHeight = CONTENT_H) {
  return {
    clientHeight,
    scrollHeight,
    scrollTop,
    scrollCalls: [],
    scrollTo(opts) {
      this.scrollCalls.push(opts);
      this.scrollTop = opts.top;
    },
  };
}

function fakeViewportInFlight(scrollTop = 0, clientHeight = VIEWPORT_H, scrollHeight = CONTENT_H) {
  return {
    clientHeight,
    scrollHeight,
    scrollTop,
    scrollCalls: [],
    scrollTo(opts) {
      this.scrollCalls.push(opts);
    },
  };
}

function lineOffset(index) {
  const last = CONTENT_H - LINE_H;
  return LINE0_TOP + (index / (LINE_COUNT - 1)) * (last - LINE0_TOP);
}

function modelLineLayout(viewportHeight) {
  const { _lyricsEdgeSpacerPx, _lyricsScrollTarget } = loadLyricsHelpers();
  const pad = _lyricsEdgeSpacerPx(viewportHeight, LINE_H);
  const firstTop = pad;
  const lastTop = pad + (LINE_COUNT - 1) * LINE_STEP;
  const contentHeight = pad + LINE_COUNT * LINE_H + (LINE_COUNT - 1) * 36 + pad;
  return { pad, firstTop, lastTop, contentHeight, _lyricsScrollTarget };
}

function expectLineVisible(scrollTop, lineTop, viewportHeight) {
  expect(lineTop).toBeGreaterThanOrEqual(scrollTop);
  expect(lineTop).toBeLessThanOrEqual(scrollTop + viewportHeight);
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
      expectLineVisible(scrollTop, top, VIEWPORT_H);
    }
  });
});

describe('lyrics edge spacer', () => {
  test('uses viewport height, not panel width, for end padding', () => {
    const { _lyricsEdgeSpacerPx } = loadLyricsHelpers();
    const narrowTallPad = _lyricsEdgeSpacerPx(1281, LINE_H);
    const widthRelativeWrong = 380 * 0.5;

    expect(narrowTallPad).toBeCloseTo(603.75, 1);
    expect(narrowTallPad).toBeGreaterThan(600);
    expect(narrowTallPad).not.toBeCloseTo(widthRelativeWrong, 0);
    expect(cssSource).not.toMatch(/\.lyrics-synced-list[\s\S]*padding-block:\s*50%/);
    expect(playerSource).toContain('_lyricsApplyListSpacer');
    expect(playerSource).toContain('_lyricsEdgeSpacerPx');
  });

  test('centers first and last lines across narrow/tall and normal widths', () => {
    for (const profile of VIEWPORT_PROFILES) {
      const { pad, firstTop, lastTop, contentHeight, _lyricsScrollTarget } = modelLineLayout(profile.height);
      const firstScroll = _lyricsScrollTarget(firstTop, LINE_H, profile.height, contentHeight);
      const lastScroll = _lyricsScrollTarget(lastTop, LINE_H, profile.height, contentHeight);

      expect(pad).toBeCloseTo((profile.height - LINE_H) / 2, 1);
      expect(firstScroll).toBe(0);
      expectLineVisible(firstScroll, firstTop, profile.height);
      expectLineVisible(lastScroll, lastTop, profile.height);
      expect(lastScroll).toBe(contentHeight - profile.height);
    }
  });

  test('writes height-relative padding on the list at runtime', () => {
    const { _lyricsApplyListSpacer } = loadLyricsHelpers();
    const viewport = fakeViewport(0, 1281);
    const list = fakeList();

    const pad = _lyricsApplyListSpacer(viewport, list);

    expect(pad).toBeCloseTo(603.75, 1);
    expect(list.style.paddingTop).toBe(`${pad}px`);
    expect(list.style.paddingBottom).toBe(`${pad}px`);
  });
});

describe('lyrics follow / detach state machine', () => {
  test('user wheel detaches follow immediately', () => {
    expect(playerSource).toMatch(/addEventListener\('wheel'[\s\S]*?detachFromUser/);
    expect(playerSource).toMatch(/function _bindLyricsViewport[\s\S]*?_lyricsDetachFollow/);
    const { _lyricsDetachFollow } = loadLyricsHelpers();
    const state = makeState();
    _lyricsDetachFollow(state);
    expect(state.lyricsFollow).toBe(false);
  });

  test('keyboard scroll intent detaches on the next scroll event', () => {
    const { _lyricsMarkUserScrollIntent, _lyricsOnViewportScroll, _lyricsUserScrollKey } = loadLyricsHelpers();
    const state = makeState();
    const viewport = fakeViewport(10);

    expect(_lyricsUserScrollKey('ArrowUp')).toBe(true);
    expect(_lyricsUserScrollKey('Escape')).toBe(false);

    _lyricsMarkUserScrollIntent(state);
    _lyricsOnViewportScroll(state, viewport);
    expect(state.lyricsFollow).toBe(false);
  });

  test('layout scroll without user intent does not detach', () => {
    const { _lyricsOnViewportScroll } = loadLyricsHelpers();
    const state = makeState();
    const viewport = fakeViewport(50);

    _lyricsOnViewportScroll(state, viewport);
    expect(state.lyricsFollow).toBe(true);
    expect(state.lyricsProgrammaticGen).toBe(0);
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
    const { _lyricsFollowActiveLine, _lyricsOnViewportScroll } = loadLyricsHelpers();
    const state = makeState();
    const viewport = fakeViewportInFlight(0);
    const activeEl = fakeLine(800, LINE_H);

    _lyricsFollowActiveLine(state, viewport, activeEl, false);
    expect(state.lyricsProgrammaticGen).toBeGreaterThan(0);
    expect(viewport.scrollCalls).toHaveLength(1);

    _lyricsOnViewportScroll(state, viewport);
    expect(state.lyricsFollow).toBe(true);
    expect(state.lyricsProgrammaticGen).toBeGreaterThan(0);
  });

  test('interrupted or no-op smooth scroll stays attached', () => {
    const { _lyricsFollowActiveLine, _lyricsOnViewportScroll, _lyricsScrollTarget } = loadLyricsHelpers();
    const activeEl = fakeLine(800, LINE_H);
    const target = _lyricsScrollTarget(800, LINE_H, VIEWPORT_H, CONTENT_H);
    const noopState = makeState();
    const noopViewport = fakeViewport(target);

    _lyricsFollowActiveLine(noopState, noopViewport, activeEl, false);
    expect(noopState.lyricsFollow).toBe(true);
    expect(noopState.lyricsProgrammaticGen).toBe(0);
    expect(noopViewport.scrollCalls).toEqual([]);

    const interruptedState = makeState();
    const interruptedViewport = fakeViewportInFlight(120);
    interruptedState.lyricsFollowScrollTop = target;
    interruptedState.lyricsProgrammaticGen = 2;

    _lyricsOnViewportScroll(interruptedState, interruptedViewport);
    expect(interruptedState.lyricsFollow).toBe(true);
    expect(interruptedState.lyricsProgrammaticGen).toBe(2);
  });

  test('resize while attached recenters and stays attached', () => {
    const { _lyricsReflowAttachedViewport, _lyricsOnViewportScroll } = loadLyricsHelpers();
    const state = makeState();
    const viewport = fakeViewport(200, 620, CONTENT_H);
    const list = fakeList();
    const lineEls = [fakeLine(309, LINE_H), fakeLine(900, LINE_H)];
    const lines = [
      { start_ms: 0, end_ms: 1000 },
      { start_ms: 1000, end_ms: 2000 },
    ];

    viewport.clientHeight = 1281;
    _lyricsReflowAttachedViewport(state, viewport, list, lineEls, lines, 1500, true);

    expect(state.lyricsFollow).toBe(true);
    expect(list.style.paddingTop).toBeTruthy();
    expect(viewport.scrollCalls.length).toBeGreaterThan(0);

    viewport.scrollTop = 400;
    state.lyricsFollowScrollTop = 500;
    state.lyricsProgrammaticGen = 1;
    _lyricsOnViewportScroll(state, viewport);
    expect(state.lyricsFollow).toBe(true);
  });

  test('attached paused resize recenters the current line within two frames', () => {
    const helpers = loadLyricsHelpers();
    const H0 = 716;
    const H1 = 516;
    const pad0 = helpers._lyricsEdgeSpacerPx(H0, LINE_H);
    const pad1 = helpers._lyricsEdgeSpacerPx(H1, LINE_H);
    const index = 10;
    const offset0 = pad0 + index * LINE_STEP;
    const offset1 = pad1 + index * LINE_STEP;
    const content0 = pad0 + 20 * LINE_STEP + pad0;
    const content1 = pad1 + 20 * LINE_STEP + pad1;
    const target0 = helpers._lyricsScrollTarget(offset0, LINE_H, H0, content0);
    const lineEls = Array.from({ length: 20 }, (_, i) => fakeLine(pad0 + i * LINE_STEP, LINE_H));
    const activeEl = lineEls[index];
    const lines = lineEls.map((_, i) => ({ start_ms: i * 10000, end_ms: (i + 1) * 10000 }));
    const currentTimeMs = index * 10000 + 250;
    const state = makeState({ lyricsFollowScrollTop: target0 });
    const viewport = fakeViewport(target0, H1, content1);
    const list = fakeList();
    const schedule = makeFrameScheduler();

    helpers._lyricsReflowViewport(state, viewport, list, lineEls, lines, currentTimeMs, false, schedule);

    lineEls.forEach((el, i) => { el.offsetTop = pad1 + i * LINE_STEP; });
    viewport.scrollTop = target0 - (pad0 - pad1);
    viewport.scrollHeight = content1;

    expect(helpers._lyricsActiveIndexAt(lines, currentTimeMs)).toBe(index);
    expect(Math.abs(helpers._lyricsLineCenterError(viewport, activeEl))).toBeGreaterThan(90);

    expect(schedule.pending()).toBe(1);
    schedule.flushOne();
    expect(schedule.pending()).toBe(1);
    schedule.flushOne();

    expect(helpers._lyricsActiveIndexAt(lines, currentTimeMs)).toBe(index);
    expect(Math.abs(helpers._lyricsLineCenterError(viewport, activeEl))).toBeLessThanOrEqual(2);
    expect(state.lyricsFollow).toBe(true);
  });

  test('attached playing resize recenters the same line without waiting for the next timestamp', () => {
    const helpers = loadLyricsHelpers();
    const H0 = 716;
    const H1 = 516;
    const pad0 = helpers._lyricsEdgeSpacerPx(H0, LINE_H);
    const pad1 = helpers._lyricsEdgeSpacerPx(H1, LINE_H);
    const index = 10;
    const offset0 = pad0 + index * LINE_STEP;
    const content0 = pad0 + 20 * LINE_STEP + pad0;
    const content1 = pad1 + 20 * LINE_STEP + pad1;
    const target0 = helpers._lyricsScrollTarget(offset0, LINE_H, H0, content0);
    const lineEls = Array.from({ length: 20 }, (_, i) => fakeLine(pad0 + i * LINE_STEP, LINE_H));
    const lines = lineEls.map((_, i) => ({ start_ms: i * 10000, end_ms: (i + 1) * 10000 }));
    const t0 = index * 10000 + 100;
    const tLater = t0 + 400;
    const state = makeState({ lyricsFollowScrollTop: target0 });
    const viewport = fakeViewport(target0, H1, content1);
    const schedule = makeFrameScheduler();

    helpers._lyricsReflowViewport(state, viewport, fakeList(), lineEls, lines, t0, false, schedule);
    lineEls.forEach((el, i) => { el.offsetTop = pad1 + i * LINE_STEP; });
    viewport.scrollTop = target0 - (pad0 - pad1);
    schedule.flush(2);

    expect(helpers._lyricsActiveIndexAt(lines, tLater)).toBe(index);
    expect(helpers._lyricsActiveIndexAt(lines, t0)).toBe(index);
    expect(Math.abs(helpers._lyricsLineCenterError(viewport, lineEls[index]))).toBeLessThanOrEqual(2);
    expect(state.lyricsFollow).toBe(true);
  });

  test('cached target skip does not block a drifted scrollTop on the same lyric', () => {
    const helpers = loadLyricsHelpers();
    const H0 = 716;
    const H1 = 516;
    const pad0 = helpers._lyricsEdgeSpacerPx(H0, LINE_H);
    const pad1 = helpers._lyricsEdgeSpacerPx(H1, LINE_H);
    const index = 10;
    const offset1 = pad1 + index * LINE_STEP;
    const content1 = pad1 + 20 * LINE_STEP + pad1;
    const target = helpers._lyricsScrollTarget(offset1, LINE_H, H1, content1);
    const state = makeState({ lyricsFollowScrollTop: target, lyricsProgrammaticGen: 0 });
    const viewport = fakeViewport(target - (pad0 - pad1), H1, content1);
    const activeEl = fakeLine(offset1, LINE_H);

    expect(Math.abs(helpers._lyricsLineCenterError(viewport, activeEl))).toBeGreaterThan(90);
    helpers._lyricsFollowActiveLine(state, viewport, activeEl, true);
    expect(Math.abs(helpers._lyricsLineCenterError(viewport, activeEl))).toBeLessThanOrEqual(2);
  });

  test('detached resize preserves the reading anchor including Safari-like scroll anchoring', () => {
    const helpers = loadLyricsHelpers();
    const H0 = 716;
    const H1 = 516;
    const pad0 = helpers._lyricsEdgeSpacerPx(H0, LINE_H);
    const pad1 = helpers._lyricsEdgeSpacerPx(H1, LINE_H);
    const index = 8;
    const viewOffset = H0 / 2 - LINE_H / 2;
    const lineEls = Array.from({ length: 20 }, (_, i) => fakeLine(pad0 + i * LINE_STEP, LINE_H));
    const lines = lineEls.map((_, i) => ({ start_ms: i * 1000, end_ms: (i + 1) * 1000 }));
    const content1 = pad1 + 20 * LINE_STEP + pad1;
    const state = makeState({ lyricsFollow: false });
    const viewport = fakeViewport(lineEls[index].offsetTop - viewOffset, H0, pad0 + 20 * LINE_STEP + pad0);
    const list = fakeList();
    const schedule = makeFrameScheduler();

    const anchor = helpers._lyricsReadingAnchor(viewport, lineEls);
    expect(anchor.index).toBe(index);
    expect(anchor.viewOffset).toBeCloseTo(viewOffset, 5);

    helpers._lyricsReflowViewport(state, viewport, list, lineEls, lines, 8500, false, schedule);

    lineEls.forEach((el, i) => { el.offsetTop = pad1 + i * LINE_STEP; });
    viewport.clientHeight = H1;
    viewport.scrollHeight = content1;
    viewport.scrollTop += (pad1 - pad0);

    schedule.flush(2);

    expect(state.lyricsFollow).toBe(false);
    expect(helpers._lyricsSyncButtonVisible('synced', state.lyricsFollow)).toBe(true);
    expect(lineEls[index].offsetTop - viewport.scrollTop).toBeCloseTo(viewOffset, 1);
  });

  test('reduced motion selects instant scroll behaviour', () => {
    const { _lyricsScrollBehavior, _lyricsFollowActiveLine } = loadLyricsHelpers();
    expect(_lyricsScrollBehavior(true)).toBe('instant');
    expect(_lyricsScrollBehavior(false)).toBe('smooth');

    const state = makeState();
    const viewport = fakeViewport(0);
    _lyricsFollowActiveLine(state, viewport, fakeLine(800, LINE_H), true);
    expect(viewport.scrollCalls[0].behavior).toBe('instant');
    expect(state.lyricsProgrammaticGen).toBe(0);
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
    expect(cssRule('.lyrics-synced-list')).not.toMatch(/padding-block:\s*50%/);
    expect(cssRule('.lyrics-synced-list')).not.toMatch(/will-change:\s*transform/);
    expect(playerSource).not.toMatch(/lyricsListEl\.style\.transform/);
    expect(playerSource).not.toContain("translateY(0px)");
    expect(playerSource).not.toContain('scrollend');
    expect(playerSource).toContain('ResizeObserver');
    expect(playerSource).toContain('lyricsProgrammaticGen');
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
