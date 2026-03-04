"""Mutagen-based metadata writer supporting FLAC, MP3, and MP4 containers."""

import pathlib

import mutagen
from mutagen import flac, id3, mp4
from mutagen.id3 import APIC, SYLT, TALB, TBPM, TCOM, TCOP, TDRC, TIT2, TKEY, TPE1, TPE2, TPOS, TRCK, TSRC, TXXX, USLT, WOAS


class Metadata:
    """Write metadata tags to a media file.

    Supports FLAC, MP3 (ID3), and MP4/M4A containers.

    Attributes:
        path_file (str | pathlib.Path): Path to the media file.
        title (str): Track title.
        album (str): Album name.
        albumartist (str): Album artist string.
        artists (str): Track artist string.
        ... (see __init__ for full list)
    """

    path_file: str | pathlib.Path
    title: str
    album: str
    albumartist: str
    artists: str
    copy_right: str
    tracknumber: int
    discnumber: int
    totaldisc: int
    totaltrack: int
    date: str
    composer: str
    isrc: str
    lyrics: str
    lyrics_unsynced: str
    cover_data: bytes | None
    album_replay_gain: float
    album_peak_amplitude: float
    track_replay_gain: float
    track_peak_amplitude: float
    url_share: str
    replay_gain_write: bool
    upc: str
    target_upc: dict[str, str]
    explicit: bool
    bpm: int
    initial_key: str
    m: mutagen.FileType

    def __init__(
        self,
        path_file: str | pathlib.Path,
        target_upc: dict[str, str],
        album: str = "",
        title: str = "",
        artists: str = "",
        copy_right: str = "",
        tracknumber: int = 0,
        discnumber: int = 0,
        totaltrack: int = 0,
        totaldisc: int = 0,
        composer: str = "",
        isrc: str = "",
        albumartist: str = "",
        date: str = "",
        lyrics: str = "",
        lyrics_unsynced: str = "",
        cover_data: bytes | None = None,
        album_replay_gain: float = 1.0,
        album_peak_amplitude: float = 1.0,
        track_replay_gain: float = 1.0,
        track_peak_amplitude: float = 1.0,
        url_share: str = "",
        replay_gain_write: bool = True,
        upc: str = "",
        explicit: bool = False,
        bpm: int = 0,
        initial_key: str = "",
    ) -> None:
        self.path_file = path_file
        self.title = title
        self.album = album
        self.albumartist = albumartist
        self.artists = artists
        self.copy_right = copy_right
        self.tracknumber = tracknumber
        self.discnumber = discnumber
        self.totaldisc = totaldisc
        self.totaltrack = totaltrack
        self.date = date
        self.composer = composer
        self.isrc = isrc
        self.lyrics = lyrics
        self.lyrics_unsynced = lyrics_unsynced
        self.cover_data = cover_data
        self.album_replay_gain = album_replay_gain
        self.album_peak_amplitude = album_peak_amplitude
        self.track_replay_gain = track_replay_gain
        self.track_peak_amplitude = track_peak_amplitude
        self.url_share = url_share
        self.replay_gain_write = replay_gain_write
        self.upc = upc
        self.target_upc = target_upc
        self.explicit = explicit
        self.bpm = bpm
        self.initial_key = initial_key
        self.m = mutagen.File(self.path_file)

    def _cover(self) -> bool:
        """Embed the cover image into the file.

        Returns:
            bool: True if cover was embedded.
        """
        if not self.cover_data:
            return False

        if isinstance(self.m, mutagen.flac.FLAC):
            flac_cover = flac.Picture()
            flac_cover.type = id3.PictureType.COVER_FRONT
            flac_cover.data = self.cover_data
            flac_cover.mime = "image/jpeg"
            self.m.clear_pictures()
            self.m.add_picture(flac_cover)
        elif isinstance(self.m, mutagen.mp3.MP3):
            self.m.tags.add(APIC(encoding=3, data=self.cover_data))
        elif isinstance(self.m, mutagen.mp4.MP4):
            self.m.tags["covr"] = [mp4.MP4Cover(self.cover_data)]

        return True

    def save(self) -> bool:
        """Write all tags and cover to the file.

        Returns:
            bool: True if tags were saved successfully.
        """
        if not self.m.tags:
            self.m.add_tags()

        if isinstance(self.m, mutagen.flac.FLAC):
            self.set_flac()
        elif isinstance(self.m, mutagen.mp3.MP3):
            self.set_mp3()
        elif isinstance(self.m, mutagen.mp4.MP4):
            self.set_mp4()

        self._cover()
        self.cleanup_tags()
        self.m.save()

        return True

    def set_flac(self) -> None:
        """Write Vorbis Comment tags for FLAC files."""
        self.m.tags["TITLE"] = self.title
        self.m.tags["ALBUM"] = self.album
        self.m.tags["ALBUMARTIST"] = self.albumartist
        self.m.tags["ARTIST"] = self.artists
        self.m.tags["COPYRIGHT"] = self.copy_right
        self.m.tags["TRACKNUMBER"] = str(self.tracknumber)
        self.m.tags["TRACKTOTAL"] = str(self.totaltrack)
        self.m.tags["DISCNUMBER"] = str(self.discnumber)
        self.m.tags["DISCTOTAL"] = str(self.totaldisc)
        self.m.tags["DATE"] = self.date
        self.m.tags["COMPOSER"] = self.composer
        self.m.tags["ISRC"] = self.isrc
        self.m.tags["LYRICS"] = self.lyrics
        self.m.tags["UNSYNCEDLYRICS"] = self.lyrics_unsynced
        self.m.tags["URL"] = self.url_share
        self.m.tags[self.target_upc["FLAC"]] = self.upc
        self.m.tags["BPM"] = str(self.bpm if self.bpm > 0 else "")
        self.m.tags["INITIALKEY"] = self.initial_key

        if self.replay_gain_write:
            self.m.tags["REPLAYGAIN_ALBUM_GAIN"] = str(self.album_replay_gain)
            self.m.tags["REPLAYGAIN_ALBUM_PEAK"] = str(self.album_peak_amplitude)
            self.m.tags["REPLAYGAIN_TRACK_GAIN"] = str(self.track_replay_gain)
            self.m.tags["REPLAYGAIN_TRACK_PEAK"] = str(self.track_peak_amplitude)

    def set_mp3(self) -> None:
        """Write ID3 tags for MP3 files."""
        self.m.tags.add(TIT2(encoding=3, text=self.title))
        self.m.tags.add(TALB(encoding=3, text=self.album))
        self.m.tags.add(TPE2(encoding=3, text=self.albumartist))  # Album artist (Band/Orchestra)
        self.m.tags.add(TPE1(encoding=3, text=self.artists))
        self.m.tags.add(TCOP(encoding=3, text=self.copy_right))
        self.m.tags.add(TRCK(encoding=3, text=f"{self.tracknumber}/{self.totaltrack}"))
        self.m.tags.add(TPOS(encoding=3, text=f"{self.discnumber}/{self.totaldisc}"))  # Disc number
        self.m.tags.add(TDRC(encoding=3, text=self.date))
        self.m.tags.add(TCOM(encoding=3, text=self.composer))
        self.m.tags.add(TSRC(encoding=3, text=self.isrc))
        self.m.tags.add(SYLT(encoding=3, desc="text", text=self.lyrics))
        self.m.tags.add(USLT(encoding=3, desc="text", text=self.lyrics_unsynced))
        self.m.tags.add(WOAS(text=self.url_share))  # Official Audio Source URL
        self.m.tags.add(TXXX(encoding=3, desc=self.target_upc["MP3"], text=self.upc))
        self.m.tags.add(TBPM(encoding=3, text=str(self.bpm if self.bpm > 0 else "")))
        self.m.tags.add(TKEY(encoding=3, text=self.initial_key))

        if self.replay_gain_write:
            self.m.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_ALBUM_GAIN", text=str(self.album_replay_gain)))
            self.m.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_ALBUM_PEAK", text=str(self.album_peak_amplitude)))
            self.m.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=str(self.track_replay_gain)))
            self.m.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text=str(self.track_peak_amplitude)))

    def set_mp4(self) -> None:
        """Write iTunes-style atoms for MP4/M4A files."""
        self.m.tags["\xa9nam"] = self.title
        self.m.tags["\xa9alb"] = self.album
        self.m.tags["aART"] = self.albumartist
        self.m.tags["\xa9ART"] = self.artists
        self.m.tags["cprt"] = self.copy_right
        self.m.tags["trkn"] = [[self.tracknumber, self.totaltrack]]
        self.m.tags["disk"] = [[self.discnumber, self.totaldisc]]
        self.m.tags["\xa9day"] = self.date
        self.m.tags["\xa9wrt"] = self.composer
        self.m.tags["\xa9lyr"] = self.lyrics
        self.m.tags["----:com.apple.iTunes:UNSYNCEDLYRICS"] = self.lyrics_unsynced.encode("utf-8")
        self.m.tags["isrc"] = self.isrc
        self.m.tags["\xa9url"] = self.url_share
        self.m.tags[f"----:com.apple.iTunes:{self.target_upc['MP4']}"] = self.upc.encode("utf-8")
        self.m.tags["rtng"] = [1 if self.explicit else 0]

        if self.bpm > 0:
            self.m.tags["tmpo"] = [self.bpm]

        self.m.tags["----:com.apple.iTunes:initialkey"] = self.initial_key.encode("utf-8")

        if self.replay_gain_write:
            self.m.tags["----:com.apple.iTunes:REPLAYGAIN_ALBUM_GAIN"] = str(self.album_replay_gain).encode("utf-8")
            self.m.tags["----:com.apple.iTunes:REPLAYGAIN_ALBUM_PEAK"] = str(self.album_peak_amplitude).encode("utf-8")
            self.m.tags["----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"] = str(self.track_replay_gain).encode("utf-8")
            self.m.tags["----:com.apple.iTunes:REPLAYGAIN_TRACK_PEAK"] = str(self.track_peak_amplitude).encode("utf-8")

    def cleanup_tags(self) -> None:
        """Remove empty tag values to keep the file clean."""
        keys_to_delete = [key for key, value in self.m.tags.items() if value in ("", [""])]

        for key in keys_to_delete:
            del self.m.tags[key]
