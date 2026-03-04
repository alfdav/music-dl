# External API Dependencies

This document tracks third-party APIs that tidal-dl integrates with (or plans to)
for downloading media outside the standard TIDAL OAuth flow.

---

## Hi-Fi API (REST — current integration target)

A lightweight Python REST API that proxies TIDAL's internal endpoints, returning
stream manifests with direct download URLs. No user authentication required —
the API instance operator provides the TIDAL subscription.

| Field | Value |
|-------|-------|
| **Upstream** | [uimaxbai/hifi-api](https://github.com/uimaxbai/hifi-api) |
| **Active fork** | [binimum/hifi-api](https://github.com/binimum/hifi-api) (132 ★, actively maintained) |
| **Our fork** | [alfdav/hifi-api](https://github.com/alfdav/hifi-api) — safety fork in case upstream disappears |
| **License** | MIT |
| **Language** | Python (FastAPI) |

### Why we forked it

Community API projects can disappear without notice. Our fork at `alfdav/hifi-api`
is a preservation copy so we can always self-host an instance if needed. Keep it
synced periodically with `binimum/hifi-api`.

### Key endpoints

```
GET /                                          → health check / version
GET /search?s=<query>                          → search tracks
GET /info/?id=<track_id>                       → track metadata (TIDAL format)
GET /track/?id=<track_id>&quality=HI_RES_LOSSLESS → stream manifest (base64 JSON)
```

Quality values: `HI_RES_LOSSLESS`, `LOSSLESS`, `HIGH`, `LOW`.

The `/track/` response contains a `manifest` field — base64-encoded JSON with:
```json
{
  "mimeType": "audio/flac",
  "codecs": "flac",
  "encryptionType": "NONE",
  "urls": ["https://lgf.audio.tidal.com/..."]
}
```

### Public instances

See [monochrome INSTANCES.md](https://github.com/monochrome-music/monochrome/blob/main/INSTANCES.md)
for a live list. Examples:

- `https://api.monochrome.tf` (official Monochrome API)
- `https://arran.monochrome.tf`
- `https://triton.squid.wtf` (community)

Instance uptime trackers:
- https://tidal-uptime.jiffy-puffs-1j.workers.dev/
- https://tidal-uptime.props-76styles.workers.dev/

---

## Hi-Fi Subsonic/Jellyfin Proxy (Go — future consideration)

A Go-based server that exposes TIDAL as a Subsonic/Jellyfin-compatible music
server. More complex than hifi-api but supports richer integrations (Plexamp,
Feishin, Finamp, etc.).

| Field | Value |
|-------|-------|
| **Repo** | [sachinsenal0x64/hifi](https://github.com/sachinsenal0x64/hifi) |
| **License** | GPL-2.0 |
| **Language** | Go |
| **Status** | Active, but self-hosted setup is complex (pending easy installer) |

### Why this matters for the future

If we ever want to integrate tidal-dl with Jellyfin/Plex/Subsonic workflows
(e.g. auto-download from a Jellyfin "want" list), this project's API would be
the bridge. It uses the OpenSubsonic protocol so any Subsonic-compatible client
can drive it.

### Key differences from hifi-api

- hifi-api: simple REST, returns raw TIDAL stream manifests, good for direct downloads
- hifi (Go): full Subsonic/Jellyfin server, manages its own library/playlists,
  better for streaming use cases but overkill for batch downloading

### Notes

- Requires a valid TIDAL subscription for self-hosting
- Managed instances exist but are designed for individual streaming, not bulk downloads
- Not suitable as a batch download backend today, but the architecture could be
  adapted if the REST API approach ever becomes unavailable

---

## Maintenance checklist

- [ ] Sync `alfdav/hifi-api` with `binimum/hifi-api` quarterly (or when updating the integration)
- [ ] Monitor instance uptime trackers before releases
- [ ] If all public instances go down permanently, self-host from our fork
