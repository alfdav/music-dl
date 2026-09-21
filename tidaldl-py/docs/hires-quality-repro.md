# Hi-Res quality negotiation — Zeratool / Mac CLI checklist

Issue #188. Shared path: `tidal_dl/download/streams.py` + `tidal_dl/download/quality.py`.
Desktop and CLI both call `_get_stream_info`.

## What the code requests vs what Tidal returns

1. Settings / CLI quality ceiling: `HI_RES_LOSSLESS`.
2. Catalog listing: `audioQuality=LOSSLESS` and `mediaMetadata.tags` often include `HIRES_LOSSLESS`.
3. OAuth `GET /v1/tracks/{id}/playbackinfopostpaywall?audioquality=HI_RES_LOSSLESS&playbackmode=STREAM&assetpresentation=FULL` (Tidal Web client) returns `audioQuality=LOSSLESS`, `bitDepth=16`, `sampleRate=44100`, BTS FLAC. That is not proof the account lacks Hi-Res.
4. Same user token, `GET https://openapi.tidal.com/v2/trackManifests/{id}` with `Accept: application/vnd.api+json` and `formats=FLAC,FLAC_HIRES` returns `attributes.formats` including `FLAC_HIRES` and a DASH rep id `FLAC_HIRES,{rate},{depth}` when Tidal has Hi-Res. Those DASH bytes are Widevine (`cbcs`); this app does not decrypt them.
5. Unencrypted Hi-Res still comes from a live Hi-Fi `/track/?quality=HI_RES_LOSSLESS` host. The parser must take the `FLAC_HIRES` representation, not `representations[0]`.

## Mac / CLI repro (Techmarine on Zeratool)

Do not run Upgrade All. Do not delete `token.json` or start a new OAuth.

```bash
cd tidaldl-py
uv run music-dl --version   # expect current source, not only 1.7.11
# Confirm login without wiping tokens
test -f "${MUSIC_DL_CONFIG_DIR:-$HOME/.config/music-dl}/token.json"

# Known listed Hi-Res track (Leonard Cohen — If I Didn't Have Your Love)
TRACK=66024828
ALBUM=66024823   # You Want It Darker

# Sample download only — one album or one track, max quality
uv run music-dl --quality HI_RES_LOSSLESS $TRACK
```

If Hi-Fi is live, the file lands under the configured download root.

```bash
# MediaInfo (preferred) or ffprobe
mediainfo --Inform="Audio;%Format% %BitDepth% %SamplingRate%" /path/to/If\ I\ Didn\'t\ Have\ Your\ Love.flac
# expect: FLAC 24 44100  (or 24 and sample rate > 44100)

ffprobe -hide_banner -show_streams -select_streams a:0 \
  "/path/to/If I Didn't Have Your Love.flac"
# PASS: bits_per_raw_sample=24 or sample_rate>44100, codec_name=flac
# FAIL: bits_per_raw_sample=16 and sample_rate=44100, or QualityMismatchError
```

CLI album repro from the report:

```bash
uv run music-dl --quality HI_RES_LOSSLESS 543561   # Songs From A Room
# or You Want It Darker:
uv run music-dl --quality HI_RES_LOSSLESS 66024823
```

## FAIL / PASS checklist

| Check | FAIL (1.7.11 / #188) | PASS (this fix) |
| --- | --- | --- |
| Login probe | Warns “subscription only delivers LOSSLESS” because OAuth `get_stream` on a CD probe track | “account supports HI_RES” from `users/{id}/subscription.highestSoundQuality` |
| Listed Hi-Res + OAuth CD + `trackManifests` has **no** `FLAC_HIRES` | Quality mismatch, download fails | CD FLAC is accepted (Tidal truly has no Hi-Res) |
| Listed Hi-Res + OAuth CD + `trackManifests` has `FLAC_HIRES` + live Hi-Fi | Quality mismatch / Hi-Fi first DASH rep is 16/44.1 | File is FLAC Hi-Res (24-bit or >44.1 kHz) |
| Listed Hi-Res + `FLAC_HIRES` + Hi-Fi down | Quality mismatch: “Hi-Fi has no Hi-Res stream” | Quality mismatch mentions `FLAC_HIRES` and unencrypted delivery; no 16/44.1 write |
| Standard lossless album (no `HIRES` tags, no `FLAC_HIRES`) | Still downloads | Still downloads 16/44.1 FLAC |

## Cloud VM note

This environment’s Tidal Web session returns LOSSLESS 16/44.1 for `66024828` while `trackManifests` reports `FLAC_HIRES` / `FLAC_HIRES,44100,24`. Public Hi-Fi tracker `api`/`streaming` were empty (all hosts `down`). Regression tests use those live JSON shapes. Zeratool must run the MediaInfo/ffprobe row above when a Hi-Fi host is up.
