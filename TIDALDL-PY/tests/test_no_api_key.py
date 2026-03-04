"""No-API-key tests for tidal-dl.

All tests in this file can run without a TIDAL API key.

Fixed failures (vs. prior run):
  - test_decrypt_security_token: build a properly CBC-encrypted token so the
    AES-CBC decryptor gets valid input (16-byte boundary).
  - test_decrypt_file: pass pathlib.Path objects (not plain str) to match
    the function signature of decrypt_file().
  - test_settings_save: use ``settings.file_path`` (the real attribute) not
    the non-existent ``settings.settings_path``.
  - test_path_file_sanitize_*: Linux does not sanitize ``:`` in filenames; the
    colon test is now marked ``skipif(not Windows)`` and platform-neutral tests
    are provided instead.
"""

import base64
import pathlib
import subprocess
import sys

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from tidal_dl.config import Settings
from tidal_dl.constants import MediaType
from tidal_dl.helper.camelot import (
    CamelotNotation,
    KeyScale,
    format_initial_key,
    key_to_alphanumeric,
    key_to_classic,
)
from tidal_dl.helper.decryption import decrypt_file, decrypt_security_token
from tidal_dl.helper.path import (
    check_file_exists,
    path_file_sanitize,
    url_to_filename,
)
from tidal_dl.helper.tidal import get_tidal_media_id, get_tidal_media_type
from tidal_dl.helper.cli import parse_timestamp


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

class TestURLParsing:
    """TIDAL URL parsing — no network required."""

    def test_track_url_type(self):
        url = "https://tidal.com/browse/track/12345678"
        assert get_tidal_media_type(url) == MediaType.TRACK

    def test_track_url_id(self):
        url = "https://tidal.com/browse/track/12345678"
        assert get_tidal_media_id(url) == "12345678"

    def test_album_url_type(self):
        url = "https://tidal.com/browse/album/87654321"
        assert get_tidal_media_type(url) == MediaType.ALBUM

    def test_album_url_id(self):
        url = "https://tidal.com/browse/album/87654321"
        assert get_tidal_media_id(url) == "87654321"

    def test_playlist_url(self):
        url = "https://tidal.com/browse/playlist/abc-def-123"
        assert get_tidal_media_type(url) == MediaType.PLAYLIST
        assert get_tidal_media_id(url) == "abc-def-123"

    def test_mix_url(self):
        url = "https://tidal.com/browse/mix/abc123def456"
        assert get_tidal_media_type(url) == MediaType.MIX
        assert get_tidal_media_id(url) == "abc123def456"

    def test_video_url(self):
        url = "https://tidal.com/browse/video/99887766"
        assert get_tidal_media_type(url) == MediaType.VIDEO
        assert get_tidal_media_id(url) == "99887766"

    def test_artist_url(self):
        url = "https://tidal.com/browse/artist/11223344"
        assert get_tidal_media_type(url) == MediaType.ARTIST
        assert get_tidal_media_id(url) == "11223344"

    def test_unknown_type_returns_false(self):
        url = "https://tidal.com/browse/unknown/99999"
        assert get_tidal_media_type(url) is False

    def test_id_strips_query_string(self):
        url = "https://tidal.com/browse/track/12345678?u"
        assert get_tidal_media_id(url) == "12345678"


# ---------------------------------------------------------------------------
# AES decryption helpers
# ---------------------------------------------------------------------------

def _make_security_token(key: bytes, nonce: bytes) -> str:
    """Build a valid TIDAL-style security token (CBC-encrypted, base64-encoded).

    Protocol:
      token_bytes = IV (16 bytes) || AES-CBC(master_key, IV, key || nonce || padding)
      security_token = base64(token_bytes)

    The plaintext must be a multiple of 16 bytes; we pad key+nonce (24 bytes)
    with 8 zero bytes to reach 32 bytes.
    """
    master_key = base64.b64decode("UIlTTEMmmLfGowo/UC60x2H45W6MdGgTRfo/umg4754=")
    plaintext = key + nonce + b"\x00" * 8  # 16 + 8 + 8 = 32 bytes (2 AES blocks)
    iv = b"\xab" * 16
    encryptor = AES.new(master_key, AES.MODE_CBC, iv)
    encrypted = encryptor.encrypt(plaintext)
    return base64.b64encode(iv + encrypted).decode()


class TestDecryption:
    """AES decryption helpers — no network required."""

    # --- decrypt_security_token ---

    def test_decrypt_security_token_returns_known_key(self):
        known_key = b"\x11" * 16
        known_nonce = b"\x22" * 8
        token = _make_security_token(known_key, known_nonce)
        key, nonce = decrypt_security_token(token)
        assert key == known_key

    def test_decrypt_security_token_returns_known_nonce(self):
        known_key = b"\x33" * 16
        known_nonce = b"\x44" * 8
        token = _make_security_token(known_key, known_nonce)
        key, nonce = decrypt_security_token(token)
        assert nonce == known_nonce

    def test_decrypt_security_token_key_length(self):
        token = _make_security_token(b"\xaa" * 16, b"\xbb" * 8)
        key, nonce = decrypt_security_token(token)
        assert len(key) == 16

    def test_decrypt_security_token_nonce_length(self):
        token = _make_security_token(b"\xcc" * 16, b"\xdd" * 8)
        key, nonce = decrypt_security_token(token)
        assert len(nonce) == 8

    def test_decrypt_security_token_different_tokens_differ(self):
        t1 = _make_security_token(b"\x01" * 16, b"\x02" * 8)
        t2 = _make_security_token(b"\x03" * 16, b"\x04" * 8)
        k1, n1 = decrypt_security_token(t1)
        k2, n2 = decrypt_security_token(t2)
        assert k1 != k2
        assert n1 != n2

    # --- decrypt_file ---

    def test_decrypt_file_roundtrip(self, tmp_path: pathlib.Path):
        """Encrypt data with AES-CTR then decrypt it; result must match original."""
        key = b"\xcc" * 16
        nonce = b"\xdd" * 8
        original_data = b"Hello TIDAL audio stream data!" * 100

        enc_path = tmp_path / "encrypted.bin"
        dec_path = tmp_path / "decrypted.bin"

        # Encrypt using the same AES-CTR setup that decrypt_file will reverse
        counter = Counter.new(64, prefix=nonce, initial_value=0)
        encryptor = AES.new(key, AES.MODE_CTR, counter=counter)
        enc_path.write_bytes(encryptor.encrypt(original_data))

        # decrypt_file expects pathlib.Path arguments — NOT plain strings
        decrypt_file(enc_path, dec_path, key, nonce)

        assert dec_path.read_bytes() == original_data

    def test_decrypt_file_creates_output(self, tmp_path: pathlib.Path):
        """Verify that decrypt_file creates the destination file."""
        key = b"\x11" * 16
        nonce = b"\x22" * 8

        enc_path = tmp_path / "enc.bin"
        dec_path = tmp_path / "dec.bin"

        counter = Counter.new(64, prefix=nonce, initial_value=0)
        encryptor = AES.new(key, AES.MODE_CTR, counter=counter)
        enc_path.write_bytes(encryptor.encrypt(b"data"))

        decrypt_file(enc_path, dec_path, key, nonce)

        assert dec_path.exists()


# ---------------------------------------------------------------------------
# Camelot key notation
# ---------------------------------------------------------------------------

class TestCamelot:
    """Camelot key notation — no network required."""

    def test_c_major_alphanumeric(self):
        assert key_to_alphanumeric("C", KeyScale.MAJOR) == "8B"

    def test_g_minor_alphanumeric(self):
        assert key_to_alphanumeric("G", KeyScale.MINOR) == "6A"

    def test_fsharp_major_alphanumeric(self):
        assert key_to_alphanumeric("FSharp", KeyScale.MAJOR) == "2B"

    def test_fsharp_minor_alphanumeric(self):
        assert key_to_alphanumeric("FSharp", KeyScale.MINOR) == "11A"

    def test_invalid_key_returns_none(self):
        assert key_to_alphanumeric("H", KeyScale.MAJOR) is None

    def test_fsharp_classic_minor(self):
        assert key_to_classic("FSharp", KeyScale.MINOR) == "F#m"

    def test_fsharp_classic_major(self):
        assert key_to_classic("FSharp", KeyScale.MAJOR) == "Gb"

    def test_format_unknown_key_classic(self):
        assert format_initial_key("UNKNOWN", "MAJOR", CamelotNotation.CLASSIC) == ""

    def test_format_unknown_key_alphanumeric(self):
        assert format_initial_key("UNKNOWN", "MINOR", CamelotNotation.ALPHANUMERIC) == ""

    def test_format_c_major_alphanumeric(self):
        assert format_initial_key("C", "MAJOR", CamelotNotation.ALPHANUMERIC) == "8B"

    def test_format_g_minor_classic(self):
        assert format_initial_key("G", "MINOR", CamelotNotation.CLASSIC) == "Gm"

    def test_format_fsharp_minor_classic(self):
        assert format_initial_key("FSharp", "MINOR", CamelotNotation.CLASSIC) == "F#m"

    def test_format_fsharp_major_alphanumeric(self):
        assert format_initial_key("FSharp", "MAJOR", CamelotNotation.ALPHANUMERIC) == "2B"

    def test_format_unknown_scale(self):
        assert format_initial_key("C", "UNKNOWN", CamelotNotation.CLASSIC) == ""

    def test_format_invalid_format_string(self):
        assert format_initial_key("C", "MAJOR", "invalid_format") == ""


# ---------------------------------------------------------------------------
# Settings / config
# ---------------------------------------------------------------------------

class TestSettings:
    """Settings singleton — no network required."""

    def test_settings_loads_without_error(self, clear_singletons):
        s = Settings()
        assert s.data is not None

    def test_settings_has_expected_field_count(self, clear_singletons):
        from dataclasses import fields
        s = Settings()
        assert len(fields(s.data)) == 42  # updated: +2 for api_cache_enabled, api_cache_ttl_sec

    def test_settings_default_quality(self, clear_singletons, tmp_path, monkeypatch):
        from tidalapi import Quality
        # Point to a non-existent file so Settings falls back to dataclass defaults.
        monkeypatch.setattr(
            "tidal_dl.config.path_file_settings",
            lambda: str(tmp_path / "settings.json"),
        )
        s = Settings()
        assert s.data.quality_audio == Quality.hi_res_lossless

    def test_settings_default_base_path(self, clear_singletons):
        s = Settings()
        assert s.data.download_base_path == "~/download"

    def test_settings_save_writes_file(self, clear_singletons, tmp_path):
        """save() must write to file_path — the correct attribute name."""
        s = Settings()
        # Override to temp dir so we don't touch the real config
        s.file_path = str(tmp_path / "settings.json")
        s.path_base = str(tmp_path)

        s.save()

        assert (tmp_path / "settings.json").exists()

    def test_settings_save_produces_valid_json(self, clear_singletons, tmp_path):
        import json

        s = Settings()
        s.file_path = str(tmp_path / "settings.json")
        s.path_base = str(tmp_path)
        s.save()

        with open(s.file_path) as f:
            loaded = json.load(f)

        assert "skip_existing" in loaded
        assert "quality_audio" in loaded

    def test_settings_file_path_attribute_exists(self, clear_singletons):
        """Ensure Settings has a file_path attribute (was a source of failure)."""
        s = Settings()
        assert hasattr(s, "file_path")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestPathHelpers:
    """Path utilities — no network required."""

    # check_file_exists

    def test_check_file_exists_nonexistent(self):
        p = pathlib.Path("/tmp/this_file_does_not_exist_tidal_dl_test_xyz.flac")
        assert check_file_exists(p) is False

    def test_check_file_exists_real_file(self, tmp_path):
        p = tmp_path / "exists.flac"
        p.write_bytes(b"")
        assert check_file_exists(p) is True

    def test_check_file_exists_extension_ignore(self, tmp_path):
        # Create a .flac file, then check existence ignoring extension from .mp3
        flac = tmp_path / "track.flac"
        flac.write_bytes(b"")
        mp3 = tmp_path / "track.mp3"
        assert check_file_exists(mp3, extension_ignore=True) is True

    # url_to_filename

    def test_url_to_filename_jpg(self):
        url = "https://resources.tidal.com/images/abc123/640x640.jpg"
        result = url_to_filename(url)
        assert result == "640x640.jpg"

    def test_url_to_filename_ts(self):
        url = "https://pr-od.cf.tidal.com/1234/5678.ts"
        result = url_to_filename(url)
        assert result == "5678.ts"

    def test_url_to_filename_traversal_raises(self):
        # url_to_filename detects URL-encoded path separators (%2F) which would
        # allow traversal when decoded.  Plain '/' in the URL is handled by
        # posixpath.basename and does NOT trigger the guard.
        bad_url = "https://example.com/legit/foo%2F..%2Fetc%2Fpasswd"
        with pytest.raises(ValueError):
            url_to_filename(bad_url)

    # path_file_sanitize — platform-neutral tests

    def test_path_file_sanitize_returns_path(self):
        p = pathlib.Path("/tmp/normal_artist_track.flac")
        result = path_file_sanitize(p)
        assert isinstance(result, pathlib.Path)

    def test_path_file_sanitize_preserves_clean_name(self):
        p = pathlib.Path("/tmp/Artist - Track Title.flac")
        result = path_file_sanitize(p)
        assert result.name == "Artist - Track Title.flac"

    def test_path_file_sanitize_preserves_extension(self):
        p = pathlib.Path("/tmp/song.flac")
        result = path_file_sanitize(p)
        assert result.suffix == ".flac"

    def test_path_file_sanitize_uniquify_no_conflict(self, tmp_path):
        p = tmp_path / "nonexistent.flac"
        result = path_file_sanitize(p, uniquify=True)
        # No file exists → no suffix appended
        assert result.stem == "nonexistent"

    def test_path_file_sanitize_uniquify_with_conflict(self, tmp_path):
        p = tmp_path / "duplicate.flac"
        p.write_bytes(b"")  # create the file so uniquify triggers
        result = path_file_sanitize(p, uniquify=True)
        # After the fix to path_file_uniquify the extension must be preserved
        assert result.stem.startswith("duplicate")
        assert result.stem != "duplicate"
        assert result.suffix == ".flac"

    @pytest.mark.skipif(sys.platform != "win32", reason="Colon is only invalid in filenames on Windows")
    def test_path_file_sanitize_colon_windows_only(self):
        """On Windows, colons in filenames must be replaced."""
        p = pathlib.Path("C:/tmp/Artist: Track.flac")
        result = path_file_sanitize(p)
        assert ":" not in result.name


# ---------------------------------------------------------------------------
# IsrcIndex
# ---------------------------------------------------------------------------

class TestIsrcIndex:
    """IsrcIndex — persistent ISRC duplicate-detection index. No network."""

    def test_empty_on_missing_file(self, tmp_path):
        from tidal_dl.helper.isrc_index import IsrcIndex
        idx = IsrcIndex(tmp_path / "isrc.json")
        idx.load()  # file does not exist
        assert idx.size == 0

    def test_add_and_contains_live_file(self, tmp_path):
        from tidal_dl.helper.isrc_index import IsrcIndex
        track = tmp_path / "track.flac"
        track.write_bytes(b"")
        idx = IsrcIndex(tmp_path / "isrc.json")
        idx.add("USRC12345678", track)
        assert idx.contains("USRC12345678")

    def test_contains_returns_false_for_unknown_isrc(self, tmp_path):
        from tidal_dl.helper.isrc_index import IsrcIndex
        idx = IsrcIndex(tmp_path / "isrc.json")
        assert not idx.contains("UNKNOWN")

    def test_contains_returns_false_for_empty_isrc(self, tmp_path):
        from tidal_dl.helper.isrc_index import IsrcIndex
        idx = IsrcIndex(tmp_path / "isrc.json")
        assert not idx.contains("")

    def test_stale_entry_pruned(self, tmp_path):
        """A file that existed during add() but was deleted should not match."""
        from tidal_dl.helper.isrc_index import IsrcIndex
        track = tmp_path / "gone.flac"
        track.write_bytes(b"")
        idx = IsrcIndex(tmp_path / "isrc.json")
        idx.add("GBSTALE0001", track)
        track.unlink()  # delete the file
        assert not idx.contains("GBSTALE0001")
        # Stale entry should have been pruned from the in-memory dict
        assert idx.size == 0

    def test_save_and_reload(self, tmp_path):
        """Persisted index is correctly deserialised."""
        from tidal_dl.helper.isrc_index import IsrcIndex
        index_path = tmp_path / "isrc.json"
        track = tmp_path / "persisted.flac"
        track.write_bytes(b"")

        idx = IsrcIndex(index_path)
        idx.add("GBPERS0001", track)
        idx.save()

        idx2 = IsrcIndex(index_path)
        idx2.load()
        assert idx2.contains("GBPERS0001")

    def test_corrupt_file_handled_gracefully(self, tmp_path):
        from tidal_dl.helper.isrc_index import IsrcIndex
        index_path = tmp_path / "corrupt.json"
        index_path.write_text("not valid json {{{")  # corrupt
        idx = IsrcIndex(index_path)
        idx.load()  # must not raise
        assert idx.size == 0

    def test_thread_safety_concurrent_adds(self, tmp_path):
        """Concurrent add() calls must not corrupt the index."""
        import threading
        from tidal_dl.helper.isrc_index import IsrcIndex
        idx = IsrcIndex(tmp_path / "isrc.json")

        tracks = []
        for i in range(20):
            t = tmp_path / f"track_{i:02d}.flac"
            t.write_bytes(b"")
            tracks.append((f"ISRC{i:08d}", t))

        threads = [threading.Thread(target=lambda item=item: idx.add(*item)) for item in tracks]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert idx.size == 20


# ---------------------------------------------------------------------------
# playlist_populate consolidation
# ---------------------------------------------------------------------------

class TestPlaylistPopulate:
    """playlist_populate multi-dir M3U consolidation — no network."""

    def _make_dl(self, fn_logger=None):
        """Return a bare Download instance with just enough state to call playlist_populate."""
        from unittest.mock import MagicMock
        from tidal_dl.download import Download

        dl = Download.__new__(Download)
        dl.fn_logger = fn_logger or MagicMock()
        return dl

    def test_single_dir_creates_m3u_in_that_dir(self, tmp_path):
        track = tmp_path / "track.flac"
        track.write_bytes(b"")
        dl = self._make_dl()
        result = dl.playlist_populate({tmp_path}, "My Album", is_album=True, sort_alphabetically=True)
        assert len(result) == 1
        assert result[0].parent == tmp_path

    def test_single_dir_m3u_lists_track(self, tmp_path):
        track = tmp_path / "track.flac"
        track.write_bytes(b"")
        dl = self._make_dl()
        result = dl.playlist_populate({tmp_path}, "My Album", is_album=True, sort_alphabetically=True)
        content = result[0].read_text(encoding="utf-8")
        assert "track.flac" in content

    def test_multi_dir_creates_single_m3u_at_common_parent(self, tmp_path):
        """Two disc dirs → one M3U at album root."""
        cd1 = tmp_path / "CD1"
        cd2 = tmp_path / "CD2"
        cd1.mkdir()
        cd2.mkdir()
        (cd1 / "01 Track.flac").write_bytes(b"")
        (cd2 / "01 Track.flac").write_bytes(b"")

        dl = self._make_dl()
        result = dl.playlist_populate({cd1, cd2}, "Double Album", is_album=True, sort_alphabetically=True)

        # Only one M3U created, at the common parent (tmp_path)
        assert len(result) == 1
        assert result[0].parent == tmp_path

    def test_multi_dir_m3u_contains_relative_paths(self, tmp_path):
        """Paths in the M3U must be relative to the M3U's location."""
        cd1 = tmp_path / "CD1"
        cd2 = tmp_path / "CD2"
        cd1.mkdir()
        cd2.mkdir()
        (cd1 / "song_a.flac").write_bytes(b"")
        (cd2 / "song_b.flac").write_bytes(b"")

        dl = self._make_dl()
        result = dl.playlist_populate({cd1, cd2}, "Multi Disc", is_album=True, sort_alphabetically=True)
        content = result[0].read_text(encoding="utf-8")

        # Both tracks must appear; paths must be relative (not absolute)
        assert any("song_a.flac" in line for line in content.splitlines())
        assert any("song_b.flac" in line for line in content.splitlines())
        for line in content.splitlines():
            if line.strip():
                assert not pathlib.Path(line.strip()).is_absolute(), f"Path should be relative: {line!r}"

    def test_empty_dirs_scoped_returns_empty(self, tmp_path):
        dl = self._make_dl()
        result = dl.playlist_populate(set(), "Empty", is_album=False, sort_alphabetically=False)
        assert result == []

    def test_multi_dir_m3u_sorted_alphabetically(self, tmp_path):
        """CD1 tracks appear before CD2 tracks after alphabetic sort."""
        cd1 = tmp_path / "CD1"
        cd2 = tmp_path / "CD2"
        cd1.mkdir()
        cd2.mkdir()
        (cd1 / "aaa.flac").write_bytes(b"")
        (cd2 / "zzz.flac").write_bytes(b"")

        dl = self._make_dl()
        result = dl.playlist_populate({cd1, cd2}, "Sort Test", is_album=True, sort_alphabetically=True)
        lines = [line.strip() for line in result[0].read_text().splitlines() if line.strip()]
        assert lines[0].endswith("aaa.flac")
        assert lines[1].endswith("zzz.flac")


# ---------------------------------------------------------------------------
# Timestamp parsing (CLI helper)
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    """parse_timestamp helper — no network required."""

    def test_unix_integer(self):
        from datetime import UTC
        result = parse_timestamp("1705330200")
        assert result.year == 2024
        assert result.tzinfo == UTC

    def test_iso_date_only(self):
        from datetime import UTC
        result = parse_timestamp("2024-01-15")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo == UTC

    def test_iso_datetime_T(self):
        from datetime import UTC
        result = parse_timestamp("2024-01-15T14:30:45")
        assert result.hour == 14
        assert result.minute == 30
        assert result.tzinfo == UTC

    def test_invalid_raises(self):
        import typer
        with pytest.raises(typer.BadParameter):
            parse_timestamp("not-a-timestamp")


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------

class TestTTLCache:
    """TTLCache — thread-safe TTL cache. No network."""

    def test_cache_hit(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        c.set("k", "value")
        assert c.get("k") == "value"

    def test_cache_miss_unknown_key(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        assert c.get("missing") is None

    def test_cache_expiry(self):
        import time
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=0)  # expires immediately
        c.set("k", "stale")
        time.sleep(0.01)  # ensure monotonic clock advances
        assert c.get("k") is None

    def test_cache_expiry_prunes_entry(self):
        import time
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=0)
        c.set("k", "stale")
        time.sleep(0.01)
        c.get("k")  # triggers prune
        assert c.size == 0

    def test_cache_invalidate(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        c.set("k", "v")
        c.invalidate("k")
        assert c.get("k") is None

    def test_cache_invalidate_noop_on_missing(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        c.invalidate("nonexistent")  # must not raise

    def test_cache_clear(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size == 0

    def test_cache_size(self):
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)
        c.set("x", 10)
        c.set("y", 20)
        assert c.size == 2

    def test_cache_overwrite_resets_ttl(self):
        import time
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=1)
        c.set("k", "first")
        c.set("k", "second")  # overwrite — should refresh TTL
        assert c.get("k") == "second"

    def test_cache_thread_safety_concurrent_sets(self, tmp_path):
        """Concurrent set() calls must not corrupt the cache."""
        import threading
        from tidal_dl.helper.cache import TTLCache
        c = TTLCache(ttl_sec=60)

        def setter(i):
            c.set(f"key{i}", i)

        threads = [threading.Thread(target=setter, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert c.size == 50


# ---------------------------------------------------------------------------
# PlaylistImporter (parse_file only — no network)
# ---------------------------------------------------------------------------

class TestPlaylistImporter:
    """PlaylistImporter.parse_file — no network, no TIDAL session."""

    def _make_importer(self):
        """Return a PlaylistImporter with a dummy session (parse_file doesn't use it)."""
        from unittest.mock import MagicMock
        from tidal_dl.helper.playlist_import import PlaylistImporter
        return PlaylistImporter(session=MagicMock())

    def test_parse_csv_basic(self, tmp_path):
        f = tmp_path / "tracks.csv"
        f.write_text("title,artist,isrc\nBohemian Rhapsody,Queen,GBUM71029604\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 1
        assert entries[0].title == "Bohemian Rhapsody"
        assert entries[0].artist == "Queen"
        assert entries[0].isrc == "GBUM71029604"

    def test_parse_csv_missing_isrc_column(self, tmp_path):
        f = tmp_path / "no_isrc.csv"
        f.write_text("title,artist\nHotel California,Eagles\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 1
        assert entries[0].isrc == ""

    def test_parse_csv_multiple_rows(self, tmp_path):
        f = tmp_path / "multi.csv"
        f.write_text(
            "title,artist\nTrack A,Artist A\nTrack B,Artist B\nTrack C,Artist C\n",
            encoding="utf-8",
        )
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 3

    def test_parse_csv_skips_blank_rows(self, tmp_path):
        f = tmp_path / "blanks.csv"
        f.write_text("title,artist\nTrack A,Artist A\n,,\nTrack B,Artist B\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 2

    def test_parse_plain_basic(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("Queen - Bohemian Rhapsody\nEagles - Hotel California\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 2
        assert entries[0].artist == "Queen"
        assert entries[0].title == "Bohemian Rhapsody"

    def test_parse_plain_title_with_dash(self, tmp_path):
        """Titles containing ' - ' must be preserved correctly (split on first only)."""
        f = tmp_path / "dash.txt"
        f.write_text("Artist - Title - With - Many - Dashes\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert entries[0].artist == "Artist"
        assert entries[0].title == "Title - With - Many - Dashes"

    def test_parse_plain_skips_comments(self, tmp_path):
        f = tmp_path / "comments.txt"
        f.write_text("# This is a comment\nQueen - Radio Ga Ga\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 1

    def test_parse_plain_skips_blank_lines(self, tmp_path):
        f = tmp_path / "blanks.txt"
        f.write_text("\nQueen - Radio Ga Ga\n\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert len(entries) == 1

    def test_parse_plain_isrc_is_empty(self, tmp_path):
        f = tmp_path / "plain_isrc.txt"
        f.write_text("Artist - Song Title\n", encoding="utf-8")
        importer = self._make_importer()
        entries = importer.parse_file(f)
        assert entries[0].isrc == ""


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

class TestCLI:
    """Basic CLI invocation — no network required."""

    def test_version_command(self):
        result = subprocess.run(
            ["tidal-dl", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "3.0.0" in result.stdout

    def test_help_command(self):
        result = subprocess.run(
            ["tidal-dl", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "dl" in result.stdout.lower()
