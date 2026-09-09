"""Release-level metadata extraction tests for the existing scan pass."""

from mutagen.id3 import ID3, TDRC, TPE2, TPOS, TRCK, TXXX

from tidal_dl.gui.api.library import _extract_release_metadata

EXPECTED = {
    "album_artist": "Marcos Witt",
    "release_date": "2011-03-15",
    "track_number": 4,
    "track_total": 30,
    "disc_number": 1,
    "disc_total": 2,
    "musicbrainz_release_id": "mb-release",
    "musicbrainz_release_group_id": "mb-group",
    "provider_namespace": "tidal",
    "provider_album_id": "12345",
    "barcode": "0081000000000",
}


def test_extracts_vorbis_release_tags_case_insensitively():
    tags = {
        "ALBUMARTIST": ["Marcos Witt"],
        "DATE": ["2011-03-15"],
        "TRACKNUMBER": ["4"],
        "TRACKTOTAL": ["30"],
        "DISCNUMBER": ["1"],
        "DISCTOTAL": ["2"],
        "MUSICBRAINZ_ALBUMID": ["mb-release"],
        "MUSICBRAINZ_RELEASEGROUPID": ["mb-group"],
        "TIDAL_ALBUM_ID": ["12345"],
        "BARCODE": ["0081000000000"],
    }

    assert _extract_release_metadata(tags, tags) == EXPECTED


def test_extracts_id3_release_frames():
    tags = ID3()
    tags.add(TPE2(encoding=3, text=["Marcos Witt"]))
    tags.add(TDRC(encoding=3, text=["2011-03-15"]))
    tags.add(TRCK(encoding=3, text=["4/30"]))
    tags.add(TPOS(encoding=3, text=["1/2"]))
    for description, value in (
        ("MusicBrainz Album Id", "mb-release"),
        ("MusicBrainz Release Group Id", "mb-group"),
        ("TIDAL_ALBUM_ID", "12345"),
        ("BARCODE", "0081000000000"),
    ):
        tags.add(TXXX(encoding=3, desc=description, text=[value]))

    assert _extract_release_metadata({}, tags) == EXPECTED


def test_extracts_mp4_release_atoms():
    tags = {
        "aART": ["Marcos Witt"],
        "\xa9day": ["2011-03-15"],
        "trkn": [(4, 30)],
        "disk": [(1, 2)],
        "----:com.apple.iTunes:MusicBrainz Album Id": [b"mb-release"],
        "----:com.apple.iTunes:MusicBrainz Release Group Id": [b"mb-group"],
        "----:com.apple.iTunes:TIDAL_ALBUM_ID": [b"12345"],
        "----:com.apple.iTunes:UPC": [b"0081000000000"],
    }

    assert _extract_release_metadata({}, tags) == EXPECTED


def test_missing_release_tags_stay_null():
    assert _extract_release_metadata({}, {}) == {
        key: None for key in EXPECTED
    }


def test_extracts_spaced_and_multivalue_album_artist_tags():
    """Vorbis ALBUM ARTIST and multi-value ALBUMARTIST must both land."""
    spaced = _extract_release_metadata({}, {"ALBUM ARTIST": ["Nia Coltrane; Juniper Vale"]})
    assert spaced["album_artist"] == "Nia Coltrane; Juniper Vale"

    multi = _extract_release_metadata({}, {"ALBUMARTIST": ["Nia Coltrane", "Juniper Vale"]})
    assert "Nia Coltrane" in (multi["album_artist"] or "")
    assert "Juniper Vale" in (multi["album_artist"] or "")
