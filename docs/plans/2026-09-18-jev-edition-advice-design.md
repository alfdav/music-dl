# Design: Jev edition advice in music-dl Clean Up

Date: 2026-09-18  
Status: approved + planned 2026-09-18; plan in 2026-09-18-jev-edition-advice-plan.md  
Owner: Techmarine  

## Goal

Help the human make an informed Clean Up decision using TypeSafe Jev edition classification (relation + confidence), with Reveal-in-Finder for manual checks. Optionally auto-remove only high-confidence layout/true-duplicate extras when the user confirms Clean Up.

## Non-goals (v1)

- Replacing `album_grouping_assessments` / ISRC grouping engines.
- Silent full-library Clean Up or any delete without an explicit Clean Up confirm.
- Auto-deleting `keep_both_editions` or `insufficient_evidence` at any confidence.
- Auto-deleting unscored pairs.
- Calling Jev for every row when the Clean Up list opens (list stays lazy).

## Decisions locked

| Topic | Choice |
| --- | --- |
| Architecture | Sidecar scorer + music-dl adapter/cache (Approach A) |
| UI | Compact most-cautious chip on preview rows; full breakdown in group detail |
| When to score | On group detail open (and Re-score); list shows pending/unknown until cached |
| Multi-file groups | Score keeper↔each extra; chip = most cautious relation |
| Human agency | Confidence + relation inform the user; folder icon opens containing folder |
| Auto-act on Clean Up confirm | Delete extra only if `relation ∈ {true_duplicate_candidate, layout_twin_extra}` AND `confidence ≥ 0.95` |
| Never auto-delete | `keep_both_editions`, `insufficient_evidence`, missing/error/unscored |

## Architecture

```
Clean Up UI ──read──► edition_advice cache
     │                      ▲
     │ detail open          │
     ▼                      │
 adapter (feature-flagged) ─┴──► scorer CLI (typesafe-music-edition)
     │
     └── does NOT feed delete eligibility except via explicit act rules below
```

### 1. Scorer (external)

- Binary/CLI compatible with `/home/box/bin/typesafe-music-edition` (installable on Zeratool for desktop).
- Auth: TypeSafe key from secure env / settings the desktop already uses for household tools — never logged.
- Input: metadata JSON for item A (keeper) and item B (extra).
- Output JSON: `relation`, `confidence`, `probabilities`, `same_isrc_misleading`, `clarity`, `model`, `usage`.
- Relations: `keep_both_editions` | `layout_twin_extra` | `true_duplicate_candidate` | `insufficient_evidence`.

### 2. Adapter (in music-dl)

- Resolve keeper + extras using **existing** Clean Up group rules (unchanged).
- On `scoreGroup(groupId)`: for each extra, call scorer if cache miss/stale; concurrency cap 2.
- Persist results to `edition_advice` cache.
- Expose: cached chip for list; full per-pair payload for detail.
- DJAI module off → no process spawn, Clean Up chips hidden, Clean Up identical to today. Enablement lives on the DJAI Edition advice card (persisted as `edition_advice_enabled` in Settings/cfg; not a Settings toggle).

### 3. Clean Up act hook (narrow)

When user confirms Clean Up:

1. Build the delete set exactly as today from user checkboxes / current product rules.
2. **Additionally**, for each extra that is in the confirm set OR is eligible under product rules: if cached advice exists with `confidence ≥ 0.95` and `relation` is `true_duplicate_candidate` or `layout_twin_extra`, include that extra in the delete set (even if the user left it ambiguous — see open point below).
3. Never add/remove based on `keep_both_editions` or `insufficient_evidence`.
4. Never add based on missing cache.

**Open point for implementer (resolve in plan):** whether ≥0.95 layout/true-dup **forces** delete on confirm regardless of checkbox, or only **defaults** the checkbox and still honors an explicit uncheck. Spec default: **honor explicit uncheck**; auto-check those extras when scores land so confirm deletes them unless the user unticks.

## UI

### Preview list chip

| State | Label |
| --- | --- |
| No cache | `Edition: —` |
| Scoring | `Edition: …` |
| Aggregate | Short form + confidence, e.g. `Keep both · 0.99` |
| Error / no scorer | `Edition: n/a` |

Short forms: Keep both / Unclear / Layout twin / Dup candidate.

Cautious aggregate order (most → least):  
`keep_both_editions` > `insufficient_evidence` > `layout_twin_extra` > `true_duplicate_candidate`.

### Group detail

- Aggregate chip + one-line: advisory labels; Clean Up confirm still required for deletes.
- Per-extra row: relation, confidence, `same_isrc_misleading` if set, truncated paths.
- **Reveal in Finder** (or OS equivalent) icon per path → open containing folder.
- `Score` / `Re-score` buttons.
- Copy must never say “safe to delete”; use “candidate” for true duplicates.

## Data

Table `edition_advice` (name flexible) under music-dl config DB/store:

- `path_a`, `path_b` (ordered keeper/extra or canonical sort)
- `fingerprint_a`, `fingerprint_b` (size+mtime; hash optional later)
- `relation`, `confidence`, `probabilities_json`, `same_isrc_misleading`
- `model`, `usage_json`, `scored_at`, `error` nullable
- Optional `group_id`

Invalidate when fingerprint changes. Do not write into `album_grouping_assessments` delete outcomes.

## Errors

- Scorer timeout/HTTP/parse: pair `error`; other pairs continue; Clean Up still works.
- Missing key/binary: chips `n/a`; act rules treat as unscored (no auto-delete).

## Testing

- Unit: cautious aggregate; ≥0.95 act allowlist; keep_both/unclear never act; fingerprint invalidate.
- Integration: mock scorer; detail open does not mutate grouping tables; Clean Up confirm with/without cache.
- Manual gate: DJAI module off ≡ baseline Clean Up counts; Reveal in Finder; one remaster pair never auto-deletes even at 0.99 keep_both.

## Success criteria

1. User can see relation + confidence before confirming Clean Up.
2. User can open the folder for a manual check in one click.
3. Confirming Clean Up never removes `keep_both` / `unclear` / unscored via Jev.
4. Confirming Clean Up can remove ≥0.95 `layout_twin_extra` and `true_duplicate_candidate` extras (subject to checkbox honor rule above).
5. Grouping engine and preview math otherwise unchanged when the DJAI module is off.

## Out of scope follow-ups

- Eager scoring of visible list rows.
- Replacing ISRC grouping with Jev.
- Windows/mini-plex parity until Mac path is clicked_pass.
