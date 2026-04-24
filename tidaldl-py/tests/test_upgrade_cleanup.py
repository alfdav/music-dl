import os

from tidal_dl.gui.services.upgrade_jobs import cleanup_replaced_track_files
from tidal_dl.helper.library_db import LibraryDB


def test_cleanup_replaced_track_files_removes_stale_same_isrc_rows_and_files(tmp_path, monkeypatch):
    """Same ISRC, same album, same directory → all stale copies removed."""
    db = LibraryDB(tmp_path / "library.db")
    db.open()

    album_dir = tmp_path / "Artist" / "Album"
    album_dir.mkdir(parents=True)

    old_path = album_dir / "old.flac"
    existing_upgrade = album_dir / "existing-upgrade.flac"
    new_path = album_dir / "new-upgrade_01.flac"
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

    monkeypatch.setattr("tidal_dl.gui.services.upgrade_jobs.trash_file", _fake_trash)

    removed = cleanup_replaced_track_files(db, old_path=str(old_path), new_path=str(new_path))
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


def test_cleanup_preserves_same_isrc_in_different_albums(tmp_path, monkeypatch):
    """Same ISRC in a different album/directory must NOT be touched."""
    db = LibraryDB(tmp_path / "library.db")
    db.open()

    # Compilation album
    comp_dir = tmp_path / "Stevie Wonder" / "Number 1's"
    comp_dir.mkdir(parents=True)
    old_path = comp_dir / "Superstition.m4a"
    old_path.write_bytes(b"lossy")

    # Original album — same ISRC, different album
    orig_dir = tmp_path / "Stevie Wonder" / "Talking Book"
    orig_dir.mkdir(parents=True)
    orig_path = orig_dir / "Superstition.flac"
    orig_path.write_bytes(b"lossless")

    # Greatest hits — same ISRC, yet another album
    hits_dir = tmp_path / "Stevie Wonder" / "Greatest Hits"
    hits_dir.mkdir(parents=True)
    hits_path = hits_dir / "Superstition.flac"
    hits_path.write_bytes(b"lossless")

    # New upgraded file in the compilation
    new_path = comp_dir / "Superstition.flac"
    new_path.write_bytes(b"hires")

    db.record(str(old_path), status="tagged", isrc="USMO17200003",
              artist="Stevie Wonder", title="Superstition",
              album="Number 1's", quality="44100Hz/16bit", fmt="M4A")
    db.record(str(orig_path), status="tagged", isrc="USMO17200003",
              artist="Stevie Wonder", title="Superstition",
              album="Talking Book", quality="44100Hz/16bit", fmt="FLAC")
    db.record(str(hits_path), status="tagged", isrc="USMO17200003",
              artist="Stevie Wonder", title="Superstition",
              album="Greatest Hits", quality="44100Hz/16bit", fmt="FLAC")
    db.commit()

    trashed = []

    def _fake_trash(path: str) -> None:
        trashed.append(path)
        if os.path.exists(path):
            os.remove(path)

    monkeypatch.setattr("tidal_dl.gui.services.upgrade_jobs.trash_file", _fake_trash)

    removed = cleanup_replaced_track_files(db, old_path=str(old_path), new_path=str(new_path))
    db.commit()

    # Only the old compilation file should be removed
    assert removed == [str(old_path)]
    assert not old_path.exists()

    # Original album and greatest hits copies must survive
    assert orig_path.exists()
    assert hits_path.exists()
    assert db.get(str(orig_path)) is not None
    assert db.get(str(hits_path)) is not None

    db.close()


def test_cleanup_preserves_same_album_name_in_different_directory(tmp_path, monkeypatch):
    """Edge case: same album name but different parent directory (different artist).
    Should NOT be cleaned up."""
    db = LibraryDB(tmp_path / "library.db")
    db.open()

    dir_a = tmp_path / "Artist A" / "Hits"
    dir_a.mkdir(parents=True)
    old_path = dir_a / "Song.flac"
    old_path.write_bytes(b"audio")

    dir_b = tmp_path / "Artist B" / "Hits"
    dir_b.mkdir(parents=True)
    other_path = dir_b / "Song.flac"
    other_path.write_bytes(b"audio")

    new_path = dir_a / "Song_hires.flac"
    new_path.write_bytes(b"hires")

    db.record(str(old_path), status="tagged", isrc="ISRC001",
              artist="Artist A", title="Song", album="Hits",
              quality="44100Hz/16bit", fmt="FLAC")
    # Same album name "Hits" but different artist/directory
    db.record(str(other_path), status="tagged", isrc="ISRC001",
              artist="Artist B", title="Song", album="Hits",
              quality="44100Hz/16bit", fmt="FLAC")
    db.commit()

    trashed = []
    monkeypatch.setattr("tidal_dl.gui.services.upgrade_jobs.trash_file",
                        lambda p: trashed.append(p) or (os.remove(p) if os.path.exists(p) else None))

    removed = cleanup_replaced_track_files(db, old_path=str(old_path), new_path=str(new_path))
    db.commit()

    # Only old_path removed — other_path has same album name but different dir
    assert removed == [str(old_path)]
    assert other_path.exists()
    assert db.get(str(other_path)) is not None

    db.close()
