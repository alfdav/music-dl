# Jev Edition Advice (Clean Up) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add feature-flagged TypeSafe/Jev edition advice to music-dl Clean Up: chips + detail scoring via sidecar CLI, Reveal in Finder, and confirm-time deletes only for ≥0.95 `layout_twin_extra` / `true_duplicate_candidate` while honoring explicit unchecks.

**Architecture:** External scorer CLI (`typesafe-music-edition` compatible) + in-app adapter/cache (`edition_advice` table). Grouping engines and `album_grouping_assessments` stay untouched. Flag off ⇒ UI and `/duplicates/clean` behave exactly as today.

**Tech Stack:** Python FastAPI (tidaldl-py), SQLite `library.db` via `LibraryDB`, vanilla JS GUI (`views.js` / `api.js`), existing `/downloads/reveal`, Settings persistence in `model/cfg.py`. Enablement UX is a DJAI module card, not a Settings toggle.

**Spec:** `docs/plans/2026-09-18-jev-edition-advice-design.md` (approved 2026-09-18). User guide: `tidaldl-py/docs/djai-edition-advice.md` (facts from `docs/plans/2026-09-18-typesafe-key-access-verified.md`, 2026-09-18). Also attached / Inbox copy OK.

## Global Constraints

- Never auto-delete `keep_both_editions`, `insufficient_evidence`, missing/error/unscored pairs.
- Never write Jev outcomes into `album_grouping_assessments`.
- Never say “safe to delete” in UI copy; use “candidate” for true duplicates.
- Honor explicit checkbox uncheck on confirm; auto-check ≥0.95 layout/true-dup when scores land.
- Concurrency cap 2 for scorer calls; do not score all rows on preview open.
- Persistence flag `edition_advice_enabled` default **False**. Only human toggle: DJAI Edition advice module card.
- Mac path first; Windows/mini-plex parity out of scope for this PR.
- Scorer API key never logged.
- Base branch: `master`. Do not commit unrelated dirty local changes from other branches.
- YAGNI / ponytail: no eager list scoring, no in-process TypeSafe SDK.

---

## File map

| Responsibility | Path |
| --- | --- |
| Pure policy (aggregate + act gate) | Create `tidaldl-py/tidal_dl/gui/services/edition_advice_policy.py` |
| Cache CRUD | Create `tidaldl-py/tidal_dl/helper/library_db/edition_advice.py` + wire in `library_db/__init__.py` / `core.py` migrate |
| Scorer subprocess | Create `tidaldl-py/tidal_dl/gui/services/edition_scorer.py` |
| Adapter (score group) | Create `tidaldl-py/tidal_dl/gui/services/edition_advice_adapter.py` |
| API routes | Modify `tidaldl-py/tidal_dl/gui/api/duplicates.py`; optional thin router include |
| DJAI module enablement | Persist `edition_advice_enabled` in `cfg.py` / settings API; toggle only on the DJAI Edition advice card in `views.js` |
| Clean Up UI | Modify `tidaldl-py/tidal_dl/gui/static/views.js` (+ minimal CSS in `style.css`) |
| Tests | Create `tidaldl-py/tests/test_edition_advice_policy.py`; extend `tests/test_duplicates.py` |
| Design pointer | Keep design in `docs/plans/`; plan this file |

---

### Task 1: Policy pure functions (TDD)

**Files:**
- Create: `tidaldl-py/tidal_dl/gui/services/edition_advice_policy.py`
- Test: `tidaldl-py/tests/test_edition_advice_policy.py`

**Interfaces:**
- Produces:
  - `RELATION_CAUTION_ORDER: list[str]` most → least cautious
  - `SHORT_LABELS: dict[str, str]` → Keep both / Unclear / Layout twin / Dup candidate
  - `fingerprint(path: str, size: int | None, mtime: float | None) -> str`
  - `aggregate_relation(relations: list[str]) -> str | None` (most cautious present)
  - `chip_label(state: str, relation: str | None, confidence: float | None) -> str` for `pending|scoring|ready|error|missing`
  - `may_auto_act(relation: str | None, confidence: float | None) -> bool` True iff relation in `{true_duplicate_candidate, layout_twin_extra}` and confidence ≥ 0.95
  - `default_checked(status: str, relation: str | None, confidence: float | None) -> bool` True if status==`auto` OR `may_auto_act(...)`
  - `resolve_delete_paths(*, selected_paths: set[str], advice_by_path: dict[str, dict], honor_uncheck: bool = True) -> set[str]` returns selected_paths only when honor_uncheck (never force-add unchecked); when building defaults use `default_checked`

- [x] **Step 1: Write failing tests** covering caution order, may_auto_act true/false for keep_both@0.99 and dup@0.94/0.95, fingerprint stability, chip labels.

- [x] **Step 2: Run** `cd tidaldl-py && python -m pytest tests/test_edition_advice_policy.py -v` → FAIL (import error).

- [x] **Step 3: Implement minimal policy module.**

- [x] **Step 4: Run tests → PASS.**

- [x] **Step 5: Commit** `test: edition advice policy gates`

---

### Task 2: `edition_advice` table + CRUD

**Files:**
- Modify: `tidaldl-py/tidal_dl/helper/library_db/core.py` `_migrate` — add:

```sql
CREATE TABLE IF NOT EXISTS edition_advice (
  path_a TEXT NOT NULL,
  path_b TEXT NOT NULL,
  fingerprint_a TEXT NOT NULL,
  fingerprint_b TEXT NOT NULL,
  relation TEXT,
  confidence REAL,
  probabilities_json TEXT,
  same_isrc_misleading INTEGER,
  model TEXT,
  usage_json TEXT,
  scored_at REAL,
  error TEXT,
  group_id TEXT,
  PRIMARY KEY (path_a, path_b)
);
CREATE INDEX IF NOT EXISTS idx_edition_advice_group ON edition_advice(group_id);
```

- Create: `tidaldl-py/tidal_dl/helper/library_db/edition_advice.py` with `get_pair`, `upsert_pair`, `invalidate_stale(path, fingerprint)`, `list_for_group(group_id)`
- Wire exports on `LibraryDB` like other mixins
- Test: extend `tests/test_library_db.py` or new `tests/test_edition_advice_db.py` — upsert, fingerprint mismatch returns None / force rescore

- [x] **Step 1–5:** TDD migrate + CRUD; commit `feat: edition_advice cache table`

---

### Task 3: Scorer subprocess wrapper

**Files:**
- Create: `tidaldl-py/tidal_dl/gui/services/edition_scorer.py`

**Interfaces:**
- Consumes: env `TYPESAFE_API_KEY` or Settings path `edition_scorer_path` (optional string; default look for `typesafe-music-edition` on PATH / well-known install)
- Produces: `score_pair(item_a: dict, item_b: dict, *, timeout_s: float = 60) -> dict` returning `{relation, confidence, probabilities, same_isrc_misleading, clarity, model, usage}` or raises `EditionScorerError`
- Spawns: `subprocess.run([bin, "--a", json.dumps(a), "--b", json.dumps(b)], capture_output=True, text=True, timeout=..., env=os.environ)` — never print API key
- If binary missing → raise typed error consumed as chip `n/a`

Item dict fields from scanned row: `artist, album, title, path, codec, format, quality, isrc, album_artist` plus optional `edition` derived from path/title tokens if cheap.

- [x] Unit test with monkeypatched `subprocess.run` returning fixture JSON.
- [x] Commit `feat: edition scorer CLI wrapper`

---

### Task 4: Adapter `score_group`

**Files:**
- Create: `tidaldl-py/tidal_dl/gui/services/edition_advice_adapter.py`

**Interfaces:**
- `score_group(db, group: dict, *, force: bool = False) -> dict`  
  group shape = preview serialize (`key`, `keeper`, `duplicates`)  
  For each extra: cache hit if fingerprints match; else call scorer (asyncio semaphore 2 or thread pool max 2); upsert; return `{group_id, pairs: [...], aggregate: {relation, confidence, chip}}`
- Does **not** mutate grouping / does **not** delete files

- [x] Test with mock scorer: two extras, one cache hit, concurrency cap honored (optional assert call count).
- [x] Commit `feat: edition advice score_group adapter`

---

### Task 5: DJAI module enablement (not a Settings toggle)

**Files:**
- Modify: `tidaldl-py/tidal_dl/model/cfg.py` — persist `edition_advice_enabled: bool = False`
- Modify: `tidaldl-py/tidal_dl/gui/api/settings.py` — include in `get_settings` / `SettingsUpdate` plus `edition_scorer_status` (`ready` / `missing` / `n/a`)
- Modify: `views.js` `renderDjai` — second `djai-module-card` (Edition advice (Jev)): header, desc, status pills, enable control. Do **not** add a Settings toggle next to `skip_duplicate_isrc`.

- [x] Commit `feat: edition_advice_enabled setting` (persistence)
- [x] Follow-up: DJAI module card is the only human toggle
- [x] User guide `tidaldl-py/docs/djai-edition-advice.md` from verified 2026-09-18 TypeSafe note

---

### Task 6: API — score + preview enrichment + clean selection

**Files:**
- Modify: `tidaldl-py/tidal_dl/gui/api/duplicates.py`

**Endpoints:**
1. `GET /duplicates/preview` — when flag on, attach per-group `edition_chip` from cache only (`pending` if no rows). Never spawn scorer here.
2. `POST /duplicates/score` body `{ "group_key": str, "force": bool=false }` — load group from fresh `_find_duplicate_groups`, call adapter, return full payload. 404 if key missing; 503 if scorer unavailable (still return pair errors).
3. `POST /duplicates/clean` — accept optional body `{ "paths": [str] }`:
   - Flag **off** or body omitted: today’s behavior (all `auto` extras).
   - Flag **on** + `paths` provided: move only those paths that still appear as extras in current groups **and** are either (a) in the posted selection or (b) N/A — **do not** force-add from advice when honor_uncheck. Client is responsible for posting the checked set. Server still **filters out** any path whose cached advice is `keep_both_editions` or `insufficient_evidence` if somehow posted (belt-and-suspenders). Never delete keeper paths.
4. Reuse `POST /downloads/reveal` for Reveal (no new endpoint).

- [x] Extend `tests/test_duplicates.py`: clean with paths; refuse keep_both even if path listed; flag off ignores paths body and cleans all auto; preview chip pending without scorer.
- [x] Commit `feat: duplicates score API + selective clean`

---

### Task 7: Clean Up UI

**Files:**
- Modify: `tidaldl-py/tidal_dl/gui/static/views.js` (`_showDuplicatePreview`)
- Modify: `tidaldl-py/tidal_dl/gui/static/style.css` (minimal chip/detail styles)

**Behavior when `edition_advice_enabled`:**
1. Each group card shows chip from preview (`Edition: —` / `…` / short form · conf / `n/a`).
2. Click card expands detail: aggregate line, per-extra relation/confidence/`same_isrc_misleading`, truncated paths, folder icon → `POST /downloads/reveal` with that path.
3. Per-extra checkbox: default checked if `status==='auto'`; after score, set checked if `default_checked` / `may_auto_act`; user may uncheck.
4. Buttons `Score` / `Re-score` call `/duplicates/score` for that `group.key`; update chip + checkboxes; never toast “safe to delete”.
5. Clean Up button: collect checked extra paths → `POST /duplicates/clean` with `{paths}`; label reflects count of checked.
6. Uncertain groups: still shown; checkboxes default off until ≥0.95 layout/true-dup scores land.

**Flag off:** render exactly current UI (no chips, no checkboxes, clean posts with no body).

- [x] Manual note in PR: verify flag off pixel-parity; remaster keep_both@0.99 never checked by default after score.
- [x] Commit `feat: Clean Up edition advice UI`

---

### Task 8: Docs + self-check

- [x] Update design status line to `approved + planned`.
- [x] PR description lists success criteria from design §Success criteria.
- [x] Run `cd tidaldl-py && python -m pytest tests/test_edition_advice_policy.py tests/test_duplicates.py tests/test_edition_advice_db.py -q` (and any new files) → green.
- [x] Commit if docs dirty; open PR against `master`.

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Sidecar + adapter/cache | 3, 4 |
| Feature flag off ≡ baseline | 5, 6, 7 |
| Score on detail / Re-score; list lazy | 6, 7 |
| Keeper↔each extra; cautious chip | 1, 4, 7 |
| Reveal in Finder | 7 (existing reveal) |
| ≥0.95 layout/true-dup act; honor uncheck | 1, 6, 7 |
| Never keep_both / unclear / unscored | 1, 6 |
| edition_advice table + fingerprint invalidate | 2 |
| Errors → n/a; Clean Up still works | 3, 6, 7 |
| Unit + integration tests | 1, 2, 6 |

## Open point (resolved)

**Honor explicit uncheck.** Server deletes intersection of posted `paths` with current extras, minus keep_both/unclear cached advice. Client auto-checks ≥0.95 layout/true-dup when scores land.
