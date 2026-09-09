"""Product-wide local identity: a live library file stamps is_local / local_path.

Search, album detail, playlists, and the player bar all consume the same
stamp so a file on disk cannot keep showing a download affordance.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tidal_dl.helper.album_grouping import compatible_title, normalize_text
from tidal_dl.helper.library_scanner import path_has_skipped_scan_dir
from tidal_dl.helper.path import _album_identity, _strip_codec_brackets, resolve_live_library_path

_FEAT_MARKER = re.compile(
    r"\s*[\(\[]\s*(?:feat(?:uring)?\.?|ft\.?|with)\s+[^\)\]]+[\)\]]",
    re.IGNORECASE,
)
_LEFTOVER_TITLE_MARKER = re.compile(
    r"\s*[\(\[]\s*(?:explicit|clean|bonus(?:\s+track)?|deluxe(?:\s+edition)?)\s*[\)\]]\s*$",
    re.IGNORECASE,
)
_CATALOG_QUALITY = "_catalog_quality"


def fold_identity(value: object | None) -> str:
    return normalize_text(value)


def album_identity_key(album: object | None, artist: object | None = "") -> str:
    return _album_identity(str(album or ""), str(artist or ""))


def albums_compatible(left: object | None, right: object | None, artist: object | None = "") -> bool:
    if not left or not right:
        return False
    keyed = album_identity_key(left, artist)
    if keyed and keyed == album_identity_key(right, artist):
        return True
    bare_left = album_identity_key(left, "")
    bare_right = album_identity_key(right, "")
    return bool(bare_left) and bare_left == bare_right


def artists_compatible(left: object | None, right: object | None) -> bool:
    first = fold_identity(left)
    second = fold_identity(right)
    if not first or not second:
        return False
    if first == second:
        return True
    return first in second or second in first


def titles_compatible(left: object | None, right: object | None) -> bool:
    return compatible_title(str(left or ""), str(right or ""))


def recording_title(value: object | None) -> str:
    """Fold a title while keeping remix / live / radio-edit version tokens.

    Feature credits and leftover codec brackets are the same recording.
    Stripping every trailing parenthetical would collapse those versions
    onto the original and let shortest-path pick the wrong file.
    """
    title = _strip_codec_brackets(str(value or "").strip())
    while True:
        stripped = _FEAT_MARKER.sub("", title)
        stripped = _LEFTOVER_TITLE_MARKER.sub("", stripped)
        stripped = re.sub(r"\s{2,}", " ", stripped).strip()
        if stripped == title:
            return fold_identity(title)
        title = stripped


def _title_variants(*values: object | None) -> set[str]:
    variants: set[str] = set()
    for value in values:
        if not value:
            continue
        folded = fold_identity(value)
        if folded:
            variants.add(folded)
        recording = recording_title(value)
        if recording:
            variants.add(recording)
    return variants


def identity_path_for_row(row: Mapping[str, Any]) -> str | None:
    """Prefer a live file, including a layout-moved sibling of a stale index path.

    If the indexed parent is missing (unmounted volume or a unit-test stub),
    keep the indexed path so identity still stamps. A parent that exists
    without the file means the recording is gone.
    """
    path = row.get("path") or ""
    if not path or path_has_skipped_scan_dir(path):
        return None
    live = resolve_live_library_path(path)
    if live:
        return live
    parent = Path(path).parent
    try:
        parent_exists = parent.exists()
    except OSError:
        return path
    if parent_exists:
        return None
    return path


def with_identity_path(row: Mapping[str, Any]) -> dict | None:
    live = identity_path_for_row(row)
    if not live:
        return None
    stamped = dict(row)
    indexed = str(row.get("indexed_path") or row.get("path") or "")
    if indexed:
        stamped["indexed_path"] = indexed
    stamped["path"] = live
    return stamped


def indexed_path_for_row(row: Mapping[str, Any] | None) -> str | None:
    """Scanned-key path for persist-heal. Identity may have already rewritten ``path``."""
    if not row:
        return None
    indexed = str(row.get("indexed_path") or row.get("path") or "").strip()
    return indexed or None


def artist_credit_queries(artist: str) -> list[str]:
    """Full credit string plus each comma-separated featured artist."""
    full = (artist or "").strip()
    credits: list[str] = []
    if full:
        credits.append(full)
    for part in full.split(","):
        part = part.strip()
        if part and part not in credits:
            credits.append(part)
    return credits


def _various_artists(value: object | None) -> bool:
    return fold_identity(value) == "various artists"


def _leftover_codec_album(row_album: object | None, album: str) -> bool:
    raw = str(row_album or "").strip()
    stripped = _strip_codec_brackets(raw)
    return bool(stripped) and fold_identity(stripped) == fold_identity(album) and stripped != raw


_DISC_DIR = re.compile(
    r"^(?:cd|disc|disk|vol(?:ume)?)\s*\d+$",
    re.IGNORECASE,
)


def _leftover_artist_album_dir(name: str, artist: str) -> bool:
    stripped = _strip_codec_brackets(str(name or "").strip())
    if " - " not in stripped:
        return False
    left, _right = stripped.split(" - ", 1)
    return bool(left) and artists_compatible(artist, left)


def _album_like_directory(directory: str | None, album: str, artist: str) -> bool:
    """True when a folder name is this album or a leftover Artist - Album dir."""
    if not directory:
        return False
    name = Path(directory).name
    if albums_compatible(name, album, artist):
        return True
    stripped = _strip_codec_brackets(name)
    if " - " not in stripped:
        return False
    left, right = stripped.split(" - ", 1)
    return bool(right) and artists_compatible(artist, left) and albums_compatible(right, album, artist)


def path_under_artist(path: object | None, artist: str) -> bool:
    """True when the album folder sits directly under the host artist directory."""
    folded = fold_identity(artist)
    if not folded or not path:
        return False
    album_dir = album_directory_key(path)
    if not album_dir:
        return False
    folder = Path(album_dir)
    if _leftover_artist_album_dir(folder.name, artist):
        return True
    artist_dir = folder.parent
    if not artist_dir.parts or artist_dir == artist_dir.anchor:
        return False
    return fold_identity(artist_dir.name) == folded


def album_directory_key(path: object | None) -> str | None:
    """Album folder for a file, skipping a trailing CD/Disc directory."""
    if not path:
        return None
    parent = Path(str(path)).parent
    if not parent.parts or parent == parent.anchor:
        return None
    if _DISC_DIR.match(parent.name.strip()):
        parent = parent.parent
        if not parent.parts or parent == parent.anchor:
            return None
    return str(parent)


def folder_siblings_for_album(
    host_rows: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    artist: str,
    album: str,
) -> list[dict]:
    """Keep same-folder rows after a host match, even when album_artist is empty."""
    host_dirs = {
        key for key in (album_directory_key(row.get("path")) for row in host_rows)
        if key and _album_like_directory(key, album, artist)
    }
    if not host_dirs:
        return []
    extra: list[dict] = []
    seen: set[str] = set()
    for row in candidates:
        path = str(row.get("path") or "")
        if not path or path in seen:
            continue
        if not albums_compatible(row.get("album"), album, artist or row.get("artist")):
            continue
        key = album_directory_key(path)
        if key not in host_dirs:
            continue
        extra.append(dict(row))
        seen.add(path)
    return extra


def filter_album_rows(
    rows: Iterable[Mapping[str, Any]],
    artist: str,
    album: str,
) -> list[dict]:
    matched: list[dict] = []
    various = _various_artists(artist)
    for row in rows:
        row_album = row.get("album")
        if not albums_compatible(row_album, album, artist or row.get("artist")):
            continue
        row_artist = row.get("artist")
        row_album_artist = row.get("album_artist")
        if various:
            # Guest credits stay via album_artist=VA. A leftover Album [FLAC]
            # from a solo artist is a different release.
            if row_album_artist and not _various_artists(row_album_artist):
                continue
            if (
                not row_album_artist
                and _leftover_codec_album(row_album, album)
                and row_artist
                and not _various_artists(row_artist)
            ):
                continue
        elif not (
            artists_compatible(artist, row_artist)
            or artists_compatible(artist, row_album_artist)
            or path_under_artist(row.get("path"), artist)
        ):
            continue
        matched.append(dict(row))
    return matched


def match_local_row(
    track: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    *,
    album_scoped: bool = False,
    scope_artist: str = "",
    scope_album: str = "",
) -> dict | None:
    """Pick one library row for a catalog track.

    Album-scoped callers (album lookup / Tidal album detail) may use ISRC
    only inside that release's rows so a shared ISRC cannot steal a file
    from another album.
    """
    rows = [dict(row) for row in candidates if row]
    if not rows:
        return None

    isrc = str(track.get("isrc") or "").strip()
    track_album = scope_album or str(track.get("album") or "")
    catalog_artist = str(track.get("artist") or "")
    album_artist = scope_artist or catalog_artist
    # Title matching uses the catalog track artist. Album scope_artist only
    # narrows the release — it must not replace a compilation/guest credit.
    title_artist = catalog_artist or ("" if _various_artists(scope_artist) else scope_artist)
    track_title = str(track.get("name") or track.get("title") or track.get("full_name") or "")
    track_titles = _title_variants(track.get("name"), track.get("title"), track.get("full_name"))

    def in_scope(row: Mapping[str, Any]) -> bool:
        if not album_scoped:
            return True
        if not track_album:
            return True
        return albums_compatible(row.get("album"), track_album, album_artist or row.get("artist"))

    if isrc:
        isrc_hits = [
            row for row in rows
            if str(row.get("isrc") or "").strip() == isrc and in_scope(row)
        ]
        picked = _pick_identity_row(isrc_hits, prefer_album=track_album, prefer_title=track_title)
        if picked:
            return picked

    title_hits: list[dict] = []
    for row in rows:
        if not in_scope(row):
            continue
        row_titles = _title_variants(row.get("title"))
        if not (track_titles & row_titles):
            continue
        if title_artist and not artists_compatible(title_artist, row.get("artist")):
            continue
        title_hits.append(row)

    if not album_scoped and len(title_hits) > 1 and track_album:
        album_hits = [
            row for row in title_hits
            if albums_compatible(row.get("album"), track_album, album_artist)
        ]
        if album_hits:
            title_hits = album_hits
        else:
            return None

    return _pick_identity_row(title_hits, prefer_album=track_album, prefer_title=track_title)


def _pick_identity_row(
    rows: list[dict],
    *,
    prefer_album: str = "",
    prefer_title: str = "",
) -> dict | None:
    live: list[dict] = []
    for row in rows:
        stamped = with_identity_path(row)
        if stamped:
            live.append(stamped)
    if not live:
        return None
    wanted_recording = recording_title(prefer_title)
    wanted_exact = fold_identity(prefer_title)
    live.sort(key=lambda row: (
        0 if albums_compatible(row.get("album"), prefer_album, row.get("artist")) else 1,
        0 if wanted_recording and recording_title(row.get("title")) == wanted_recording else 1,
        0 if wanted_exact and fold_identity(row.get("title")) == wanted_exact else 1,
        len(row.get("path") or ""),
        row.get("path") or "",
    ))
    return live[0]


def stamp_track(track: dict, row: Mapping[str, Any] | None) -> dict:
    """Write is_local plus path / local_path (and on-disk quality when present).

    ``playable`` is a local-file opinion: True when a row is stamped, omitted
    when the restamp misses. Clear leftover ``missing_since`` when playable.
    """
    if _CATALOG_QUALITY not in track and not track.get("format") and not track.get("codec"):
        track[_CATALOG_QUALITY] = track.get("quality")
    if not row:
        track["is_local"] = False
        track.pop("playable", None)
        track.pop("local_path", None)
        track.pop("path", None)
        track.pop("format", None)
        track.pop("codec", None)
        catalog = track.pop(_CATALOG_QUALITY, None)
        if catalog is not None:
            track["quality"] = catalog
        else:
            track.pop("quality", None)
        return track
    path = row.get("path") or ""
    track["is_local"] = True
    track["playable"] = True
    track["missing_since"] = None
    if path:
        track["local_path"] = path
        track["path"] = path
    if row.get("quality"):
        track["quality"] = row["quality"]
    if row.get("format"):
        track["format"] = row["format"]
    if row.get("codec"):
        track["codec"] = row["codec"]
    elif "codec" not in track:
        track["codec"] = "unknown"
    return track


def finish_stamp(track: dict) -> dict:
    """Drop internal catalog-quality stash before a track leaves the API."""
    track.pop(_CATALOG_QUALITY, None)
    return track


def candidate_rows_for_track(db: Any, track: Mapping[str, Any]) -> list[dict]:
    """Collect ISRC + title/artist rows from whatever the DB exposes."""
    isrc = str(track.get("isrc") or "").strip()
    title = str(track.get("name") or track.get("title") or "")
    artist = str(track.get("artist") or "")
    album = str(track.get("album") or "")
    if hasattr(db, "tracks_for_identity"):
        return list(db.tracks_for_identity(isrc=isrc, title=title, artist=artist, album=album) or [])

    seen: set[str] = set()
    rows: list[dict] = []

    def add(found: Iterable[Mapping[str, Any]] | None) -> None:
        for row in found or []:
            path = row.get("path") or ""
            if not path or path in seen:
                continue
            seen.add(path)
            rows.append(dict(row))

    if isrc and hasattr(db, "tracks_by_isrc"):
        add(db.tracks_by_isrc(isrc))
    if artist and hasattr(db, "tracks_for_artist"):
        for credit in artist_credit_queries(artist):
            add(db.tracks_for_artist(credit))
    if album and hasattr(db, "tracks_for_albums"):
        add(db.tracks_for_albums([album]))
    if hasattr(db, "all_tracks") and (not rows or (title and not isrc)):
        add(db.all_tracks())
    return rows
