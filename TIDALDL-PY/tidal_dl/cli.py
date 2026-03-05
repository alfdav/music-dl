#!/usr/bin/env python
import signal
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer
import requests
from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
app_source = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=True,
    help="Inspect and manage download source settings.",
)
app_scan = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=True,
    help="Scan local music directories and seed the ISRC duplicate index.",
)
from rich.table import Table

import pathlib as _pathlib

from tidal_dl import __version__
from tidal_dl.config import HandlingApp, Settings, Tidal
from tidal_dl.constants import CTX_TIDAL, FAVORITES, MediaType, DownloadSource
from tidal_dl.download import Download
from tidal_dl.hifi_api import HiFiApiClient
from tidal_dl.helper.cli import parse_timestamp
from tidal_dl.helper.path import get_format_template, path_file_settings
from tidal_dl.helper.playlist_import import PlaylistImporter
from tidal_dl.helper.tidal import (
    all_artist_album_ids,
    get_tidal_media_id,
    get_tidal_media_type,
    instantiate_media,
    url_ending_clean,
)
from tidal_dl.helper.wrapper import LoggerWrapped
from tidal_dl.model.cfg import HelpSettings

app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]}, add_completion=False)
app_dl_fav = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=True,
    help="Download from a favorites collection.",
)

app.add_typer(app_dl_fav, name="dl_fav")
app.add_typer(app_source, name="source")
app.add_typer(app_scan, name="scan")


def version_callback(value: bool):
    """Callback to print version and exit if version flag is set.

    Args:
        value (bool): If True, prints version and exits.
    """
    if value:
        print(f"{__version__}")

        raise typer.Exit()


@app.callback()
def callback_app(
    ctx: typer.Context,
    version: Annotated[bool | None, typer.Option("--version", "-v", callback=version_callback, is_eager=True)] = None,
):
    """App callback to initialize context and handle version option.

    Args:
        ctx (typer.Context): Typer context object.
        version (bool | None, optional): Version flag. Defaults to None.
    """
    ctx.obj = {"tidal": None}


def _handle_track_or_video(
    dl: Download, ctx: typer.Context, item: str, media: object, file_template: str, idx: int, urls_pos_last: int
) -> None:
    """Handle downloading a track or video item.

    Args:
        dl (Download): The Download instance.
        ctx (typer.Context): Typer context object.
        item (str): The URL or identifier of the item.
        media: The media object to download.
        file_template (str): The file template for saving the media.
        idx (int): The index of the item in the list.
        urls_pos_last (int): The last index in the URLs list.
    """
    settings = ctx.obj[CTX_TIDAL].settings
    download_delay: bool = bool(settings.data.download_delay and idx < urls_pos_last)

    dl.item(
        media=media,
        file_template=file_template,
        download_delay=download_delay,
        quality_audio=settings.data.quality_audio,
        quality_video=settings.data.quality_video,
    )


def _handle_album_playlist_mix_artist(
    ctx: typer.Context,
    dl: Download,
    handling_app: HandlingApp,
    media_type: MediaType,
    media: object,
    item_id: str,
    file_template: str,
) -> bool:
    """Handle downloading albums, playlists, mixes, or artist collections.

    Args:
        ctx (typer.Context): Typer context object.
        dl (Download): The Download instance.
        handling_app (HandlingApp): The HandlingApp instance.
        media_type (MediaType): The type of media (album, playlist, mix, or artist).
        media: The media object to download.
        item_id (str): The ID of the media item.
        file_template (str): The file template for saving the media.

    Returns:
        bool: False if aborted, True otherwise.
    """
    item_ids: list[str] = []
    settings = ctx.obj[CTX_TIDAL].settings

    if media_type == MediaType.ARTIST:
        media_type = MediaType.ALBUM
        item_ids += all_artist_album_ids(media)
    else:
        item_ids.append(item_id)

    for _item_id in item_ids:
        if handling_app.event_abort.is_set():
            return False

        dl.items(
            media_id=_item_id,
            media_type=media_type,
            file_template=file_template,
            video_download=settings.data.video_download,
            download_delay=settings.data.download_delay,
            quality_audio=settings.data.quality_audio,
            quality_video=settings.data.quality_video,
        )

    return True


def _process_url(
    dl: Download,
    ctx: typer.Context,
    handling_app: HandlingApp,
    url: str,
    idx: int,
    urls_pos_last: int,
) -> bool:
    """Process a single URL or ID for download.

    Args:
        dl (Download): The Download instance.
        ctx (typer.Context): Typer context object.
        handling_app (HandlingApp): The HandlingApp instance.
        url (str): The URL or identifier to process.
        idx (int): The index of the url in the list.
        urls_pos_last (int): The last index in the URLs list.

    Returns:
        bool: False if aborted, True otherwise.
    """
    settings = ctx.obj[CTX_TIDAL].settings

    if handling_app.event_abort.is_set():
        return False

    if "http" not in url:
        print(f"It seems like you have supplied an invalid URL: {url}")
        return False

    url_clean: str = url_ending_clean(url)

    media_type = get_tidal_media_type(url_clean)
    if not isinstance(media_type, MediaType):
        print(f"Could not determine media type for: {url_clean}")
        return False

    url_clean_id = get_tidal_media_id(url_clean)
    if not isinstance(url_clean_id, str):
        print(f"Could not determine media id for: {url_clean}")
        return False

    file_template = get_format_template(media_type, settings)
    if not isinstance(file_template, str):
        print(f"Could not determine file template for: {url_clean}")
        return False
    tidal = ctx.obj[CTX_TIDAL]
    prefer_hifi = tidal.active_source == DownloadSource.HIFI_API and tidal.hifi_client is not None

    try:
        media = instantiate_media(
            session=tidal.session,
            media_type=media_type,
            id_media=url_clean_id,
            hifi_client=tidal.hifi_client,
            prefer_hifi=prefer_hifi,
            oauth_fallback=bool(settings.data.download_source_fallback),
        )
    except Exception:
        print(f"Media not found (ID: {url_clean_id}). Maybe it is not available anymore.")
        return False

    if media_type in [MediaType.TRACK, MediaType.VIDEO]:
        _handle_track_or_video(dl, ctx, url_clean, media, file_template, idx, urls_pos_last)
    elif media_type in [MediaType.ALBUM, MediaType.PLAYLIST, MediaType.MIX, MediaType.ARTIST]:
        return _handle_album_playlist_mix_artist(ctx, dl, handling_app, media_type, media, url_clean_id, file_template)
    return True


def _download(
    ctx: typer.Context,
    urls: list[str],
    try_login: bool = True,
    debug: bool = False,
    output_path: Path | None = None,
) -> bool:
    """Invokes download function and tracks progress.

    Args:
        ctx (typer.Context): The typer context object.
        urls (list[str]): The list of URLs to download.
        try_login (bool, optional): If true, attempts to login to TIDAL. Defaults to True.
        debug (bool, optional): If true, enables debug output with full tracebacks. Defaults to False.
        output_path (Path | None, optional): Override download destination. Defaults to None.

    Returns:
        bool: True if ran successfully.
    """
    if try_login and not ctx.invoke(login, ctx):
        return False

    settings: Settings = ctx.obj[CTX_TIDAL].settings
    handling_app: HandlingApp = HandlingApp()

    # One-off output path override — does not mutate persisted settings.
    path_base: str = str(output_path) if output_path else settings.data.download_base_path

    progress: Progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TaskProgressColumn(),
        refresh_per_second=20,
        auto_refresh=True,
        expand=True,
        transient=False,
    )

    progress_overall = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TaskProgressColumn(),
        refresh_per_second=20,
        auto_refresh=True,
        expand=True,
        transient=False,
    )

    fn_logger = LoggerWrapped(progress.print, debug=debug)

    dl = Download(
        tidal_obj=ctx.obj[CTX_TIDAL],
        skip_existing=settings.data.skip_existing,
        path_base=path_base,
        fn_logger=fn_logger,
        progress=progress,
        progress_overall=progress_overall,
        event_abort=handling_app.event_abort,
        event_run=handling_app.event_run,
    )

    progress_table = Table.grid()
    progress_table.add_row(progress)
    progress_table.add_row(progress_overall)
    progress_group = Group(progress_table)

    urls_pos_last = len(urls) - 1

    with Live(progress_group, refresh_per_second=20, vertical_overflow="visible"):
        try:
            for idx, item in enumerate(urls):
                if _process_url(dl, ctx, handling_app, item, idx, urls_pos_last) is False:
                    return False
        finally:
            progress.refresh()
            progress.stop()

    return True


@app.command(name="cfg")
def settings_management(
    names: Annotated[list[str] | None, typer.Argument()] = None,
    editor: Annotated[
        bool, typer.Option("--editor", "-e", help="Open the settings file in your default editor.")
    ] = False,
    reset: Annotated[
        bool,
        typer.Option(
            "--reset",
            help="Reset all settings to defaults (current file is backed up as settings.json.bak).",
        ),
    ] = False,
) -> None:
    """Print or set an option, or open the settings file in an editor.

    Args:
        names (list[str] | None, optional): None (list all options), one (list the value only for this option) or two arguments (set the value for the option). Defaults to None.
        editor (bool, optional): If set, your default system editor will be opened. Defaults to False.
        reset (bool, optional): Reset settings to defaults. Defaults to False.
    """
    console = Console()

    if reset:
        config_path = Path(path_file_settings())

        if config_path.is_file():
            bak_path = config_path.with_suffix(".json.bak")
            config_path.rename(bak_path)
            console.print(f"[yellow]Existing config backed up to:[/yellow] {bak_path}")

        from tidal_dl.helper.decorator import SingletonMeta
        SingletonMeta._instances.clear()

        fresh = Settings()
        fresh.save()
        console.print(f"[green]Settings reset to defaults:[/green] {fresh.file_path}")
        return

    if editor:
        config_path = Path(path_file_settings())

        if not config_path.is_file():
            config_path.write_text('{"version": "1.0.0"}')

        typer.launch(str(config_path))
    else:
        settings = Settings()
        d_settings = settings.data.to_dict()

        if names:
            if names[0] not in d_settings:
                print(f'Option "{names[0]}" is not valid!')
            elif len(names) == 1:
                print(f'{names[0]}: "{d_settings[names[0]]}"')
            elif len(names) > 1:
                settings.set_option(names[0], names[1])
                settings.save()
        else:
            help_settings: dict = HelpSettings().to_dict()
            table = Table(title=f"Config: {path_file_settings()}")
            table.add_column("Key", style="cyan", no_wrap=True)
            table.add_column("Value", style="magenta")
            table.add_column("Description", style="green")

            for key, value in sorted(d_settings.items()):
                table.add_row(key, str(value), help_settings[key])

            console.print(table)


@app.command(name="login")
def login(ctx: typer.Context) -> bool:
    """Login to TIDAL and update context object.

    Args:
        ctx (typer.Context): Typer context object.

    Returns:
        bool: True if login was successful, False otherwise.
    """
    print("Let us check if you are already logged in... ", end="")

    settings = Settings()
    tidal = Tidal(settings)
    result = tidal.resolve_source(fn_print=print)
    ctx.obj[CTX_TIDAL] = tidal

    return result


@app_source.callback(invoke_without_command=True)
def source_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    source_show()


@app_source.command(name="show")
def source_show() -> None:
    settings = Settings()
    preferred = DownloadSource(settings.data.download_source).value
    fallback = bool(settings.data.download_source_fallback)
    instances = [x.strip() for x in (settings.data.hifi_api_instances or "").split(",") if x.strip()]
    print(f"preferred_source: {preferred}")
    print(f"fallback_enabled: {fallback}")
    print(f"hifi_instances_count: {len(instances)} (0 means auto-discover)")


@app_source.command(name="set")
def source_set(source: DownloadSource) -> None:
    settings = Settings()
    settings.data.download_source = source
    settings.save()
    print(f"Preferred source set to: {source.value}")


@app_source.command(name="instances")
def source_instances() -> None:
    settings = Settings()
    configured = [x.strip().rstrip("/") for x in (settings.data.hifi_api_instances or "").split(",") if x.strip()]
    if not configured:
        tidal = Tidal(settings)
        tidal.hifi_client = tidal.hifi_client or HiFiApiClient()
        configured = tidal.hifi_client.instances

    for url in configured:
        status = "down"
        try:
            r = requests.get(url + "/", timeout=8)
            r.raise_for_status()
            status = "up"
        except requests.RequestException:
            status = "down"
        print(f"{url} [{status}]")


@app_source.command(name="add")
def source_add(url: str) -> None:
    settings = Settings()
    current = [x.strip().rstrip("/") for x in (settings.data.hifi_api_instances or "").split(",") if x.strip()]
    normalized = url.strip().rstrip("/")
    if normalized and normalized not in current:
        current.append(normalized)
        settings.data.hifi_api_instances = ",".join(current)
        settings.save()
    print(f"Configured instances: {settings.data.hifi_api_instances}")


@app_source.command(name="remove")
def source_remove(url: str) -> None:
    settings = Settings()
    current = [x.strip().rstrip("/") for x in (settings.data.hifi_api_instances or "").split(",") if x.strip()]
    normalized = url.strip().rstrip("/")
    current = [x for x in current if x != normalized]
    settings.data.hifi_api_instances = ",".join(current)
    settings.save()
    print(f"Configured instances: {settings.data.hifi_api_instances}")


@app.command(name="logout")
def logout() -> bool:
    """Logout from TIDAL.

    Returns:
        bool: True if logout was successful, False otherwise.
    """
    settings = Settings()
    tidal = Tidal(settings)
    result = tidal.logout()

    if result:
        print("You have been successfully logged out.")

    return result


@app.command(name="dl")
def download(
    ctx: typer.Context,
    urls: Annotated[list[str] | None, typer.Argument()] = None,
    file_urls: Annotated[
        Path | None,
        typer.Option(
            "--list",
            "-l",
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
            help="File with URLs to download. One URL per line.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Override the download destination for this run only (does not change saved config).",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            "-d",
            help="Enable debug mode with full error tracebacks.",
        ),
    ] = False,
) -> bool:
    """Download media from provided URLs or a file containing URLs.

    Args:
        ctx (typer.Context): Typer context object.
        urls (list[str] | None, optional): List of URLs to download. Defaults to None.
        file_urls (Path | None, optional): Path to file containing URLs. Defaults to None.
        output (Path | None, optional): One-off output directory override. Defaults to None.
        debug (bool, optional): Enable debug mode with full error tracebacks. Defaults to False.

    Returns:
        bool: True if download was successful, False otherwise.
    """
    if not urls:
        # Read the text file provided.
        if file_urls:
            text: str = file_urls.read_text()
            urls = text.splitlines()
        else:
            print("Provide either URLs or a file containing URLs (one per line).")

            raise typer.Abort()

    result = _download(ctx, urls, debug=debug, output_path=output)
    if not result:
        raise typer.Exit(code=1)
    return result


@app_dl_fav.command(
    name="tracks",
    help="Download your favorite track collection.",
)
def download_fav_tracks(
    ctx: typer.Context,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            "-s",
            help="Download only tracks added to favorites after this timestamp (UTC). Format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or Unix timestamp.",
        ),
    ] = None,
) -> bool:
    """Download your favorite track collection.

    Args:
        ctx (typer.Context): Typer context object.
        since (str | None, optional): Timestamp filter (UTC) for incremental downloads. Defaults to None.

    Returns:
        bool: Download result.
    """
    # Method name
    func_name_favorites: str = FAVORITES["fav_tracks"]["function_name"]

    # Parse timestamp if provided
    since_datetime: datetime | None = None
    if since:
        since_datetime = parse_timestamp(since)

    return _download_fav_factory(ctx, func_name_favorites, since_datetime)


@app_dl_fav.command(
    name="artists",
    help="Download your favorite artist collection.",
)
def download_fav_artists(
    ctx: typer.Context,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            "-s",
            help="Download only artists added to favorites after this timestamp (UTC). Format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or Unix timestamp.",
        ),
    ] = None,
) -> bool:
    """Download your favorite artist collection.

    Args:
        ctx (typer.Context): Typer context object.
        since (str | None, optional): Timestamp filter (UTC) for incremental downloads. Defaults to None.

    Returns:
        bool: Download result.
    """
    # Method name
    func_name_favorites: str = FAVORITES["fav_artists"]["function_name"]

    # Parse timestamp if provided
    since_datetime: datetime | None = None
    if since:
        since_datetime = parse_timestamp(since)

    return _download_fav_factory(ctx, func_name_favorites, since_datetime)


@app_dl_fav.command(
    name="albums",
    help="Download your favorite album collection.",
)
def download_fav_albums(
    ctx: typer.Context,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            "-s",
            help="Download only albums added to favorites after this timestamp (UTC). Format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or Unix timestamp.",
        ),
    ] = None,
) -> bool:
    """Download your favorite album collection.

    Args:
        ctx (typer.Context): Typer context object.
        since (str | None, optional): Timestamp filter (UTC) for incremental downloads. Defaults to None.

    Returns:
        bool: Download result.
    """
    # Method name
    func_name_favorites: str = FAVORITES["fav_albums"]["function_name"]

    # Parse timestamp if provided
    since_datetime: datetime | None = None
    if since:
        since_datetime = parse_timestamp(since)

    return _download_fav_factory(ctx, func_name_favorites, since_datetime)


@app_dl_fav.command(
    name="videos",
    help="Download your favorite video collection.",
)
def download_fav_videos(
    ctx: typer.Context,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            "-s",
            help="Download only videos added to favorites after this timestamp (UTC). Format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS or Unix timestamp.",
        ),
    ] = None,
) -> bool:
    """Download your favorite video collection.

    Args:
        ctx (typer.Context): Typer context object.
        since (str | None, optional): Timestamp filter (UTC) for incremental downloads. Defaults to None.

    Returns:
        bool: Download result.
    """
    # Method name
    func_name_favorites: str = FAVORITES["fav_videos"]["function_name"]

    # Parse timestamp if provided
    since_datetime: datetime | None = None
    if since:
        since_datetime = parse_timestamp(since)

    return _download_fav_factory(ctx, func_name_favorites, since_datetime)


def _download_fav_factory(ctx: typer.Context, func_name_favorites: str, since: datetime | None = None) -> bool:
    """Factory which helps to download items from the favorites collections.

    Args:
        ctx (typer.Context): Typer context object.
        func_name_favorites (str): Method name to call from `tidalapi` favorites object.
        since (datetime | None, optional): Only include items added after this timestamp. Defaults to None.

    Returns:
        bool: Download result.
    """
    ctx.invoke(login, ctx)
    func_favorites: Callable = getattr(ctx.obj[CTX_TIDAL].session.user.favorites, func_name_favorites)

    # Get all favorite items
    all_media: list = list(func_favorites())

    # Filter by timestamp if provided (only for items with user_date_added attribute)
    if since is not None:
        console: Console = Console()
        console.print(f"[cyan]Filtering favorites added since: {since.strftime('%Y-%m-%d %H:%M:%S')}[/cyan]")

        filtered_media: list = []
        for media in all_media:
            # Check if media has user_date_added attribute and it's after the since timestamp
            if hasattr(media, "user_date_added") and media.user_date_added is not None:
                if media.user_date_added >= since:
                    filtered_media.append(media)
            else:
                # If no timestamp available, include the item (conservative approach)
                filtered_media.append(media)

        console.print(f"[cyan]Found {len(all_media)} total favorites, {len(filtered_media)} match filter[/cyan]")
        media_urls: list[str] = [media.share_url for media in filtered_media]
    else:
        media_urls: list[str] = [media.share_url for media in all_media]

    result = _download(ctx, media_urls, try_login=False)
    if not result:
        raise typer.Exit(code=1)
    return result


@app.command(name="import")
def import_playlist(
    ctx: typer.Context,
    file_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Path to the import file (CSV/TSV with title+artist[+isrc] columns, or plain text 'Artist - Title' lines).",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Override the download destination for this run only.",
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", "-d", help="Enable debug mode with full error tracebacks."),
    ] = False,
) -> None:
    """Import a playlist from any platform and download matched tracks from TIDAL.

    Accepts a CSV/TSV file (with 'title', 'artist', and optional 'isrc' columns)
    or a plain-text file with one 'Artist - Title' entry per line.
    Each entry is matched to a TIDAL track via ISRC (exact) or title/artist
    search (fallback), then downloaded using the configured track format.

    Args:
        ctx (typer.Context): Typer context object.
        file_path (Path): Path to the import file.
        output (Path | None, optional): One-off output directory override.
        debug (bool, optional): Enable debug mode.
    """
    ctx.invoke(login, ctx)

    settings: Settings = ctx.obj[CTX_TIDAL].settings
    tidal: Tidal = ctx.obj[CTX_TIDAL]
    handling_app: HandlingApp = HandlingApp()
    path_base: str = str(output) if output else settings.data.download_base_path

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TaskProgressColumn(),
        refresh_per_second=20,
        auto_refresh=True,
        expand=True,
        transient=False,
    )
    progress_overall = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TaskProgressColumn(),
        refresh_per_second=20,
        auto_refresh=True,
        expand=True,
        transient=False,
    )

    fn_logger = LoggerWrapped(progress.print, debug=debug)

    dl = Download(
        tidal_obj=tidal,
        skip_existing=settings.data.skip_existing,
        path_base=path_base,
        fn_logger=fn_logger,
        progress=progress,
        progress_overall=progress_overall,
        event_abort=handling_app.event_abort,
        event_run=handling_app.event_run,
    )

    importer = PlaylistImporter(session=tidal.session)

    progress_table = Table.grid()
    progress_table.add_row(progress)
    progress_table.add_row(progress_overall)

    with Live(progress_table, refresh_per_second=20, vertical_overflow="visible"):
        try:
            importer.import_and_download(
                path=file_path,
                dl=dl,
                file_template=settings.data.format_track,
            )
        finally:
            progress.refresh()
            progress.stop()


def handle_sigint_term(signum, frame):
    """Set app abort event, so threads can check it and shutdown.

    Args:
        signum: Signal number.
        frame: Current stack frame.
    """
    handling_app: HandlingApp = HandlingApp()

    handling_app.event_abort.set()


# ---------------------------------------------------------------------------
# Scan subcommand group
# ---------------------------------------------------------------------------


def _scan_paths_list(settings: Settings) -> list[str]:
    """Return the configured scan paths as a cleaned list."""
    raw = settings.data.scan_paths or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def _run_scan(paths: list[str], *, dry_run: bool, verbose: bool) -> None:
    """Execute a scan over one or more directories and display a summary."""
    import time
    from rich.panel import Panel
    from rich.table import Table as RichTable
    from tidal_dl.helper.isrc_index import IsrcIndex
    from tidal_dl.helper.library_scanner import scan_directory
    from tidal_dl.helper.path import path_config_base

    console = Console()
    index_path = _pathlib.Path(path_config_base()) / "isrc_index.json"
    isrc_index = IsrcIndex(index_path)
    isrc_index.load()

    total_files = 0
    total_found = 0
    total_already = 0
    total_no_isrc = 0
    total_errors = 0
    all_error_paths: list[str] = []

    for scan_root in paths:
        root = _pathlib.Path(scan_root).expanduser()
        if not root.is_dir():
            console.print(f"[yellow]Warning:[/yellow] '{scan_root}' is not a directory — skipping.")
            continue

        console.print(f"\n[cyan]Scanning:[/cyan] {root}")

        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            SpinnerColumn(),
            BarColumn(),
            TextColumn("{task.fields[scanned]} files"),
            refresh_per_second=20,
            expand=True,
            transient=True,
        )

        task = progress.add_task("Scanning...", scanned=0)
        scanned_count = 0

        def _on_file(p: _pathlib.Path) -> None:
            nonlocal scanned_count
            scanned_count += 1
            progress.update(task, scanned=scanned_count)
            if verbose:
                progress.print(f"  [dim]{p}[/dim]")

        with progress:
            result = scan_directory(root, isrc_index, dry_run=dry_run, on_file=_on_file)

        total_files += result.files_scanned
        total_found += result.isrcs_found
        total_already += result.already_indexed
        total_no_isrc += result.no_isrc
        total_errors += result.errors
        all_error_paths.extend(result.error_paths)

        console.print(
            f"  [green]{result.isrcs_found}[/green] new  "
            f"[dim]{result.already_indexed}[/dim] already indexed  "
            f"[yellow]{result.no_isrc}[/yellow] no ISRC  "
            f"[red]{result.errors}[/red] errors  "
            f"({result.elapsed_sec:.1f}s)"
        )

    # Persist unless dry-run
    if not dry_run and total_found > 0:
        isrc_index.save()

    # Summary panel
    summary = RichTable.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Directories scanned", str(len(paths)))
    summary.add_row("Audio files examined", str(total_files))
    summary.add_row("[green]New ISRCs indexed[/green]", str(total_found))
    summary.add_row("Already in index", str(total_already))
    summary.add_row("No ISRC tag", str(total_no_isrc))
    summary.add_row("[red]Errors[/red]", str(total_errors))
    if dry_run:
        summary.add_row("Mode", "[yellow]dry-run — nothing written[/yellow]")

    console.print()
    console.print(Panel(summary, title="[bold]Scan Summary[/bold]", expand=False))

    if all_error_paths:
        console.print("\n[red]Files with errors (first 50):[/red]")
        for ep in all_error_paths[:50]:
            console.print(f"  {ep}")


@app_scan.callback(invoke_without_command=True)
def scan_callback(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Discover ISRCs without writing to the index."),
    ] = False,
    scan_all: Annotated[
        bool,
        typer.Option("--all", help="Scan all configured paths without prompting."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Print each file path as it is scanned."),
    ] = False,
) -> None:
    """Run the library scanner against configured scan directories.

    If only one path is configured it is used automatically.
    If multiple paths are configured you will be prompted to choose (or use --all).
    """
    if ctx.invoked_subcommand is not None:
        return

    settings = Settings()
    paths = _scan_paths_list(settings)
    console = Console()

    if not paths:
        console.print(
            "[yellow]No scan directories configured.[/yellow]\n"
            "Add one with:  [cyan]tidal-dl scan add <PATH>[/cyan]"
        )
        raise typer.Exit(1)

    if len(paths) == 1 or scan_all:
        chosen = paths
    else:
        console.print("[cyan]Configured scan directories:[/cyan]")
        for i, p in enumerate(paths, 1):
            console.print(f"  [{i}] {p}")
        console.print(f"  [a] All ({len(paths)} directories)")
        choice = typer.prompt("Select directory (number or 'a')", default="a")
        if choice.strip().lower() == "a":
            chosen = paths
        else:
            try:
                idx = int(choice.strip()) - 1
                if not 0 <= idx < len(paths):
                    raise ValueError
                chosen = [paths[idx]]
            except ValueError:
                console.print("[red]Invalid selection.[/red]")
                raise typer.Exit(1)

    _run_scan(chosen, dry_run=dry_run, verbose=verbose)


@app_scan.command(name="add")
def scan_add(
    path: Annotated[
        str,
        typer.Argument(help="Directory path to add to the scan list."),
    ],
    no_scan: Annotated[
        bool,
        typer.Option("--no-scan", help="Only save the path without scanning it."),
    ] = False,
) -> None:
    """Add a directory to the persistent scan path list and scan it."""
    settings = Settings()
    current = _scan_paths_list(settings)
    normalized = path.strip().rstrip("/").rstrip("\\")
    already_configured = normalized in current
    if normalized and not already_configured:
        current.append(normalized)
        settings.data.scan_paths = ",".join(current)
        settings.save()
        print(f"Added: {normalized}")
    else:
        print(f"Already configured: {normalized}")
    if not no_scan:
        _run_scan([normalized], dry_run=False, verbose=False)


@app_scan.command(name="remove")
def scan_remove(
    path: Annotated[
        str,
        typer.Argument(help="Directory path to remove from the scan list."),
    ],
) -> None:
    """Remove a directory from the persistent scan path list."""
    settings = Settings()
    current = _scan_paths_list(settings)
    normalized = path.strip().rstrip("/").rstrip("\\")
    updated = [p for p in current if p != normalized]
    if len(updated) == len(current):
        print(f"Not found in scan paths: {normalized}")
    else:
        settings.data.scan_paths = ",".join(updated)
        settings.save()
        print(f"Removed: {normalized}")
    print(f"Scan paths: {settings.data.scan_paths or '(none)'}")


@app_scan.command(name="show")
def scan_show() -> None:
    """List all configured scan directories."""
    settings = Settings()
    paths = _scan_paths_list(settings)
    if not paths:
        print("No scan paths configured. Add one with: tidal-dl scan add <PATH>")
        return
    for i, p in enumerate(paths, 1):
        exists = _pathlib.Path(p).expanduser().is_dir()
        status = "[green]ok[/green]" if exists else "[red]missing[/red]"
        Console().print(f"  [{i}] {p}  {status}")


def main() -> None:
    """Installed entry-point wrapper.

    Applies bare-URL rewriting so that ``tidal-dl <URL>`` works identically
    to ``tidal-dl dl <URL>`` when invoked via the installed script.
    """
    # Ensure UTF-8 output on Windows to prevent Rich/Unicode crashes (cp1252).
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

    signal.signal(signal.SIGINT, handle_sigint_term)
    signal.signal(signal.SIGTERM, handle_sigint_term)

    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        parsed_url = urlparse(first_arg)

        if parsed_url.scheme in ["http", "https"] and parsed_url.netloc:
            sys.argv.insert(1, "dl")

    app()


if __name__ == "__main__":
    main()
