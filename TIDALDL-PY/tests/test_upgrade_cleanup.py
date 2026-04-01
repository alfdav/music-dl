import os

from tidal_dl.gui.api.upgrade import _cleanup_replaced_track_files
from tidal_dl.helper.library_db import LibraryDB


def test_cleanup_replaced_track_files_removes_stale_same_isrc_rows_and_files(tmp_path, monkeypatch):
    db = LibraryDB(tmp_path / "library.db")
    db.open()

    old_path = tmp_path / "old.flac"
    existing_upgrade = tmp_path / "existing-upgrade.flac"
    new_path = tmp_path / "new-upgrade_01.flac"
    for p in (old_path, existing_upgrade, new_path):
        p.write_bytes(b"audio")

    db.record(
        str(old_path),
        status="tagged",
        isrc="US-TST-00-00001",
        artist="Artist",
        title="Song",
        album="Album",
        quality="44100Hz/16bit",
        fmt="FLAC",
    )
    db.record(
        str(existing_upgrade),
        status="tagged",
        isrc="US-TST-00-00001",
        artist="Artist",
        title="Song",
        album="Album",
        quality="96000Hz/24bit",
        fmt="FLAC",
    )
    db.record(
        str(new_path),
        status="tagged",
        isrc="US-TST-00-00001",
        artist="Artist",
        title="Song",
        album="Album",
        quality="96000Hz/24bit",
        fmt="FLAC",
    )
    db.commit()

    trashed = []

    def _fake_trash(path: str) -> None:
        trashed.append(path)
        if os.path.exists(path):
            os.remove(path)

    monkeypatch.setattr("tidal_dl.gui.api.upgrade._trash_file", _fake_trash)

    removed = _cleanup_replaced_track_files(db, old_path=str(old_path), new_path=str(new_path))
    db.commit()

    assert set(removed) == {str(old_path), str(existing_upgrade)}
    assert not old_path.exists()
    assert not existing_upgrade.exists()
    assert new_path.exists()
    assert db.get(str(old_path)) is None
    assert db.get(str(existing_upgrade)) is None
    assert db.get(str(new_path)) is not None
    assert trashed == [str(old_path), str(existing_upgrade)]

    db.close()
