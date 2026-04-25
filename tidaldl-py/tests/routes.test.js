const { describe, expect, test } = require('bun:test');
const {
  buildAlbumView,
  buildArtistView,
  buildLocalAlbumView,
  normalizeLaunchView,
  normalizeView,
} = require('../tidal_dl/gui/static/routes.js');

describe('routes', () => {
  test('keeps known static views', () => {
    expect(normalizeView('library')).toBe('library');
    expect(normalizeView('settings')).toBe('settings');
  });

  test('keeps encoded deep links', () => {
    expect(normalizeView(buildArtistView('AC/DC'))).toBe('artist:AC%2FDC');
    expect(normalizeView(buildLocalAlbumView('A Tribe Called Quest', 'Midnight Marauders'))).toBe(
      'localalbum:A%20Tribe%20Called%20Quest:Midnight%20Marauders',
    );
    expect(normalizeView(buildAlbumView(12345))).toBe('album:12345');
  });

  test('falls back to home for invalid or external-looking values', () => {
    expect(normalizeView('https://evil.example')).toBe('home');
    expect(normalizeView('artist:../../etc/passwd')).toBe('home');
    expect(normalizeView('localalbum:ok:bad/path')).toBe('home');
    expect(normalizeView('album:not-a-number')).toBe('home');
    expect(normalizeView('')).toBe('home');
  });

  test('normalizes desktop launch URLs into internal views', () => {
    expect(normalizeLaunchView('music-dl://open#library')).toBe('library');
    expect(normalizeLaunchView('music-dl://open#artist:AC%2FDC')).toBe('artist:AC%2FDC');
    expect(normalizeLaunchView('music-dl://open?view=album:12345')).toBe('album:12345');
  });

  test('rejects unsafe desktop launch URLs', () => {
    expect(normalizeLaunchView('https://evil.example/#library')).toBe('home');
    expect(normalizeLaunchView('music-dl://open#artist:../../etc/passwd')).toBe('home');
    expect(normalizeLaunchView('music-dl://open?view=https://evil.example')).toBe('home');
    expect(normalizeLaunchView('not a url')).toBe('home');
  });
});
