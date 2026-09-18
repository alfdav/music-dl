"""Score a Clean Up group via sidecar + edition_advice cache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tidal_dl.gui.services.edition_advice_policy import (
    aggregate_relation,
    chip_label,
    fingerprint,
)
from tidal_dl.gui.services.edition_scorer import EditionScorerError, score_pair

_SCORE_WORKERS = 2


def _item_from_row(row: dict) -> dict:
    return {
        "artist": row.get("artist"),
        "album": row.get("album"),
        "title": row.get("title"),
        "path": row.get("path"),
        "codec": row.get("codec"),
        "format": row.get("format"),
        "quality": row.get("quality"),
        "isrc": row.get("isrc"),
        "album_artist": row.get("album_artist"),
    }


def _row_fingerprint(row: dict | None, path: str) -> str:
    if not row:
        return fingerprint(path, None, None)
    return fingerprint(path, row.get("file_size"), row.get("file_mtime"))


def _pair_payload(
    *,
    path_a: str,
    path_b: str,
    cached: bool,
    result: dict | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    result = result or {}
    return {
        "path_a": path_a,
        "path_b": path_b,
        "relation": result.get("relation"),
        "confidence": result.get("confidence"),
        "probabilities": result.get("probabilities"),
        "same_isrc_misleading": result.get("same_isrc_misleading"),
        "clarity": result.get("clarity"),
        "model": result.get("model"),
        "usage": result.get("usage"),
        "error": error or result.get("error"),
        "cached": cached,
    }


def _aggregate(pairs: list[dict]) -> dict[str, Any]:
    relations = [p["relation"] for p in pairs if p.get("relation")]
    relation = aggregate_relation(relations)
    confidence = None
    if relation:
        for pair in pairs:
            if pair.get("relation") == relation:
                confidence = pair.get("confidence")
                break
    if relation:
        state = "ready"
    elif any(p.get("error") for p in pairs):
        state = "error"
    else:
        state = "pending"
    return {
        "relation": relation,
        "confidence": confidence,
        "state": state,
        "chip": chip_label(state, relation, confidence),
    }


def score_group(db, group: dict, *, force: bool = False) -> dict[str, Any]:
    """Score keeper↔each extra. Cache hits skip the sidecar unless ``force``."""
    group_id = group.get("key") or ""
    keeper_path = group["keeper"]["path"]
    keeper_row = db.get(keeper_path) or {"path": keeper_path}
    fp_a = _row_fingerprint(keeper_row, keeper_path)
    item_a = _item_from_row(keeper_row)

    cached_pairs: list[dict] = []
    to_score: list[tuple[str, dict, str]] = []
    for extra in group.get("duplicates") or []:
        extra_path = extra["path"]
        extra_row = db.get(extra_path) or {"path": extra_path}
        fp_b = _row_fingerprint(extra_row, extra_path)
        hit = None
        if not force:
            hit = db.get_edition_advice(
                keeper_path, extra_path, fingerprint_a=fp_a, fingerprint_b=fp_b
            )
        if hit and not hit.get("error"):
            cached_pairs.append(
                _pair_payload(path_a=keeper_path, path_b=extra_path, cached=True, result=hit)
            )
        else:
            to_score.append((extra_path, extra_row, fp_b))

    scored: list[dict] = []
    if to_score:
        with ThreadPoolExecutor(max_workers=_SCORE_WORKERS) as pool:
            futures = {
                pool.submit(score_pair, item_a, _item_from_row(extra_row)): (
                    extra_path,
                    fp_b,
                )
                for extra_path, extra_row, fp_b in to_score
            }
            for future in as_completed(futures):
                extra_path, fp_b = futures[future]
                try:
                    raw = future.result()
                    db.upsert_edition_advice(
                        path_a=keeper_path,
                        path_b=extra_path,
                        fingerprint_a=fp_a,
                        fingerprint_b=fp_b,
                        relation=raw.get("relation"),
                        confidence=raw.get("confidence"),
                        probabilities=raw.get("probabilities"),
                        same_isrc_misleading=raw.get("same_isrc_misleading"),
                        model=raw.get("model"),
                        usage=raw.get("usage"),
                        error=None,
                        group_id=group_id,
                    )
                    scored.append(
                        _pair_payload(
                            path_a=keeper_path,
                            path_b=extra_path,
                            cached=False,
                            result=raw,
                        )
                    )
                except EditionScorerError as exc:
                    db.upsert_edition_advice(
                        path_a=keeper_path,
                        path_b=extra_path,
                        fingerprint_a=fp_a,
                        fingerprint_b=fp_b,
                        error=str(exc),
                        group_id=group_id,
                    )
                    scored.append(
                        _pair_payload(
                            path_a=keeper_path,
                            path_b=extra_path,
                            cached=False,
                            error=str(exc),
                        )
                    )

    pairs = cached_pairs + scored
    pairs.sort(key=lambda p: p["path_b"])
    return {
        "group_id": group_id,
        "pairs": pairs,
        "aggregate": _aggregate(pairs),
    }
