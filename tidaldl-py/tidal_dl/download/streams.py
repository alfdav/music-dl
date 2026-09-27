"""Download streams helpers."""

from tidal_dl.download._common import *
from tidal_dl.download.quality import (
    delivered_quality_label,
    delivery_is_cd_lossless,
    fetch_track_manifest_formats,
    hifi_quality_param,
    is_preview_presentation,
    remember_session_hires_fallback,
    session_can_deliver_hires,
    should_require_hires_delivery,
    tidal_offers_hires,
)


class QualityMismatchError(ValueError):
    """The provider cannot satisfy the selected audio-quality contract."""


class PreviewStreamError(ValueError):
    """The provider returned a preview clip instead of the full track.

    This is not a quality mismatch. Callers fall through to the next source
    instead of saving the clip or fail-closing the track.
    """


_LOSSLESS_TIERS = frozenset({"LOSSLESS", "HI_RES", "HI_RES_LOSSLESS"})
_HIRES_TIERS = frozenset({"HI_RES", "HI_RES_LOSSLESS"})
_EXPECTED_CODECS = {
    "LOW": ("aac", "mp4a"),
    "HIGH": ("aac", "mp4a"),
    "LOSSLESS": ("flac",),
    "HI_RES": ("flac",),
    "HI_RES_LOSSLESS": ("flac",),
}


def _stream_media_label(media: object) -> str:
    """Label a track for logs without requiring a fully built tidalapi object."""
    title = getattr(media, "name", None) or getattr(media, "title", None) or getattr(media, "id", "track")
    artist = getattr(media, "artist", None)
    artist_name = getattr(artist, "name", None) if artist is not None else None
    if artist_name:
        return f"{artist_name} - {title}"
    return str(title)


def is_flac_codec(codecs: str | None) -> bool:
    """True when the stream codec is FLAC (Hi-Res or CD lossless)."""
    return "FLAC" in (codecs or "").upper()


def mp4_box_contains_flac(path: pathlib.Path) -> bool:
    """True when an MP4/M4A box carries a FLAC sample (fLaC / dfLa)."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 8 or data[4:8] != b"ftyp":
        return False
    return b"fLaC" in data or b"dfLa" in data


def plan_flac_output(codecs: str | None, file_extension: str, extract_flac: bool) -> tuple[str, bool]:
    """Force a native .flac dest when the audio codec is FLAC.

    Tidal often labels FLAC as audio/mp4. That is a container, not a lossy default.
    Always plan extract when extract_flac is on — the bytes may still be an MP4 box
    even if mime+codec already report `.flac`.
    """
    if not is_flac_codec(codecs):
        return file_extension, False
    return str(AudioExtensions.FLAC), bool(extract_flac)


def _track_lists_hires(media: Track) -> bool:
    return tidal_offers_hires(getattr(media, "media_metadata_tags", None), None)


def _requested_wants_hires(requested: Quality | str | None) -> bool:
    return bool(requested) and quality_name(requested).upper() in _HIRES_TIERS


def _delivery_is_cd_lossless(
    quality: Quality | str | None,
    bit_depth: int | None = None,
    sample_rate: int | None = None,
    representation_id: str | None = None,
) -> bool:
    return delivery_is_cd_lossless(quality, bit_depth, sample_rate, representation_id)


def _require_exact_quality(requested: Quality | str, delivered: Quality | str | None, codec: str | None) -> None:
    """Accept the best available delivery that stays in the requested family.

    Settings quality is a ceiling, not an exact-match requirement. A Hi-Res
    preference may fall back to Blue Lossless FLAC when that is all Tidal has.
    Lossy AAC/MP4A is still rejected when a lossless tier was requested.
    """
    requested_name = quality_name(requested).upper()
    delivered_name = quality_name(delivered).upper() if delivered else "unknown"
    codec_name = (codec or "unknown").strip().lower() or "unknown"
    requested_codecs = _EXPECTED_CODECS.get(requested_name)
    delivered_codecs = _EXPECTED_CODECS.get(delivered_name)
    same_family = (
        requested_name in _LOSSLESS_TIERS and delivered_name in _LOSSLESS_TIERS
    ) or requested_name == delivered_name

    if (
        requested_codecs is None
        or delivered_codecs is None
        or not same_family
        or not codec_name.startswith(delivered_codecs)
    ):
        raise QualityMismatchError(
            f"Quality mismatch: requested {requested_name if requested_codecs else 'unknown'} "
            f"but received {delivered_name if delivered_name in _EXPECTED_CODECS else 'unknown'} "
            f"with codec {codec_name}."
        )


class StreamMixin:
    def _pace_stream_api(self, enabled: bool) -> float:
        """Pace Tidal stream-info/auth API calls. No-op when disabled."""
        pace = getattr(self, "_pace_tidal_api", None)
        if callable(pace):
            return pace(enabled=enabled)
        if not enabled:
            return 0.0
        from tidal_dl.download.api_pacing import shared_pacer

        return shared_pacer().wait_before_api(
            enabled=True,
            event_stop=getattr(self, "event_abort", None),
        )

    def _requested_audio_quality(self, quality_audio: Quality | None = None) -> Quality | None:
        if quality_audio is not None:
            return quality_audio
        return getattr(self.session, "audio_quality", None)

    def _bind_call_quality(
        self, quality_audio: Quality | None, quality_video: QualityVideo | None
    ) -> tuple[Quality | None, QualityVideo | None, bool, bool]:
        old_audio: Quality | None = None
        old_video: QualityVideo | None = None
        bound_audio = False
        bound_video = False
        if quality_audio is not None:
            old_audio = getattr(self.session, "audio_quality", None)
            self.session.audio_quality = quality_audio
            bound_audio = True
        if quality_video is not None:
            data = getattr(getattr(self, "settings", None), "data", None)
            if data is not None and hasattr(data, "quality_video"):
                old_video = data.quality_video
                data.quality_video = quality_video
                bound_video = True
        return old_audio, old_video, bound_audio, bound_video

    def _restore_call_quality(
        self,
        old_audio: Quality | None,
        old_video: QualityVideo | None,
        bound_audio: bool,
        bound_video: bool,
    ) -> None:
        if bound_audio:
            self.session.audio_quality = old_audio
        if bound_video:
            self.settings.data.quality_video = old_video

    def _get_track_stream_info_hifi(
        self, media: Track, quality_audio: Quality | None = None, *, pace_api: bool = False
    ) -> TrackStreamInfo:
        """Fetch stream info via the Hi-Fi API client and wrap it in a HiFiStreamManifest.

        Every Hi-Fi stream-info request goes through ``_pace_stream_api`` here so
        callers (primary Hi-Fi path and listed-Hi-Res fallback) cannot skip the
        shared API pacer. Media/CDN byte transfer is not paced.

        Args:
            media (Track): The track to fetch.
            quality_audio (Quality | None): Per-call quality. Defaults to session quality.
            pace_api (bool): Wait on the shared Tidal API pacer before the request.

        Returns:
            TrackStreamInfo: Stream info with a HiFiStreamManifest as the manifest.

        Raises:
            Exception: Propagates any exception from the Hi-Fi client so the caller
                       can decide whether to fall back to OAuth.
        """
        requested = self._requested_audio_quality(quality_audio)
        quality_str = hifi_quality_param(requested)
        hifi_client = self.tidal.hifi_client
        if hifi_client is None:
            raise RuntimeError("Hi-Fi client is not configured")
        self._pace_stream_api(pace_api)
        result = hifi_client.track_stream(media.id, quality_str)
        if is_preview_presentation(getattr(result, "asset_presentation", None)):
            raise PreviewStreamError(
                f"Hi-Fi returned assetPresentation PREVIEW at {result.audio_quality} "
                f"for track {media.id}. That clip is not the full track."
            )
        _require_exact_quality(requested, result.audio_quality, result.codecs)
        file_extension, requires_flac_extraction = plan_flac_output(
            result.codecs, result.file_extension, self.settings.data.extract_flac
        )
        manifest = HiFiStreamManifest(
            urls=result.urls,
            file_extension=file_extension,
            codecs=result.codecs,
            is_encrypted=result.encryption_type not in ("NONE", ""),
            encryption_key=None,
            audio_quality=result.audio_quality,
            bit_depth=result.bit_depth,
            sample_rate=result.sample_rate,
            asset_presentation=str(getattr(result, "asset_presentation", "") or ""),
        )
        return TrackStreamInfo(
            stream_manifest=manifest,
            file_extension=file_extension,
            requires_flac_extraction=requires_flac_extraction,
            media_stream=None,
        )

    def _ensure_hifi_client(self):
        if getattr(self.tidal, "hifi_client", None) is not None:
            return self.tidal.hifi_client
        from tidal_dl.hifi_api import HiFiApiClient

        instances = []
        configured = getattr(self.tidal, "_configured_hifi_instances", None)
        if callable(configured):
            instances = configured()
        self.tidal.hifi_client = HiFiApiClient(instances=instances or None)
        return self.tidal.hifi_client

    def _track_manifest_formats(self, media: Track, *, pace_api: bool = False) -> list[str] | None:
        session = getattr(self, "session", None)
        token = getattr(session, "access_token", None)
        track_id = getattr(media, "id", None)
        if not token or track_id is None:
            return None
        try:
            self._pace_stream_api(pace_api)
            return fetch_track_manifest_formats(str(token), track_id)
        except (TypeError, ValueError, OSError, requests.RequestException, AttributeError, KeyError):
            return None

    def _session_max_quality(self) -> object | None:
        return getattr(getattr(self, "tidal", None), "session_max_quality", None)

    def _accept_session_capped_cd(self) -> bool:
        """Accept CD when this login was measured below Hi-Res.

        Probe first when this login has not been measured yet (silent restore,
        CLI token start). Unprobed after that still fail-closes. Strict
        mismatch is only for a Hi-Res-capable (or still-unknown) session.
        """
        tidal = getattr(self, "tidal", None)
        ensure = getattr(tidal, "ensure_session_max_quality", None)
        if callable(ensure):
            ensure()
        elif session_can_deliver_hires(self._session_max_quality()) is None:
            probe = getattr(tidal, "_probe_subscription_quality", None)
            if callable(probe):
                probe()
        if session_can_deliver_hires(self._session_max_quality()) is not False:
            return False
        self._pending_session_capped_cd = True
        return True

    def _note_accepted_lossless_fallback(self) -> None:
        """Print the Lossless notice only after a file is actually kept."""
        if not getattr(self, "_pending_session_capped_cd", False):
            return
        self._pending_session_capped_cd = False
        remember_session_hires_fallback(getattr(self, "tidal", None), getattr(self, "fn_logger", None))

    def _record_last_delivered_quality(
        self,
        quality: Quality | str | None,
        bit_depth: int | None = None,
        sample_rate: int | None = None,
        representation_id: str | None = None,
    ) -> None:
        label = delivered_quality_label(quality, bit_depth, sample_rate, representation_id)
        if not label:
            return
        self.last_delivered_quality = label

    def _require_unencrypted_hires_if_offered(
        self,
        media: Track,
        quality: Quality | str | None,
        bit_depth: int | None,
        sample_rate: int | None,
        quality_audio: Quality | None,
        *,
        pace_api: bool = False,
    ) -> None:
        requested = self._requested_audio_quality(quality_audio)
        if not _requested_wants_hires(requested):
            return
        if not _delivery_is_cd_lossless(quality, bit_depth, sample_rate):
            return
        formats = self._track_manifest_formats(media, pace_api=pace_api)
        if not should_require_hires_delivery(True, _track_lists_hires(media), formats):
            return
        if self._accept_session_capped_cd():
            return
        requested_name = quality_name(requested).upper()
        delivered = quality_name(quality).upper() if quality else "LOSSLESS"
        offered = ""
        if formats and any(str(item).upper() == "FLAC_HIRES" for item in formats):
            offered = "; Tidal offers FLAC_HIRES"
        raise QualityMismatchError(
            f"Quality mismatch: requested {requested_name} for listed Hi-Res track "
            f"but received {delivered}{offered} and no unencrypted Hi-Res stream is available."
        )

    def _prefer_listed_hires(
        self,
        media: Track,
        oauth_info: TrackStreamInfo,
        quality_audio: Quality | None = None,
        pace_api: bool = False,
    ) -> TrackStreamInfo | None:
        """Upgrade a CD OAuth delivery to Hi-Res when Tidal actually offers it."""
        requested = self._requested_audio_quality(quality_audio)
        if not _requested_wants_hires(requested):
            return None
        stream = oauth_info.media_stream
        if not _delivery_is_cd_lossless(
            getattr(stream, "audio_quality", None),
            getattr(stream, "bit_depth", None),
            getattr(stream, "sample_rate", None),
        ):
            return None
        formats = self._track_manifest_formats(media, pace_api=pace_api)
        if not should_require_hires_delivery(True, _track_lists_hires(media), formats):
            return None
        try:
            self._ensure_hifi_client()
            hifi_info = self._get_track_stream_info_hifi(
                media, quality_audio=requested, pace_api=pace_api
            )
        except PreviewStreamError as exc:
            self.fn_logger.warning(
                f"Hi-Fi upgrade for '{_stream_media_label(media)}' was a PREVIEW, not the full track. {exc}"
            )
            hifi_info = None
        except (QualityMismatchError, RuntimeError, ValueError, OSError, requests.RequestException):
            hifi_info = None
        manifest = getattr(hifi_info, "stream_manifest", None)
        if manifest is not None and not _delivery_is_cd_lossless(
            getattr(manifest, "audio_quality", None),
            getattr(manifest, "bit_depth", None),
            getattr(manifest, "sample_rate", None),
        ):
            return hifi_info
        if self._accept_session_capped_cd():
            return None
        requested_name = quality_name(requested).upper()
        delivered = quality_name(getattr(stream, "audio_quality", None)).upper() if getattr(stream, "audio_quality", None) else "LOSSLESS"
        offered = ""
        if formats and any(str(item).upper() == "FLAC_HIRES" for item in formats):
            offered = "; Tidal offers FLAC_HIRES"
        raise QualityMismatchError(
            f"Quality mismatch: requested {requested_name} for listed Hi-Res track "
            f"but received {delivered}{offered} and no unencrypted Hi-Res stream is available."
        )

    def _get_stream_info(
        self,
        media: Track | Video,
        *,
        pace_api: bool = False,
        quality_audio: Quality | None = None,
        quality_video: QualityVideo | None = None,
    ) -> tuple[StreamManifest | HiFiStreamManifest | None, str, bool, Stream | None]:
        """Get stream information for media, routing through Hi-Fi API or OAuth path.

        For the Hi-Fi API source the stream lock is intentionally skipped because
        Hi-Fi requests are stateless and do not mutate the tidalapi session.  The
        OAuth path retains the broad lock to prevent the Atmos/Normal credential
        race condition described in the original comments below.

        Concurrent GUI workers share one Tidal session. Per-call quality is applied
        only for the locked get_stream window so peers cannot clobber each other.

        Args:
            media (Track | Video): Media item.

        Returns:
            tuple[StreamManifest | None, str, bool, Stream | None]: Stream info.
        """
        # ------------------------------------------------------------------
        # Hi-Fi API path (Track only) — stateless, no session lock required
        # ------------------------------------------------------------------
        if (
            isinstance(media, Track)
            and self.tidal.active_source == DownloadSource.HIFI_API
            and self.tidal.hifi_client is not None
        ):
            try:
                track_info = self._get_track_stream_info_hifi(
                    media, quality_audio=quality_audio, pace_api=pace_api
                )
                if track_info.stream_manifest is not None:
                    manifest = track_info.stream_manifest
                    self._require_unencrypted_hires_if_offered(
                        media,
                        getattr(manifest, "audio_quality", None),
                        getattr(manifest, "bit_depth", None),
                        getattr(manifest, "sample_rate", None),
                        quality_audio,
                        pace_api=pace_api,
                    )
                    self._record_last_delivered_quality(
                        getattr(manifest, "audio_quality", None),
                        getattr(manifest, "bit_depth", None),
                        getattr(manifest, "sample_rate", None),
                    )
                    return (
                        track_info.stream_manifest,
                        track_info.file_extension,
                        track_info.requires_flac_extraction,
                        track_info.media_stream,
                    )
            except QualityMismatchError:
                raise
            except PreviewStreamError as exc:
                message = (
                    f"Hi-Fi returned a PREVIEW for '{_stream_media_label(media)}', not the full track. {exc}"
                )
                allow_fallback = getattr(self.settings.data, "download_source_fallback", True)
                if not allow_fallback:
                    self.fn_logger.error(f"{message} Fallback is disabled. This track was not saved.")
                    return None, "", False, None
                self.fn_logger.warning(f"{message} Trying the next source.")
            except TooManyRequests:
                self._on_rate_limit_hit()
                self.fn_logger.exception(
                    f"Too many requests (Hi-Fi API). Skipping '{name_builder_item(media)}'.  "
                    f"Consider activating download delay."
                )
                return None, "", False, None
            except Exception:
                allow_fallback = getattr(self.settings.data, "download_source_fallback", True)
                if not allow_fallback:
                    self.fn_logger.exception(
                        f"Hi-Fi API failed for '{name_builder_item(media)}'. Fallback is disabled."
                    )
                    return None, "", False, None
                self.fn_logger.warning(f"Hi-Fi API failed for '{name_builder_item(media)}'. Falling back to OAuth.")
                # Fall through to OAuth path below

        # ------------------------------------------------------------------
        # OAuth path — CRITICAL: broad lock serializes session credential changes
        #
        # THE PROBLEM: The shared tidalapi session must switch credentials to
        # serve Atmos vs Hi-Res/Normal streams.  Without this lock a thread
        # could overwrite the credentials mid-flight in another thread.
        #
        # THE TRADEOFF: This creates a "tollbooth" bottleneck on stream-info
        # fetching; actual segment downloads still run in parallel.
        #
        # DO NOT "OPTIMIZE" THIS by making the lock more granular.
        # Correctness > Performance.
        # ------------------------------------------------------------------
        track_info: TrackStreamInfo | None = None
        with self.tidal.stream_lock:
            old_audio, old_video, bound_audio, bound_video = self._bind_call_quality(
                quality_audio, quality_video
            )
            try:
                # Proactively refresh a near-expiry OAuth token before the API call.
                self._pace_stream_api(pace_api)
                self.tidal._ensure_token_fresh()

                try:
                    if isinstance(media, Track):
                        track_info = self._get_track_stream_info(media)

                        if track_info.stream_manifest is None:
                            return None, "", False, None

                    elif isinstance(media, Video):
                        # Videos always require the normal session
                        if not self.tidal.restore_normal_session():
                            self.fn_logger.error(f"Failed to restore normal session for video: {media.id}")
                            return None, "", False, None

                        file_extension = str(
                            AudioExtensions.MP4 if self.settings.data.video_convert_mp4 else VideoExtensions.TS
                        )
                        return None, file_extension, False, None

                    else:
                        self.fn_logger.error(f"Unknown media type for stream info: {type(media)}")
                        return None, "", False, None

                except TooManyRequests:
                    self._on_rate_limit_hit()
                    self.fn_logger.exception(
                        f"Too many requests against TIDAL backend. Skipping '{name_builder_item(media)}'. "
                        f"Consider activating delay between downloads."
                    )
                    return None, "", False, None

                except QualityMismatchError:
                    raise
                except Exception:
                    self.fn_logger.exception(f"Something went wrong. Skipping '{name_builder_item(media)}'.")
                    return None, "", False, None
            finally:
                self._restore_call_quality(old_audio, old_video, bound_audio, bound_video)

        if isinstance(media, Track) and track_info is not None:
            upgraded = self._prefer_listed_hires(
                media, track_info, quality_audio=quality_audio, pace_api=pace_api
            )
            if upgraded is not None:
                track_info = upgraded
            stream = track_info.media_stream
            upgraded_manifest = getattr(track_info, "stream_manifest", None)
            delivered = None
            bit_depth = None
            sample_rate = None
            if upgraded_manifest is not None:
                delivered = getattr(upgraded_manifest, "audio_quality", None)
                bit_depth = getattr(upgraded_manifest, "bit_depth", None)
                sample_rate = getattr(upgraded_manifest, "sample_rate", None)
            if stream is not None:
                if delivered is None:
                    delivered = getattr(stream, "audio_quality", None)
                if bit_depth is None:
                    bit_depth = getattr(stream, "bit_depth", None)
                if sample_rate is None:
                    sample_rate = getattr(stream, "sample_rate", None)
            self._record_last_delivered_quality(delivered, bit_depth, sample_rate)
            return (
                track_info.stream_manifest,
                track_info.file_extension,
                track_info.requires_flac_extraction,
                track_info.media_stream,
            )

        return None, "", False, None

    def _track_needs_login_session(self, media: Track) -> bool:
        """Hi-Fi builds Track with object.__new__, so get_stream has no session.

        Doubles that replace get_stream keep their own method. A real tidalapi
        Track without session or requests is loaded through the login session.
        """
        if type(media).get_stream is not Track.get_stream:
            return False
        return getattr(media, "session", None) is None or getattr(media, "requests", None) is None

    def _get_track_stream_info(self, media: Track) -> TrackStreamInfo:
        """Get stream info for a Track, handling Atmos/Normal session switching.

        Args:
            media: The track to get stream information for.

        Returns:
            TrackStreamInfo: Container with stream manifest, file extension,
                            FLAC extraction flag, and media stream object.
                            Returns TrackStreamInfo with None/empty values if fails.
        """
        want_atmos = (
            self.settings.data.download_dolby_atmos
            and hasattr(media, "audio_modes")
            and str(AudioMode.dolby_atmos) in [str(mode) for mode in getattr(media, "audio_modes", [])]
        )

        if want_atmos:
            if not self.tidal.switch_to_atmos_session():
                self.fn_logger.error(f"Failed to switch to Atmos session for track: {media.id}")
                return TrackStreamInfo(None, "", False, None)
        else:
            if not self.tidal.restore_normal_session():
                self.fn_logger.error(f"Failed to restore normal session for track: {media.id}")
                return TrackStreamInfo(None, "", False, None)

        if want_atmos or self._track_needs_login_session(media):
            media_stream = self.session.track(str(media.id)).get_stream()
        else:
            media_stream = media.get_stream()

        stream_manifest = media_stream.get_stream_manifest()
        if not want_atmos:
            _require_exact_quality(self.session.audio_quality, media_stream.audio_quality, stream_manifest.codecs)
        file_extension, requires_flac_extraction = plan_flac_output(
            stream_manifest.codecs, str(stream_manifest.file_extension), self.settings.data.extract_flac
        )

        return TrackStreamInfo(
            stream_manifest=stream_manifest,
            file_extension=file_extension,
            requires_flac_extraction=requires_flac_extraction,
            media_stream=media_stream,
        )
