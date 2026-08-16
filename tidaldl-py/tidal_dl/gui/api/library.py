"""GET /api/library — local file metadata backed by LibraryDB cache.

The library lives on a NAS (/Volumes/Music), so scanning is slow. Strategy:
- GET /api/library returns whatever is in the DB instantly.
- POST /api/library/scan kicks off a background thread that walks the disk,
  reads tags for new files, prunes deleted ones, and updates the DB.
- The frontend calls scan on first visit (if DB is empty) or on Sync click,
  then polls /api/library to pick up results as they stream in.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from base64 import b64decode
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from mutagen import File as MutagenFile
from pydantic import BaseModel

from tidal_dl.config import Settings
from tidal_dl.helper.library_db import LibraryDB
from tidal_dl.helper.library_db.utils import _album_track_key, _album_track_preference
from tidal_dl.helper.library_scanner import (
    drop_skipped_scan_paths,
    is_skipped_scan_dir,
    path_has_skipped_scan_dir,
)
from tidal_dl.helper.path import path_config_base

router = APIRouter()

_AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".wav", ".aac"}
_COVER_NAMES = [
    "cover.jpg", "cover.png", "folder.jpg", "folder.png",
    "front.jpg", "front.png", "album.jpg", "album.png",
]
_NO_ART_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9"
    "9wAAAABJRU5ErkJggg=="
)

_GENRE_MAP = {
    "electronica/dance": "Electronic",
    "electronica": "Electronic",
    "electronic/dance": "Electronic",
    "hip-hop/rap": "Hip-Hop",
    "hip hop": "Hip-Hop",
    "r&b/soul": "R&B",
    "alternative rock": "Alt Rock",
    "alt-rock": "Alt Rock",
    "indie rock": "Alt Rock",
}


def _normalize_genre(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    g = raw.strip()
    return _GENRE_MAP.get(g.lower(), g)


_db: LibraryDB | None = None  # Compatibility alias for tests/debugging.
_db_opened_at: float = 0  # Compatibility alias for tests/debugging.
_DB_MAX_AGE = 300  # Force reconnect every 5 min to catch stale NAS handles
_scan_lock = threading.Lock()
_scan_running = False
_scan_progress = {"scanned": 0, "total": 0, "done": True}
_db_local = threading.local()
_db_generation = 0
_db_generation_lock = threading.Lock()
_musicbrainz_rate_lock = threading.Lock()
_album_enrichment_lock = threading.Lock()


def _close_thread_db() -> None:
    db = getattr(_db_local, "db", None)
    if db is not None:
        try:
            db.close()
        except Exception:  # noqa: BLE001, S110
            pass
    _db_local.db = None
    _db_local.opened_at = 0.0
    _db_local.generation = -1


def _invalidate_db_cache() -> None:
    global _db, _db_opened_at, _db_generation
    _close_thread_db()
    _db = None
    _db_opened_at = 0
    with _db_generation_lock:
        _db_generation += 1


def _get_db() -> LibraryDB:
    global _db, _db_opened_at
    now = time.time()
    db_path = Path(path_config_base()) / "library.db"
    db = getattr(_db_local, "db", None)
    opened_at = getattr(_db_local, "opened_at", 0.0)
    generation = getattr(_db_local, "generation", -1)

    if db is not None:
        expired = (now - opened_at) > _DB_MAX_AGE
        stale_generation = generation != _db_generation
        stale_path = db._path != db_path
        if expired or stale_generation or stale_path:
            _close_thread_db()
            db = None

    if db is None:
        db = LibraryDB(db_path)
        db.open()
        _db_local.db = db
        _db_local.opened_at = now
        _db_local.generation = _db_generation
    else:
        # Validate the connection is still alive (NAS mounts can drop)
        try:
            db._conn.execute("SELECT 1")
        except Exception:  # noqa: BLE001
            _close_thread_db()
            db = LibraryDB(db_path)
            db.open()
            _db_local.db = db
            _db_local.opened_at = now
            _db_local.generation = _db_generation

    _db = db
    _db_opened_at = getattr(_db_local, "opened_at", now)
    return db


def get_download_path() -> str:
    settings = Settings()
    return settings.data.download_base_path


def _path_in_library(path: str) -> bool:
    """Thread-safe check: is this path in our library DB? Opens its own connection."""
    import sqlite3

    db_path = Path(path_config_base()) / "library.db"
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT 1 FROM scanned WHERE path = ? LIMIT 1", (path,)).fetchone()
        conn.close()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


def _trusted_library_path(path: str) -> Path | None:
    """Return a resolved path from the library DB when the exact path is known."""
    import sqlite3

    db_path = Path(path_config_base()) / "library.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT path FROM scanned WHERE path = ? LIMIT 1", (path,)).fetchone()
        conn.close()
        if not row:
            return None
        return Path(row[0]).resolve(strict=True)
    except Exception:  # noqa: BLE001
        return None


def _codec_family(info: object | None) -> str:
    if info is None:
        return "unknown"
    codec = " ".join(
        str(value).casefold()
        for value in (
            getattr(info, "codec", None),
            getattr(info, "codec_description", None),
        )
        if value
    )
    for family, markers in (
        ("flac", ("flac",)),
        ("alac", ("alac", "apple lossless")),
        ("aac", ("aac", "mp4a")),
        ("mp3", ("mp3", "mpeg layer iii", "mpeg-1 layer 3")),
        ("opus", ("opus",)),
        ("vorbis", ("vorbis",)),
        ("pcm", ("pcm", "wave")),
    ):
        if any(marker in codec for marker in markers):
            return family
    return "unknown"


def _native_codec_from_extension(file_path: Path) -> str | None:
    return {
        ".flac": "flac",
        ".mp3": "mp3",
        ".aac": "aac",
        ".ogg": "ogg",
        ".wav": "pcm",
    }.get(file_path.suffix.casefold())


_GENERIC_TRACK = re.compile(r"^track\s*\d+$", re.IGNORECASE)


def _meaningful(value: str | None, unknown: str) -> bool:
    cleaned = (value or "").strip()
    return bool(cleaned and cleaned.casefold() != unknown.casefold())


def _meaningful_title(value: str | None) -> bool:
    cleaned = (value or "").strip()
    return bool(cleaned and not _GENERIC_TRACK.fullmatch(cleaned))


def _structured_path_metadata(file_path: Path, scan_dirs: list[Path]) -> tuple[str, str] | None:
    resolved_file = file_path.resolve(strict=False)
    roots = sorted(
        (root.resolve(strict=False) for root in scan_dirs),
        key=lambda root: len(root.parts),
        reverse=True,
    )
    for root in roots:
        try:
            relative = resolved_file.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) >= 3:
            return relative.parts[0].strip(), relative.parts[-2].strip()
    return None


def _resolve_local_metadata(
    file_path: Path,
    scan_dirs: list[Path],
    *,
    title: str = "",
    artist: str = "",
    album: str = "",
) -> dict:
    structured = _structured_path_metadata(file_path, scan_dirs)
    path_artist, path_album = structured or ("", "")
    resolved_artist = artist.strip() if _meaningful(artist, "Unknown Artist") else path_artist
    resolved_artist = resolved_artist or "Unknown Artist"

    resolved_album = album.strip() if _meaningful(album, "Unknown Album") else path_album
    if path_artist and resolved_album == path_album:
        for separator in (" - ", " – ", " — "):
            prefix = path_artist + separator
            if resolved_album.casefold().startswith(prefix.casefold()):
                resolved_album = resolved_album[len(prefix):].strip()
                break
    resolved_album = resolved_album or "Unknown Album"

    filename_title = re.sub(r"^\d{1,3}[\s._-]+", "", file_path.stem).strip()
    if _meaningful_title(title):
        resolved_title = title.strip()
    elif _meaningful_title(filename_title):
        resolved_title = filename_title
    else:
        resolved_title = title.strip() or file_path.stem

    return {
        "name": resolved_title,
        "artist": resolved_artist,
        "album": resolved_album,
    }


def _raw_tag(tags: object, *names: str) -> object | None:
    if not tags or not hasattr(tags, "items"):
        return None
    wanted = {name.casefold() for name in names}
    for key, value in tags.items():
        if str(key).casefold() in wanted:
            return value
    return None


def _tag_scalar(value: object | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    cleaned = str(value).strip()
    return cleaned or None


def _tag_position(value: object | None, total: object | None = None) -> tuple[int | None, int | None]:
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, tuple):
        first = value[0] if value else None
        second = value[1] if len(value) > 1 else None
    else:
        parts = (_tag_scalar(value) or "").split("/", 1)
        first = parts[0] or None
        second = parts[1] if len(parts) > 1 else None
    total_value = _tag_scalar(total) or second

    def positive_int(raw: object | None) -> int | None:
        try:
            number = int(str(raw))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    return positive_int(first), positive_int(total_value)


def _extract_release_metadata(easy_tags: object, raw_tags: object) -> dict:
    """Normalize release identity fields from Vorbis, ID3, and MP4 tag shapes."""
    def value(*names: str) -> object | None:
        return _raw_tag(easy_tags, *names) or _raw_tag(raw_tags, *names)

    track_number, track_total = _tag_position(
        value("tracknumber", "TRCK", "trkn"),
        value("tracktotal", "totaltracks", "TRACKTOTAL"),
    )
    disc_number, disc_total = _tag_position(
        value("discnumber", "TPOS", "disk"),
        value("disctotal", "totaldiscs", "DISCTOTAL"),
    )
    tidal_album_id = _tag_scalar(value(
        "tidal_album_id",
        "TXXX:TIDAL_ALBUM_ID",
        "----:com.apple.iTunes:TIDAL_ALBUM_ID",
    ))
    provider_namespace = _tag_scalar(value("provider_namespace", "PROVIDER_NAMESPACE"))
    provider_album_id = _tag_scalar(value("provider_album_id", "PROVIDER_ALBUM_ID"))
    if tidal_album_id:
        provider_namespace = "tidal"
        provider_album_id = tidal_album_id

    return {
        "album_artist": _tag_scalar(value("albumartist", "ALBUMARTIST", "TPE2", "aART")),
        "release_date": _tag_scalar(value("date", "DATE", "TDRC", "\xa9day")),
        "track_number": track_number,
        "track_total": track_total,
        "disc_number": disc_number,
        "disc_total": disc_total,
        "musicbrainz_release_id": _tag_scalar(value(
            "musicbrainz_albumid",
            "MUSICBRAINZ_ALBUMID",
            "TXXX:MusicBrainz Album Id",
            "----:com.apple.iTunes:MusicBrainz Album Id",
        )),
        "musicbrainz_release_group_id": _tag_scalar(value(
            "musicbrainz_releasegroupid",
            "MUSICBRAINZ_RELEASEGROUPID",
            "TXXX:MusicBrainz Release Group Id",
            "----:com.apple.iTunes:MusicBrainz Release Group Id",
        )),
        "provider_namespace": provider_namespace,
        "provider_album_id": provider_album_id,
        "barcode": _tag_scalar(value(
            "barcode", "upc", "ean", "TXXX:BARCODE", "TXXX:UPC", "TXXX:EAN",
            "----:com.apple.iTunes:BARCODE", "----:com.apple.iTunes:UPC",
            "----:com.apple.iTunes:EAN",
        )),
    }


def _read_metadata(file_path: Path, scan_dirs: list[Path] | None = None) -> dict | None:
    try:
        # easy=True gives uniform tag keys across ID3, MP4, Vorbis, etc.
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            return None

        def _tag(key: str, fallback: str = "") -> str:
            val = audio.get(key)
            if val and isinstance(val, list):
                return str(val[0])
            return str(val) if val else fallback

        # Need raw audio for info (bitrate, sample rate) — easy mode still has .info
        quality = file_path.suffix[1:].upper()
        if audio.info and hasattr(audio.info, "bits_per_sample"):
            quality = f"{audio.info.sample_rate}Hz/{audio.info.bits_per_sample}bit"

        # ISRC and release identities may require raw MP4 or ID3 tags.
        raw = MutagenFile(file_path)
        isrc = _tag("isrc")
        if not isrc and raw and raw.tags:
                # MP4: stored as freeform atom or direct key
                for key in ("isrc", "----:com.apple.iTunes:isrc", "TSRC"):
                    val = raw.tags.get(key)
                    if val:
                        if isinstance(val, list):
                            isrc = str(val[0])
                        else:
                            isrc = str(val)
                        break

        release_metadata = _extract_release_metadata(audio, raw.tags if raw else {})

        resolved = _resolve_local_metadata(
            file_path,
            scan_dirs or [],
            title=_tag("title"),
            artist=_tag("artist"),
            album=_tag("album"),
        )
        codec = _codec_family(audio.info)
        if codec == "unknown":
            codec = _native_codec_from_extension(file_path) or "unknown"

        return {
            "path": str(file_path),
            **resolved,
            **release_metadata,
            "duration": round(audio.info.length) if audio.info else 0,
            "isrc": isrc,
            "genre": _normalize_genre(_tag("genre")),
            "quality": quality,
            "format": file_path.suffix[1:].upper(),
            "codec": codec,
            "metadata_complete": True,
            "is_local": True,
        }
    except Exception:  # noqa: BLE001
        return None


def _has_local_art(file_path: Path) -> bool:
    """Return whether an audio file has embedded or sibling cover art."""
    try:
        audio = MutagenFile(str(file_path))
        if audio is not None:
            if hasattr(audio, "pictures") and audio.pictures:
                return True
            tags = audio.tags or {}
            if any(str(key).startswith("APIC") for key in tags):
                return True
            if tags.get("covr"):
                return True
    except Exception:  # noqa: BLE001, S110
        pass
    return any((file_path.parent / name).is_file() for name in _COVER_NAMES)


def _read_local_art_bytes(file_path: Path) -> tuple[bytes | None, str]:
    """Read embedded or sibling artwork without mutating the audio file."""
    try:
        audio = MutagenFile(str(file_path))
        if audio is not None:
            if hasattr(audio, "pictures") and audio.pictures:
                picture = audio.pictures[0]
                return picture.data, picture.mime or "image/jpeg"
            tags = audio.tags or {}
            for key in tags:
                if str(key).startswith("APIC"):
                    picture = tags[key]
                    return picture.data, picture.mime or "image/jpeg"
            if tags.get("covr"):
                return bytes(tags["covr"][0]), "image/jpeg"
    except Exception:  # noqa: BLE001, S110
        pass
    for name in _COVER_NAMES:
        image_path = file_path.parent / name
        if image_path.is_file():
            try:
                return image_path.read_bytes(), "image/png" if name.endswith(".png") else "image/jpeg"
            except OSError:
                return None, "image/jpeg"
    return None, "image/jpeg"


def _local_cover_url(path: str | None, art_available: bool | int | None) -> str:
    if not path or art_available == 0:
        return ""
    from urllib.parse import quote

    return "/api/library/art?path=" + quote(path, safe="")


def _db_row_to_track(row: dict) -> dict:
    p = Path(row["path"])
    return {
        "path": row["path"],
        "name": row.get("title") or p.stem,
        "artist": row.get("artist") or "Unknown Artist",
        "album": row.get("album") or "Unknown Album",
        "duration": row.get("duration") or 0,
        "isrc": row.get("isrc") or "",
        "genre": row.get("genre") or "",
        "quality": row.get("quality") or p.suffix[1:].upper(),
        "format": row.get("format") or p.suffix[1:].upper(),
        "codec": row.get("codec") or "unknown",
        "cover_url": _local_cover_url(row["path"], row.get("art_available")),
        "play_count": row.get("play_count") or 0,
        "is_local": True,
    }


def _assessment_payload(assessment, titles: dict[str, str]) -> dict:
    return {
        "left_signature": assessment.left_signature,
        "right_signature": assessment.right_signature,
        "left_title": titles.get(assessment.left_signature, ""),
        "right_title": titles.get(assessment.right_signature, ""),
        "score": assessment.score,
        "outcome": assessment.outcome,
        "family_scores": assessment.family_scores,
        "diversity_bonus": assessment.diversity_bonus,
        "coverage": assessment.coverage,
        "evidence": [
            {
                "code": item.code,
                "family": item.family,
                "points": item.points,
                "sources": sorted(item.sources),
                "explanation": item.explanation,
            }
            for item in assessment.evidence
        ],
        "vetoes": [
            {"code": veto.code, "explanation": veto.explanation}
            for veto in assessment.vetoes
        ],
        "contradictions": assessment.contradictions,
        "user_decision": assessment.user_decision,
        "user_decision_superseded": assessment.user_decision_superseded,
    }


def _catalog_source_eligible(
    stored: dict | None,
    source: str,
    *,
    now: float,
    direct_identity: bool = False,
) -> bool:
    if direct_identity or (stored and (stored.get("user_decision") or stored.get("vetoes"))):
        return False
    state = (stored or {}).get("catalog", {}).get(source)
    if not state:
        return True
    if state.get("status") != "failed":
        return False
    return now - float(state.get("attempted_at") or 0) >= 86_400


def _musicbrainz_json(
    url: str,
    *,
    request_get=None,
    clock=time.monotonic,
    sleeper=time.sleep,
) -> dict:
    import requests

    request_get = request_get or requests.get
    with _musicbrainz_rate_lock:
        now = clock()
        wait = max(0.0, float(getattr(_musicbrainz_json, "_last_request", 0.0)) + 1.0 - now)
        if wait:
            sleeper(wait)
        response = request_get(
            url,
            headers={"User-Agent": "music-dl/1.7.2 (https://github.com/alfdav/music-dl)"},
            timeout=10,
        )
        _musicbrainz_json._last_request = clock()
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("MusicBrainz returned malformed JSON")
    return payload


_musicbrainz_json._last_request = 0.0


def _catalog_group_matches(group, album_artist: str, track_titles: list[str]) -> bool:
    from tidal_dl.helper.album_grouping import normalize_text

    if not group.album_artist or group.album_artist != normalize_text(album_artist):
        return False
    source_titles = Counter(normalize_text(title) for title in track_titles if normalize_text(title))
    matches = 0
    for slot in group.slots:
        title = slot.key[1]
        if source_titles[title] > 0:
            source_titles[title] -= 1
            matches += 1
    required = min(3, len(group.slots))
    return bool(group.slots) and matches >= required and matches / len(group.slots) >= 0.9


def _tidal_catalog_lookup(left, right, session) -> dict:
    from tidalapi.album import Album

    result = session.search(f"{left.album_artist} {left.title}", models=[Album], limit=10)
    albums = result.get("albums", result) if isinstance(result, dict) else result
    for album in albums or []:
        artist = getattr(getattr(album, "artist", None), "name", "")
        tracks = album.tracks() if hasattr(album, "tracks") else []
        titles = [str(getattr(track, "name", "")) for track in tracks or []]
        if _catalog_group_matches(left, artist, titles) and _catalog_group_matches(right, artist, titles):
            return {
                "status": "matched",
                "same_release": True,
                "release_id": str(getattr(album, "id", "")),
                "title": str(getattr(album, "name", "") or getattr(album, "title", "")),
            }
    return {"status": "no_match", "same_release": False}


def _musicbrainz_catalog_lookup(left, right) -> dict:
    query = urlencode({
        "query": f'artist:"{left.album_artist}" AND release:"{left.title}"',
        "fmt": "json",
        "limit": 3,
    })
    search = _musicbrainz_json("https://musicbrainz.org/ws/2/release/?" + query)
    for release in search.get("releases", [])[:3]:
        release_id = release.get("id")
        if not release_id:
            continue
        detail = _musicbrainz_json(
            f"https://musicbrainz.org/ws/2/release/{release_id}?inc=recordings+artist-credits&fmt=json"
        )
        artist_credit = detail.get("artist-credit") or []
        artist = "".join(
            str(item.get("name") or item.get("artist", {}).get("name") or "")
            for item in artist_credit if isinstance(item, dict)
        )
        titles = [
            str(track.get("recording", {}).get("title") or track.get("title") or "")
            for medium in detail.get("media", [])
            for track in medium.get("tracks", [])
        ]
        if _catalog_group_matches(left, artist, titles) and _catalog_group_matches(right, artist, titles):
            return {
                "status": "matched",
                "same_release": True,
                "release_id": str(release_id),
                "title": str(detail.get("title") or release.get("title") or ""),
            }
    return {"status": "no_match", "same_release": False}


def _album_cards(db: LibraryDB, *, include_artwork: bool = False) -> list[dict]:
    """Build current release cards from cached rows without network access."""
    from tidal_dl.helper.album_grouping import (
        accepted_components,
        assess_pair,
        base_title,
        build_local_album_groups,
        canonical_title,
        card_id,
        find_candidates,
    )

    groups = build_local_album_groups(db.all_tracks())
    titles = {group.signature: group.title for group in groups}
    assessments = {}
    stored_rows = {}
    for left, right in find_candidates(groups):
        stored = db.get_grouping_assessment(left.signature, right.signature)
        stored_rows[frozenset({left.signature, right.signature})] = stored
        cached_artwork = bool(stored and any(
            item.get("code") == "artwork" for item in stored.get("evidence", [])
        ))
        artwork_digests = None
        if include_artwork:
            from tidal_dl.helper.album_grouping import weak_evidence_sets

            artwork_digests = (
                set(weak_evidence_sets(left.rows, lambda path: _read_local_art_bytes(Path(path))[0])[0]),
                set(weak_evidence_sets(right.rows, lambda path: _read_local_art_bytes(Path(path))[0])[0]),
            )
        elif cached_artwork:
            artwork_digests = ({"cached"}, {"cached"})
        assessment = assess_pair(
            left,
            right,
            user_decision=stored.get("user_decision") if stored else None,
            catalog_results=stored.get("catalog") if stored else None,
            artwork_digests=artwork_digests,
            directory_names=(
                {base_title(Path(row["path"]).parent.name) for row in left.rows},
                {base_title(Path(row["path"]).parent.name) for row in right.rows},
            ),
        )
        pair = frozenset({left.signature, right.signature})
        assessments[pair] = assessment
        payload = _assessment_payload(assessment, titles)
        db.save_grouping_assessment(
            left_signature=left.signature,
            right_signature=right.signature,
            score=assessment.score,
            outcome=assessment.outcome,
            evidence=payload["evidence"],
            vetoes=payload["vetoes"],
            contradictions=assessment.contradictions,
            catalog=stored.get("catalog") if stored else None,
        )
    if assessments:
        db.commit()

    components, clique_review = accepted_components(groups, assessments)
    cards: list[dict] = []
    for component in components:
        signatures = {group.signature for group in component}
        component_assessments = [
            assessment
            for pair, assessment in assessments.items()
            if pair & signatures
        ]
        selected_titles = [
            stored["canonical_title"]
            for pair, stored in stored_rows.items()
            if stored and stored.get("canonical_title") and pair <= signatures
        ]
        tracks = [row for group in component for row in group.rows]
        ordered = sorted(tracks, key=_album_track_preference)
        distinct: dict[tuple[str, str], dict] = {}
        for row in ordered:
            distinct.setdefault(_album_track_key(row), row)
        presented = sorted(distinct.values(), key=lambda row: (
            row.get("disc_number") or 0,
            row.get("track_number") or 0,
            row.get("path") or "",
        ))
        artists = {str(row.get("artist")) for row in tracks if row.get("artist")}
        cover = min(tracks, key=lambda row: (not bool(row.get("art_available")), row.get("path") or ""))
        possible_duplicate = bool(
            signatures & clique_review
            or any(assessment.outcome == "review" for assessment in component_assessments)
            or any(assessment.user_decision_superseded for assessment in component_assessments)
        )
        cards.append({
            "id": card_id(component),
            "name": canonical_title(component, user_titles=selected_titles),
            "artist": next(iter(artists)) if len(artists) == 1 else "Various Artists",
            "track_count": len(presented),
            "cover_path": cover.get("path"),
            "cover_art_available": cover.get("art_available"),
            "best_quality": max((str(row.get("quality") or "") for row in tracks), default=""),
            "members": sorted(group.title for group in component),
            "possible_duplicate": possible_duplicate,
            "assessments": [_assessment_payload(assessment, titles) for assessment in component_assessments],
            "tracks": presented,
            "recent_at": max((int(row.get("scanned_at") or 0) for row in tracks), default=0),
            "recent_source": "scan",
        })
    return sorted(cards, key=lambda card: (card["name"].casefold(), card["artist"].casefold()))


def _enrich_album_candidates(db: LibraryDB) -> None:
    """Run optional catalog work after scanning, never during rendering."""
    from tidal_dl.config import Tidal
    from tidal_dl.gui.api.settings import _local_auth_status
    from tidal_dl.helper.album_grouping import build_local_album_groups, find_candidates

    groups = build_local_album_groups(db.all_tracks())
    for left, right in find_candidates(groups):
        stored = db.get_grouping_assessment(left.signature, right.signature)
        if stored is None:
            continue
        catalog = dict(stored.get("catalog") or {})
        now = time.time()
        same_provider = bool(
            left.values("provider_album_id") & right.values("provider_album_id")
            and left.values("provider_namespace") & right.values("provider_namespace")
        )
        same_musicbrainz = bool(
            left.values("musicbrainz_release_id") & right.values("musicbrainz_release_id")
        )
        sources: list[tuple[str, Callable[[], dict]]] = []

        tidal = Tidal()
        if _local_auth_status(tidal)["logged_in"] and _catalog_source_eligible(
            stored, "tidal", now=now, direct_identity=same_provider,
        ):
            sources.append((
                "tidal",
                lambda left=left, right=right, session=tidal.session: _tidal_catalog_lookup(left, right, session),
            ))
        if _catalog_source_eligible(
            stored, "musicbrainz", now=now, direct_identity=same_musicbrainz,
        ):
            sources.append((
                "musicbrainz",
                lambda left=left, right=right: _musicbrainz_catalog_lookup(left, right),
            ))

        for source, lookup in sources:
            attempted_at = time.time()
            result = _safe_catalog_lookup(lookup)
            catalog[source] = {**result, "attempted_at": attempted_at}
            db.save_grouping_assessment(
                left_signature=left.signature,
                right_signature=right.signature,
                score=stored["score"],
                outcome=stored["outcome"],
                evidence=stored["evidence"],
                vetoes=stored["vetoes"],
                contradictions=stored["contradictions"],
                catalog=catalog,
            )
            db.commit()
            _album_cards(db)
            stored = db.get_grouping_assessment(left.signature, right.signature) or stored


def _safe_catalog_lookup(lookup: Callable[[], dict]) -> dict:
    try:
        return lookup()
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": type(exc).__name__}


def _background_album_enrichment() -> None:
    """Enrich the latest local assessments without extending scan busy state."""
    if not _album_enrichment_lock.acquire(blocking=False):
        return
    db = None
    try:
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()
        _enrich_album_candidates(db)
    finally:
        if db is not None:
            db.close()
        _invalidate_db_cache()
        _album_enrichment_lock.release()


def _schedule_album_enrichment() -> None:
    threading.Thread(target=_background_album_enrichment, daemon=True).start()


def _finish_album_scan(db: LibraryDB) -> None:
    """Persist local assessments, release scan resources, then enrich."""
    _album_cards(db, include_artwork=True)
    db.close()
    _invalidate_db_cache()
    _schedule_album_enrichment()


def _scan_directories() -> list[Path]:
    """Return all directories to scan: download_base_path + scan_paths."""
    settings = Settings()
    dirs: list[Path] = []
    dl = Path(settings.data.download_base_path).expanduser()
    if dl.is_dir():
        dirs.append(dl)
    if settings.data.scan_paths:
        for p in settings.data.scan_paths.split(","):
            p = p.strip()
            if p:
                expanded = Path(p).expanduser()
                if expanded.is_dir() and expanded not in dirs:
                    dirs.append(expanded)
    return dirs


def _backup_library_db(db_path: Path) -> Path:
    """Create a consistent rolling SQLite backup, including committed WAL pages."""
    backup_path = Path(str(db_path) + ".bak")
    if not db_path.is_file():
        return backup_path

    source = sqlite3.connect(str(db_path))
    try:
        source.execute("PRAGMA busy_timeout=5000")
        target = sqlite3.connect(str(backup_path))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return backup_path


def _migrate_volume_prefixes(db: LibraryDB, scan_dirs: list[Path]) -> None:
    """Rewrite stored path prefixes when a volume remounts under a different name.

    macOS can remount e.g. /Volumes/Music as /Volumes/Music 1.  All paths in
    the DB become stale.  We detect this by sampling stored paths and comparing
    their prefix against the current scan directories.  If they diverge, we
    batch-UPDATE every table that stores file paths.
    """
    assert db._conn
    conn = db._conn

    # Sample a few stored paths to discover what prefix the DB currently holds
    sample_rows = conn.execute(
        "SELECT path FROM scanned LIMIT 10"
    ).fetchall()
    if not sample_rows:
        return  # empty DB, nothing to migrate

    stored_paths = [r["path"] for r in sample_rows]

    for scan_dir in scan_dirs:
        current_prefix = str(scan_dir)
        # Check if any stored path already starts with this scan dir — no migration needed
        if any(p.startswith((current_prefix + os.sep, current_prefix + "/")) for p in stored_paths):
            continue

        # Try to find a stored prefix that looks like a variant of this scan dir.
        # e.g. current = /Volumes/Music, stored = /Volumes/Music 1/Artist/...
        # Strategy: walk up from the scan dir to find the mount point, then look
        # for stored paths sharing the same parent but with a different leaf name.
        scan_parent = str(Path(current_prefix).parent)  # e.g. /Volumes
        scan_leaf = Path(current_prefix).name            # e.g. Music

        # Find stored prefixes that share the same parent directory
        old_prefix = None
        for sp in stored_paths:
            if not sp.startswith(scan_parent + "/"):
                continue
            # Extract the leaf directory name from the stored path
            remainder = sp[len(scan_parent) + 1:]  # e.g. "Music 1/Artist/track.flac"
            stored_leaf = remainder.split("/")[0]    # e.g. "Music 1"
            if stored_leaf != scan_leaf:
                candidate = scan_parent + "/" + stored_leaf
                old_prefix = candidate
                break

        if not old_prefix:
            continue

        # Verify this old prefix is actually prevalent (not just one rogue row)
        count = conn.execute(
            "SELECT COUNT(*) FROM scanned WHERE path LIKE ? || '/%'",
            (old_prefix,),
        ).fetchone()[0]
        if count == 0:
            continue

        new_prefix = current_prefix
        print(f"[library] Volume remount detected: rewriting {count} paths")
        print(f"[library]   old prefix: {old_prefix}")
        print(f"[library]   new prefix: {new_prefix}")

        # Batch rewrite all tables that store file paths
        conn.execute(
            "UPDATE scanned SET path = replace(path, ?, ?) WHERE path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.execute(
            "UPDATE play_events SET path = replace(path, ?, ?) WHERE path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.execute(
            "UPDATE favorites SET path = replace(path, ?, ?) WHERE path IS NOT NULL AND path LIKE ? || '/%'",
            (old_prefix, new_prefix, old_prefix),
        )
        conn.commit()
        print(f"[library] Volume prefix migration complete — {count} paths updated")


def _reconcile_library_rows(db: LibraryDB, *, scan_dirs: list[Path]) -> int:
    """Resolve legacy metadata facts once without repeating waveform work."""
    repaired = 0
    for row in db.metadata_repair_worklist():
        file_path = Path(row["path"])
        if not file_path.is_file():
            continue
        meta = _read_metadata(file_path, scan_dirs)
        if meta:
            db.record(
                row["path"],
                status="tagged" if meta["isrc"] else "needs_isrc",
                isrc=meta["isrc"] or None,
                artist=meta["artist"],
                title=meta["name"],
                album=meta["album"],
                album_artist=meta.get("album_artist"),
                release_date=meta.get("release_date"),
                track_number=meta.get("track_number"),
                track_total=meta.get("track_total"),
                disc_number=meta.get("disc_number"),
                disc_total=meta.get("disc_total"),
                musicbrainz_release_id=meta.get("musicbrainz_release_id"),
                musicbrainz_release_group_id=meta.get("musicbrainz_release_group_id"),
                provider_namespace=meta.get("provider_namespace"),
                provider_album_id=meta.get("provider_album_id"),
                barcode=meta.get("barcode"),
                duration=meta["duration"],
                genre=meta.get("genre"),
                quality=meta["quality"],
                fmt=meta["format"],
                codec=meta["codec"],
                metadata_complete=True,
            )
        else:
            db.record(
                row["path"],
                status=row["status"],
                isrc=row.get("isrc"),
                artist=row.get("artist"),
                title=row.get("title"),
                album=row.get("album"),
                duration=row.get("duration"),
                genre=row.get("genre"),
                quality=row.get("quality"),
                fmt=row.get("format"),
                codec=row.get("codec") or "unknown",
                metadata_complete=True,
            )
        repaired += 1
    if repaired:
        db.commit()
    return repaired


def _background_scan(rescan: bool) -> None:
    """Walk all configured dirs, read tags for unknown files, prune deleted ones."""
    global _scan_running, _scan_progress
    try:
        scan_dirs = _scan_directories()

        # Backup DB before scan — single rolling .bak for disaster recovery.
        # Use SQLite backup API so committed WAL pages are included.
        _backup_library_db(Path(path_config_base()) / "library.db")

        # Own connection for the background thread — SQLite doesn't share across threads
        db = LibraryDB(Path(path_config_base()) / "library.db")
        db.open()

        # --- Volume remount prefix migration ---
        # macOS sometimes remounts /Volumes/Music as /Volumes/Music 1 (or back).
        # Stored absolute paths become stale, causing full rescans and data loss.
        # Detect and batch-rewrite prefixes before anything else touches the DB.
        if scan_dirs:
            _migrate_volume_prefixes(db, scan_dirs)

        # If no scan directories are reachable, skip scan entirely to preserve
        # the cached library data.  Without this guard the prune logic would
        # delete every row because disk_paths would be empty.
        if not scan_dirs:
            print("[library] No scan directories reachable — skipping scan to preserve cache")
            with _scan_lock:
                _scan_progress = {"scanned": 0, "total": 0, "done": True}
            db.close()
            return

        dropped = drop_skipped_scan_paths(db)
        if dropped:
            db.commit()
            print(f"[library] Dropped {dropped} rows under skipped directories")

        if not rescan:
            repaired = _reconcile_library_rows(db, scan_dirs=scan_dirs)
            if repaired:
                print(f"[library] Repaired metadata for {repaired} cached rows")

        known = set() if rescan else db.known_paths()

        # --- Fast-path: skip walk if nothing changed on disk ---
        import json as _json

        try:
            finger = _json.dumps({
                "dirs": sorted(str(d) for d in scan_dirs),
                "mtimes": [os.stat(str(d)).st_mtime for d in sorted(scan_dirs)],
                "known_count": len(known),
            }, sort_keys=True)
        except OSError:
            finger = None

        if not rescan and finger:
            stored = db.get_meta("scan_fingerprint")
            if stored == finger:
                print("[library] Scan directories unchanged — skipping")
                with _scan_lock:
                    _scan_progress = {"scanned": 0, "total": 0, "done": True}
                _finish_album_scan(db)
                return

        with _scan_lock:
            _scan_progress = {"scanned": 0, "total": 0, "done": False}
        disk_paths: set[str] = set()
        batch = 0

        if scan_dirs:
            # Phase 1: Walk filesystem — fast, just collect paths
            for scan_dir in scan_dirs:
                for walk_root, dirs, files in os.walk(scan_dir):
                    dirs[:] = [name for name in dirs if not is_skipped_scan_dir(name)]
                    for fname in files:
                        f = Path(walk_root) / fname
                        if path_has_skipped_scan_dir(f):
                            continue
                        if f.is_symlink():  # symlink → arbitrary target recorded as trusted path (DB poisoning)
                            continue
                        if f.suffix.lower() not in _AUDIO_EXTENSIONS:
                            continue
                        disk_paths.add(str(f))
                        _scan_progress["total"] = len(disk_paths)

            # Phase 2: Read metadata + waveform only for NEW files (the diff)
            from tidal_dl.helper.waveform import extract_both, peaks_to_json

            new_paths = disk_paths - known
            _scan_progress["scanned"] = 0
            for path_str in new_paths:
                file_path = Path(path_str)
                art_available = _has_local_art(file_path)
                meta = _read_metadata(file_path, scan_dirs)
                if meta:
                    # Extract waveform peaks (single ffmpeg decode, ~30ms per file)
                    waveform_json = None
                    hires_json = None
                    both = extract_both(Path(path_str))
                    if both:
                        waveform_json = peaks_to_json(both[0])
                        hires_json = peaks_to_json(both[1])

                    db.record(
                        path_str,
                        status="tagged" if meta["isrc"] else "needs_isrc",
                        isrc=meta["isrc"] or None,
                        artist=meta["artist"],
                        title=meta["name"],
                        album=meta["album"],
                        album_artist=meta.get("album_artist"),
                        release_date=meta.get("release_date"),
                        track_number=meta.get("track_number"),
                        track_total=meta.get("track_total"),
                        disc_number=meta.get("disc_number"),
                        disc_total=meta.get("disc_total"),
                        musicbrainz_release_id=meta.get("musicbrainz_release_id"),
                        musicbrainz_release_group_id=meta.get("musicbrainz_release_group_id"),
                        provider_namespace=meta.get("provider_namespace"),
                        provider_album_id=meta.get("provider_album_id"),
                        barcode=meta.get("barcode"),
                        duration=meta["duration"],
                        genre=meta.get("genre"),
                        quality=meta["quality"],
                        fmt=meta["format"],
                        codec=meta["codec"],
                        metadata_complete=True,
                        waveform=waveform_json,
                        waveform_hires=hires_json,
                        art_available=art_available,
                    )
                else:
                    db.record(
                        path_str,
                        status="unreadable",
                        art_available=art_available,
                        codec="unknown",
                        metadata_complete=True,
                    )
                batch += 1
                if batch >= 50:
                    db.commit()
                    batch = 0
                _scan_progress["scanned"] += 1

            # Prune deleted files — with safety threshold for volume remounts
            stale = known - disk_paths
            if len(stale) > 0.5 * len(known) and len(known) > 100:
                print(
                    f"[library] Skipping prune: {len(stale)}/{len(known)} paths would be removed"
                    " — possible volume remount"
                )
            else:
                for p in stale:
                    db.remove(p)

            if batch > 0 or stale:
                db.commit()

        with _scan_lock:
            _scan_progress["done"] = True

        # Save scan fingerprint so next scan can skip if nothing changed
        if finger:
            # Recompute with final known_count (scan may have added/removed rows)
            try:
                final_known = len(db.known_paths()) if not rescan else len(disk_paths)
                finger = _json.dumps({
                    "dirs": sorted(str(d) for d in scan_dirs),
                    "mtimes": [os.stat(str(d)).st_mtime for d in sorted(scan_dirs)],
                    "known_count": final_known,
                }, sort_keys=True)
                db.set_meta("scan_fingerprint", finger)
                db.commit()
            except OSError:
                pass

        # Backfill genres for tracks scanned before genre support was added.
        # Runs AFTER scan is marked done so the UI doesn't show a stuck spinner.
        # Limit to 200 files per scan to avoid long NAS hangs.
        missing = db._conn.execute(
            "SELECT path FROM scanned WHERE (genre IS NULL OR genre = '') AND status != 'unreadable' LIMIT 200"
        ).fetchall()
        if missing:
            gfilled = 0
            for row in missing:
                p = Path(row[0])
                try:
                    if not p.exists():
                        continue
                    audio = MutagenFile(str(p), easy=True)
                    if audio and audio.tags:
                        raw = audio.tags.get("genre")
                        if raw and isinstance(raw, list):
                            genre = _normalize_genre(str(raw[0]))
                        elif raw:
                            genre = _normalize_genre(str(raw))
                        else:
                            genre = None
                        if genre:
                            db._conn.execute(
                                "UPDATE scanned SET genre = ? WHERE path = ?",
                                (genre, row[0]),
                            )
                            gfilled += 1
                except Exception:  # noqa: BLE001, S110
                    pass
            if gfilled:
                db.commit()

        # Local scoring completes with the scan. Optional network work gets its
        # own background pass so it cannot extend the scan's busy state.
        _finish_album_scan(db)
    finally:
        with _scan_lock:
            _scan_running = False


@router.get("/library/artists")
def library_artists(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search filter"),
) -> dict:
    """Return paginated artists with track/album counts."""
    db = _get_db()
    rows, total = db.artists_page(limit=limit, offset=offset, query=q.strip())
    artists = [
        {
            "name": r["artist"],
            "track_count": r["track_count"],
            "album_count": r["album_count"],
            "cover_url": _local_cover_url(r.get("cover_path"), r.get("cover_art_available")),
        }
        for r in rows
    ]
    return {"artists": artists, "total": total}


@router.get("/library/albums")
def all_albums(q: str = Query("", description="Search filter")):
    """Return all albums in the local library as a gallery."""
    db = _get_db()
    albums = _album_cards(db)
    query = q.strip().casefold()
    if query:
        albums = [
            album for album in albums
            if query in album["name"].casefold()
            or query in album["artist"].casefold()
            or any(query in member.casefold() for member in album["members"])
        ]
    return {
        "albums": [
            {
                "id": a["id"],
                "name": a["name"],
                "artist": a["artist"],
                "track_count": a["track_count"],
                "cover_url": _local_cover_url(a.get("cover_path"), a.get("cover_art_available")),
                "best_quality": a.get("best_quality") or "",
                "members": a["members"],
                "possible_duplicate": a["possible_duplicate"],
                "assessments": a["assessments"],
            }
            for a in albums
        ],
        "total": len(albums),
    }


@router.get("/library/recent-albums")
def library_recent_albums(
    limit: int = Query(12, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    db = _get_db()
    rows = sorted(_album_cards(db), key=lambda row: -row["recent_at"])
    total = len(rows)
    rows = rows[offset:offset + limit]
    albums = [
        {
            "id": row["id"],
            "name": row["name"],
            "artist": row["artist"],
            "track_count": row["track_count"],
            "cover_url": _local_cover_url(row.get("cover_path"), row.get("cover_art_available")),
            "recent_at": row["recent_at"],
            "recent_source": row["recent_source"],
            "possible_duplicate": row["possible_duplicate"],
        }
        for row in rows
    ]
    return {"albums": albums, "total": total, "limit": limit, "offset": offset}


@router.get("/library/artist/{artist_name}/albums")
def artist_albums(artist_name: str):
    """Return all albums by an artist from the local library."""
    db = _get_db()
    albums = [album for album in _album_cards(db) if any(
        str(row.get("artist") or "").casefold() == artist_name.casefold()
        for row in album["tracks"]
    )]
    return {
        "artist": artist_name,
        "albums": [
            {
                "id": a["id"],
                "name": a["name"],
                "track_count": a["track_count"],
                "cover_url": _local_cover_url(a.get("cover_path"), a.get("cover_art_available")),
                "genres": ",".join(sorted({
                    str(row.get("genre")) for row in a["tracks"] if row.get("genre")
                })),
                "best_quality": a.get("best_quality") or "",
                "possible_duplicate": a["possible_duplicate"],
            }
            for a in albums
        ],
        "total": len(albums),
    }


@router.get("/library/artist/{artist_name}/album/{album_name}/tracks")
def artist_album_tracks(artist_name: str, album_name: str):
    """Return all tracks for a specific album by an artist."""
    db = _get_db()
    card = next((
        card for card in _album_cards(db)
        if album_name in card["members"]
        and (card["artist"] == artist_name or artist_name == "Various Artists")
    ), None)
    tracks = card["tracks"] if card else db.album_tracks(artist_name, album_name)
    return {
        "artist": artist_name,
        "album": album_name,
        "tracks": [_db_row_to_track(t) for t in tracks],
        "total": len(tracks),
    }


@router.get("/library/releases/{release_hash}/tracks")
def release_tracks(release_hash: str):
    db = _get_db()
    release_id = "release:" + release_hash
    card = next((card for card in _album_cards(db) if card["id"] == release_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Release not found")
    return {
        "id": card["id"],
        "artist": card["artist"],
        "album": card["name"],
        "tracks": [_db_row_to_track(track) for track in card["tracks"]],
        "total": card["track_count"],
    }


class GroupingDecisionRequest(BaseModel):
    left_signature: str
    right_signature: str
    decision: str
    canonical_title: str | None = None


@router.post("/library/grouping/decision")
def save_grouping_decision(body: GroupingDecisionRequest):
    from tidal_dl.helper.album_grouping import build_local_album_groups

    if body.decision not in {"group_together", "keep_separate"}:
        raise HTTPException(status_code=422, detail="Invalid grouping decision")
    db = _get_db()
    groups = {group.signature: group for group in build_local_album_groups(db.all_tracks())}
    left = groups.get(body.left_signature)
    right = groups.get(body.right_signature)
    if left is None or right is None:
        raise HTTPException(status_code=409, detail="Grouping assessment is stale")
    if body.decision == "group_together" and body.canonical_title not in {left.title, right.title}:
        raise HTTPException(status_code=422, detail="Canonical title must be a current member title")
    if not db.set_grouping_decision(
        body.left_signature,
        body.right_signature,
        decision=body.decision,
        canonical_title=body.canonical_title,
    ):
        raise HTTPException(status_code=409, detail="Grouping assessment is stale")
    db.commit()
    return {"status": "saved", "decision": body.decision}


def _art_cache_dir() -> Path:
    """Return (and create) the art cache directory."""
    d = Path(path_config_base()) / "art_cache"
    d.mkdir(exist_ok=True)
    return d


def _art_cache_key(path: str) -> str:
    """Stable cache filename from audio path."""
    import hashlib
    return hashlib.md5(path.encode()).hexdigest() + ".jpg"


@router.get("/library/art")
def library_art(path: str = Query(..., description="Absolute path to audio file")):
    """Extract and serve embedded album art from a local audio file. Disk-cached."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, Response

    from tidal_dl.gui.security import resolve_local_audio_path

    settings = Settings()
    allowed = [str(Path(settings.data.download_base_path).expanduser())]
    if settings.data.scan_paths:
        allowed.extend(str(Path(p.strip()).expanduser()) for p in settings.data.scan_paths.split(",") if p.strip())

    resolution = resolve_local_audio_path(
        path,
        allowed,
        library_trusts_raw_path=_path_in_library(path),
        library_resolved_path=_trusted_library_path(path),
    )
    if resolution.kind != "ok" or resolution.path is None:
        raise HTTPException(status_code=403, detail="Access denied")
    validated = resolution.path

    # Check disk cache only after the requested audio path is authorized.
    cache_dir = _art_cache_dir()
    cache_file = cache_dir / _art_cache_key(path)
    if cache_file.is_file():
        db = _get_db()
        row = db.get(path)
        if row and row.get("art_available") is None:
            db._conn.execute("UPDATE scanned SET art_available = 1 WHERE path = ?", (path,))
            db.commit()
        return FileResponse(
            cache_file, media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    art_data, art_mime = _read_local_art_bytes(validated)

    # Write to disk cache and return
    if art_data:
        cache_file.write_bytes(art_data)
        db = _get_db()
        row = db.get(path)
        if row and row.get("art_available") is None:
            db._conn.execute("UPDATE scanned SET art_available = 1 WHERE path = ?", (path,))
            db.commit()
        return Response(
            content=art_data, media_type=art_mime,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    db = _get_db()
    row = db.get(path)
    if row and row.get("art_available") is None:
        db._conn.execute("UPDATE scanned SET art_available = 0 WHERE path = ?", (path,))
        db.commit()
    return Response(content=_NO_ART_PNG, media_type="image/png")


@router.get("/library")
def library(
    sort: str = Query("recent", description="Sort: recent, artist, album, title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Search query (matches title, artist, album)"),
) -> dict:
    """Return a page of cached library from DB. Instant, no disk I/O."""
    db = _get_db()
    rows, total = db.tracks_page(sort=sort, limit=limit, offset=offset, query=q.strip())
    tracks = [_db_row_to_track(row) for row in rows]
    return {"tracks": tracks, "total": total, "scanning": _scan_running}


@router.get("/library/search")
def library_search(
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("tracks", description="Search type: tracks, albums, artists"),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Search the local library by title, artist, or album."""
    db = _get_db()

    if type == "tracks":
        rows, total = db.tracks_page(sort="artist", limit=limit, offset=0, query=q.strip())
        return {"tracks": [_db_row_to_track(r) for r in rows], "total": total}

    if type == "albums":
        query = q.strip().casefold()
        albums = [
            album for album in _album_cards(db)
            if query in album["name"].casefold()
            or query in album["artist"].casefold()
            or any(query in member.casefold() for member in album["members"])
        ]
        return {
            "albums": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "artist": a["artist"],
                    "track_count": a["track_count"],
                    "cover_url": _local_cover_url(a.get("cover_path"), a.get("cover_art_available")),
                    "is_local": True,
                    "possible_duplicate": a["possible_duplicate"],
                }
                for a in albums[:limit]
            ],
            "total": len(albums),
        }

    if type == "artists":
        assert db._conn
        like = f"%{q.strip()}%"
        rows = db._conn.execute(
            """SELECT s.artist, COUNT(*) as track_count, COUNT(DISTINCT album) as album_count,
                      MIN(s.path) as cover_path,
                      (SELECT s2.art_available FROM scanned s2
                       WHERE s2.artist = s.artist AND s2.status != 'unreadable'
                       ORDER BY s2.path ASC LIMIT 1) as cover_art_available
               FROM scanned s
               WHERE artist LIKE ? AND status != 'unreadable'
               GROUP BY artist ORDER BY track_count DESC LIMIT ?""",
            (like, limit),
        ).fetchall()
        return {
            "artists": [
                {
                    "name": r["artist"],
                    "track_count": r["track_count"],
                    "album_count": r["album_count"],
                    "cover_url": _local_cover_url(r["cover_path"], r["cover_art_available"]),
                    "is_local": True,
                }
                for r in rows
            ],
            "total": len(rows),
        }

    return {"error": "Unknown type", "total": 0}


@router.post("/library/scan")
def scan_library(
    rescan: bool = Query(False, description="Re-read all files, ignoring cache"),
) -> dict:
    """Kick off a background scan. Returns immediately."""
    global _scan_running, _scan_progress
    with _scan_lock:
        if _scan_running:
            return {"status": "already_running", **_scan_progress}
        _scan_running = True
        _scan_progress = {"scanned": 0, "total": 0, "done": False}

    thread = threading.Thread(target=_background_scan, args=(rescan,), daemon=True)
    thread.start()
    return {"status": "started"}


@router.get("/library/scan/status")
def scan_status() -> dict:
    """Check background scan progress."""
    with _scan_lock:
        return {"scanning": _scan_running, **_scan_progress}


class FavoriteToggleRequest(BaseModel):
    path: str | None = None
    tidal_id: int | None = None
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    isrc: str | None = None
    cover_url: str | None = None


@router.get("/library/favorites")
def get_favorites():
    """Return all favorited tracks."""
    db = _get_db()
    favs = db.all_favorites()
    total_duration = 0
    result = []
    for f in favs:
        quality = f.get("scanned_quality") or ""
        duration = f.get("scanned_duration") or 0
        if duration:
            total_duration += duration
        entry = {
            "id": f["id"],
            "path": f.get("path"),
            "local_path": f.get("path"),
            "tidal_id": f.get("tidal_id"),
            "artist": f.get("artist") or "Unknown Artist",
            "name": f.get("title") or "Unknown",
            "album": f.get("album") or "",
            "isrc": f.get("isrc") or "",
            "cover_url": f.get("cover_url") or "",
            "quality": quality,
            "format": f.get("scanned_format") or "",
            "codec": f.get("scanned_codec") or "unknown",
            "duration": duration,
            "favorited_at": f["favorited_at"],
            "is_local": bool(f.get("path")),
        }
        if entry["path"]:
            entry["cover_url"] = _local_cover_url(entry["path"], f.get("scanned_art_available"))
        result.append(entry)
    return {"favorites": result, "total": len(result), "total_duration": total_duration}


@router.get("/library/favorites/check")
def check_favorites(
    paths: str = Query("", description="Comma-separated paths"),
    tidal_ids: str = Query("", description="Comma-separated tidal IDs"),
):
    """Bulk check which items are favorited."""
    db = _get_db()
    fav_paths = db.favorite_paths()
    fav_tids = db.favorite_tidal_ids()

    result = {}
    if paths:
        for p in paths.split(","):
            p = p.strip()
            if p:
                result[p] = p in fav_paths
    if tidal_ids:
        for tid in tidal_ids.split(","):
            tid = tid.strip()
            if tid:
                result["tidal:" + tid] = int(tid) in fav_tids
    return {"favorites": result}


@router.post("/library/favorites/toggle")
def toggle_favorite(req: FavoriteToggleRequest):
    """Toggle favorite status. Returns new state."""
    db = _get_db()
    is_fav = db.is_favorite(path=req.path, tidal_id=req.tidal_id)

    if is_fav:
        db.remove_favorite(path=req.path, tidal_id=req.tidal_id)
    else:
        db.add_favorite(
            path=req.path,
            tidal_id=req.tidal_id,
            artist=req.artist,
            title=req.title,
            album=req.album,
            isrc=req.isrc,
            cover_url=req.cover_url,
        )
    db.commit()

    return {"favorited": not is_fav}
