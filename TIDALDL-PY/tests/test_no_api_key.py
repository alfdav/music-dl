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
        assert len(fields(s.data)) == 39

    def test_settings_default_quality(self, clear_singletons):
        from tidalapi import Quality
        s = Settings()
        assert s.data.quality_audio == Quality.low_320k

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
