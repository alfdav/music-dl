"""Tests that static asset resolution works in both normal and frozen modes.

Catches the _MEIPASS bug: PyInstaller onefile bundles datas in the extraction
dir, but Path(__file__) points into the PYZ archive. Without the _MEIPASS
fallback, the app serves stale/missing assets from the wrong location.
"""

from pathlib import Path
from unittest.mock import patch
import re
import sys

from tests.gui_js_source import GUI_JS_FILES, read_gui_js


def _css_rule_bodies(css: str, selector: str) -> list[str]:
    pattern = re.compile(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}")
    return [body.strip() for body in pattern.findall(css)]

STATIC_DIR = Path(__file__).resolve().parents[1] / "tidal_dl" / "gui" / "static"
REQUIRED_FILES = ["index.html", "favicon.ico", "routes.js", *GUI_JS_FILES, "style.css"]


class TestPlaybackStatusAssets:
    def test_connected_tidal_status_uses_green_dot_and_account_chip(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        html = (STATIC_DIR / "index.html").read_text()

        assert "return { label: data.username || 'connected', dot: '' };" in js
        assert "_tidalStatusPresentation(data)" in js
        assert "_renderAccountQualityChip(accountEl, quality)" in js
        assert "connection-account" in html
        assert "tidal-servers" not in html
        assert "connection-hifi" not in html
        assert ".connection-account[hidden]" in css
        assert ".quality-hires" in css
        assert ".connection-dot.neutral" in css


class TestStaticAssetsExist:
    """Static files required by the GUI are present on disk."""

    def test_static_dir_exists(self):
        assert STATIC_DIR.is_dir(), f"Static directory missing: {STATIC_DIR}"

    def test_required_files_present(self):
        for name in REQUIRED_FILES:
            assert (STATIC_DIR / name).is_file(), f"Missing: {STATIC_DIR / name}"


class TestStaticDirResolution:
    """create_app resolves _STATIC_DIR correctly in normal and frozen modes."""

    def test_normal_mode_resolves_to_real_static(self):
        from tidal_dl.gui import _STATIC_DIR
        assert _STATIC_DIR.is_dir()
        for name in REQUIRED_FILES:
            assert (_STATIC_DIR / name).is_file(), f"Missing in resolved dir: {name}"

    def test_frozen_mode_uses_meipass(self, tmp_path):
        """Simulate PyInstaller frozen env — _STATIC_DIR should use _MEIPASS."""
        # Create a fake _MEIPASS structure
        fake_static = tmp_path / "tidal_dl" / "gui" / "static"
        fake_static.mkdir(parents=True)
        (fake_static / "api.js").write_text("// frozen")
        (fake_static / "views.js").write_text("// frozen")
        (fake_static / "player.js").write_text("// frozen")

        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            # Re-import to trigger the resolution logic
            import importlib
            import tidal_dl.gui
            importlib.reload(tidal_dl.gui)
            resolved = tidal_dl.gui._STATIC_DIR
            assert str(resolved) == str(fake_static), \
                f"Frozen mode should use _MEIPASS, got: {resolved}"

        # Restore normal mode
        importlib.reload(tidal_dl.gui)


class TestAppJsFeatureMarkers:
    """app.js contains expected feature markers — catches stale bundle issues."""

    def test_artist_gallery_eager_loads_first_six_covers_and_keeps_fallback(self):
        js = read_gui_js()
        gallery_source = js.split("async function renderArtistGallery(")[1].split(
            "// ---- LOCAL ALBUM DETAIL"
        )[0]

        assert "albums.forEach((album, index) => {" in gallery_source
        assert "loading: index < 6 ? 'eager' : 'lazy'" in gallery_source
        assert "img.onerror = function() {" in gallery_source
        assert "artWrap.style.background = artGradient(album.name);" in gallery_source
        assert "albums.length + ' album' + (albums.length !== 1 ? 's' : '')" in gallery_source
        assert "data.albums.length + ' albums'" not in gallery_source
        assert "skeleton-row" not in gallery_source
        assert "Loading albums" in gallery_source or "home-loading-hint" in gallery_source

    def test_artist_hero_tile_singularizes_album_count(self):
        js = read_gui_js()
        tile_source = js.split("function _artistTile(artist, hero) {")[1].split("\nfunction ")[0]
        assert "artist.album_count + ' album' + (artist.album_count !== 1 ? 's' : '')" in tile_source
        assert "artist.album_count + ' albums'" not in tile_source

    def test_local_album_detail_skips_artist_albums_when_cover_is_prefetched(self):
        js = read_gui_js()
        detail_source = js.split(
            "async function renderLocalAlbumDetail(container, artistName, albumName, prefetchedData) {"
        )[1].split("\nasync function ")[0]
        assert "prefetchedData" in detail_source
        assert "cover_url" in detail_source.split("// Album header")[0]
        assert "if (!coverUrl" in detail_source.split("// Album header")[0]
        assert "skeleton-row" not in detail_source
        assert "Loading tracks" in detail_source or "home-loading-hint" in detail_source

    def test_has_csrf_token_handling(self):
        js = read_gui_js()
        assert "X-CSRF-Token" in js

    def test_has_media_session(self):
        js = read_gui_js()
        assert "mediaSession" in js, "Media Session API integration missing"

    def test_has_waveform_hires(self):
        js = read_gui_js()
        assert "_wfHires" in js, "Hires waveform animation missing"

    def test_has_queue_persistence(self):
        js = read_gui_js()
        assert "playerQueue" in js, "Queue persistence missing"

    def test_has_continue_listening_home_card(self):
        js = read_gui_js()
        assert "Continue Listening" in js
        assert "_getContinueListeningState" in js
        assert "_resumeContinueListening" in js
        assert "_isResumePositionUsable" in js
        assert "localStorage.removeItem('playerPosition')" in js

    def test_has_requested_keyboard_shortcuts(self):
        js = read_gui_js()
        assert "_isTypingTarget" in js
        assert "metaKey || e.ctrlKey" in js
        assert "Cmd/Ctrl+K" in js
        assert "Cmd/Ctrl+L" in js
        assert "Cmd/Ctrl+Shift+Q" in js

    def test_has_recent_filters_and_clear_old(self):
        js = read_gui_js()
        assert "recentPlayedFilter" in js
        assert "This Week" in js
        assert "Clear older than 30 days" in js
        assert "_clearRecentOlderThan30Days" in js

    def test_has_accessible_album_search_filters_without_catalog_refetch(self):
        js = read_gui_js()
        source = js.split("function _renderAlbumFilterControls(")[1].split(
            "function renderSearch(container) {"
        )[0]
        cached_source = js.split("function _rerenderCachedSearch(")[1].split(
            "function _renderAlbumFilterControls("
        )[0]
        assert "albumQualityFilter: 'all'" in js
        assert "albumRatingFilter: 'all'" in js
        assert "aria-pressed" in source
        assert "data-filter-key" in source
        assert "data-filter-value" in source
        assert ".focus()" in source
        assert "Clear filters" in source
        assert "_rerenderCachedSearch(resultsArea)" in source
        assert "doSearch(" not in source
        assert "doSearch(" not in cached_source
        assert "api(" not in cached_source
        assert "querySelector('.album-search-filters')" in js
        assert "No albums match these filters" in js

    def test_tidal_album_results_have_metadata_badges_and_responsive_styles(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        results_source = js.split("function renderSearchResults(")[1].split(
            "function _trackKey("
        )[0]
        artwork_source = results_source.split(
            "const artDiv = h('div', { className: 'album-card-art' });"
        )[1].split("const meta = h('div', { className: 'album-card-meta' });")[0]

        assert "if (state.searchType === 'albums') {" in artwork_source
        badge_source = artwork_source.split("if (state.searchType === 'albums') {")[1]
        for quality, label in [
            ("HI_RES_LOSSLESS", "MAX"),
            ("HI_RES", "MAX"),
            ("LOSSLESS", "LOSSLESS"),
            ("HIGH", "HIGH"),
            ("LOW", "LOW"),
        ]:
            assert f"{quality}: '{label}'" in badge_source
        assert "[item.quality] || 'UNKNOWN'" in badge_source
        assert "textEl('span', qualityLabel, 'album-search-badge')" in badge_source
        assert "item.atmos === true" in badge_source
        assert "textEl('span', 'ATMOS', 'album-search-badge')" in badge_source
        assert "item.explicit === true" in badge_source
        assert "textEl('span', 'E', 'album-search-badge')" in badge_source
        assert "artDiv.appendChild(badges)" in badge_source
        assert ".album-search-filters" in css
        assert ".album-search-filters[hidden]" in css
        hidden_rule = css.split(".album-search-filters[hidden]")[1].split("}")[0]
        assert "display: none" in hidden_rule
        assert ".album-search-badges" in css
        assert ".album-search-badge" in css
        badge_rule = css.split(".album-search-badge {")[1].split("}")[0]
        assert "background: var(--glass)" in badge_rule
        assert ".album-search-filters .pill:focus-visible" in css
        assert "outline:" in css.split(
            ".album-search-filters .pill:focus-visible"
        )[1].split("}")[0]

    def test_filter_pills_center_labels_and_clear_the_search_rail(self):
        css = (STATIC_DIR / "style.css").read_text()

        search_area = _css_rule_bodies(css, ".search-area")
        assert any("gap: 16px" in body for body in search_area)

        search_focus = _css_rule_bodies(css, ".search-input:focus")
        assert any("0 0 0 4px var(--accent-glow)" in body for body in search_focus)

        row = _css_rule_bodies(css, ".filter-pills")
        assert row, ".filter-pills rule is missing"
        assert any(
            "padding: 8px 2px 0" in body and "align-items: center" in body
            for body in row
        ), "top padding must keep 36px chips off the focused search rail"

        pill = _css_rule_bodies(css, ".pill")
        assert pill, ".pill rule is missing"
        assert any(
            "display: flex" in body
            and "align-items: center" in body
            and "justify-content: center" in body
            and "min-height: 36px" in body
            for body in pill
        )

        album_pill = _css_rule_bodies(css, ".album-search-filters .pill")
        assert album_pill, ".album-search-filters .pill rule is missing"
        assert any("min-height: 28px" in body for body in album_pill)

    def test_search_cards_keep_visible_titles_and_square_art(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        results_source = js.split("function renderSearchResults(")[1].split(
            "function _trackKey("
        )[0]
        local_artists = js.split("} else if (type === 'artists') {")[1].split(
            "container.appendChild(grid);"
        )[0]

        assert "textEl('div', item.name || '', 'album-card-title')" in results_source
        assert "img.alt = item.name || '';" in results_source
        assert "img.alt = '';" not in results_source
        assert "textEl('div', a.name || 'Unknown', 'album-card-title')" in local_artists
        assert "alt: a.name || ''" in local_artists

        bare_art = _css_rule_bodies(css, ".album-card-art")
        assert bare_art, "square sibling .album-card-art rule is missing"
        assert all("height: 100%" not in body for body in bare_art)
        assert any("aspect-ratio: 1" in body for body in bare_art)

        wrap_art = _css_rule_bodies(css, ".album-card-art-wrap .album-card-art")
        assert wrap_art, "cover fill must target img inside .album-card-art-wrap"
        assert any(
            "height: 100%" in body and "object-fit: cover" in body
            for body in wrap_art
        )

        grid = _css_rule_bodies(css, ".album-grid")
        gallery = _css_rule_bodies(css, ".album-gallery")
        assert any("align-items: start" in body for body in grid)
        assert any("align-items: start" in body for body in gallery)

    def test_album_results_have_one_header_and_filtered_empty_path(self):
        js = read_gui_js()
        source = js.split("function renderUnifiedSearchResults(")[1].split(
            "function renderSearchResults("
        )[0]
        results_source = js.split("function renderSearchResults(")[1].split(
            "function _trackKey("
        )[0]
        filtered_condition = "state.searchType === 'albums' && data.unfiltered_total > 0"
        assert source.count("'Tidal Albums'") == 1
        assert "className: 'search-divider'" in source
        assert "type !== 'albums' && localItems.length > 0" not in source
        assert "renderSearchResults(tidalWrap, tidalResponse, false)" in source
        assert "unfiltered_total: originalTidalItems.length" in source
        assert "originalTidalItems.length === 0" in source
        assert filtered_condition in results_source
        filtered_branch = results_source.split(filtered_condition)[1].split(
            "textEl('div', 'Nothing here', 'empty-state-title')"
        )[0]
        assert "No albums match these filters" in filtered_branch
        assert "Use Clear filters above to see every album." in filtered_branch
        assert "return;" in filtered_branch

        css = (STATIC_DIR / "style.css").read_text()
        header = _css_rule_bodies(css, ".results-header")
        assert any("align-items: center" in body for body in header)
        assert all("align-items: baseline" not in body for body in header)

    def test_search_cache_matches_query_and_type_and_drops_stale_results(self):
        js = read_gui_js()
        search_source = js.split("async function doSearch(resultsArea) {")[1].split(
            "function renderTidalSearchAuthPanel("
        )[0]
        cached_source = js.split("function _rerenderCachedSearch(")[1].split(
            "function _renderAlbumFilterControls("
        )[0]
        view_source = js.split("function renderSearch(container) {")[1].split(
            "function _greeting() {"
        )[0]
        assert "const query = state.searchQuery.trim();" in search_source
        assert "const type = state.searchType;" in search_source
        assert "state.searchQuery.trim() !== query || state.searchType !== type" in search_source
        assert "state.searchResults = { query, type, local: localData, tidal: tidalData, tidalAuthRequired };" in search_source
        assert "state.searchResults.query === state.searchQuery.trim()" in cached_source
        assert "state.searchResults.type === state.searchType" in cached_source
        assert "state.searchResults.query === state.searchQuery.trim()" in view_source
        assert "state.searchResults.type === state.searchType" in view_source

    def test_search_resolves_tidal_urls_and_keeps_recent_chip_dismiss_visible(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        search_source = js.split("async function doSearch(resultsArea) {")[1].split(
            "function renderTidalSearchAuthPanel("
        )[0]
        results_source = js.split("function renderSearchResults(")[1].split(
            "function _trackKey("
        )[0]
        gallery_source = js.split("async function renderArtistGallery(")[1].split(
            "// ---- LOCAL ALBUM DETAIL"
        )[0]
        recent_source = js.split("function _renderRecentSearches(")[1].split(
            "function _filterTidalAlbums("
        )[0]

        assert "Promise.all([localP, tidalP])" in search_source
        assert "timeoutMs: 2500" in search_source
        assert "_followSearchResolve(resultsArea, tidalData)" in search_source
        assert "tidalData.resolve" in js
        assert "downloadTrack" in js
        assert "buildArtistView(item.name, item.id)" in results_source
        assert "/artists/" in js
        assert "/library/artist/" in gallery_source
        assert "recent-chip-query" in recent_source

        query = _css_rule_bodies(css, ".recent-chip-query")
        assert query, ".recent-chip-query rule is missing"
        assert any(
            "overflow: hidden" in body
            and "text-overflow: ellipsis" in body
            and "min-width: 0" in body
            for body in query
        )
        dismiss = _css_rule_bodies(css, ".recent-chip-x")
        assert any("flex-shrink: 0" in body for body in dismiss)

    def test_has_queue_context_actions(self):
        js = read_gui_js()
        assert "Play Next" in js
        assert "Add to Queue" in js
        assert "_queueTrackNext" in js
        assert "_queueTrackLast" in js

    def test_has_player_preferences(self):
        js = read_gui_js()
        assert "playerPrefs" in js
        assert "_restorePlayerPrefs" in js
        assert "_savePlayerPrefs" in js
        assert "volFill.style.width" in js

    def test_has_smart_shuffle_hooks(self):
        js = read_gui_js()
        assert "Smart Shuffle" in js
        assert "_smartShuffleTracks" in js
        assert "smartShuffle" in js

    def test_has_visible_djai_panel(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        html = (STATIC_DIR / "index.html").read_text()
        assert "djai-shell" in js
        assert "textEl('h2', 'DJAI'" in js
        assert "textEl('h3', 'Discord Bot'" in js
        assert "textEl('h2', 'Deploy Discord Bot'" not in js
        assert ">lab</span>" in html
        assert ">soon</span>" not in html
        assert ".djai-module-card" in css

    def test_has_static_bug_report_link(self):
        html = (STATIC_DIR / "index.html").read_text()
        css = (STATIC_DIR / "style.css").read_text()
        issue_url = "https://github.com/alfdav/music-dl/issues/new?template=bug-report.yml"
        assert html.count(issue_url) == 3
        assert "Report bug" in html
        assert "Report a bug" in html
        assert "bug-report-link-sidebar" in html
        assert "bug-report-link-topbar" in html
        assert 'target="_blank"' in html
        assert 'rel="noopener noreferrer"' in html
        assert ".bug-report-link" in css

    def test_has_djai_discord_bot_deploy_controls(self):
        js = read_gui_js()
        css = (STATIC_DIR / "style.css").read_text()
        assert "/bot-control/status" in js
        assert "/bot-control/configure" in js
        assert "/bot-control/start" in js
        assert "/bot-control/restart" in js
        assert "/bot-control/stop" in js
        assert "Deploy Discord Bot" in js
        assert "Start Discord Bot" in js
        assert "Restart" in js
        assert "Shutdown" in js
        assert "Edit Config" in js
        assert "Saved (hidden)" in js
        assert "data.saved_labels?.[name]" in js
        assert "data.saved_ids?.[name]" in js
        assert "Invalid Discord IDs" in js
        assert "djai-ghost-input" in js
        assert "Existing config detected" in js
        assert ".djai-ghost-input.ok" in css
        assert "className: 'djai-config-summary'" not in js
        assert ".djai-config-summary" not in css
        assert "var(--green)" in css
        assert "djai-discord-card" in css

    def test_library_artist_view_uses_page_size(self):
        js = read_gui_js()
        assert "const LIBRARY_PAGE_SIZE = 50" in js
        assert "sort=artist&limit=' + LIBRARY_PAGE_SIZE" in js
        assert "sort=artist&limit=200" not in js

    def test_album_view_caches_and_batches_rendering(self):
        js = read_gui_js()
        assert "_libraryAlbumCache" in js
        assert "_getLibraryAlbums" in js
        assert "_renderAlbumCardsBatch" in js
        assert "requestAnimationFrame" in js
        assert "_failedAlbumArtUrls" in js

    def test_library_no_longer_renders_recent_shelf(self):
        js = read_gui_js()
        assert "Recently Added" in js
        assert "loadLibraryRecentAlbumsExpanded" in js
        assert "recentAddedPill" not in js
        assert "textEl('div', 'Recently Added', 'pill" not in js
        assert "loadLibraryRecentShelf" not in js
        assert "library-shelf" not in js

    def test_recently_added_paints_home_loading_hint_before_fetch(self):
        js = read_gui_js()
        loader = js.split("async function loadLibraryRecentAlbumsExpanded(resultsArea, append) {")[1].split(
            "\nfunction renderLibrary(container) {"
        )[0]
        before_await = loader.split("await loadLibraryRecentAlbumsPage")[0]
        assert "home-loading-hint" in before_await
        assert "Loading albums" in before_await
        assert "skeleton-row" not in loader

    def test_has_sleep_timer(self):
        js = read_gui_js()
        assert "_sleepTimerId" in js, "Sleep timer missing"

    def test_html_has_preload_audio(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "audio-preload" in html, "Preload audio element missing"

    def test_html_has_sleep_button(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert "btn-sleep" in html, "Sleep timer button missing"

    def test_html_loads_route_helper_before_app_js(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert html.index('/routes.js') < html.index('/api.js')
        assert html.index('/api.js') < html.index('/views.js')
        assert html.index('/views.js') < html.index('/player.js')

    def test_html_declares_favicon(self):
        html = (STATIC_DIR / "index.html").read_text()
        assert '<link rel="icon" href="/favicon.ico"' in html

    def test_h_helper_does_not_write_false_boolean_attributes(self):
        js = read_gui_js()
        assert "else if (typeof v === 'boolean')" in js
        assert "if (v) e.setAttribute(k, '')" in js
        assert "else e.setAttribute(k, v)" in js

    def test_update_links_use_external_open_helper(self):
        js = read_gui_js()
        assert "className: 'toast-update-link',\n      type: 'button'," in js
        assert "className: 'update-notification-btn',\n    type: 'button'," in js
        assert "_openExternal(data.release_url)" in js

    def test_updater_settings_exposes_staged_install_action(self):
        js = read_gui_js()
        assert "us.status === 'ready_to_install'" in js
        assert "className: 'updater-btn-install', type: 'button'" in js
        assert "installBtn.onclick = () => installUpdate()" in js

    def test_web_update_card_exposes_copyable_install_commands(self):
        js = read_gui_js()
        assert "function _updateInstallCommands()" in js
        assert "scripts/install.sh | bash" in js
        assert "scripts/install.ps1 | iex" in js
        assert "function _fallbackCopyText(text)" in js
        assert "Copy install command" in js
        assert "Copy Windows command" in js
        assert "Copy macOS/Linux command" in js

    def test_tauri_updater_state_is_normalized_for_frontend(self):
        js = read_gui_js()
        assert "function _normalizeUpdaterState(us)" in js
        assert "status: us.status || us.phase || 'idle'" in js
        assert "available_version: us.available_version || us.version || ''" in js
        assert "error_message: us.error_message || us.error || ''" in js


def _css_gap_px(body: str) -> int | None:
    match = re.search(r"(?<![-\w])gap:\s*(\d+)px", body)
    return int(match.group(1)) if match else None


def _grid_columns(body: str) -> list[str] | None:
    match = re.search(r"grid-template-columns:\s*([^;]+)", body)
    if not match:
        return None
    return match.group(1).split()


class TestTrackRowActionSpacing:
    """Source label + download icon sit in .track-actions on every track row."""

    def test_actions_cluster_has_horizontal_gap_and_column_room(self):
        css = (STATIC_DIR / "style.css").read_text()
        js = read_gui_js()

        assert "className: 'track-actions visible'" in js
        assert "className: 'source-tag ' + (track.is_local ? 'local-tag' : 'tidal-tag')" in js
        assert "className: 'dl-btn'" in js

        actions = _css_rule_bodies(css, ".track-actions")
        assert actions, ".track-actions rule is missing"
        assert any(
            "display: flex" in body
            and "align-items: center" in body
            and (_css_gap_px(body) or 0) >= 8
            for body in actions
        ), "source-tag and sibling action icons need >= 8px flex gap"

        source = _css_rule_bodies(css, ".source-tag")
        assert source, ".source-tag rule is missing"
        assert all("letter-spacing: 0.5px" in body for body in source)

        dl_btn = _css_rule_bodies(css, ".dl-btn")
        assert any("width: 40px" in body and "height: 40px" in body for body in dl_btn)

        for selector in (".track", ".track-header"):
            columns = [
                cols for body in _css_rule_bodies(css, selector)
                if (cols := _grid_columns(body)) and len(cols) >= 9
            ]
            assert columns, f"{selector} grid-template-columns is missing"
            for cols in columns:
                actions_col = cols[8]
                assert actions_col.endswith("px"), f"{selector} actions column must be a fixed px width"
                assert int(actions_col[:-2]) >= 80, (
                    f"{selector} actions column {actions_col} is too narrow "
                    "for source label + gap + download icon"
                )


class TestNavBackControl:
    def test_nav_back_is_a_quiet_chevron_not_a_toolbar(self):
        css = (STATIC_DIR / "style.css").read_text()
        js = read_gui_js()
        assert ".nav-back {" in css
        rule = css.split(".nav-back {")[1].split("}")[0]
        assert "background: transparent" in rule
        assert "var(--text-muted)" in rule
        assert "width: 24px" in rule
        assert "min-height: 48px" not in rule
        assert ".nav-back:hover" in css
        assert "var(--accent)" in css.split(".nav-back:hover")[1].split("}")[0]
        assert "function _navBackControl(" in js
        assert "aria-label', 'Back'" in js


class TestLibraryScanStatusLabel:
    def test_sync_button_uses_named_scan_phase(self):
        js = read_gui_js()
        assert "function _scanStatusLabel(status)" in js
        assert "textNode.textContent = _scanStatusLabel(status);" in js
        assert "phase === 'discovering'" in js
        assert "phase === 'error'" in js
        assert "previous library kept" in js
