const { describe, expect, test, beforeEach } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const apiSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/api.js'),
  'utf8',
);
const viewsSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/views.js'),
  'utf8',
);
const playerSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/player.js'),
  'utf8',
);
const cssSource = readFileSync(
  join(import.meta.dir, '../tidal_dl/gui/static/style.css'),
  'utf8',
);

function createNode(tag) {
  const attrs = {};
  const node = {
    tag,
    className: '',
    children: [],
    parentNode: null,
    style: {},
    attrs,
    appendChild(child) {
      if (typeof child === 'string') {
        const text = createNode('#text');
        text._text = child;
        child = text;
      }
      child.parentNode = node;
      node.children.push(child);
      return child;
    },
    setAttribute(name, value) { attrs[name] = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
    set textContent(value) { this._text = String(value); this.children = []; },
    get textContent() {
      return (this._text || '') + this.children.map(child => child.textContent).join('');
    },
  };
  return node;
}

function createH() {
  const h = (tag, props = {}, ...children) => {
    const node = createNode(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (key === 'className') node.className = value;
      else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
      else node.setAttribute(key, value);
    }
    children.forEach(child => {
      if (child) node.appendChild(child);
    });
    return node;
  };
  const textEl = (tag, value, className) => h(tag, { className }, value);
  return { h, textEl };
}

function loadShortcutHelpers() {
  const start = apiSource.indexOf('let _shortcutPlatformCache = null;');
  const end = apiSource.indexOf('// ---- SHORTCUTS HELP OVERLAY ----');
  const block = start >= 0 && end > start ? apiSource.slice(start, end) : '';
  if (!block.includes('function _renderShortcutStrip')) {
    throw new Error('shortcut keycap helpers not found');
  }
  const { h, textEl } = createH();
  return new Function(
    'h',
    'textEl',
    `${block}\nreturn {\n  _normalizeShortcutPlatform,\n  _navigatorShortcutPlatform,\n  _resetShortcutPlatformCache,\n  _resolveShortcutPlatform,\n  _shortcutKeycaps,\n  _playbackShortcutRows,\n  _renderShortcutKeycaps,\n  _renderShortcutStrip,\n};`,
  )(h, textEl);
}

function rowByLabel(strip, label) {
  return strip.children.find(row => (
    row.children[0] && row.children[0].textContent === label
  ));
}

function keycapsOf(row) {
  const keys = row.children[1];
  return keys.children.map(cap => ({
    tag: cap.tag,
    className: cap.className,
    glyph: cap.textContent,
    aria: cap.getAttribute('aria-label'),
  }));
}

describe('shortcut platform detection', () => {
  let helpers;

  beforeEach(() => {
    helpers = loadShortcutHelpers();
    helpers._resetShortcutPlatformCache();
  });

  test('normalizes Tauri and navigator platform strings', () => {
    expect(helpers._normalizeShortcutPlatform('macos')).toBe('mac');
    expect(helpers._normalizeShortcutPlatform('darwin')).toBe('mac');
    expect(helpers._normalizeShortcutPlatform('MacIntel')).toBe('mac');
    expect(helpers._normalizeShortcutPlatform('windows')).toBe('win');
    expect(helpers._normalizeShortcutPlatform('Win32')).toBe('win');
    expect(helpers._normalizeShortcutPlatform('linux')).toBe('linux');
    expect(helpers._normalizeShortcutPlatform('Linux x86_64')).toBe('linux');
  });

  test('reads userAgentData.platform before navigator.platform', () => {
    expect(helpers._navigatorShortcutPlatform({
      userAgentData: { platform: 'macOS' },
      platform: 'Win32',
    })).toBe('mac');
    expect(helpers._navigatorShortcutPlatform({
      platform: 'Win32',
    })).toBe('win');
  });

  test('prefers the Tauri OS API when it is available', async () => {
    const platform = await helpers._resolveShortcutPlatform({
      tauri: { os: { platform: async () => 'macos' } },
      navigator: { platform: 'Win32' },
    });
    expect(platform).toBe('mac');
  });

  test('falls back to plugin:os|platform invoke', async () => {
    const platform = await helpers._resolveShortcutPlatform({
      tauri: { core: { invoke: async (cmd) => {
        expect(cmd).toBe('plugin:os|platform');
        return 'windows';
      } } },
      navigator: { platform: 'MacIntel' },
    });
    expect(platform).toBe('win');
  });

  test('falls back to navigator when Tauri is missing', async () => {
    const platform = await helpers._resolveShortcutPlatform({
      navigator: { userAgentData: { platform: 'Linux' } },
    });
    expect(platform).toBe('linux');
  });
});

describe('shortcut keycaps', () => {
  const helpers = loadShortcutHelpers();

  test('macOS uses symbols and never Cmd/Ctrl', () => {
    const queue = helpers._shortcutKeycaps(['Mod', 'Shift', 'Q'], 'mac');
    expect(queue.map(cap => cap.glyph)).toEqual(['\u2318', '\u21E7', 'Q']);
    expect(queue.map(cap => cap.ariaLabel).join(' ')).toBe('Command Shift Q');
    expect(queue.map(cap => cap.symbol)).toEqual([true, true, false]);
    expect(JSON.stringify(queue)).not.toContain('Cmd/Ctrl');
    expect(JSON.stringify(queue)).not.toContain('Ctrl');
  });

  test('Windows and Linux spell Ctrl and Shift', () => {
    for (const platform of ['win', 'linux']) {
      const queue = helpers._shortcutKeycaps(['Mod', 'Shift', 'Q'], platform);
      expect(queue.map(cap => cap.glyph)).toEqual(['Ctrl', 'Shift', 'Q']);
      expect(queue.map(cap => cap.ariaLabel).join(' ')).toBe('Control Shift Q');
      expect(queue.every(cap => cap.symbol === false)).toBe(true);
      expect(JSON.stringify(queue)).not.toContain('Cmd/Ctrl');
      expect(JSON.stringify(queue)).not.toContain('\u2318');
    }
  });

  test('arrows and Space stay compact on every platform', () => {
    for (const platform of ['mac', 'win', 'linux']) {
      expect(helpers._shortcutKeycaps(['Space'], platform)).toEqual([
        { glyph: 'Space', ariaLabel: 'Space', symbol: false },
      ]);
      expect(helpers._shortcutKeycaps(['ArrowLeft'], platform)).toEqual([
        { glyph: '\u2190', ariaLabel: 'Left arrow', symbol: true },
      ]);
      expect(helpers._shortcutKeycaps(['ArrowRight'], platform)).toEqual([
        { glyph: '\u2192', ariaLabel: 'Right arrow', symbol: true },
      ]);
    }
  });

  test('the settings strip uses sentence-case labels and kbd keycaps', () => {
    const rows = helpers._playbackShortcutRows();
    expect(rows.map(row => row.label)).toEqual([
      'Play / Pause',
      'Back 10s',
      'Forward 10s',
      'Search',
      'Lyrics',
      'Queue',
    ]);

    const strip = helpers._renderShortcutStrip('mac');
    expect(strip.className).toBe('settings-shortcuts');
    expect(strip.children).toHaveLength(6);

    const play = rowByLabel(strip, 'Play / Pause');
    expect(play.children[0].className).toBe('settings-shortcut-label');
    expect(keycapsOf(play)).toEqual([
      { tag: 'kbd', className: 'shortcut-keycap', glyph: 'Space', aria: 'Space' },
    ]);

    const queue = rowByLabel(strip, 'Queue');
    expect(keycapsOf(queue).map(cap => cap.glyph)).toEqual(['\u2318', '\u21E7', 'Q']);
    expect(keycapsOf(queue).map(cap => cap.aria).join(' ')).toBe('Command Shift Q');
    expect(keycapsOf(queue).map(cap => cap.className)).toEqual([
      'shortcut-keycap shortcut-keycap-symbol',
      'shortcut-keycap shortcut-keycap-symbol',
      'shortcut-keycap',
    ]);
  });

  test('Windows strip renders Control Shift Q without overflowing labels', () => {
    const strip = helpers._renderShortcutStrip('win');
    const forward = rowByLabel(strip, 'Forward 10s');
    expect(keycapsOf(forward).map(cap => cap.glyph)).toEqual(['\u2192']);
    const queue = rowByLabel(strip, 'Queue');
    expect(keycapsOf(queue).map(cap => cap.glyph)).toEqual(['Ctrl', 'Shift', 'Q']);
    expect(queue.children[0].textContent).toBe('Queue');
  });
});

describe('shortcut display source', () => {
  test('GUI JS never shows Cmd/Ctrl and keeps shortcut behavior', () => {
    const js = apiSource + viewsSource + playerSource;
    expect(js).not.toContain('Cmd/Ctrl');
    expect(js).not.toContain('After ·');
    expect(js).not.toContain('Before ·');
    expect(playerSource).toContain('metaKey || e.ctrlKey');
    expect(js).toContain('_renderShortcutStrip');
    expect(js).toContain('shortcut-keycap');
    expect(viewsSource).toContain('_renderShortcutStrip(');
  });

  test('settings strip CSS is a 3-or-6 grid with readable keycaps', () => {
    expect(cssSource).toContain('grid-template-columns: repeat(3, minmax(0, 1fr))');
    expect(cssSource).toContain('grid-template-columns: repeat(6, minmax(0, 1fr))');
    expect(cssSource).toContain('@media (min-width: 1680px)');
    expect(cssSource).toContain('.settings-shortcut-label');
    expect(cssSource).toContain('white-space: nowrap');
    expect(cssSource).toContain('text-overflow: ellipsis');
    expect(cssSource).toContain('.shortcut-keycap');
    expect(cssSource).toContain('.shortcut-keycap-symbol');
    expect(cssSource).toMatch(/\.shortcut-keycap[\s\S]*color: var\(--text\)/);
    expect(cssSource).toMatch(/\.shortcut-keycap[\s\S]*min-width: 28px/);
    expect(cssSource).toMatch(/\.shortcut-keycap[\s\S]*height: 28px/);
    expect(cssSource).toMatch(/\.shortcut-keycap-symbol[\s\S]*font-size: 15px/);
    expect(cssSource).toMatch(/\.shortcut-keycap[\s\S]*box-shadow/);
    expect(cssSource).toContain('prefers-reduced-motion');
  });

  test('overlay keycaps do not share the shortcuts-card fill', () => {
    expect(cssSource).toMatch(/\.shortcuts-card\s*\{[^}]*background:\s*var\(--bg-warm\)/);
    expect(cssSource).toMatch(/\.shortcut-keycap\s*\{[^}]*background:\s*var\(--bg-warm\)/);
    const overlay = cssSource.match(/\.shortcuts-card\s+\.shortcut-keycap\s*\{([^}]+)\}/);
    expect(overlay).toBeTruthy();
    expect(overlay[1]).toMatch(/background:\s*var\(--surface-active\)/);
    expect(overlay[1]).not.toMatch(/--bg-warm/);
    expect(apiSource).toContain('_renderShortcutKeycaps(row.keys, platform)');
  });
});
