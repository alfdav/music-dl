const { describe, expect, test } = require('bun:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const staticDir = join(import.meta.dir, '../tidal_dl/gui/static');
const apiSource = readFileSync(join(staticDir, 'api.js'), 'utf8');
const playerSource = readFileSync(join(staticDir, 'player.js'), 'utf8');
const viewsSource = readFileSync(join(staticDir, 'views.js'), 'utf8');

function loadQualityTier() {
  const source = apiSource.match(
    /function _qualityTier\(q, fmt, codec\) \{[\s\S]*?\n\}\n\nfunction qualityClass/,
  );
  if (!source) throw new Error('Codec-aware quality helper not found');
  return new Function(`${source[0].replace('\n\nfunction qualityClass', '')}\nreturn _qualityTier;`)();
}

describe('local codec quality decisions', () => {
  test('AAC and ALAC in the same M4A container remain distinct', () => {
    const tier = loadQualityTier();

    expect(tier('44100Hz/16bit', 'M4A', 'aac').tier).toBe('Lossy');
    expect(tier('44100Hz/16bit', 'M4A', 'alac').tier).toBe('Lossless');
  });

  test('unknown M4A codec is not guessed from container or bit depth', () => {
    const unknown = loadQualityTier()('44100Hz/16bit', 'M4A', null);
    expect(unknown.tier).toBe('Unknown');
    expect(unknown.desc).not.toMatch(/Lossless|16-bit/);
    expect(unknown.desc).not.toBe('44100Hz/16bit');
  });

  test('Hz/bit is never CD lossless for AAC', () => {
    const aac = loadQualityTier()('44100Hz/16bit', 'M4A', 'aac');
    expect(aac.tier).toBe('Lossy');
    expect(aac.desc).not.toMatch(/Lossless|16-bit|44100Hz\/16bit/);
  });

  test('persisted AAC quality stays Lossy even when codec is omitted', () => {
    expect(loadQualityTier()('AAC', 'M4A', null).tier).toBe('Lossy');
  });

  test('track table and Now Playing pass the same persisted facts', () => {
    const args = 'track.quality, track.format, track.codec';

    expect(viewsSource).toContain(`qualityLabel(${args})`);
    expect(viewsSource).toContain(`qualityClass(${args})`);
    expect(viewsSource).toContain(`qualityTitle(${args})`);
    expect(playerSource).toContain(`qualityLabel(${args})`);
    expect(playerSource).toContain(`qualityClass(${args})`);
    expect(playerSource).toContain(`qualityTitle(${args})`);
  });

  test('local upgrade ranking never drops the persisted codec fact', () => {
    const missingCodec = /qualityRank\((\w+)\.quality, \1\.format\)/;

    expect(apiSource).not.toMatch(missingCodec);
    expect(viewsSource).not.toMatch(missingCodec);
    expect(apiSource).toContain('qualityRank(track.quality, track.format, track.codec)');
    expect(viewsSource).toContain('qualityRank(mt.quality, mt.format, mt.codec)');
  });
});
