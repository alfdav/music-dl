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

function buildArtistView(name) {
  return `artist:${_encodeSegment(name)}`;
}

function buildAlbumView(albumId) {
  const id = String(albumId ?? '').trim();
  return /^[0-9]+$/.test(id) ? `album:${id}` : 'home';
}

function buildLocalAlbumView(artistName, albumName) {
  return `localalbum:${_encodeSegment(artistName)}:${_encodeSegment(albumName)}`;
}

function normalizeView(view) {
  const raw = typeof view === 'string' ? view.trim() : '';
  if (!raw) return 'home';
  if (STATIC_VIEWS.has(raw)) return raw;
  if (/^artist:[^/?#]+$/.test(raw)) return raw;
  if (/^album:[0-9]+$/.test(raw)) return raw;
  if (/^localalbum:[^:#/?]+:[^:#/?]+$/.test(raw)) return raw;
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
  normalizeLaunchView,
  normalizeView,
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = exported;
}

if (typeof globalThis !== 'undefined') {
  Object.assign(globalThis, exported);
}
