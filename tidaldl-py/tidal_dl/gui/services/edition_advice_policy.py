"""Pure edition-advice policy: chips, caution order, and delete gates."""

from __future__ import annotations

RELATION_CAUTION_ORDER: list[str] = [
    "keep_both_editions",
    "insufficient_evidence",
    "layout_twin_extra",
    "true_duplicate_candidate",
]

SHORT_LABELS: dict[str, str] = {
    "keep_both_editions": "Keep both",
    "insufficient_evidence": "Unclear",
    "layout_twin_extra": "Layout twin",
    "true_duplicate_candidate": "Dup candidate",
}

_AUTO_ACT_RELATIONS = frozenset({"true_duplicate_candidate", "layout_twin_extra"})
_NEVER_ACT_RELATIONS = frozenset({"keep_both_editions", "insufficient_evidence"})
_AUTO_ACT_MIN_CONFIDENCE = 0.95


def fingerprint(path: str, size: int | None, mtime: float | None) -> str:
    """Stable size+mtime fingerprint for a scanned path."""
    return f"{path}|{size}|{mtime}"


def aggregate_relation(relations: list[str]) -> str | None:
    """Return the most cautious known relation, or None if none match."""
    present = set(relations)
    for relation in RELATION_CAUTION_ORDER:
        if relation in present:
            return relation
    return None


def chip_label(state: str, relation: str | None, confidence: float | None) -> str:
    if state == "pending":
        return "Edition: —"
    if state == "scoring":
        return "Edition: …"
    if state in {"error", "missing"}:
        return "Edition: n/a"
    if state == "ready" and relation:
        short = SHORT_LABELS.get(relation, relation)
        if confidence is not None:
            return f"{short} · {confidence:.2f}"
        return short
    return "Edition: —"


def may_auto_act(relation: str | None, confidence: float | None) -> bool:
    if relation not in _AUTO_ACT_RELATIONS or confidence is None:
        return False
    return confidence >= _AUTO_ACT_MIN_CONFIDENCE


def default_checked(status: str, relation: str | None, confidence: float | None) -> bool:
    """Per-extra checkbox default. Group status and aggregate chips never check."""
    return may_auto_act(relation, confidence)


def resolve_delete_paths(
    *,
    selected_paths: set[str],
    advice_by_path: dict[str, dict],
    honor_uncheck: bool = True,
) -> set[str]:
    """Return posted extras that may be deleted.

    When ``honor_uncheck`` is True, never force-add unchecked paths.
    Keep only extras with actable per-path advice. Strip keep_both,
    insufficient_evidence, unscored, and error even if they were posted.
    """
    result = set(selected_paths)
    if not honor_uncheck:
        for path, advice in advice_by_path.items():
            if may_auto_act(advice.get("relation"), advice.get("confidence")):
                result.add(path)
    kept: set[str] = set()
    for path in result:
        advice = advice_by_path.get(path) or {}
        if advice.get("error"):
            continue
        if may_auto_act(advice.get("relation"), advice.get("confidence")):
            kept.add(path)
    return kept
