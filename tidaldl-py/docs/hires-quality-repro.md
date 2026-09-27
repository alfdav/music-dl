# Hi-Res quality — live MediaInfo proof (owner Mac)

Issue #188. Shared path: `tidal_dl/download/streams.py` + `tidal_dl/download/quality.py`.
Desktop and CLI both call `_get_stream_info`. No version bump, no tags, no binaries.

## What the code requests vs what Tidal returns

1. Settings / CLI quality ceiling: `HI_RES_LOSSLESS`.
2. Catalog listing: `audioQuality=LOSSLESS` and `mediaMetadata.tags` often include `HIRES_LOSSLESS`.
3. OAuth `GET /v1/tracks/{id}/playbackinfopostpaywall?audioquality=HI_RES_LOSSLESS` (Tidal Web client) returns `audioQuality=LOSSLESS`, `bitDepth=16`, `sampleRate=44100`, BTS FLAC. That is the **session** cap, not proof the account lacks Hi-Res.
4. Same user token, OpenAPI `trackManifests` may still list `FLAC_HIRES`. Those DASH bytes are Widevine; this app does not decrypt them.
5. Unencrypted Hi-Res still comes from a live Hi-Fi `/track/?quality=HI_RES_LOSSLESS` host, or from an OAuth client that actually returns `HI_RES_LOSSLESS`.

Login-client root cause (documented, not implemented): Tidal Web API key `[0]` accepts a Hi-Res request and silently delivers CD. A future login-client picker (overlap with Tidal auth v2) could choose a Hi-Res-capable client. This app will not start a new login or wipe `token.json`.

## Install the #189 branch on a Mac without touching the app

Do **not** delete `~/.config/music-dl/token.json`. Do **not** run `music-dl login`. Do **not** Upgrade All.

The desktop app keeps using its installed binary. Test CLI from an isolated tool install that **reads** the existing login:

```bash
# Isolated CLI from this branch. Reuses ~/.config/music-dl read-only.
uv tool install --force --from \
  'git+https://github.com/alfdav/music-dl@cursor/fix-tidal-hires-quality-cbb2#subdirectory=tidaldl-py' \
  music-dl

# Or one-shot, same isolated venv idea:
# uvx --from 'git+https://github.com/alfdav/music-dl@cursor/fix-tidal-hires-quality-cbb2#subdirectory=tidaldl-py' \
#   music-dl --version

test -f "${MUSIC_DL_CONFIG_DIR:-$HOME/.config/music-dl}/token.json"
music-dl --version
music-dl cfg quality_audio HI_RES_LOSSLESS
```

There is no `--quality` flag on `dl`. Quality is the saved `quality_audio` ceiling.

## Track used for every proof

| | |
| --- | --- |
| Track | Leonard Cohen — If I Didn't Have Your Love |
| Tidal track id | `66024828` |
| Album | You Want It Darker (`66024823`) |
| Quality setting | `HI_RES_LOSSLESS` |

```bash
TRACK_URL=https://tidal.com/browse/track/66024828
ALBUM_URL=https://tidal.com/browse/album/66024823
PLAYLIST_URL='https://tidal.com/browse/playlist/<any-playlist-id-with-that-track>'
MIX_URL='https://tidal.com/browse/mix/<any-mix-id>'
OUT="$HOME/Downloads/music-dl-188-proof"
mkdir -p "$OUT"
```

MediaInfo / ffprobe fields to record:

```bash
mediainfo --Inform="Audio;%Format% %BitDepth% %SamplingRate%" "/path/to/If I Didn't Have Your Love.flac"
# also fine:
ffprobe -hide_banner -show_streams -select_streams a:0 \
  "/path/to/If I Didn't Have Your Love.flac"
```

| Field | Hi-Fi-capped / Tidal Web LOSSLESS session | Hi-Res-capable session + live Hi-Fi |
| --- | --- | --- |
| Format / codec_name | `FLAC` / `flac` | `FLAC` / `flac` |
| BitDepth / bits_per_raw_sample | `16` | `24` |
| SamplingRate / sample_rate | `44100` | `44100` (or `>44100`) |

A 24-bit / 44.1 kHz FLAC (DASH id `FLAC_HIRES,44100,24`) is Hi-Res. 16/44.1 is CD lossless.

## Proof A — Hi-Fi-capped host (reporter first-install / Tidal Web)

Use the Mac whose login probe says this login only delivers LOSSLESS (Tidal Web key `[0]`), even if the account is Max.

```bash
music-dl dl --output "$OUT" "$TRACK_URL"
echo $?   # expect 0
# stdout: one line
#   This login can't get Hi-Res streams, so downloading Lossless instead. ...
# no QualityMismatchError, no Rich traceback

music-dl dl --output "$OUT" "$ALBUM_URL"
echo $?   # expect 0; same notice at most once per process

# Optional playlist / mix (same session, same ceiling):
# music-dl dl --output "$OUT" "$PLAYLIST_URL"
# music-dl dl --output "$OUT" "$MIX_URL"
```

Expected file: FLAC, **16-bit**, **44100 Hz**. History / job quality must say `LOSSLESS`, not `HI_RES_LOSSLESS`.

```bash
FILE=$(find "$OUT" -iname "*Didn't Have Your Love*.flac" | head -n 1)
mediainfo --Inform="Audio;%Format% %BitDepth% %SamplingRate%" "$FILE"
# PASS: FLAC 16 44100
# FAIL: QualityMismatchError, non-zero exit, or no file
```

## Proof B — Hi-Res-capable host (owner’s working Mac)

Use the Mac whose login already gets Hi-Res (or a live Hi-Fi `/track/` host). Same track, same `HI_RES_LOSSLESS` setting.

```bash
music-dl dl --output "$OUT" "$TRACK_URL"
echo $?   # expect 0
# no fallback notice

FILE=$(find "$OUT" -iname "*Didn't Have Your Love*.flac" | head -n 1)
mediainfo --Inform="Audio;%Format% %BitDepth% %SamplingRate%" "$FILE"
# PASS: FLAC 24 44100   (or FLAC 24 and sample rate > 44100)
# FAIL: FLAC 16 44100, or QualityMismatchError
```

If this host is Hi-Res capable **and** Hi-Fi is down **and** OAuth still returns 16/44.1 while `trackManifests` lists `FLAC_HIRES`, the CLI must print a **clean** `Quality mismatch: ... FLAC_HIRES ...` line, exit **non-zero**, and write **no** 16/44.1 file. No Rich traceback. There is no separate strict setting; this is that case.

## FAIL / PASS checklist

| Check | FAIL (1.7.11 / #188) | PASS (this fix) |
| --- | --- | --- |
| Login probe | “subscription only delivers LOSSLESS” as if the account is Hi-Fi | Account may report HI_RES; this **login** is measured separately |
| LOSSLESS-capped session + listed Hi-Res + `FLAC_HIRES` + Hi-Fi down | `QualityMismatchError` / CLI traceback | CD FLAC accepted; one notice; exit 0 |
| Hi-Res-capable session + listed Hi-Res + `FLAC_HIRES` + live Hi-Fi | 16/44.1 or mismatch | MediaInfo FLAC 24 (or 24 and rate >44100) |
| Hi-Res-capable session + `FLAC_HIRES` + Hi-Fi down | traceback / 16/44.1 write | Clean mismatch naming `FLAC_HIRES`; no 16/44.1 write |
| Listed Hi-Res + `trackManifests` has **no** `FLAC_HIRES` | Quality mismatch | CD FLAC accepted (Tidal has no Hi-Res) |
| Standard lossless album | still downloads | still downloads 16/44.1 FLAC |
| Auth | — | No new login, no `token.json` wipe |

## Cloud VM note

This environment’s Tidal Web session returns LOSSLESS 16/44.1 for `66024828` while `trackManifests` reports `FLAC_HIRES`. Public Hi-Fi hosts may be down. Automated tests use those live JSON shapes. The two MediaInfo rows above still need a human on the owner’s Macs.
