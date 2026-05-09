from types import SimpleNamespace


def _track(*, name="Song", artists=None, duration=180, track_id=123, isrc="US123"):
    return SimpleNamespace(
        id=track_id,
        name=name,
        full_name=name,
        artists=[SimpleNamespace(name=a) for a in (artists or [])],
        duration=duration,
        isrc=isrc,
        audio_quality="HI_RES_LOSSLESS",
        media_metadata_tags=["HI_RES_LOSSLESS"],
    )


class _Session:
    def __init__(self, tracks):
        self.tracks = tracks
        self.queries = []

    def search(self, query, models=None, limit=10):
        self.queries.append(query)
        return {"tracks": self.tracks}


def test_probe_tidal_meta_matches_when_local_artist_is_primary_and_tidal_has_collaborator():
    from tidal_dl.gui.api.upgrade import _probe_tidal_meta

    session = _Session([
        _track(name="Song", artists=["Main Artist", "Featured Artist"], track_id=456, isrc="US-COLLAB-1")
    ])

    result = _probe_tidal_meta(session, "Song", "Main Artist", duration=180)

    assert result is not None
    assert result["tidal_track_id"] == 456
    assert result["isrc"] == "US-COLLAB-1"


def test_probe_tidal_meta_matches_when_local_artist_contains_collaborator_separator():
    from tidal_dl.gui.api.upgrade import _probe_tidal_meta

    session = _Session([
        _track(name="Song", artists=["Main Artist", "Featured Artist"], track_id=789, isrc="US-COLLAB-2")
    ])

    result = _probe_tidal_meta(session, "Song", "Main Artist feat. Featured Artist", duration=180)

    assert result is not None
    assert result["tidal_track_id"] == 789


def test_probe_tidal_meta_still_rejects_different_artist_with_shared_prefix():
    from tidal_dl.gui.api.upgrade import _probe_tidal_meta

    session = _Session([
        _track(name="Song", artists=["Main Artist Bell"], track_id=999, isrc="US-WRONG")
    ])

    result = _probe_tidal_meta(session, "Song", "Main Artist", duration=180)

    assert result is None
