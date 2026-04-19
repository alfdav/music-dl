"""Discord bot frontend for music-dl.

Provides slash commands to trigger Tidal downloads, check queue status,
and search the library — all from Discord. Reuses the existing Download
pipeline so behavior is identical to CLI/GUI downloads.

Usage:
    music-dl bot              # starts the bot (token from Keychain)
    music-dl bot --token XYZ  # explicit token override
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
import discord
from discord import app_commands

log = logging.getLogger("music-dl.discord")

# ---------------------------------------------------------------------------
# Queue model
# ---------------------------------------------------------------------------

class JobStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


@dataclass
class DownloadJob:
    url: str
    requested_by: str
    channel_id: int
    message_id: int | None = None
    status: JobStatus = JobStatus.QUEUED
    title: str = ""
    artist: str = ""
    album: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


# ---------------------------------------------------------------------------
# Download worker (runs on a background thread, same pattern as GUI)
# ---------------------------------------------------------------------------

_queue: deque[DownloadJob] = deque()
_queue_lock = threading.Lock()
_queue_event = threading.Event()
_history: deque[DownloadJob] = deque(maxlen=50)
_worker_thread: threading.Thread | None = None
_loop: asyncio.AbstractEventLoop | None = None
_bot_ref: MusicDLBot | None = None


def _notify_channel(job: DownloadJob, embed: discord.Embed) -> None:
    """Send an embed to the channel that requested the download (thread-safe).

    All discord.py internal state access (including get_channel) must happen on
    the event loop thread — never from the worker thread directly.
    """
    if _loop is None or _bot_ref is None:
        return

    async def _send() -> None:
        channel = _bot_ref.get_channel(job.channel_id)  # type: ignore[union-attr]
        if channel and isinstance(channel, discord.abc.Messageable):
            await channel.send(embed=embed)

    asyncio.run_coroutine_threadsafe(_send(), _loop)


def _process_single_url(job: DownloadJob) -> None:
    """Download a single Tidal URL using the existing pipeline."""
    from tidal_dl.config import Settings, Tidal
    from tidal_dl.constants import DownloadSource, MediaType
    from tidal_dl.download import Download
    from tidal_dl.helper.path import get_format_template
    from tidal_dl.helper.tidal import (
        get_tidal_media_id,
        get_tidal_media_type,
        instantiate_media,
        url_ending_clean,
    )

    tidal = Tidal()
    settings = Settings()

    if not tidal.session.check_login():
        tidal.session.load_oauth_session(
            tidal.session.token_type,
            tidal.session.access_token,
            tidal.session.refresh_token,
            tidal.session.expiry_time,
        )

    dl = Download(
        tidal_obj=tidal,
        path_base=settings.data.download_base_path,
        fn_logger=log,
        skip_existing=settings.data.skip_existing,
    )

    url_clean = url_ending_clean(job.url)
    media_type = get_tidal_media_type(url_clean)
    if not isinstance(media_type, MediaType):
        raise ValueError(f"Could not determine media type from URL: {job.url}")

    media_id = get_tidal_media_id(url_clean)
    file_template = get_format_template(media_type, settings)
    if not isinstance(file_template, str):
        raise ValueError(f"No file template for media type: {media_type}")

    prefer_hifi = (
        tidal.active_source == DownloadSource.HIFI_API
        and tidal.hifi_client is not None
    )

    media = instantiate_media(
        session=tidal.session,
        media_type=media_type,
        id_media=media_id,
        hifi_client=tidal.hifi_client,
        prefer_hifi=prefer_hifi,
        oauth_fallback=bool(settings.data.download_source_fallback),
    )

    # Populate job metadata for the embed
    if hasattr(media, "name"):
        job.title = getattr(media, "full_name", None) or media.name or ""
    if hasattr(media, "artists") and media.artists:
        job.artist = ", ".join(a.name for a in media.artists if a.name)
    if hasattr(media, "album") and media.album:
        job.album = media.album.name or ""
    elif hasattr(media, "name"):
        job.album = media.name or ""

    # Dispatch to the right handler
    if media_type in (MediaType.TRACK, MediaType.VIDEO):
        dl.item(
            file_template=file_template,
            media=media,
            quality_audio=settings.data.quality_audio,
            quality_video=settings.data.quality_video,
        )
    elif media_type in (MediaType.ALBUM, MediaType.PLAYLIST, MediaType.MIX):
        dl.items(
            file_template=file_template,
            media=media,
            media_type=media_type,
            video_download=settings.data.video_download,
            download_delay=settings.data.download_delay,
            quality_audio=settings.data.quality_audio,
            quality_video=settings.data.quality_video,
        )
    elif media_type == MediaType.ARTIST:
        from tidalapi.artist import Artist

        if isinstance(media, Artist):
            from tidal_dl.helper.tidal import all_artist_album_ids

            for album_id in all_artist_album_ids(media):
                if album_id is not None:
                    dl.items(
                        media_id=str(album_id),
                        media_type=MediaType.ALBUM,
                        file_template=file_template,
                        video_download=settings.data.video_download,
                        download_delay=settings.data.download_delay,
                        quality_audio=settings.data.quality_audio,
                        quality_video=settings.data.quality_video,
                    )


def _worker_loop() -> None:
    """Background worker: pulls jobs off the queue and downloads them."""
    while True:
        _queue_event.wait()

        while True:
            with _queue_lock:
                if not _queue:
                    _queue_event.clear()
                    break
                job = _queue[0]

            job.status = JobStatus.DOWNLOADING
            _notify_channel(job, _embed_status(job, "Downloading…", discord.Color.blue()))

            try:
                _process_single_url(job)
                job.status = JobStatus.DONE
                job.finished_at = time.time()
                elapsed = job.finished_at - job.started_at
                _notify_channel(
                    job,
                    _embed_status(job, f"Done in {elapsed:.0f}s", discord.Color.green()),
                )
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)[:200]
                job.finished_at = time.time()
                _notify_channel(
                    job,
                    _embed_status(job, f"Failed: {job.error}", discord.Color.red()),
                )
                log.exception("Download failed for %s", job.url)

            with _queue_lock:
                if _queue and _queue[0] is job:
                    _queue.popleft()
                _history.appendleft(job)


def _embed_status(job: DownloadJob, status_text: str, color: discord.Color) -> discord.Embed:
    """Build a status embed for a download job."""
    title = job.title or job.url
    embed = discord.Embed(title=title[:256], color=color)
    if job.artist:
        embed.add_field(name="Artist", value=job.artist[:100], inline=True)
    if job.album:
        embed.add_field(name="Album", value=job.album[:100], inline=True)
    embed.add_field(name="Status", value=status_text, inline=False)
    embed.set_footer(text=f"Requested by {job.requested_by}")
    return embed


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

TIDAL_URL_RE = re.compile(r"https?://(?:listen\.)?tidal\.com/\S+", re.IGNORECASE)


class MusicDLBot(discord.Client):
    """Discord client with slash command tree."""

    def __init__(
        self,
        *,
        allowed_channel_ids: set[int] | None = None,
        dev_guild_id: int | None = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.allowed_channel_ids = allowed_channel_ids or set()
        self.dev_guild_id = dev_guild_id
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="dl", description="Download a Tidal track, album, playlist, or artist")
        @app_commands.describe(url="Tidal URL (e.g. https://tidal.com/browse/track/12345)")
        async def cmd_dl(interaction: discord.Interaction, url: str) -> None:
            if self.allowed_channel_ids and interaction.channel_id not in self.allowed_channel_ids:
                await interaction.response.send_message("Not allowed in this channel.", ephemeral=True)
                return

            if not TIDAL_URL_RE.match(url):
                await interaction.response.send_message(
                    "That doesn't look like a Tidal URL. Paste a full link like "
                    "`https://tidal.com/browse/track/12345`.",
                    ephemeral=True,
                )
                return

            job = DownloadJob(
                url=url,
                requested_by=interaction.user.display_name,
                channel_id=interaction.channel_id,
            )

            with _queue_lock:
                _queue.append(job)
                pos = len(_queue)
            _queue_event.set()

            await interaction.response.send_message(
                embed=_embed_status(job, f"Queued (position {pos})", discord.Color.light_grey()),
            )

        @self.tree.command(name="queue", description="Show the current download queue")
        async def cmd_queue(interaction: discord.Interaction) -> None:
            with _queue_lock:
                items = list(_queue)

            if not items:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return

            embed = discord.Embed(title="Download Queue", color=discord.Color.blurple())
            for i, job in enumerate(items[:10]):
                label = job.title or job.url
                embed.add_field(
                    name=f"{i + 1}. {label[:80]}",
                    value=f"{job.status.value} — by {job.requested_by}",
                    inline=False,
                )
            if len(items) > 10:
                embed.set_footer(text=f"…and {len(items) - 10} more")

            await interaction.response.send_message(embed=embed)

        @self.tree.command(name="history", description="Show recent downloads")
        async def cmd_history(interaction: discord.Interaction) -> None:
            items = list(_history)[:10]
            if not items:
                await interaction.response.send_message("No download history yet.", ephemeral=True)
                return

            embed = discord.Embed(title="Recent Downloads", color=discord.Color.dark_grey())
            for job in items:
                icon = "✅" if job.status == JobStatus.DONE else "❌"
                label = job.title or job.url
                elapsed = ""
                if job.finished_at:
                    elapsed = f" ({job.finished_at - job.started_at:.0f}s)"
                embed.add_field(
                    name=f"{icon} {label[:80]}",
                    value=f"{job.artist or 'Unknown'}{elapsed}",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

    async def setup_hook(self) -> None:
        try:
            if self.dev_guild_id:
                guild = discord.Object(id=self.dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Slash commands synced to dev guild %d.", self.dev_guild_id)
            else:
                await self.tree.sync()
                log.info("Slash commands synced globally.")
        except discord.Forbidden:
            log.error(
                "Failed to sync slash commands — bot lacks 'applications.commands' scope. "
                "Re-invite with both 'bot' and 'applications.commands' scopes."
            )
        except discord.HTTPException as exc:
            log.error("Command sync failed: %s — bot will still respond to messages.", exc)

    async def on_ready(self) -> None:
        global _loop, _bot_ref, _worker_thread
        _loop = asyncio.get_running_loop()
        _bot_ref = self

        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="dl-worker")
            _worker_thread.start()

        log.info("Bot ready as %s", self.user)

    async def on_message(self, message: discord.Message) -> None:
        """Auto-detect Tidal URLs in messages and queue downloads.

        Only active when allowed_channel_ids is explicitly set — prevents
        any guild member from flooding the queue in unrestricted mode.
        """
        if message.author == self.user or message.author.bot:
            return
        # Auto-detect is opt-in: only works in explicitly allowed channels
        if not self.allowed_channel_ids or message.channel.id not in self.allowed_channel_ids:
            return

        urls = TIDAL_URL_RE.findall(message.content)
        if not urls:
            return

        for url in urls[:5]:  # cap at 5 per message
            job = DownloadJob(
                url=url,
                requested_by=message.author.display_name,
                channel_id=message.channel.id,
                message_id=message.id,
            )
            with _queue_lock:
                _queue.append(job)
                pos = len(_queue)
            _queue_event.set()

            await message.reply(
                embed=_embed_status(job, f"Queued (position {pos})", discord.Color.light_grey()),
                mention_author=False,
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_bot(
    token: str,
    allowed_channels: list[int] | None = None,
    dev_guild_id: int | None = None,
) -> None:
    """Start the Discord bot (blocking call).

    Args:
        token: Discord bot token.
        allowed_channels: Optional list of channel IDs to restrict commands to.
        dev_guild_id: Guild ID for instant slash command sync (dev mode).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    channel_set = set(allowed_channels) if allowed_channels else set()
    bot = MusicDLBot(allowed_channel_ids=channel_set, dev_guild_id=dev_guild_id)
    bot.run(token, log_handler=None)
