const STATIC_VIEWS = new Set([
  'home',
  'search',
  'library',
  'recent-added',
  'recent',
  'playlists',
  'favorites',
  'downloads',
  'settings',
  'djai',
  'upgrades',
]);

function _encodeSegment(value) {
  return encodeURIComponent(String(value ?? ''));
}

function buildArtistView(name, tidalId) {
  const base = `artist:${_encodeSegment(name)}`;
  const id = String(tidalId ?? '').trim();
  return /^[0-9]+$/.test(id) ? `${base}:${id}` : base;
}

function parseArtistView(view) {
  const raw = typeof view === 'string' ? view.trim() : '';
  if (!raw.startsWith('artist:')) return { name: '', tidalId: '' };
  const rest = raw.slice(7);
  const parts = rest.split(':');
  const last = parts[parts.length - 1] || '';
  if (parts.length > 1 && /^[0-9]+$/.test(last)) {
    return {
      name: decodeURIComponent(parts.slice(0, -1).join(':')),
      tidalId: last,
    };
  }
  return { name: decodeURIComponent(rest), tidalId: '' };
}

function buildAlbumView(albumId) {
  const id = String(albumId ?? '').trim();
  return /^[0-9]+$/.test(id) ? `album:${id}` : 'home';
}

function buildLocalAlbumView(artistName, albumName) {
  return `localalbum:${_encodeSegment(artistName)}:${_encodeSegment(albumName)}`;
}

function buildLocalReleaseView(releaseId) {
  const hash = String(releaseId ?? '').replace(/^release:/, '');
  return /^[a-f0-9]{6,64}$/.test(hash) ? `localrelease:${hash}` : 'library';
}

function normalizeView(view) {
  const raw = typeof view === 'string' ? view.trim() : '';
  if (!raw) return 'home';
  if (STATIC_VIEWS.has(raw)) return raw;
  if (/^artist:[^/?#]+$/.test(raw)) return raw;
  if (/^album:[0-9]+$/.test(raw)) return raw;
  if (/^localalbum:[^:#/?]+:[^:#/?]+$/.test(raw)) return raw;
  if (/^localrelease:[a-f0-9]{6,64}$/.test(raw)) return raw;
  return 'home';
}

function normalizeLaunchView(value) {
  const raw = typeof value === 'string' ? value.trim() : '';
  if (!raw) return 'home';

  try {
    const url = new URL(raw);
    if (url.protocol !== 'music-dl:') return 'home';
    const fromHash = url.hash.startsWith('#') ? url.hash.slice(1) : '';
    return normalizeView(fromHash || url.searchParams.get('view') || '');
  } catch (_) {
    return normalizeView(raw);
  }
}

const exported = {
  buildAlbumView,
  buildArtistView,
  buildLocalAlbumView,
  buildLocalReleaseView,
  normalizeLaunchView,
  normalizeView,
  parseArtistView,
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = exported;
}

if (typeof globalThis !== 'undefined') {
  Object.assign(globalThis, exported);
}
