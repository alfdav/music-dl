# Mistakes

## 2026-08-31 — Bugbot: album fallback, empty-before-Tidal, hostname ValueError

**What happened:** Artist-name track search (Carlos Vives) replaced real track hits with a self-titled album. Local-empty paint showed `No results found` while Tidal was still in flight. `urlparse(...).hostname` can raise `ValueError` on broken IPv6 zones / trailing `%`, which would 500 `/api/search`.

**Root cause:** Album-title fallback ran whenever titles scored `< 0.7`, including artist queries. `paint()` treated `tidalData === null` as settled empty. Host parse had no `ValueError` guard.

**Prevention:** Album fallback only when track search is empty or the query is not a strong artist match on those hits. Keep the skeleton while Tidal is pending and local is empty. Catch `ValueError` in `_hostname`.

## 2026-08-31 — Albums search skipped the local/Tidal divider

**What happened:** Albums pill Search showed one Your Library card (Various Artists) then "Tidal Albums 50 albums" flush against the card. The header collided with the local gallery.

**Root cause:** `renderUnifiedSearchResults` skipped `.search-divider` when `type === 'albums'` because albums already paint a "Tidal Albums" h3. The local `.album-gallery` has no bottom margin, so that h3 sat on the card. `.results-header` also used `align-items: baseline`, so the count sat off the title.

**Prevention:** Show the divider whenever local results and a Tidal section both exist, including albums (`originalTidalItems.length > 0`). Keep `.album-gallery + .search-divider` padding. Center `.results-header` (`align-items: center`). Singularize `1 result`.

## 2026-08-31 — CodeQL flagged `"tidal.com/" in url` as incomplete sanitization

**What happened:** PR 154's `looks_like_web_url` used `"tidal.com/" in raw` so a scheme-less Tidal paste would not go to `session.search`. CodeQL High: Incomplete URL substring sanitization (`py/incomplete-url-substring-sanitization`).

**Root cause:** A path can contain the substring (`https://evil.example/tidal.com/track/1`) without the host being Tidal. Substring host checks are the CodeQL pattern.

**Prevention:** Parse the host (`urlparse`, then `hostname == "tidal.com"` or `.endswith(".tidal.com")`). Scheme-prefixed queries still count as URLs so they never hit `session.search`. `parse_tidal_ref` still requires a Tidal host at the start of the string, so a planted path is `None` and Search returns the recognized-URL error.

## 2026-08-31 — Search hid a live Tidal album and froze the Albums pill

**What happened:** Pasting `https://tidal.com/track/330865538/u` or searching the album title `Clásicos de la Provincia 30 Años (Remastered & Expanded)` returned 0 tracks even though Tidal had album 330865537 / track 330865538. Artist cards routed to local-only `/library/artist/{name}/albums`. Albums pill for `Los Grandes Del Vallenato` sat on the skeleton for ~26s.

**Root cause:** Search sent the raw URL/id to `session.search`. Track search never fell back to album search. Artist drill-in ignored Tidal ids. `doSearch` awaited `/library/search` first, and album library search called `_album_cards(db)` on the whole library.

**Prevention:** Parse Tidal URLs/ids and resolve with `session.track/album/artist/playlist`. Never `session.search(url)`. When track search misses a title, fetch tracks from a close album-name match. Artist view is hybrid (local + `/artists/{id}/albums`). Fire library and Tidal search in parallel and bound library album search to SQL `all_albums(q, limit)` — never full-library grouping. Truncate recent-search query text so the dismiss x stays visible.

## 2026-08-31 — Home insight cards showed a hero and left the listening facts unused

**What happened:** The Home insight fan already had `/api/home` fields (`streak`, `most_replayed`, `this_week.most_replayed` / `genre_breakdown`, `top_artist.genre` / `album_count` / `track_count`, `weekly_activity`). Cards rendered a gold hero and label, then a void. Total plays, this week, and listening time taught almost nothing.

**Root cause:** `_homeInsightCards` treated unused payload keys as optional extras instead of the middle of the card. The test loader later started at `_homeInsightFacts` and omitted sibling helpers (`_homePushFact`), so extracted tests threw `not defined`.

**Prevention:** Fill each insight card with 1–3 facts from the already-loaded `/home` payload. Skip missing or zero values. Empty library stays empty — never invent numbers. When a views.js test extracts a helper, include the sibling functions it calls. Do not add API fields when the fact is already on first-paint `/home`.

## 2026-08-31 — Bugbot: refresh success treated as a live session, skip treated as rejected

**What happened:** PR 152 stayed merge-blocked. Startup persist after a Hi-Fi-only `resolve_source` could write an empty `token.json`. `login_token` / `call_tidal` / `require_tidal` treated `_ensure_token_fresh` True as a usable session without `load_oauth_session` / `check_login`, so `session.user` stayed unset and `list_playlists` crashed. `auth_login` mapped a non-rejected refresh to expired and aborted an in-flight device-code wait. Reset raced keepalive persist. A window skip (`False` because the token was still inside the window) was cached as `REFRESH_REJECTED` and could start `login_oauth`.

**Root cause:** Persist ran on restore-true without checking that a refresh/access token still existed. Refresh-ok was confused with a loaded user. Window-skip `False` was collapsed into rejected. `logout` did not take `_token_fresh_lock`.

**Prevention:** Persist after restore only if refresh_token or access_token is still present. After refresh-ok, reload the session (`_reload_oauth_session` / `check_login`) before returning success. `list_playlists` returns `[]` when `session.user` is missing. Distinguish skip vs rejected vs failed; never arm rejected backoff on a window skip; never start `login_oauth` from a cached skip. `logout`/Reset take the same lock as persist. Non-rejected refresh must not abort a pending device-code wait. Never wipe `token.json` and never start `login_oauth` while a refresh_token can still revive.

## 2026-08-31 — Tidal 401 after fail-silent refresh sent the UI back to login

**What happened:** `TokenRefreshMiddleware` swallowed refresh errors, then search/download/playlists/albums raised 401 `"Not logged in to Tidal"`. UI `apiTidal` / `_isTidalAuthError` treated that as login-required even when `refresh_token` was still valid. `GET /auth/status` also re-hit Tidal on every poll after a transient refresh failure.

**Root cause:** Routes trusted local `check_login()` or wrapped a Tidal 401 as 502/401 without one refresh+retry. Transient refresh failure was not backed off, so status polls hammered Tidal.

**Prevention:** One shared `call_tidal`: on Tidal 401, refresh once and retry. 401/expired only if refresh is rejected. Transient failure → 503 + 30s backoff so status/middleware cannot hammer Tidal. Do not wipe `token.json` and do not start `login_oauth` on this path. Only Reset deletes tokens.

## 2026-08-31 — Tidal status asked for a new login while refresh_token could revive

**What happened:** After one machine login, overnight or a restart could show `auth_state=expired` / "log in". Clicking login started a new device-code OAuth flow even when `token.json` still had a refresh_token. Extra device-code logins look like account sharing.

**Root cause:** `GET /auth/status` reported local expiry without calling `_ensure_token_fresh`. The UI only polls status and never `/auth/keepalive`. `POST /auth/login` required `check_login()` before refresh, so a dead-looking session skipped the persisted refresh_token and called `login_oauth()`. Middleware already refreshed Tidal-facing routes, but skipped `/api/auth`, and nothing ran on an idle sidecar.

**Prevention:** Status revives from refresh_token before reporting login-required. Login tries `_ensure_token_fresh` / `token_refresh` before `login_oauth()`. A refresh exception while a refresh_token exists must return `expired`, not device-code. Sidecar startup plus a 30-minute server interval call the same helper so a closed UI still persists. Tidal-facing routes refresh-and-retry once on a failed `check_login` (`ensure_tidal_logged_in`). `login_token(delete_on_failure=True)` must not unlink `token.json` while a refresh_token remains — only Reset / `logout()` wipes. `not_configured` only when both access and refresh are missing. Tokens stay in `path_file_token()` under the per-user config dir, not the download folder. A binary update (`install_update`) replaces the app and restarts the sidecar; it does not delete `token.json`. Do not rotate the bundled OAuth `clientId`s — that would force a world-wide re-login.

## 2026-08-30 — HiRes FLAC landed as `.m4a` (FLAC stuffed in MP4)

**What happened:** After #149, Zeratool downloaded tidal 534789853 via Hi-Fi. ffprobe showed 24/96 FLAC plus an MJPEG cover stream, but the path ended in `.m4a`. Best quality is a real `*.flac`.

**Root cause:** Shared mux/extension path, not discovery. Hi-Fi hardcoded `requires_flac_extraction=False`. BTS/DASH often labels FLAC as `audio/mp4`. `_detect_downloaded_audio_extension` then saw `ftyp` and *renamed* the dest to `.m4a` instead of extracting native FLAC. Mutagen wrote an MP4 `covr` (ffprobe: mjpeg). OAuth already extracted when codecs=FLAC and the container was not `.flac`; Hi-Fi skipped that plan. Dummy `extension_guess` also defaulted empty tags to `.m4a`.

**Prevention:** If the audio codec is FLAC, dest is `.flac` and MP4-boxed FLAC is extracted (`-map 0:a -vn -acodec copy`) before metadata. Empty codec + dest `.m4a` still extracts when the box has `fLaC`/`dfLa`. Cover stays as FLAC PICTURE, not ffmpeg MJPEG→PNG. Detect must not flip boxed FLAC to `.m4a`. Extract failure fails closed. Dummy guess for lossless settings is `.flac`.

## 2026-08-26 — Listed-HiRes downloads wrote 16-bit/44.1 FLAC

**What happened:** First-install desktop (v1.7.6) and Tetrarch live on SHA 15ba50a listed Sting — The Last Ship (tidal 534789853) as HiRes. The download wrote Mutagen-tagged FLAC at 16-bit/44.1 kHz / ~765 kb/s. Settings: `hifi_api_instances` empty, `hifi_instances []`, `hifi_health` None, active source oauth. Probe: requested `HI_RES_LOSSLESS`, delivered `LOSSLESS`.

**Root cause:** OAuth `get_stream` already sends `audioquality=HI_RES_LOSSLESS` and this client still returns `LOSSLESS` 16/44.1. Empty `hifi_api_instances` auto-discovers, but `discover_instances` only read tracker `streaming`. Live tracker JSON had `streaming: []` (hosts 504) and a live host under `api`. Discover returned [] → resolve fell back to OAuth → fail-closed or a 16/44.1 write. Catalog tags still list Hi-Res.

**Prevention:** Auto-discover `streaming` first, then tracker `api` when streaming is empty. Resolve/health then treat Hi-Fi as available and download Hi-Res from that host. Fail-closed only after that discovery still has no Hi-Res stream. Do not close #148 on synthetic tests or fail-closed alone.

## 2026-08-18 — Home insight fan would outlive a sidebar navigate

**What happened:** The fan overlay mounts on `.main` so it can cover the Home pane without a hash view. `navigate()` only tears down `#view`. Leaving the overlay on `.main` would keep the fan up after Home was gone.

**Root cause:** Overlay host ≠ view container. `#view` is replaced; `.main` is not.

**Prevention:** Call `_closeHomeInsightFan()` at the start of `navigate(view, opts)`. Sidebar `{ jump: true }` then closes the overlay. Keep `_navStack` / `.nav-back`. Do not restore the old `function navigate(view)`. Do not add a hash route for the fan.

## 2026-08-18 — Library sort pills sat low in the gold capsule

**What happened:** Library Artist / Album / Title / Plays chips used `.filter-pills` / `.pill`. Active Plays sat low in the gold capsule (more space above the letters than below). Search type chips had the same chrome: the active chip also sat flush against the search field’s gold curve.

**Root cause:** `.pill` is a 36px box with padding but was not a flex-centered box, so the label did not sit in the capsule. `.filter-pills` had horizontal padding only (`0 2px`). A 36px pill and the focused input’s 4px gold glow met across the 16px `.search-area` gap. PR 132 already named both defects and the CSS fix, but that branch stayed behind master and was never re-applied.

**Prevention:** Flex-center every `.pill` label (`display: flex; align-items: center; justify-content: center`) and `align-items: center` the row. Keep `.filter-pills` top padding (`8px 2px 0`) so an active chip cannot meet a rounded gold control above it. Do not give `.pill.active` a different height or padding. Leave `.album-search-filters .pill` at 28px. `button.pill` (Play/Shuffle, grouping, load-more) shares this chrome.
## 2026-08-18 — Library remount lost Plays, search, and the way back

**What happened:** Tetrarch opened a song/album cell from Library → Plays, landed on the album, and had no way back to that Plays list. Library and Plays in the sidebar were the only exits, and both felt like starting over.

**Root cause:** `navigate()` remounts and only saved `scrollY` in `_viewState`. Breadcrumbs are destination jumps, not a stack — album crumbs go to Library. `renderLibrary` wiped `libraryQuery` on every mount and reloaded albums/artists with `''`, so even a Library remount dropped search. `librarySort` survived as a global, but the Plays context still felt gone because there was no previous-view pop.

**Prevention:** Keep a `_navStack` of `{ view, librarySort, libraryQuery, scrollY }`. Default `navigate()` pushes the outgoing snapshot. `{ jump: true }` / `{ replace: true }` (sidebar, Sync Library) clear the stack. `{ back: true }` pops and restores library sort/query before `renderLibrary`. Do not wipe `libraryQuery` on mount. Show a quiet `.nav-back` chevron on drill-ins only when the stack is non-empty. Do not treat sidebar clicks as stack pops.

## 2026-08-18 — Albums gallery regrouped the whole library on every paint

**What happened:** Library sort pill "Album" called `GET /api/library/albums` and sat ~16–25s with zero bytes on a ~12k-row / ~1565-album library. `GET /api/library` was ~22ms.

**Root cause:** `all_albums` always called `_album_cards(db)` with no row subset. That is `db.all_tracks()` plus `find_candidates` = `combinations(N albums, 2)` (~1.2M pairs) and `assess_pair` for every pair. Scan/enrichment had already stamped `release_id` and stored assessments; the gallery ignored both. The same full-library grouping cost was already forbidden on artist click (PR 133) and Home/recent-albums (PR 137).

**Prevention:** When `release_stamps_complete()`, build gallery cards from stamped `release_id` groups. Do not call `all_tracks()` or `find_candidates` on the whole library. Attach stored `album_grouping_assessments` by reconstructing `release:` ids from left/right signatures so possible_duplicate / review / members / Various Artists / cover_url stay correct. Avoid correlated cover-art subqueries. Cold after v9 migrate (stamps incomplete): one full `_album_cards(db)` that writes every stamp, then later paints use the stamp path. A grouping decision restamps only the pair. Lock the warmed 12k gallery to the same <250ms budget as artist/release/recent-albums.

## 2026-08-18 — Lyrics panel stayed empty for years

**What happened:** Opening Lyrics on now-playing (including library files with no `.lrc` / tags, and Tidal-only streams) showed nothing. Live 1.7.6 `GET /api/lyrics/local` returned `{mode: none}` because download settings `lyrics_embed` and `lyrics_file` default off, so `metadata_write` never called `track.lyrics()`.

**Root cause:** The player was local-only (`is_local` + a disk path) and never asked Tidal. Tidal already had the sanctioned lyrics object (`text` / `subtitles`) on the download path. The panel and the library stayed empty unless someone opted into download-time writes.

**Prevention:** Keep `read_local_lyrics` first. If local is `none` and Tidal is signed in, fetch via `track.lyrics()` and cache. Enable `#btn-lyrics` for Tidal-only now-playing. Do not silently flip `lyrics_embed` / `lyrics_file`. Offer panel **Save lyrics** so a sidecar can be written for offline local playback. No Genius/web scrape.

## 2026-08-18 — Home showed two identical Continue Listening tiles

**What happened:** After v1.7.6 the Tetrarch saw two resume tiles on Home for the same track (Huelepega / Sandy, PAPO — Otra Vez) with Resume 1:58 and Resume 1:59. The pair appeared when `/Volumes/Music` was unmounted or unreachable. After a quit/reopen with the volume up, Home was one tile again. Footer `#now-playing` was not the extra copy.

**Root cause:** `renderHome` appends a `.home-wrap` before `await /home`. When the music volume is down, `/home` is slow or retried (NAS `Path.is_dir()`/`stat`, or a second navigate while the first fetch is still in flight). The second paint appended another wrap instead of replacing. `_renderContinueListening` and `_renderRecentStrip` were also append-only. `_initApp` can paint `.home-recent-section` when `/home/recent` wins the race, then `renderHome` paints it again on the same wrap. `volume_available === false` correctly adds the offline banner; that path must still leave one resume tile.

**Prevention:** At most one `.home-wrap` in the view container, one `.continue-card`, and one `.home-recent-section`. A later paint — including an overlapping delayed `/home` with `volume_available: false` — removes the previous node and appends the new one. Offline banner + one Continue Listening tile is fine; two resume tiles is not. Keep the live eyebrow **Continue Listening**. Do not add a second Now Playing section. Decision-test the delayed offline `/home` race, not only a generic second navigate.

## 2026-08-18 — Artist search tiles showed photos with no name

**What happened:** Searching Tetrarch (David Diaz) by Artist showed a grid of square photos and no readable name under or on the tiles.

**Root cause:** Search already put `item.name` in `.album-card-title`. A later `.album-card-art { height: 100%; object-fit: cover }` rule, meant for `img` inside `.album-card-art-wrap`, also hit Tidal’s sibling `div.album-card-art`. Grid stretch plus `.album-card { overflow: hidden }` then clipped `.album-card-meta`. Tidal search images used `alt: ''`.

**Prevention:** Keep square art with `aspect-ratio: 1`. Scope `height: 100%; object-fit: cover` to `.album-card-art-wrap .album-card-art`. Set `align-items: start` on `.album-grid` / `.album-gallery` so cards grow for the caption. Artist `img` alt is the name; the legend is visible title text, not overlay-only.

## 2026-08-18 — Now-playing Download shown for a file already in the library

**What happened:** Playing a downloaded track (Huelepega / Sandy, PAPO / Otra Vez) still showed `#now-download` on the now-playing bar. Repeat-one and mid-play did not matter. The footer treated the queue item as a Tidal download target.

**Root cause:** `updateNowPlayingButtons` hid Download only when `current.is_local` was truthy. Tidal-shaped queue items (search, album tracks, Show on Tidal) often have an `id` and omit `is_local` even when the same recording is on disk. `album_lookup` then forced `is_local = False` and only restored it on a `(title, artist, album)` triple against Tidal's album string, without stamping `path` / `local_path`. A leftover ISRC `path` from `_serialize_track` was ignored by the player, which also streams unless `is_local` is set.

**Prevention:** Hide `#now-download` when `is_local`, `path` / `local_path`, or the audio src is `/api/playback/local`. Stamp `is_local` plus `path` / `local_path` from album-scoped title+artist (the queried release's files), never ISRC. Clicking Download on a local track toasts "Already in your library" and must not enqueue again. The now-playing bar must name the source: `#now-source` uses the track-row `source-tag` chip and prefers the audio src (`/api/playback/local` → local, `/api/playback/stream/` → tidal) over queue flags.

## 2026-08-18 — Now-playing bar did not name Local vs Tidal

**What happened:** While a downloaded track played, the footer showed title, artist — album, and quality, but not whether audio came from the file or a Tidal stream.

**Root cause:** Track rows already paint `source-tag` / `local-tag` / `tidal-tag`. The now-playing bar did not. Queue `is_local` alone is also the wrong signal; a library match should play `/api/playback/local`.

**Prevention:** Paint `#now-source` in `.now-sub-row` with those classes and the text `local` or `tidal`. Prefer audio src, then on-disk flags vs Tidal id. Hide when idle.

## 2026-08-18 — Cold boot waited on Tidal before the sidecar was ready

**What happened:** Tauri stayed on the spinner until lifespan finished a serial Tidal `resolve_source` (Hi-Fi health, gist key refresh, OAuth restore, quality probe). Each of those calls could use the 45s download timeout against a 30s health poll. Home then awaited `/home/recent` before `navigate('home')`, and first `/api/home` paid a NAS `Path.is_dir()`/`stat` plus unused extras (completionist join, peak hours, format breakdown, best-streak, week-vs-last).

**Root cause:** Lifespan treated Tidal network and optional bot install as ready-path work. The worker already recovered before claim, but ready was written only after Tidal returned. The Home body gated first paint on a 4ms recent fetch that was not required to show the existing “Loading your library…” hint.

**Prevention:** Ready after migrate + download-job recovery. Restore Tidal silently after ready (`allow_interactive_login=False`); start the Discord bot after ready. Cap Hi-Fi / gist / quality-probe timeouts at ~2s. Do not await `/home/recent` before navigating Home. First `/api/home` returns the tiles Home actually renders and must not probe NAS or compute unused extras. Never group or scan on boot.

## 2026-08-18 — Sync Library spent minutes mutagen-reading already-tagged rows

**What happened:** After mark-and-sweep, isolated Mac Sync preserved 11,974 / 8,554 good / 3,420 skipped rows and named phases worked. First increment was 0.46s. Then `phase=repairing` sat on Synology tag reads (279/8402 at 46s; 1871/3002 at 188s). The old 90s 0/0 hang became a long repair.

**Root cause:** `_background_scan` called `_reconcile_library_rows` before the walk. `metadata_repair_worklist` selected `metadata_complete != 1 OR codec IS NULL`. Schema v7 sets `metadata_complete=0` on every non-unreadable row when release columns are added, so thousands of already-tagged tracks were mutagen-read on the NAS.

**Prevention:** Worklist is placeholder/missing identity only. Stamp complete identity in a cheap DB update. Do not open `#recycle` or already-tagged files. Discover/walk first; leftover repair is after first progress. No start-of-scan deletes.

## 2026-08-18 — Fingerprint sweep write skipped `write_transaction` after rebase onto 135

**What happened:** Rebasing scan-safety onto `717ec5a` applied the fingerprint fast-path sweep as `set_meta` + `commit`. That commit predates PR 135’s writer helper.

**Root cause:** The follow-up commit only added the DB-only recycle drop. It did not go through the new `write_transaction` contract that 135 added for every short library persist.

**Prevention:** After rebasing scanner work onto the lock-contention helper, wrap remaining `set_meta` / `record` / `remove` persists in `write_transaction`. Keep mark-and-sweep (no start-of-scan deletes) and 135’s short writer bursts together.

## 2026-08-17 — Sync Library deleted cache rows before the walk finished

**What happened:** On a clean copy of the real Mac library DB (schema v9, 11,974 rows), Sync Library stayed on `Scanning...` for 90s with `/api/library/scan/status` stuck at `{"scanning":true,"scanned":0,"total":0,"done":false}`. The isolated cache shrank to 8,554 rows before the process exited. Stale `#recycle` tracks stayed visible because the walk never completed.

**Root cause:** `_background_scan` backed up the DB, then called `drop_skipped_scan_paths()` and committed deletes before reconcile/walk finished. Status was only reset after that pre-walk work, so a Synology-backed reconcile or a locked backup looked like a 0/0 black hole. Writer transactions also stayed open across mutagen/ffmpeg reads (commit every 50 records), and full-library `_album_cards(include_artwork=True)` ran on the scan thread. A matching scan fingerprint also skipped the walk entirely, so stale `#recycle` rows could survive a later Sync.

**Prevention:** Never delete or age `scanned` rows at scan start. Mark-and-sweep skipped/stale paths only after a successful traversal, including the unchanged-fingerprint fast path (DB-only drop, no walk). An interrupted or failed scan must preserve the previous good cache. Do not read or repair rows under skipped directories. Expose a named `phase` immediately and increment `scanned` during discovery even when `total` is unknown. Stage metadata outside a writer transaction; commit short batches only. Keep the skipped-directory list centralized in `library_scanner.py`. Do not hold the scan busy state on full-library album grouping.

## 2026-08-17 — Recently Added stayed blank while a cover-art subquery scanned the library

**What happened:** Recently Added showed only the search shell and filter pills for ~3s. Warmed `/library/recent-albums` was 2.998s / 3.007s on the 11,974-row Mac library after PR 133 cut grouping from 25–53s to ~2.5–3s.

**Root cause:** The remaining cost was not page grouping. `recent_albums_page` `GROUP BY album`'d the whole library with a correlated cover-art subquery that `SCAN`ned the path PK once per album (~500–800ms on a local 12k/1.5k fixture; ~3s on NAS-backed SQLite). The endpoint then discarded that cover data and used `_album_cards`. The route also awaited the API before painting any results copy, so the wait was a blank shell.

**Prevention:** Page recency without per-album cover-art subqueries. Group only the current page titles plus already-stamped release members. Do not call `tracks_for_artist` for every page artist. Paint a Home-style `home-loading-hint` before the fetch. Lock the warmed 12-item page to the same <250ms budget as artist/release.

## 2026-08-17 — Library grouping held the SQLite writer lock until the download worker died

**What happened:** The Mac release-candidate gate saw repeated `sqlite3.OperationalError: database is locked` for minutes. A source-profile worker died at `BEGIN IMMEDIATE` while library API / scan writes were in flight. Port 8878 looked like a long scan; it was lock contention. Live v1.7.5 was left untouched.

**Root cause:** `_album_cards` called `save_grouping_assessment` inside the candidate loop. The first INSERT opened an implicit write transaction. Later `assess_pair` CPU, artwork reads, more inserts, `clear_release_ids`, and `stamp_release_ids` all ran before `commit()`. Scan/index paths did the same: `db.record()` then metadata/waveform/genre I/O before the next commit. API, scanner, enrichment, and `DownloadJobService` each open their own `LibraryDB` connection. WAL readers are fine; one reserved writer blocks every other `BEGIN IMMEDIATE`. The worker’s claim is uncaught, so a 5-second busy timeout killed the thread instead of retrying.

**Prevention:** Compute grouping, filesystem/network I/O, metadata reads, and callbacks first. Persist in one short `write_transaction`. Never hold a SQLite writer lock across that work. Multiple `LibraryDB` connections serialize writes at that helper (`BEGIN IMMEDIATE` + per-db lock). Retry a transient lock *outside* the process lock with a short acquire busy timeout — do not sit in `PRAGMA busy_timeout=5000` while holding that lock. The download worker must catch a remaining lock error and keep running to a terminal job state.

## 2026-08-17 — Post-download `rglob` walked Synology `#recycle` and stalled the worker

**What happened:** After a track finished, Downloads History showed Done while Active stayed on "Waiting to start...". The worker was busy. On a Synology library, `scan_new_downloads` used `Path.rglob("*")` on the configured download root, so it recursively entered `#recycle` and other trash trees. Large deleted folders kept the next jobs queued and pegged the worker.

**Root cause:** Local library indexing already skipped trash-like directory names through `is_skipped_scan_dir` / `os.walk` pruning. The post-download indexer did not. It also marked the job `done` and wrote History before that walk finished, so the UI looked idle while the worker was still scanning.

**Prevention:** Index the completed file path(s) directly. If a walk is required, reuse the centralized skip helpers and prune those directories. Keep the job in an `indexing` status (and show that status) until post-processing finishes, then mark `done`.

## 2026-08-17 — Full-library album grouping on a single-artist/release read

**What happened:** Artist page and release detail took 25–53s each on a 12k-row library. SQLite itself was instant. A bad release id 404'd in ~50s.

**Root cause:** `artist_albums`, `artist_album_tracks`, and `release_tracks` called `_album_cards(db)`, which is not just “group everything.” On the live Mac it ran `build_local_album_groups(db.all_tracks())` on 11,844 rows, then `find_candidates` = `combinations(1565 albums, 2)` = 1,223,830 pairs, then `assess_pair` plus SQLite writes. In-flight CPU was 98% in `normalize_text()` (`unicodedata.combining`). After the release-tracks GET, `renderLocalAlbumDetail` re-fetched artist albums only for cover. Artist/album “loading” used `skeleton-row`, which has no CSS, so the wait was a blank page. “1 albums” was both the Home hero tile and the gallery count.

**Prevention:** Group only the rows for that artist, the current recent-albums page, or a stamped release id. Do not call full-library grouping on those reads. After v9 migrate, `release_id` is NULL; a stamp miss for a real hash must recover with one full `_album_cards(db)` that writes every stamp, then return the card. A miss on a complete index 404s without walking. Skip the artist-albums cover fetch when the release payload already has `cover_url`. Use a visible Home-style loading hint, not an unstyled `skeleton-row`. Singularize both the hero tile and the gallery count.

## 2026-08-16 — Local scan indexed Synology `#recycle` as an artist

**What happened:** Artists view showed a `#recycle` heading with deleted NAS files (WAV titles like `08 Menu Groove Edit`) as if they were a real library artist.

**Root cause:** The local folder walk used `rglob("*")` with no directory-name skip. Recycle and system dirs (`#recycle`, `@eaDir`, `$RECYCLE.BIN`, `.Trash`, `lost+found`, …) were treated as music. When tags were missing, the first relative path part became the artist, so `#recycle` appeared as an artist. Duplicate scoring already penalized `#recycle` paths; the indexer did not skip them.

**Prevention:** Skip those directory names at the walk (whole component, case-insensitive). Do not match the word recycle in a track title. Drop already-indexed rows whose path contains a skipped dir so a rescan does not keep them. Hidden-dot albums stay indexed unless the name is an explicit skip.

## 2026-08-15 — Progress SSE skipped the queue counts that clear the waiting card

**What happened:** Claiming a queued job emits `progress` (and that payload already includes `queued_count`). The Active list only re-snapshotted on non-`progress` events, so the “Waiting to start…” summary stayed beside the now-running track until a later terminal or queue event.

**Root cause:** The client treated `progress` as a per-card paint and ignored the queue envelope. Separately, Cancel All marked `running`/`retrying` rows cancelled, but `_update_job` / `_mark_retrying` wrote those statuses back and broadcast `progress`, which redrew the job in Active.

**Prevention:** Apply `queued_count` / `active_count` / `paused` from progress payloads. Do not write an active job status, or emit downloading/retrying progress, after cancel has been requested or the row is already `cancelled`. If `_update_job` refuses `retrying`, `_mark_retrying` must mark cancelled and the retry loop must return — do not sleep and continue.

## 2026-08-15 — Exact quality match rejected valid Blue Lossless

**What happened:** Settings default to `HI_RES_LOSSLESS`. Tracks that Tidal only publishes as Blue Lossless failed the download gate, sat on "Waiting to start...", and could not be requeued. The Downloads badge also stayed at 1 after Clear Done / Clear All.

**Root cause:** `_require_exact_quality` required the delivered tier to equal the setting. Tidal already returns the best available stream at or below the request, so LOSSLESS FLAC was treated as a mismatch. The nav badge was a local increment/decrement that double-counted `batch_queued` and never synced from queue state, so Clear History could not hide it.

**Prevention:** Treat lossless settings as a family + ceiling. Accept FLAC `LOSSLESS`/`HI_RES`/`HI_RES_LOSSLESS` when lossless was requested; still reject AAC/HIGH. The Downloads Active list and badge are projections of `/downloads/active/snapshot` and `/downloads/queue-state`. Do not accumulate SSE cards; `batch_queued.count` is remaining queued jobs, not the last enqueue size.

## 2026-08-15 — Treated local playback as the core hello-world

**What happened:** During Cloud Agent environment setup, the first end-to-end demo indexed a synthetic local FLAC and played it in the GUI. That path works without Tidal. Catalog search, stream, and download do not.

**Root cause:** `/api/auth/status` was `not_configured` (`token.json` has null tokens). `/api/search` returns `401 Not logged in to Tidal` in that state. The UI still indexes and searches the local library, so it looks like “search works” while Tidal actions do nothing.

**Prevention:** Before claiming the product works end to end, call `GET /api/auth/status` and require `logged_in: true`. Then exercise a Tidal catalog search and a download. Local scan/playback is only a fallback when Tidal is intentionally out of scope.

## 2026-08-15 — Treated HIGH/M4A as a successful download

**What happened:** After Tidal login, `HI_RES_LOSSLESS` downloads failed with a quality mismatch. I switched `quality_audio` to `HIGH` so an M4A file landed. The user needs FLAC.

**Root cause:** This account is Hi-Res Premium (`highestSoundQuality: HI_RES`), but every OAuth client this app can use (`playbackinfopostpaywall`) still returns `HIGH` / `MP4A`. The exact-quality gate then errors, or a HIGH setting “succeeds” as lossy M4A. Public Hi-Fi API instances (the FLAC path) were all down.

**Prevention:** Do not lower quality to make a download succeed. Check subscription + raw `audioQuality`/`codecs`. FLAC requires a lossless delivery (`LOSSLESS`/`HI_RES_LOSSLESS` + `flac`), not a completed HIGH job.

## 2026-08-15 — Treated a live Tidal login as a gray "credentials saved" chip

**What happened:** After a real login, the sidebar Tidal chip stayed gray. `/api/auth/status` returns `logged_in: true` with `auth_state: credentials_ready`. The UI treated `credentials_ready` as a saved-but-offline state before the connected/green case.

**Root cause:** The presentation helper assumed `credentials_ready` meant "token on disk, session not verified." The local-only status endpoint now uses that state for a valid unexpired token.

**Prevention:** A saved unexpired token is connected. Use the default green `.connection-dot` for `logged_in` / `credentials_ready`. Keep gray only for an explicit saved-but-unverified state, which this API no longer has.
