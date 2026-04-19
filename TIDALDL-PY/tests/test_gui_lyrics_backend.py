from pathlib import Path


class DummyInfo:
    def __init__(self, length: float = 0.0):
        self.length = length


class DummyUSLT:
    def __init__(self, text: str, desc: str = "", lang: str = "eng"):
        self.text = text
        self.desc = desc
        self.lang = lang


class DummyAudio:
    def __init__(self, tags=None, length: float = 0.0):
        self.tags = tags or {}
        self.info = DummyInfo(length)


def _audio_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"fake")
    return path


def test_sidecar_synced_beats_embedded_unsynced(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.flac")
    track.with_suffix(".lrc").write_text("[00:01.00]Hello\n[00:02.00]World\n", encoding="utf-8")

    monkeypatch.setattr(
        "tidal_dl.gui.lyrics_local.MutagenFile",
        lambda path: DummyAudio(tags={"UNSYNCEDLYRICS": ["embedded plain"]}, length=10.0),
    )

    payload = read_local_lyrics(track)

    assert payload["mode"] == "synced"
    assert payload["source"] == "lrc-synced"
    assert [line["text"] for line in payload["lines"]] == ["Hello", "World"]


def test_plain_lrc_loses_to_valid_embedded_synced(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.m4a")
    track.with_suffix(".lrc").write_text("plain words only\n", encoding="utf-8")

    monkeypatch.setattr(
        "tidal_dl.gui.lyrics_local.MutagenFile",
        lambda path: DummyAudio(tags={"©lyr": ["[00:03.00]Timed line"]}, length=9.0),
    )

    payload = read_local_lyrics(track)

    assert payload["mode"] == "synced"
    assert payload["source"] == "embedded-synced"
    assert payload["lines"][0]["text"] == "Timed line"


def test_empty_unsynced_text_downgrades_to_none(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.flac")
    track.with_suffix(".lrc").write_text("[ar:artist]\n[offset:100]\n[]\n", encoding="utf-8")

    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: DummyAudio(length=0.0))

    payload = read_local_lyrics(track)

    assert payload["mode"] == "none"
    assert payload["source"] == "none"
    assert payload["text"] == ""
    assert payload["lines"] == []


def test_ambiguous_case_insensitive_sidecars_are_ignored(tmp_path, monkeypatch):
    from pathlib import Path

    from tidal_dl.gui.lyrics_local import read_local_lyrics

    class FakeChild:
        def __init__(self, name: str):
            self.name = name

        def is_file(self) -> bool:
            return True

        def is_symlink(self) -> bool:
            return False

    track = _audio_file(tmp_path, "track.flac")
    monkeypatch.setattr(Path, "iterdir", lambda self: [FakeChild("track.LRC"), FakeChild("TRACK.lrc")])
    monkeypatch.setattr(
        "tidal_dl.gui.lyrics_local.MutagenFile",
        lambda path: DummyAudio(tags={"UNSYNCEDLYRICS": ["embedded fallback"]}, length=0.0),
    )

    payload = read_local_lyrics(track)

    assert payload["mode"] == "unsynced"
    assert payload["source"] == "embedded-unsynced"
    assert payload["text"] == "embedded fallback"


def test_decode_order_and_offset_clamp_are_applied():
    from tidal_dl.gui.lyrics_local import decode_lrc_bytes, parse_lrc_text

    text = decode_lrc_bytes("\ufeff[offset:-2000]\r\n[00:01.50]Hello\r\n".encode("utf-8-sig"))
    lines, plain_text = parse_lrc_text(text)

    assert plain_text == "Hello"
    assert lines == [{"start_ms": 0, "text": "Hello"}]


def test_multi_timestamp_lines_expand_and_non_timestamp_lines_are_ignored():
    from tidal_dl.gui.lyrics_local import parse_lrc_text

    lines, plain_text = parse_lrc_text("[00:01.00][00:02.00]Twin\nloose text\n")

    assert lines == [
        {"start_ms": 1000, "text": "Twin"},
        {"start_ms": 2000, "text": "Twin"},
    ]
    assert plain_text == "Twin\nloose text"


def test_mp3_uslt_priority_prefers_empty_desc_english(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.mp3")
    audio = DummyAudio(
        tags={
            "USLT:zzz": DummyUSLT("wrong", desc="comment", lang="zzz"),
            "USLT:eng:comment": DummyUSLT("second", desc="comment", lang="eng"),
            "USLT:eng": DummyUSLT("first", desc="", lang="eng"),
        },
        length=0.0,
    )
    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: audio)

    payload = read_local_lyrics(track)

    assert payload["mode"] == "unsynced"
    assert payload["text"] == "first"


def test_m4a_multi_value_atom_selection_and_unsynced_tag(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.m4a")
    audio = DummyAudio(
        tags={
            "©lyr": ["", "[00:03.00]chosen timed"],
            "----:com.apple.iTunes:UNSYNCEDLYRICS": [b"backup plain"],
        },
        length=8.0,
    )
    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: audio)

    payload = read_local_lyrics(track)

    assert payload["mode"] == "synced"
    assert payload["source"] == "embedded-synced"
    assert payload["lines"][0]["text"] == "chosen timed"


def test_flac_multi_value_selection_and_unsynced_fallback(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.flac")
    audio = DummyAudio(
        tags={
            "LYRICS": ["", "plain words only"],
            "UNSYNCEDLYRICS": ["picked unsynced"],
        },
        length=0.0,
    )
    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: audio)

    payload = read_local_lyrics(track)

    assert payload["mode"] == "unsynced"
    assert payload["source"] == "embedded-unsynced"
    assert payload["text"] == "plain words only"


def test_normalization_merges_duplicates_and_uses_duration_fallback():
    from tidal_dl.gui.lyrics_local import normalize_synced_lines

    lines = normalize_synced_lines(
        [
            {"start_ms": 1000, "text": "A"},
            {"start_ms": 1000, "text": "B"},
            {"start_ms": 3000, "text": "C"},
        ],
        duration_ms=0,
    )

    assert lines == [
        {"start_ms": 1000, "end_ms": 3000, "text": "A\nB"},
        {"start_ms": 3000, "end_ms": 7000, "text": "C"},
    ]


def test_sidecar_over_size_cap_ignored(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import MAX_LRC_BYTES, read_local_lyrics

    track = _audio_file(tmp_path, "track.flac")
    lrc = track.with_suffix(".lrc")
    lrc.write_bytes(b"[00:01.00]Hello\n" + b"x" * MAX_LRC_BYTES)

    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: DummyAudio(length=0.0))

    payload = read_local_lyrics(track)

    assert payload["mode"] == "none"


def test_sidecar_under_size_cap_read_normally(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    track = _audio_file(tmp_path, "track.flac")
    track.with_suffix(".lrc").write_text("[00:01.00]Hello\n[00:02.00]World\n", encoding="utf-8")

    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: DummyAudio(length=10.0))

    payload = read_local_lyrics(track)

    assert payload["mode"] == "synced"
    assert payload["source"] == "lrc-synced"
    assert payload["lines"][0]["text"] == "Hello"


def test_sidecar_symlink_ignored(tmp_path, monkeypatch):
    from tidal_dl.gui.lyrics_local import read_local_lyrics

    real_lrc = tmp_path / "external.lrc"
    real_lrc.write_text("[00:01.00]Secret\n", encoding="utf-8")

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    track = audio_dir / "track.flac"
    track.write_bytes(b"fake")

    lrc_symlink = audio_dir / "track.lrc"
    lrc_symlink.symlink_to(real_lrc)

    monkeypatch.setattr("tidal_dl.gui.lyrics_local.MutagenFile", lambda path: DummyAudio(length=0.0))

    payload = read_local_lyrics(track)

    assert payload["mode"] == "none"
