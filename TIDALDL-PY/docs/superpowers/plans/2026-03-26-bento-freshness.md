# Bento Grid Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bento grid hero tiles reflect the user's last 7 days of listening instead of frozen all-time stats, and add an "on repeat" half-tile for the most-played track this week.

**Architecture:** Add a `_windowed_stats()` helper to `LibraryDB` that runs the same aggregate queries with a `played_at >= ?` time filter. The API endpoint merges both into a single response. The frontend silently prefers windowed data when available, falling back to all-time. A new CSS split-tile pattern subdivides the genre tile to hold a condensed genre + "on repeat" half-tile.

**Tech Stack:** Python/SQLite (backend), vanilla JS (frontend), CSS grid (layout)

**Spec:** `docs/superpowers/specs/2026-03-26-bento-freshness-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tidal_dl/helper/library_db.py` | Add `_windowed_stats()` helper, call from `home_stats()`, fix `top_album` query |
| `tidal_dl/gui/api/home.py` | Convert `this_week` cover paths to URLs in `home_stats()` endpoint |
| `tidal_dl/gui/static/app.js` | Recency-aware data binding in `_renderHomeGrid()`, new `_onRepeatHalf()`, split `_genreTile()` |
| `tidal_dl/gui/static/style.css` | `.bento-split`, `.bento-half`, `.bento-on-repeat` styles |
| `tests/test_home.py` | Tests for windowed stats, fallback, top_album fix |

---

### Task 1: Backend — Windowed Stats Helper + top_album Fix

**Files:**
- Modify: `tidal_dl/helper/library_db.py:593-839`
- Test: `tests/test_home.py`

- [ ] **Step 1: Write failing tests for windowed stats and top_album fix**

Add these tests to `tests/test_home.py`:

```python
import time


def test_home_stats_this_week_with_recent_plays(db):
    """this_week reflects only plays in the last 7 days."""
    now = int(time.time())
    old = now - 30 * 86400  # 30 days ago

    # Insert tracks
    db.record("a.flac", status="tagged", artist="Linkin Park", title="Numb",
              album="Meteora", duration=200, genre="Rock")
    db.record("b.flac", status="tagged", artist="Deftones", title="Change",
              album="White Pony", duration=300, genre="Alt Rock")
    db.commit()

    # Old plays — Linkin Park dominates all-time
    for _ in range(50):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Linkin Park", "Rock", 200, old),
        )
    # Recent plays — Deftones dominates this week
    for _ in range(8):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("b.flac", "Deftones", "Alt Rock", 300, now - 3600),
        )
    db.commit()

    stats = db.home_stats()

    # All-time: Linkin Park leads
    assert stats["top_artist"]["name"] == "Linkin Park"
    assert stats["top_artist"]["play_count"] == 50

    # This week: Deftones leads
    assert stats["this_week"]["total_plays"] == 8
    assert stats["this_week"]["top_artist"]["name"] == "Deftones"
    assert stats["this_week"]["top_artist"]["play_count"] == 8
    assert stats["this_week"]["most_replayed"]["name"] == "Change"
    assert stats["this_week"]["most_replayed"]["play_count"] == 8
    assert stats["this_week"]["genre_breakdown"][0]["genre"] == "Alt Rock"


def test_home_stats_this_week_empty_when_no_recent(db):
    """this_week.total_plays is 0 when no plays in last 7 days."""
    now = int(time.time())
    old = now - 30 * 86400

    db.record("a.flac", status="tagged", artist="Linkin Park", title="Numb",
              album="Meteora", duration=200, genre="Rock")
    db.commit()

    # Only old plays
    for _ in range(10):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Linkin Park", "Rock", 200, old),
        )
    db.commit()

    stats = db.home_stats()
    assert stats["this_week"]["total_plays"] == 0
    assert stats["this_week"]["top_artist"] is None
    assert stats["this_week"]["most_replayed"] is None


def test_home_stats_this_week_top_artists_list(db):
    """this_week.top_artists returns up to 5 artists sorted by play count."""
    now = int(time.time())
    db.record("a.flac", status="tagged", artist="A", title="T1", album="Al", duration=100)
    db.record("b.flac", status="tagged", artist="B", title="T2", album="Al", duration=100)
    db.record("c.flac", status="tagged", artist="C", title="T3", album="Al", duration=100)
    db.commit()

    for i, (path, artist, count) in enumerate([("a.flac", "A", 10), ("b.flac", "B", 5), ("c.flac", "C", 2)]):
        for _ in range(count):
            db._conn.execute(
                "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
                (path, artist, "Rock", 100, now - 3600),
            )
    db.commit()

    stats = db.home_stats()
    tw = stats["this_week"]
    assert len(tw["top_artists"]) == 3
    assert tw["top_artists"][0]["name"] == "A"
    assert tw["top_artists"][1]["name"] == "B"
    assert tw["top_artists"][2]["name"] == "C"


def test_top_album_from_play_events(db):
    """top_album should be derived from play_events, not scanned.play_count."""
    now = int(time.time())
    db.record("a.flac", status="tagged", artist="Daft Punk", title="One More Time",
              album="Discovery", duration=320, genre="Electronic")
    db.record("b.flac", status="tagged", artist="Daft Punk", title="Around the World",
              album="Homework", duration=420, genre="Electronic")
    db.commit()

    # 10 plays for Discovery via play_events
    for _ in range(10):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("a.flac", "Daft Punk", "Electronic", 320, now - 3600),
        )
    # 3 plays for Homework via play_events
    for _ in range(3):
        db._conn.execute(
            "INSERT INTO play_events (path, artist, genre, duration, played_at) VALUES (?,?,?,?,?)",
            ("b.flac", "Daft Punk", "Electronic", 420, now - 3600),
        )
    db.commit()

    stats = db.home_stats()
    assert stats["top_album"]["album"] == "Discovery"
    assert stats["top_album"]["play_count"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd TIDALDL-PY && python -m pytest tests/test_home.py::test_home_stats_this_week_with_recent_plays tests/test_home.py::test_home_stats_this_week_empty_when_no_recent tests/test_home.py::test_home_stats_this_week_top_artists_list tests/test_home.py::test_top_album_from_play_events -v`

Expected: FAIL — `this_week` key does not exist in stats dict, `top_album` still uses scanned.play_count.

- [ ] **Step 3: Implement `_windowed_stats()` helper and fix `top_album`**

In `tidal_dl/helper/library_db.py`, add a helper method before `home_stats()` and modify `home_stats()` to call it:

```python
    def _windowed_stats(self, since: int) -> dict:
        """Aggregate play_events stats for a time window (played_at >= since)."""
        assert self._conn
        c = self._conn

        total_plays = c.execute(
            "SELECT COUNT(*) FROM play_events WHERE played_at >= ?", (since,)
        ).fetchone()[0]

        if total_plays == 0:
            return {
                "total_plays": 0,
                "top_artist": None,
                "top_artists": [],
                "most_replayed": None,
                "genre_breakdown": [],
            }

        # Top artists in window
        top_artists_rows = c.execute(
            """SELECT artist, COUNT(*) as total
               FROM play_events WHERE artist IS NOT NULL AND played_at >= ?
               GROUP BY artist ORDER BY total DESC LIMIT 5""",
            (since,),
        ).fetchall()

        top_artist = None
        top_artists = []
        for r in top_artists_rows:
            best_path = c.execute(
                """SELECT path FROM play_events
                   WHERE artist = ? AND path IS NOT NULL AND played_at >= ?
                   GROUP BY path ORDER BY COUNT(*) DESC LIMIT 1""",
                (r["artist"], since),
            ).fetchone()
            best = best_path
            if not best:
                best = c.execute(
                    "SELECT path FROM scanned WHERE artist = ? LIMIT 1",
                    (r["artist"],),
                ).fetchone()
            artist_tracks = c.execute(
                "SELECT COUNT(*) FROM scanned WHERE artist = ?", (r["artist"],)
            ).fetchone()[0]
            artist_albums = c.execute(
                "SELECT COUNT(DISTINCT album) FROM scanned WHERE artist = ?", (r["artist"],)
            ).fetchone()[0]
            artist_genre_row = c.execute(
                "SELECT genre FROM scanned WHERE artist = ? AND genre IS NOT NULL AND genre != '' GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1",
                (r["artist"],),
            ).fetchone()
            entry = {
                "name": r["artist"],
                "play_count": r["total"],
                "cover_path": best["path"] if best else None,
                "track_count": artist_tracks,
                "album_count": artist_albums,
                "genre": artist_genre_row["genre"] if artist_genre_row else None,
            }
            top_artists.append(entry)
            if top_artist is None:
                top_artist = entry

        # Most replayed track in window
        most_replayed = None
        mr = c.execute(
            """SELECT pe.path, s.title, pe.artist, s.album, COUNT(*) as play_count
               FROM play_events pe
               LEFT JOIN scanned s ON s.path = pe.path
               WHERE pe.path IS NOT NULL AND pe.played_at >= ?
               GROUP BY pe.path ORDER BY play_count DESC LIMIT 1""",
            (since,),
        ).fetchone()
        if mr:
            most_replayed = {
                "name": mr["title"] or (pathlib.Path(mr["path"]).stem if mr["path"] else "Unknown"),
                "artist": mr["artist"],
                "album": mr["album"],
                "play_count": mr["play_count"],
                "cover_path": mr["path"],
                "path": mr["path"],
            }

        # Genre breakdown in window
        genre_breakdown = [
            {"genre": r["genre"], "count": r["cnt"]}
            for r in c.execute(
                """SELECT genre, COUNT(*) as cnt FROM play_events
                   WHERE genre IS NOT NULL AND played_at >= ?
                   GROUP BY genre ORDER BY cnt DESC LIMIT 8""",
                (since,),
            ).fetchall()
        ]

        return {
            "total_plays": total_plays,
            "top_artist": top_artist,
            "top_artists": top_artists,
            "most_replayed": most_replayed,
            "genre_breakdown": genre_breakdown,
        }
```

Then at the end of `home_stats()`, before the `return` statement, add the windowed call and fix `top_album`:

Replace the `top_album` query block (lines ~787-802):

```python
        # Album with most combined plays (from play_events — authoritative)
        top_album = None
        ta = c.execute(
            """SELECT s.album, pe.artist, COUNT(*) as total, MIN(pe.path) as cover_path
               FROM play_events pe
               LEFT JOIN scanned s ON s.path = pe.path
               WHERE pe.path IS NOT NULL AND s.album IS NOT NULL
               GROUP BY s.album, pe.artist
               ORDER BY total DESC LIMIT 1"""
        ).fetchone()
        if ta and ta["album"]:
            top_album = {
                "album": ta["album"],
                "artist": ta["artist"],
                "play_count": ta["total"],
                "cover_path": ta["cover_path"],
            }
```

And add the `this_week` key right before the return dict:

```python
        # Rolling 7-day windowed stats
        seven_days_ago = int(time.time()) - 7 * 86400
        this_week = self._windowed_stats(seven_days_ago)
```

Then add `"this_week": this_week,` to the return dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd TIDALDL-PY && python -m pytest tests/test_home.py -v`

Expected: ALL PASS (new tests + existing tests).

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/helper/library_db.py tests/test_home.py
git commit -m "feat(backend): add 7-day windowed stats to home_stats, fix top_album source"
```

---

### Task 2: API Layer — Convert this_week Cover Paths to URLs

**Files:**
- Modify: `tidal_dl/gui/api/home.py:96-130`
- Test: `tests/test_home.py`

- [ ] **Step 1: Write failing test for this_week cover URLs in API response**

Add to `tests/test_home.py`:

```python
def test_api_home_includes_this_week():
    """GET /api/home response includes this_week key."""
    from fastapi.testclient import TestClient
    from tidal_dl.gui import create_app

    client = TestClient(create_app(port=8765))
    host = {"host": "localhost:8765"}
    resp = client.get("/api/home", headers=host)
    assert resp.status_code == 200
    data = resp.json()
    assert "this_week" in data
    assert "total_plays" in data["this_week"]
    # cover_path should not leak into API response
    if data["this_week"].get("top_artist"):
        assert "cover_path" not in data["this_week"]["top_artist"]
    if data["this_week"].get("most_replayed"):
        assert "cover_path" not in data["this_week"]["most_replayed"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd TIDALDL-PY && python -m pytest tests/test_home.py::test_api_home_includes_this_week -v`

Expected: FAIL — `cover_path` leaks or `this_week` not properly transformed.

- [ ] **Step 3: Add this_week cover_url conversion to home.py**

In `tidal_dl/gui/api/home.py`, in the `home_stats()` endpoint function, after the existing cover_url conversion block (after line 128), add:

```python
    # Convert this_week cover paths to URLs
    tw = stats.get("this_week", {})
    if tw.get("top_artist") and tw["top_artist"].get("cover_path"):
        tw["top_artist"]["cover_url"] = (
            "/api/library/art?path=" + quote(tw["top_artist"]["cover_path"], safe="")
        )
    for a in tw.get("top_artists", []):
        if a.get("cover_path"):
            a["cover_url"] = "/api/library/art?path=" + quote(a["cover_path"], safe="")
    if tw.get("most_replayed") and tw["most_replayed"].get("cover_path"):
        tw["most_replayed"]["cover_url"] = (
            "/api/library/art?path=" + quote(tw["most_replayed"]["cover_path"], safe="")
        )
    # Strip internal cover_path from this_week
    if tw.get("top_artist"):
        tw["top_artist"].pop("cover_path", None)
    for a in tw.get("top_artists", []):
        a.pop("cover_path", None)
    if tw.get("most_replayed"):
        tw["most_replayed"].pop("cover_path", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd TIDALDL-PY && python -m pytest tests/test_home.py -v`

Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/gui/api/home.py tests/test_home.py
git commit -m "feat(api): convert this_week cover paths to URLs, strip internals"
```

---

### Task 3: CSS — Split-Tile and On-Repeat Styles

**Files:**
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Add split-tile and on-repeat CSS**

Append after the `.bento-replayed .bento-sub` rule (around line 1877) in `style.css`:

```css
/* ---- SPLIT TILE (two half-tiles stacked vertically) ---- */
.bento-split {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.bento-split .bento-half {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.bento-split .bento-half:first-child {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.bento-split .bento-half .bento-body {
  padding: 0;
  height: auto;
}
.bento-split .bento-half .bento-insight {
  display: none;
}
.bento-on-repeat .bento-label {
  font-size: 0.9rem;
  -webkit-line-clamp: 1;
}
.bento-on-repeat .bento-sub {
  font-size: 0.7rem;
}
.bento-on-repeat .bento-stat {
  font-size: 0.6rem;
}
```

- [ ] **Step 2: Commit**

```bash
git add tidal_dl/gui/static/style.css
git commit -m "style: add bento-split and bento-on-repeat CSS for half-tiles"
```

---

### Task 4: Frontend — Recency-Aware Data Binding

**Files:**
- Modify: `tidal_dl/gui/static/app.js:574-627` (`_renderHomeGrid`)

- [ ] **Step 1: Update `_renderHomeGrid()` to prefer this_week data**

In `app.js`, modify `_renderHomeGrid()` (around line 574). Replace the section that builds artist and genre tiles to check for `this_week` data first:

At the top of the function, after `const established = totalPlays >= 100;`, add:

```javascript
  const tw = data.this_week || {};
  const hasRecent = (tw.total_plays || 0) > 0;
```

Replace the artist tile rendering (lines ~592-617):

```javascript
  // === Core tiles (always visible) ===
  // Prefer this_week artist data when available
  const heroArtist = hasRecent && tw.top_artist ? tw.top_artist : data.top_artist;
  if (heroArtist && heroArtist.play_count >= 5) {
    grid.appendChild(_artistTile(heroArtist, true));
  }
  if (data.most_replayed && data.most_replayed.play_count >= 10) {
    grid.appendChild(_replayedTile(data.most_replayed));
  }

  // Genre tile: prefer this_week genre data, split if on-repeat qualifies
  const recentGenres = hasRecent && tw.genre_breakdown && tw.genre_breakdown.length > 0;
  const hasPlayGenres = recentGenres || (data.genre_breakdown && data.genre_breakdown.length > 0);
  const genreSource = recentGenres ? tw.genre_breakdown
    : (data.genre_breakdown && data.genre_breakdown.length > 0) ? data.genre_breakdown
    : (data.track_genres || []);
  const genreLabel = genreSource.length > 0 ? genreSource[0].genre : null;
  const fromLibrary = !recentGenres && !(data.genre_breakdown && data.genre_breakdown.length > 0);
  const onRepeatTrack = hasRecent && tw.most_replayed && tw.most_replayed.play_count >= 3
    ? tw.most_replayed : null;
  if (genreSource.length > 0) {
    grid.appendChild(_genreTile(genreLabel, genreSource, fromLibrary, onRepeatTrack));
  }
  if (data.weekly_activity && data.weekly_activity.some(v => v > 0)) {
    grid.appendChild(_listeningTimeTile(data.listening_time_hours, data.weekly_activity, data));
  }

  // === Secondary tiles (tier 1 — hidden on compact) ===
  const allTimeExtra = (data.top_artists || []).slice(1, 3);
  const recentExtra = hasRecent ? (tw.top_artists || []).slice(1, 3) : [];
  const extraArtists = recentExtra.length > 0 ? recentExtra : allTimeExtra;
  for (const a of extraArtists) {
    if (a.play_count >= 3) {
      grid.appendChild(_t(_artistTile(a, false), 1));
    }
  }
```

- [ ] **Step 2: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(frontend): recency-aware data binding for artist and genre tiles"
```

---

### Task 5: Frontend — On-Repeat Half-Tile and Genre Split

**Files:**
- Modify: `tidal_dl/gui/static/app.js` (`_genreTile`, new `_onRepeatHalf`)

- [ ] **Step 1: Add `_onRepeatHalf()` renderer**

Add this function after `_genreTile()` in `app.js`:

```javascript
function _onRepeatHalf(track) {
  const half = h('div', { className: 'bento-half bento-on-repeat' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', 'On repeat', 'bento-eyebrow'));
  body.appendChild(textEl('div', track.name || 'Unknown', 'bento-label'));
  body.appendChild(textEl('div', track.artist || '', 'bento-sub'));
  body.appendChild(textEl('div', track.play_count + ' plays this week', 'bento-stat'));
  half.appendChild(body);
  half.addEventListener('click', (e) => {
    e.stopPropagation();
    const t = { ...track, local_path: track.path, is_local: true };
    playTrack(t);
  });
  a11yClick(half);
  return half;
}
```

- [ ] **Step 2: Modify `_genreTile()` to accept optional onRepeatTrack and split**

Update the `_genreTile` function signature and body. The current signature is `_genreTile(topGenre, breakdown, fromLibrary)`. Change it to:

```javascript
function _genreTile(topGenre, breakdown, fromLibrary, onRepeatTrack) {
  if (onRepeatTrack) {
    // Split tile: condensed genre on top, on-repeat on bottom
    const tile = h('div', { className: 'bento-tile bento-stat-tile bento-split' });
    const genreHalf = h('div', { className: 'bento-half' });
    const body = h('div', { className: 'bento-body' });
    body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
    body.appendChild(textEl('div', fromLibrary ? 'Top genre' : 'Recent genre', 'bento-stat-label'));
    body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
    genreHalf.appendChild(body);
    tile.appendChild(genreHalf);
    tile.appendChild(_onRepeatHalf(onRepeatTrack));
    return tile;
  }
  // Full-size genre tile — unchanged
  const tile = h('div', { className: 'bento-tile bento-stat-tile' });
  const body = h('div', { className: 'bento-body' });
  body.appendChild(textEl('div', topGenre || 'None', 'bento-label'));
  body.appendChild(textEl('div', fromLibrary ? 'Top genre' : 'Recent genre', 'bento-stat-label'));
  body.appendChild(_genreInsight(topGenre, breakdown, fromLibrary));
  body.appendChild(_barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))));
  // Detail: full genre breakdown beyond top 4
  const allGenres = breakdown.map(g => ({
    label: g.genre,
    value: g.count + (fromLibrary ? ' tracks' : ' plays')
  }));
  if (allGenres.length > 4) {
    body.appendChild(_detailBlock(allGenres.slice(4)));
  }
  tile.appendChild(body);
  if (allGenres.length > 4) _expandToggle(tile);
  return tile;
}
```

- [ ] **Step 3: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(frontend): on-repeat half-tile with genre split when recent data exists"
```

---

### Task 6: Integration Test — Full Roundtrip

**Files:**
- Test: `tests/test_home.py`

- [ ] **Step 1: Write integration test for API response with this_week data**

Add to `tests/test_home.py`:

```python
def test_home_stats_empty_includes_this_week(db):
    """home_stats returns this_week even with no data."""
    stats = db.home_stats()
    assert "this_week" in stats
    assert stats["this_week"]["total_plays"] == 0
    assert stats["this_week"]["top_artist"] is None
    assert stats["this_week"]["most_replayed"] is None
    assert isinstance(stats["this_week"]["genre_breakdown"], list)
    assert isinstance(stats["this_week"]["top_artists"], list)
```

- [ ] **Step 2: Run full test suite**

Run: `cd TIDALDL-PY && python -m pytest tests/test_home.py tests/test_library_db.py -v`

Expected: ALL PASS. No regressions.

- [ ] **Step 3: Commit**

```bash
git add tests/test_home.py
git commit -m "test: add integration test for this_week in empty home stats"
```

---

### Task 7: Verify Existing Tests — No Regressions

**Files:** None (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd TIDALDL-PY && python -m pytest tests/ -v --tb=short`

Expected: ALL PASS. The existing `test_home_stats_with_data` and `test_home_stats_empty` tests should still pass since all-time stats are unchanged.

- [ ] **Step 2: Verify the API endpoint manually**

Run: `cd TIDALDL-PY && python -c "from tidal_dl.helper.library_db import LibraryDB; from pathlib import Path; db = LibraryDB(Path.home() / '.config/music-dl/library.db'); db.open(); s = db.home_stats(); print('this_week plays:', s['this_week']['total_plays']); print('all-time plays:', s['total_plays']); tw_a = s['this_week']['top_artist']; print('this_week top:', tw_a['name'] if tw_a else 'none'); at_a = s['top_artist']; print('all-time top:', at_a['name'] if at_a else 'none'); db.close()"`

Expected: Prints both this_week and all-time stats from the real database, showing the difference between recent and cumulative data.
