# Playback Session

> Single active player across all browsers/tabs + persistent recently played history.
> Two features, one spec — they share the same server-side session state.

---

## 1. Single Player Lock

### Problem
Two browsers open → both try to play → one is DOA or they fight for the audio device. `BroadcastChannel` only works within the same browser process.

### Solution
Server-side coordination via WebSocket. Last-to-play wins.

**Flow:**
1. Client opens WebSocket to `/ws/playback` on page load
2. Server assigns a session ID per connection
3. Client hits play → sends `{ type: "playing", track: {...} }` to server
4. Server stores active session ID, broadcasts `{ type: "pause" }` to all other connections
5. Old browser receives pause → stops playback, updates UI
6. Client disconnects (tab close) → server removes session, no broadcast needed

**Edge cases:**
- Tab refresh: new WebSocket connection, old one dies naturally
- Multiple tabs same browser: WebSocket handles this too — `BroadcastChannel` becomes redundant
- Server restart: all WebSocket connections drop, clients reconnect, first to play wins

---

## 2. Recently Played (Persistent)

### Problem
Recently played list lives in JS memory — lost on page reload, not shared across browsers.

### Solution
Server-side recently played history in the library DB.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS recently_played (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT,
    track_id INTEGER,
    title TEXT,
    artist TEXT,
    album TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recently_played_at ON recently_played(played_at DESC);
```

**Flow:**
1. Client starts playing a track → POST `/api/playback/history` with track info (already happens via play event)
2. Server inserts into `recently_played` table
3. Home view fetches GET `/api/playback/history?limit=20` on load
4. Recently played section on Home shows last 20 tracks as album art cards (horizontal strip)
5. Any browser, any tab — same history

**Dedup:** Don't insert if the same track was the last entry (pause/resume shouldn't create duplicates).

---

## Questions to Answer

- Max history depth? 100? 500? Unlimited with pagination?
- Should recently played show on the player bar (mini queue preview)?
- Do we keep `BroadcastChannel` as a fast-path for same-browser tabs, or remove it entirely in favor of WebSocket-only?
- Should the WebSocket also sync now-playing state (so opening a new tab shows what's currently playing)?
- Queue sync across browsers? (Ambitious — park for later)

---

## Ideas Parking Lot

- "Continue listening" section on Home — resume from where you left off
- Play history as a timeline visualization (what you listened to today/this week)
- "You played this 47 times" counter on track detail
- Listening streaks: "5 days in a row"
- Now-playing sync: open new tab → sees current track, progress, queue without hitting play
- Remote control: phone browser controls desktop playback (Spotify Connect style)
