# Card Inspect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace inline stat tile expand with a TCG-inspired card inspect overlay — click a stat tile to fan out a deck of detail cards, browse with keyboard, dismiss to collapse back.

**Architecture:** Clone-and-elevate pattern. Click a stat tile → clone it into a fixed overlay → animate from grid position to center via FLIP + Web Animations API → fan deck cards behind it → keyboard/click to cycle → dismiss reverses animation. Grid never reflows. All animations use `transform`/`opacity` only.

**Tech Stack:** Vanilla JS (Web Animations API, `element.animate()`), CSS, Python/SQLite (3 new queries)

**Spec:** `docs/superpowers/specs/2026-03-27-card-inspect-design.md`

**Design system:** `docs/design-system.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `tidal_dl/helper/library_db.py` | 3 new queries: `best_streak()`, `completionist_albums()`, `recent_albums()`. Add to `home_stats()` return. |
| `tidal_dl/gui/api/home.py` | Pass new fields through API response. |
| `tidal_dl/gui/static/app.js` | New card inspect module (~200 lines). Remove `_expandToggle`, `_detailBlock`. Modify 4 stat tile builders. Add keyboard guard. |
| `tidal_dl/gui/static/style.css` | New inspect overlay styles. Remove expand-related styles. |
| `tests/test_home.py` | Tests for 3 new queries. |

---

### Task 1: Backend — Three New Queries

**Files:**
- Modify: `tidal_dl/helper/library_db.py:682-934`
- Test: `tests/test_home.py`

- [ ] **Step 1: Write failing tests for the three new queries**

Add to `tests/test_home.py`:

```python
def test_best_streak(db):
    """best_streak returns longest consecutive-day play run."""
    now = int(time.time())
    day = 86400
    # Seed: 5 consecutive days, gap, then 3 consecutive days
    for i in range(5):
        db.log_play_event("track.flac", artist="A", genre="Rock", played_at=now - (i * day))
    for i in range(3):
        db.log_play_event("track.flac", artist="A", genre="Rock", played_at=now - ((i + 7) * day))
    db.commit()

    stats = db.home_stats()
    assert stats["best_streak"] == 5


def test_best_streak_empty(db):
    """best_streak is 0 when no play events exist."""
    stats = db.home_stats()
    assert stats["best_streak"] == 0


def test_completionist_albums(db):
    """completionist_albums counts albums with every track played."""
    now = int(time.time())
    # Album A: 3 tracks, all played
    for i in range(3):
        path = f"/music/albumA/track{i}.flac"
        db.record(path, status="tagged", artist="X", album="Album A", title=f"T{i}")
        db.log_play_event(path, artist="X", genre="Pop", played_at=now - i)
    # Album B: 3 tracks, only 1 played
    for i in range(3):
        path = f"/music/albumB/track{i}.flac"
        db.record(path, status="tagged", artist="X", album="Album B", title=f"T{i}")
    db.log_play_event("/music/albumB/track0.flac", artist="X", genre="Pop", played_at=now)
    # Album C: 2 tracks, both played
    for i in range(2):
        path = f"/music/albumC/track{i}.flac"
        db.record(path, status="tagged", artist="Y", album="Album C", title=f"T{i}")
        db.log_play_event(path, artist="Y", genre="Jazz", played_at=now - i)
    db.commit()

    stats = db.home_stats()
    assert stats["completionist_albums"]["complete"] == 2  # Album A and C
    assert stats["completionist_albums"]["total"] >= 3


def test_recent_albums(db):
    """recent_albums returns 3 most recently scanned albums."""
    for i in range(5):
        db.record(f"/music/album{i}/t.flac", status="tagged", artist=f"A{i}", album=f"Album {i}", title="T")
    db.commit()

    stats = db.home_stats()
    assert len(stats["recent_albums"]) == 3
    # Most recent should be last inserted
    assert stats["recent_albums"][0]["album"] == "Album 4"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_home.py::test_best_streak tests/test_home.py::test_best_streak_empty tests/test_home.py::test_completionist_albums tests/test_home.py::test_recent_albums -v`
Expected: FAIL — `best_streak`, `completionist_albums`, `recent_albums` keys not in stats dict.

- [ ] **Step 3: Implement the three queries in home_stats()**

Add these blocks to `library_db.py` inside `home_stats()`, before the return statement (before line 911):

```python
        # Best-ever listening streak (longest consecutive-day run)
        best_streak = 0
        streak_days = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT date(played_at, 'unixepoch', 'localtime') as d FROM play_events ORDER BY d"
            ).fetchall()
        ]
        if streak_days:
            from datetime import datetime, timedelta
            current_run = 1
            for i in range(1, len(streak_days)):
                prev = datetime.strptime(streak_days[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(streak_days[i], "%Y-%m-%d")
                if (curr - prev).days == 1:
                    current_run += 1
                else:
                    best_streak = max(best_streak, current_run)
                    current_run = 1
            best_streak = max(best_streak, current_run)

        # Completionist albums: albums where every scanned track has been played
        completionist_complete = 0
        completionist_total = 0
        album_rows = c.execute(
            """SELECT album, artist, COUNT(*) as track_count
               FROM scanned
               WHERE album IS NOT NULL AND status != 'unreadable'
               GROUP BY album, artist"""
        ).fetchall()
        completionist_total = len(album_rows)
        for ar in album_rows:
            played = c.execute(
                """SELECT COUNT(DISTINCT pe.path) FROM play_events pe
                   JOIN scanned s ON s.path = pe.path
                   WHERE s.album = ? AND s.artist = ?""",
                (ar["album"], ar["artist"]),
            ).fetchone()[0]
            if played >= ar["track_count"]:
                completionist_complete += 1

        # Recently scanned albums (3 most recent by rowid)
        recent_albums = [
            {"album": r["album"], "artist": r["artist"]}
            for r in c.execute(
                """SELECT album, artist, MAX(rowid) as latest
                   FROM scanned
                   WHERE album IS NOT NULL AND status != 'unreadable'
                   GROUP BY album, artist
                   ORDER BY latest DESC LIMIT 3"""
            ).fetchall()
        ]
```

Then add to the return dict (line 911-934), before the closing `}`:

```python
            "best_streak": best_streak,
            "completionist_albums": {"complete": completionist_complete, "total": completionist_total},
            "recent_albums": recent_albums,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_home.py -v`
Expected: ALL PASS (including existing tests).

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/helper/library_db.py tests/test_home.py
git commit -m "feat(backend): add best_streak, completionist_albums, recent_albums to home_stats"
```

---

### Task 2: API — Pass New Fields Through

**Files:**
- Modify: `tidal_dl/gui/api/home.py:96-151`

- [ ] **Step 1: Verify new fields pass through**

The `home.py` API handler calls `db.home_stats()` and returns the full dict. The new fields (`best_streak`, `completionist_albums`, `recent_albums`) are plain JSON-serializable values (int, dict, list of dicts) — no cover_path conversion needed.

Read `tidal_dl/gui/api/home.py` lines 96-151 and confirm no filtering removes unknown keys. The handler does:
```python
stats = db.home_stats()
# ... cover_path conversions for specific keys ...
return stats
```

No changes needed — the new keys pass through automatically.

- [ ] **Step 2: Write a test to confirm API response includes new fields**

Add to `tests/test_home.py`:

```python
def test_home_stats_includes_card_inspect_fields(db):
    """home_stats includes best_streak, completionist_albums, recent_albums."""
    stats = db.home_stats()
    assert "best_streak" in stats
    assert isinstance(stats["best_streak"], int)
    assert "completionist_albums" in stats
    assert "complete" in stats["completionist_albums"]
    assert "total" in stats["completionist_albums"]
    assert "recent_albums" in stats
    assert isinstance(stats["recent_albums"], list)
```

- [ ] **Step 3: Run test**

Run: `uv run python -m pytest tests/test_home.py::test_home_stats_includes_card_inspect_fields -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_home.py
git commit -m "test: verify card inspect fields in home_stats API response"
```

---

### Task 3: CSS — Remove Old Expand Styles, Add Inspect Overlay Styles

**Files:**
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Remove old expand-related CSS**

Delete the following CSS blocks (search for each selector and remove the entire rule):

1. `.bento-expanded .bento-chevron` (the rotation transform)
2. `.bento-chevron` (absolute positioned arrow)
3. `.bento-detail` (hidden detail container)
4. `.bento-expanded .bento-detail` (revealed detail)
5. `.bento-detail-row` (flex row)
6. `.bento-expanded .bento-detail-row` (revealed row with translateY)
7. `.bento-detail-key` (label style)
8. `.bento-detail-val` (value style)

- [ ] **Step 2: Add inspect overlay CSS**

Append to style.css:

```css
/* ---- CARD INSPECT OVERLAY ---- */
.inspect-scrim {
  position: fixed;
  inset: 0;
  z-index: 150;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.inspect-card {
  position: fixed;
  background: var(--surface);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius);
  padding: 18px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  overflow: hidden;
  will-change: transform, opacity;
  transform-origin: bottom center;
}
.inspect-card.inspect-front {
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  z-index: 152;
}
.inspect-card.inspect-back {
  opacity: 0.4;
  z-index: 151;
  cursor: pointer;
}
.inspect-card.inspect-back:hover {
  opacity: 0.6;
}

/* Rarity border glows */
.inspect-card[data-rarity="common"]    { border-color: rgba(240,235,228,0.15); }
.inspect-card[data-rarity="uncommon"]  { border-color: rgba(126,201,122,0.25); }
.inspect-card[data-rarity="rare"]      { border-color: rgba(100,160,220,0.25); }
.inspect-card[data-rarity="epic"]      { border-color: rgba(160,120,210,0.25); }
.inspect-card[data-rarity="legendary"] { border-color: rgba(212,160,83,0.25); }

/* Rarity label colors */
.inspect-card[data-rarity="uncommon"] .card-rarity  { color: rgba(126,201,122,0.5); }
.inspect-card[data-rarity="rare"] .card-rarity      { color: rgba(100,160,220,0.5); }
.inspect-card[data-rarity="epic"] .card-rarity      { color: rgba(160,120,210,0.5); }
.inspect-card[data-rarity="legendary"] .card-rarity  { color: rgba(212,160,83,0.5); }

.card-corner {
  position: absolute;
  font-size: 12px;
  opacity: 0.3;
  pointer-events: none;
}
.card-corner.top-left { top: 8px; left: 10px; }
.card-corner.bottom-right { bottom: 8px; right: 10px; transform: rotate(180deg); }

.card-rarity {
  position: absolute;
  top: 8px;
  right: 10px;
  font-family: var(--mono);
  font-size: 8px;
  letter-spacing: 1px;
  color: rgba(240,235,228,0.3);
}

.card-stats {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
  border-top: 1px solid var(--glass-border);
  padding-top: 10px;
}
.card-stats-row {
  display: flex;
  justify-content: space-between;
}
.card-stats-key {
  font-size: 9px;
  color: var(--text-muted);
}
.card-stats-val {
  font-size: 9px;
  color: var(--text-secondary);
  font-family: var(--mono);
}

.card-flavor {
  margin-top: 8px;
  font-size: 7.5px;
  color: rgba(240, 235, 228, 0.2);
  font-style: italic;
  text-align: center;
  line-height: 1.4;
}

.pip-dots {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 8px;
  z-index: 152;
}
.pip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.35);
  transition: background 0.2s ease, transform 0.2s ease;
}
.pip-dot.active {
  background: rgba(255, 255, 255, 0.95);
  transform: scale(1.3);
}

/* Inspect card internal typography — matches Format B */
.inspect-card .bento-label {
  font-family: var(--serif);
  font-size: 1.5rem;
  color: var(--accent);
  line-height: 1;
}
.inspect-card .bento-stat-label {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 4px;
}

@media (prefers-reduced-motion: reduce) {
  .inspect-card, .inspect-scrim, .pip-dot {
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add tidal_dl/gui/static/style.css
git commit -m "style: remove expand CSS, add card inspect overlay styles"
```

---

### Task 4: JS — Card Inspect Module (Core)

**Files:**
- Modify: `tidal_dl/gui/static/app.js`

This is the largest task. It adds the inspect overlay system: open, dismiss, swap, keyboard, pip dots.

- [ ] **Step 1: Add the card inspect module**

Add after the `_onRepeatHalf` function (after line ~880) in app.js:

```javascript
// ---- CARD INSPECT OVERLAY ----
// TCG-inspired stat card inspect: click tile → fan deck → keyboard browse → dismiss

const _inspect = (() => {
  let _state = null; // { scrim, cards, activeIndex, originalTile, originalRect, cleanup }
  const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DUR = REDUCED_MOTION ? 0 : 300;
  const DUR_FAST = REDUCED_MOTION ? 0 : 200;
  const EASE_PRIMARY = 'cubic-bezier(0.22, 0.61, 0.36, 1)';
  const EASE_BOUNCE = 'cubic-bezier(0.175, 0.885, 0.32, 1.275)';
  const FAN_ANGLE = 6; // degrees between cards
  const FAN_LIFT = -12; // px vertical lift per offset
  const CARD_W = Math.min(240, window.innerWidth * 0.7);
  const CARD_H = CARD_W * 1.5;

  function _noteIcon() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '12');
    svg.setAttribute('height', '12');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'currentColor');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z');
    svg.appendChild(path);
    return svg;
  }

  function _makeCard(data, index) {
    const card = h('div', { className: 'inspect-card' });
    card.style.width = CARD_W + 'px';
    card.style.height = CARD_H + 'px';
    card.dataset.index = index;
    card.dataset.rarity = data.rarity || 'common';

    // TCG corner marks
    const tl = h('div', { className: 'card-corner top-left' });
    tl.appendChild(_noteIcon());
    card.appendChild(tl);
    const br = h('div', { className: 'card-corner bottom-right' });
    br.appendChild(_noteIcon());
    card.appendChild(br);

    // Rarity label
    if (data.rarity && data.rarity !== 'common') {
      card.appendChild(textEl('span', data.rarity.toUpperCase(), 'card-rarity'));
    }

    // Body — Format B layout
    const body = h('div', { className: 'bento-body' });
    body.style.padding = '0';
    body.style.flex = '1';
    body.style.display = 'flex';
    body.style.flexDirection = 'column';

    body.appendChild(textEl('div', data.title, 'bento-label'));
    body.appendChild(textEl('div', data.statLabel, 'bento-stat-label'));

    // Content area — render function provided by the deck builder
    if (data.renderContent) {
      const content = data.renderContent();
      if (content) body.appendChild(content);
    }

    // Stats key-value pairs
    if (data.stats && data.stats.length > 0) {
      const statsEl = h('div', { className: 'card-stats' });
      for (const s of data.stats) {
        const row = h('div', { className: 'card-stats-row' });
        row.appendChild(textEl('span', s.key, 'card-stats-key'));
        const val = textEl('span', s.value, 'card-stats-val');
        if (s.color) val.style.color = s.color;
        row.appendChild(val);
        statsEl.appendChild(row);
      }
      body.appendChild(statsEl);
    }

    // Flavor text
    if (data.flavor) {
      body.appendChild(textEl('div', data.flavor, 'card-flavor'));
    }

    card.appendChild(body);
    return card;
  }

  function _fanPosition(index, activeIndex, total) {
    if (index === activeIndex) return { angle: 0, lift: 0, z: total + 1, opacity: 1 };
    const offset = index - activeIndex;
    return {
      angle: offset * FAN_ANGLE,
      lift: Math.abs(offset) * FAN_LIFT,
      z: total - Math.abs(offset),
      opacity: 0.4,
    };
  }

  function _setFan(cards, activeIndex) {
    cards.forEach((card, i) => {
      const pos = _fanPosition(i, activeIndex, cards.length);
      const isFront = i === activeIndex;
      card.className = 'inspect-card ' + (isFront ? 'inspect-front' : 'inspect-back');
      card.dataset.rarity = card._data.rarity || 'common';
      card.style.zIndex = pos.z;
      card.style.transform = `translate(${_state.centerX}px, ${_state.centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`;
      card.style.opacity = pos.opacity;
    });
  }

  function _animateSwap(fromIndex, toIndex) {
    if (!_state) return;
    const cards = _state.cards;
    _state.activeIndex = toIndex;

    cards.forEach((card, i) => {
      const pos = _fanPosition(i, toIndex, cards.length);
      const isFront = i === toIndex;
      card.className = 'inspect-card ' + (isFront ? 'inspect-front' : 'inspect-back');
      card.dataset.rarity = card._data.rarity || 'common';
      const anim = card.animate([
        { transform: card.style.transform, opacity: parseFloat(card.style.opacity) },
        { transform: `translate(${_state.centerX}px, ${_state.centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`, opacity: pos.opacity }
      ], { duration: DUR, easing: EASE_PRIMARY, fill: 'forwards' });
      anim.finished.then(() => { anim.commitStyles(); anim.cancel(); });
      card.style.zIndex = pos.z;
    });

    _updateDots(toIndex);
  }

  function _createDots(count, container) {
    const dots = h('div', { className: 'pip-dots' });
    for (let i = 0; i < count; i++) {
      dots.appendChild(h('div', { className: 'pip-dot' + (i === 0 ? ' active' : '') }));
    }
    container.appendChild(dots);
    return dots;
  }

  function _updateDots(activeIndex) {
    if (!_state) return;
    const dots = _state.scrim.querySelectorAll('.pip-dot');
    dots.forEach((d, i) => d.classList.toggle('active', i === activeIndex));
  }

  function open(tileEl, deckData) {
    if (_state) return; // already open

    const rect = tileEl.getBoundingClientRect();
    tileEl.style.opacity = '0';

    // Create scrim
    const scrim = h('div', { className: 'inspect-scrim' });
    scrim.style.opacity = '0';
    document.body.appendChild(scrim);

    // Animate scrim in
    const scrimAnim = scrim.animate(
      [{ opacity: 0 }, { opacity: 1 }],
      { duration: DUR_FAST, fill: 'forwards' }
    );
    scrimAnim.finished.then(() => { scrimAnim.commitStyles(); scrimAnim.cancel(); });

    // Calculate center position
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const centerX = (vw - CARD_W) / 2;
    const centerY = (vh - CARD_H) / 2 - 20; // slight upward offset for pip dots

    // Build cards
    const cards = deckData.map((data, i) => {
      const card = _makeCard(data, i);
      card._data = data;
      card.style.position = 'fixed';
      card.style.top = '0';
      card.style.left = '0';
      // Start all cards at the tile's position
      card.style.transform = `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`;
      card.style.opacity = '0';
      scrim.appendChild(card);
      return card;
    });

    _state = {
      scrim, cards, activeIndex: 0,
      originalTile: tileEl, originalRect: rect,
      centerX, centerY,
    };

    // Animate main card (index 0) from tile position to center
    const mainCard = cards[0];
    mainCard.style.opacity = '1';
    const mainAnim = mainCard.animate([
      { transform: `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`, opacity: 1 },
      { transform: `translate(${centerX}px, ${centerY}px) scale(1)`, opacity: 1 }
    ], { duration: DUR, easing: EASE_PRIMARY, fill: 'forwards' });
    mainAnim.finished.then(() => {
      mainAnim.commitStyles(); mainAnim.cancel();
      // Fan out remaining cards with stagger
      cards.forEach((card, i) => {
        if (i === 0) { card.className = 'inspect-card inspect-front'; card.dataset.rarity = card._data.rarity || 'common'; return; }
        const pos = _fanPosition(i, 0, cards.length);
        const delay = Math.abs(i) * 50;
        card.style.opacity = '0';
        const fanAnim = card.animate([
          { transform: `translate(${centerX}px, ${centerY}px) rotate(0deg)`, opacity: 0 },
          { transform: `translate(${centerX}px, ${centerY}px) rotate(${pos.angle}deg) translateY(${pos.lift}px)`, opacity: pos.opacity }
        ], { duration: 250, delay, easing: EASE_BOUNCE, fill: 'forwards' });
        fanAnim.finished.then(() => { fanAnim.commitStyles(); fanAnim.cancel(); });
        card.className = 'inspect-card inspect-back';
        card.dataset.rarity = card._data.rarity || 'common';
        card.style.zIndex = pos.z;

        // Click background card to swap
        card.addEventListener('click', (e) => {
          e.stopPropagation();
          if (_state && _state.activeIndex !== i) _animateSwap(_state.activeIndex, i);
        });
      });
    });

    // Pip dots
    if (cards.length > 1) {
      setTimeout(() => { if (_state) _createDots(cards.length, scrim); }, DUR + 50);
    }

    // Scrim click to dismiss
    scrim.addEventListener('click', (e) => {
      if (e.target === scrim) dismiss();
    });

    // Keyboard handler
    function onKey(e) {
      if (!_state) return;
      const key = e.key;
      if (key === 'ArrowRight' || key === 'd' || key === 'D') {
        e.preventDefault(); e.stopPropagation();
        const next = _state.activeIndex + 1;
        if (next < _state.cards.length) _animateSwap(_state.activeIndex, next);
      } else if (key === 'ArrowLeft' || key === 'a' || key === 'A') {
        e.preventDefault(); e.stopPropagation();
        const prev = _state.activeIndex - 1;
        if (prev >= 0) _animateSwap(_state.activeIndex, prev);
      } else if (key === 'Escape') {
        e.preventDefault(); e.stopPropagation();
        dismiss();
      }
    }
    // Capture phase so we get it before the global handler
    document.addEventListener('keydown', onKey, true);
    _state.cleanup = () => document.removeEventListener('keydown', onKey, true);
  }

  function dismiss() {
    if (!_state) return;
    const { scrim, cards, originalTile, cleanup } = _state;
    // Re-measure original tile position (may have scrolled)
    const rect = originalTile.getBoundingClientRect();

    // Fade out non-active cards
    cards.forEach((card, i) => {
      if (i === _state.activeIndex) return;
      const fadeOut = card.animate([{ opacity: parseFloat(card.style.opacity) }, { opacity: 0 }], { duration: DUR_FAST, fill: 'forwards' });
      fadeOut.finished.then(() => { fadeOut.commitStyles(); fadeOut.cancel(); });
    });

    // Animate active card back to original position
    const active = cards[_state.activeIndex];
    const returnAnim = active.animate([
      { transform: active.style.transform, opacity: 1 },
      { transform: `translate(${rect.left}px, ${rect.top}px) scale(${rect.width / CARD_W}, ${rect.height / CARD_H})`, opacity: 0.5 }
    ], { duration: DUR, easing: 'ease-in', fill: 'forwards' });

    // Fade scrim
    const scrimFade = scrim.animate([{ opacity: 1 }, { opacity: 0 }], { duration: DUR_FAST, delay: 100, fill: 'forwards' });

    returnAnim.finished.then(() => {
      returnAnim.commitStyles(); returnAnim.cancel();
      originalTile.style.opacity = '';
      scrim.remove();
    });
    scrimFade.finished.then(() => { scrimFade.commitStyles(); scrimFade.cancel(); });

    if (cleanup) cleanup();
    _state = null;
  }

  function isOpen() { return _state !== null; }

  return { open, dismiss, isOpen };
})();
```

- [ ] **Step 2: Add guard in global keydown handler**

In the global `keydown` handler (around line 4351), add at the top after the INPUT/TEXTAREA check:

```javascript
  // Skip arrow/letter keys when card inspect overlay is open
  if (_inspect.isOpen()) return;
```

- [ ] **Step 3: Add dismiss-on-navigate hook**

In the `navigate()` function (around line 421), add at the very top:

```javascript
  // Dismiss card inspect if open
  if (_inspect.isOpen()) _inspect.dismiss();
```

- [ ] **Step 4: Test manually**

Open the app, verify no JS errors on home page load. The inspect module is defined but not yet wired to any tiles — that's Task 5.

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(frontend): card inspect module — open, dismiss, swap, keyboard, pip dots"
```

---

### Task 5: JS — Deck Builders + Wire to Tiles

**Files:**
- Modify: `tidal_dl/gui/static/app.js`

This task builds the deck data arrays for each tile type and wires the click handler.

- [ ] **Step 1: Add deck builder functions**

Add after the `_inspect` module:

```javascript
// ---- DECK BUILDERS (card content per tile type) ----

function _listeningTimeDeck(data) {
  const deck = [];
  // Card 0: Main (what bento already shows)
  deck.push({
    title: Math.round(data.listening_time_hours) + 'h',
    statLabel: 'Listening time',
    rarity: 'common',
    renderContent: () => {
      const wrap = h('div');
      const ins = _listeningInsight(data.listening_time_hours, data.weekly_activity);
      if (ins) wrap.appendChild(ins);
      wrap.appendChild(_weeklyChart(data.weekly_activity));
      return wrap;
    },
    stats: [],
    flavor: null,
  });
  // Card 1: Peak Hour
  if (data.peak_hour !== undefined && data.peak_hours) {
    const h12 = data.peak_hour % 12 || 12;
    const ampm = data.peak_hour < 12 ? 'am' : 'pm';
    deck.push({
      title: h12 + ampm,
      statLabel: 'Peak hour',
      rarity: data.peak_hour >= 22 || data.peak_hour <= 4 ? 'uncommon' : 'common',
      renderContent: () => {
        // Mini 24-bar chart from peak_hours array
        const chart = h('div', { style: 'display:flex;align-items:flex-end;gap:1px;margin-top:12px;height:40px;' });
        const max = Math.max(...data.peak_hours, 1);
        for (let i = 0; i < 24; i++) {
          const pct = (data.peak_hours[i] / max) * 100;
          const bar = h('div', {
            style: `flex:1;background:${i === data.peak_hour ? 'var(--accent)' : 'rgba(212,160,83,0.15)'};height:${Math.max(2, pct)}%;border-radius:1px;`
          });
          chart.appendChild(bar);
        }
        return chart;
      },
      stats: [
        { key: 'Most active', value: h12 + ':00' + ampm },
        { key: 'Least active', value: (() => {
          const minH = data.peak_hours.indexOf(Math.min(...data.peak_hours));
          const m12 = minH % 12 || 12;
          return m12 + ':00' + (minH < 12 ? 'am' : 'pm');
        })() },
      ],
      flavor: data.peak_hour >= 0 && data.peak_hour <= 4 ? 'Nothing good happens after midnight. Except music.' : null,
    });
  }
  // Card 2: Streak
  if (data.streak !== undefined) {
    const streakRarity = data.streak >= 30 ? 'legendary' : data.streak >= 14 ? 'epic' : data.streak >= 7 ? 'rare' : data.streak >= 3 ? 'uncommon' : 'common';
    deck.push({
      title: data.streak + (data.streak === 1 ? ' day' : ' days'),
      statLabel: 'Streak',
      rarity: streakRarity,
      renderContent: null,
      stats: [
        { key: 'Current', value: data.streak + ' days' },
        { key: 'Best ever', value: (data.best_streak || data.streak) + ' days' },
      ],
      flavor: data.streak >= 30 ? 'Gotta catch \'em all.' : null,
    });
  }
  // Card 3: Week vs Last
  if (data.week_vs_last && data.week_vs_last.last_week > 0) {
    const diff = data.week_vs_last.this_week - data.week_vs_last.last_week;
    const pct = Math.round((diff / data.week_vs_last.last_week) * 100);
    deck.push({
      title: (pct >= 0 ? '+' : '') + pct + '%',
      statLabel: 'vs last week',
      rarity: 'common',
      renderContent: null,
      stats: [
        { key: 'This week', value: Math.round(data.week_vs_last.this_week) + ' min' },
        { key: 'Last week', value: Math.round(data.week_vs_last.last_week) + ' min' },
        { key: 'Change', value: (pct >= 0 ? '+' : '') + pct + '%', color: pct >= 0 ? 'var(--green)' : 'var(--red)' },
      ],
      flavor: null,
    });
  }
  return deck;
}

function _genreDeck(topGenre, breakdown, fromLibrary, data) {
  const deck = [];
  const tw = data.this_week || {};
  // Card 0: Main
  deck.push({
    title: topGenre || 'None',
    statLabel: fromLibrary ? 'Top genre' : 'Recent genre',
    rarity: 'common',
    renderContent: () => _barChart(breakdown.slice(0, 4).map(g => ({ label: g.genre, value: g.count }))),
    stats: breakdown.slice(0, 6).map(g => ({ key: g.genre, value: g.count + (fromLibrary ? ' tracks' : ' plays') })),
    flavor: null,
  });
  // Card 1: Deep Cut (rarest genre with plays)
  if (breakdown.length >= 3) {
    const rarest = breakdown[breakdown.length - 1];
    const total = breakdown.reduce((s, g) => s + g.count, 0);
    const pct = total > 0 ? Math.round((rarest.count / total) * 100) : 0;
    deck.push({
      title: pct + '%',
      statLabel: 'Deep cut',
      rarity: pct <= 5 ? 'rare' : 'common',
      renderContent: null,
      stats: [
        { key: 'Rarest genre', value: rarest.genre },
        { key: 'Plays', value: rarest.count.toString() },
        { key: 'Share', value: pct + '% of total' },
      ],
      flavor: pct <= 5 ? 'A person of refined and unusual taste.' : null,
    });
  }
  // Card 2: Shifting (this week vs all-time)
  const allTimeTop = data.genre_breakdown && data.genre_breakdown[0] ? data.genre_breakdown[0].genre : null;
  const weekTop = tw.genre_breakdown && tw.genre_breakdown[0] ? tw.genre_breakdown[0].genre : null;
  if (allTimeTop && weekTop && allTimeTop !== weekTop) {
    deck.push({
      title: weekTop,
      statLabel: 'Shifting',
      rarity: 'uncommon',
      renderContent: null,
      stats: [
        { key: 'This week', value: weekTop },
        { key: 'All-time', value: allTimeTop },
      ],
      flavor: 'Tastes evolve. The ear knows what it wants.',
    });
  }
  return deck;
}

function _tracksDeck(count, genres, data) {
  const deck = [];
  // Card 0: Main
  deck.push({
    title: count.toLocaleString(),
    statLabel: 'Tracks',
    rarity: 'common',
    renderContent: () => {
      if (genres && genres.length > 0) {
        return _barChart(genres.slice(0, 4).map(g => ({ label: g.genre, value: g.count })));
      }
      return null;
    },
    stats: [],
    flavor: null,
  });
  // Card 1: Quality
  if (data.format_breakdown && data.format_breakdown.length > 0) {
    const topFormat = data.format_breakdown[0];
    const topPct = Math.round((topFormat.count / count) * 100);
    const lossless = data.format_breakdown.filter(f => ['FLAC', 'WAV', 'ALAC', 'AIFF'].includes(f.format.toUpperCase())).reduce((s, f) => s + f.count, 0);
    const losslessPct = Math.round((lossless / count) * 100);
    const qualityRarity = losslessPct >= 80 ? 'rare' : 'common';
    deck.push({
      title: topFormat.format + ' ' + topPct + '%',
      statLabel: 'Quality',
      rarity: qualityRarity,
      renderContent: () => _barChart(data.format_breakdown.slice(0, 4).map(f => ({ label: f.format, value: f.count }))),
      stats: [
        { key: 'Lossless', value: losslessPct + '%' },
        { key: 'Formats', value: data.format_breakdown.length.toString() },
      ],
      flavor: losslessPct >= 80 ? 'Your ears deserve nothing less.' : null,
    });
  }
  // Card 2: Unplayed
  if (data.unplayed_count > 0) {
    const unplayedPct = Math.round((data.unplayed_count / count) * 100);
    deck.push({
      title: data.unplayed_count.toLocaleString(),
      statLabel: 'Unplayed',
      rarity: unplayedPct < 10 ? 'uncommon' : 'common',
      renderContent: null,
      stats: [
        { key: 'Never played', value: data.unplayed_count.toLocaleString() + ' tracks' },
        { key: 'Share', value: unplayedPct + '% of library' },
      ],
      flavor: unplayedPct < 10 ? 'Achievement unlocked: No stone unturned.' : null,
    });
  }
  return deck;
}

function _albumsDeck(count, artists, data) {
  const deck = [];
  // Card 0: Main
  deck.push({
    title: count.toLocaleString(),
    statLabel: 'Albums',
    rarity: 'common',
    renderContent: () => {
      if (artists && artists.length > 0) {
        return _barChart(artists.slice(0, 4).map(a => ({ label: a.artist, value: a.count })));
      }
      return null;
    },
    stats: data.top_album ? [
      { key: 'Most played', value: data.top_album.album },
      { key: 'Artist', value: data.top_album.artist },
    ] : [],
    flavor: null,
  });
  // Card 1: Completionist
  if (data.completionist_albums && data.completionist_albums.total > 0) {
    const ca = data.completionist_albums;
    const pct = Math.round((ca.complete / ca.total) * 100);
    const rarity = pct >= 100 ? 'legendary' : pct >= 50 ? 'epic' : 'common';
    deck.push({
      title: ca.complete + ' / ' + ca.total,
      statLabel: 'Completionist',
      rarity,
      renderContent: null,
      stats: [
        { key: 'Fully played', value: ca.complete + ' albums' },
        { key: 'Completion', value: pct + '%' },
      ],
      flavor: pct >= 100 ? 'Achievement unlocked: No stone unturned.' : null,
    });
  }
  // Card 2: Recent
  if (data.recent_albums && data.recent_albums.length > 0) {
    deck.push({
      title: data.recent_albums.length + ' new',
      statLabel: 'Recent',
      rarity: 'common',
      renderContent: null,
      stats: data.recent_albums.map(a => ({ key: a.artist, value: a.album })),
      flavor: null,
    });
  }
  return deck;
}
```

- [ ] **Step 2: Modify stat tile builders to wire card inspect**

Replace the `_expandToggle` calls and `_detailBlock` calls in each tile builder. The tiles now attach a click handler that opens the inspect overlay.

**In `_genreTile()` (full-size path, around line 842-860):**

Replace:
```javascript
  const allGenres = breakdown.map(g => ({
    label: g.genre,
    value: g.count + (fromLibrary ? ' tracks' : ' plays')
  }));
  if (allGenres.length > 4) {
    body.appendChild(_detailBlock(allGenres.slice(4)));
  }
  tile.appendChild(body);
  if (allGenres.length > 4) _expandToggle(tile);
```

With:
```javascript
  tile.appendChild(body);
  tile._inspectDeck = null; // lazy — built on click
  tile._inspectDeckArgs = { topGenre, breakdown, fromLibrary };
  tile.addEventListener('click', () => {
    if (!tile._inspectDeck) tile._inspectDeck = _genreDeck(tile._inspectDeckArgs.topGenre, tile._inspectDeckArgs.breakdown, tile._inspectDeckArgs.fromLibrary, tile._homeData || {});
    if (tile._inspectDeck.length > 1) _inspect.open(tile, tile._inspectDeck);
  });
  a11yClick(tile);
```

**In `_genreTile()` (split-tile path, around line 832-838):**

Add click handler to the genre half:
```javascript
    genreHalf.addEventListener('click', (e) => {
      e.stopPropagation();
      const deck = _genreDeck(topGenre, breakdown, fromLibrary, genreHalf._homeData || {});
      if (deck.length > 1) _inspect.open(genreHalf, deck);
    });
    a11yClick(genreHalf);
```

**In `_listeningTimeTile()` (around line 905-911):**

Replace:
```javascript
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
```

With:
```javascript
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _listeningTimeDeck(tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
```

**In `_tracksTile()` (around line 931-938):**

Replace:
```javascript
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
```

With:
```javascript
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _tracksDeck(count, genres, tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
```

**In `_albumsTile()` (around line 954-961):**

Replace:
```javascript
  if (details.length > 0) body.appendChild(_detailBlock(details));
  tile.appendChild(body);
  if (details.length > 0) _expandToggle(tile);
```

With:
```javascript
  tile.appendChild(body);
  tile.addEventListener('click', () => {
    const deck = _albumsDeck(count, artists, tile._homeData || data);
    if (deck.length > 1) _inspect.open(tile, deck);
  });
  a11yClick(tile);
```

- [ ] **Step 3: Pass `data` to tiles via `_homeData`**

In `_renderHomeGrid()`, after building each stat tile, attach the full `data` object so deck builders can access all fields:

After the `_genreTile` call (around line 628):
```javascript
    const genreTile = _genreTile(genreLabel, genreSource, fromLibrary, onRepeatTrack);
    genreTile._homeData = data;
    // For split tiles, also set on the genre half
    if (onRepeatTrack) {
      const genreHalf = genreTile.querySelector('.bento-half:not(.bento-on-repeat)');
      if (genreHalf) genreHalf._homeData = data;
    }
    grid.appendChild(genreTile);
```

After `_listeningTimeTile` call (around line 631):
```javascript
    const ltTile = _listeningTimeTile(data.listening_time_hours, data.weekly_activity, data);
    ltTile._homeData = data;
    grid.appendChild(ltTile);
```

After `_tracksTile` call (around line 646):
```javascript
    const tTile = _tracksTile(data.track_count, data.track_genres || [], data);
    tTile._homeData = data;
    grid.appendChild(_t(tTile, 2));
```

After `_albumsTile` call (around line 649):
```javascript
    const aTile = _albumsTile(data.album_count, data.album_artists, data);
    aTile._homeData = data;
    grid.appendChild(_t(aTile, 2));
```

- [ ] **Step 4: Remove `_expandToggle` and `_detailBlock` functions**

Delete the `_expandToggle` function (lines 809-814) and `_detailBlock` function (lines 816-826).

- [ ] **Step 5: Commit**

```bash
git add tidal_dl/gui/static/app.js
git commit -m "feat(frontend): deck builders + wire stat tiles to card inspect"
```

---

### Task 6: CSS Cleanup — Remove Orphaned Expand Styles

**Files:**
- Modify: `tidal_dl/gui/static/style.css`

- [ ] **Step 1: Search and remove orphaned references**

Now that `_expandToggle` and `_detailBlock` are gone from JS, verify no other JS code references these CSS classes:

Search app.js for: `bento-expanded`, `bento-detail`, `bento-chevron`. Should find zero matches.

If the expand styles weren't fully removed in Task 3, remove any remaining now.

- [ ] **Step 2: Commit**

```bash
git add tidal_dl/gui/static/style.css
git commit -m "chore: remove orphaned expand CSS references"
```

---

### Task 7: Integration Test + Final Verification

**Files:**
- Test: `tests/test_home.py`

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest tests/test_home.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run full project test suite**

Run: `uv run python -m pytest -v`
Expected: ALL PASS (no regressions)

- [ ] **Step 3: Manual browser testing**

Open the app in the browser. Verify:
1. Home page loads without JS errors
2. Stat tiles no longer have "More" hint or expand behavior
3. Click Listening Time tile → inspect overlay opens with fanned deck
4. Arrow keys / A/D cycle through cards
5. Click a background card → it swaps to front
6. Escape → overlay dismisses, tile restores
7. Click outside (scrim) → dismisses
8. Arrow keys do NOT seek audio while overlay is open
9. Navigate to another view while overlay is open → overlay dismisses
10. Genre tile (full-size) → inspect works
11. Genre tile (split) → clicking genre half opens inspect
12. Tracks tile → inspect works
13. Albums tile → inspect works
14. Pip dots update correctly when cycling

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: card inspect overlay — TCG-inspired stat tile deck fan

Replace inline expand with clone-and-elevate card inspect. Click stat
tile to fan out a deck of detail cards. Browse with keyboard (arrows/AD)
or click. Dismiss with Escape or click outside. Rarity system tied to
RPG quality tiers. Flavor text easter eggs."
```

---

## Self-Review

**Spec coverage:**
- ✅ Section 1 (Interaction Model): Task 4 — keyboard, click, dismiss, route change
- ✅ Section 2 (Animation): Task 4 — FLIP, stagger, swap, close
- ✅ Section 3 (Card Dimensions): Task 3 — fixed 2:3 ratio CSS
- ✅ Section 4 (Card Content): Task 5 — all 4 deck builders with all cards
- ✅ Section 5 (Visual Treatment): Task 3 + 5 — rarity, corners, flavor, pip dots
- ✅ Section 6 (Scrim): Task 3 — z-index 150, backdrop blur
- ✅ Section 7 (Removals): Task 4 step 4, Task 3 step 1, Task 6
- ✅ Section 8 (Files Changed): All 4 files covered
- ✅ Section 9 (Not Changed): Verified — no grid/layout/player changes
- ✅ Reduced motion: Task 4 — `matchMedia` check in JS
- ✅ Animation cleanup: Task 4 — `commitStyles()`/`cancel()` everywhere
- ✅ Split tile: Task 5 — genre half click handler with `stopPropagation`
- ✅ Keyboard guard: Task 4 — capture phase + global handler guard

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code blocks complete.

**Type consistency:** `_inspect.open(tileEl, deckData)` matches across all call sites. Deck data shape `{ title, statLabel, rarity, renderContent, stats, flavor }` consistent across all builders. `_state` fields consistent between `open()` and `dismiss()`.
