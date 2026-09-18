"""Edition-advice policy: caution order, chips, and delete gates."""

from tidal_dl.gui.services.edition_advice_policy import (
    RELATION_CAUTION_ORDER,
    SHORT_LABELS,
    aggregate_relation,
    chip_label,
    default_checked,
    fingerprint,
    may_auto_act,
    resolve_delete_paths,
)


class TestCautionOrder:
    def test_most_to_least_cautious(self):
        assert RELATION_CAUTION_ORDER == [
            "keep_both_editions",
            "insufficient_evidence",
            "layout_twin_extra",
            "true_duplicate_candidate",
        ]

    def test_short_labels(self):
        assert SHORT_LABELS["keep_both_editions"] == "Keep both"
        assert SHORT_LABELS["insufficient_evidence"] == "Unclear"
        assert SHORT_LABELS["layout_twin_extra"] == "Layout twin"
        assert SHORT_LABELS["true_duplicate_candidate"] == "Dup candidate"

    def test_aggregate_picks_most_cautious(self):
        assert (
            aggregate_relation(
                ["true_duplicate_candidate", "keep_both_editions", "layout_twin_extra"]
            )
            == "keep_both_editions"
        )
        assert (
            aggregate_relation(["true_duplicate_candidate", "insufficient_evidence"])
            == "insufficient_evidence"
        )
        assert aggregate_relation(["true_duplicate_candidate"]) == "true_duplicate_candidate"
        assert aggregate_relation([]) is None
        assert aggregate_relation(["unknown"]) is None


class TestMayAutoAct:
    def test_keep_both_never_even_at_0_99(self):
        assert may_auto_act("keep_both_editions", 0.99) is False

    def test_unclear_never(self):
        assert may_auto_act("insufficient_evidence", 0.99) is False

    def test_dup_below_threshold(self):
        assert may_auto_act("true_duplicate_candidate", 0.94) is False

    def test_dup_at_threshold(self):
        assert may_auto_act("true_duplicate_candidate", 0.95) is True

    def test_layout_twin_at_threshold(self):
        assert may_auto_act("layout_twin_extra", 0.95) is True

    def test_missing_or_none(self):
        assert may_auto_act(None, 0.99) is False
        assert may_auto_act("layout_twin_extra", None) is False


class TestDefaultChecked:
    def test_auto_status_checked(self):
        assert default_checked("auto", None, None) is True

    def test_uncertain_unchecked_until_actable(self):
        assert default_checked("uncertain", "keep_both_editions", 0.99) is False
        assert default_checked("uncertain", "true_duplicate_candidate", 0.95) is True


class TestFingerprint:
    def test_stable_for_same_inputs(self):
        a = fingerprint("/music/a.flac", 1024, 1700000000.0)
        b = fingerprint("/music/a.flac", 1024, 1700000000.0)
        assert a == b
        assert a

    def test_changes_when_size_or_mtime_changes(self):
        base = fingerprint("/music/a.flac", 1024, 1700000000.0)
        assert fingerprint("/music/a.flac", 2048, 1700000000.0) != base
        assert fingerprint("/music/a.flac", 1024, 1700000001.0) != base


class TestChipLabel:
    def test_pending(self):
        assert chip_label("pending", None, None) == "Edition: —"

    def test_scoring(self):
        assert chip_label("scoring", None, None) == "Edition: …"

    def test_error_and_missing(self):
        assert chip_label("error", None, None) == "Edition: n/a"
        assert chip_label("missing", None, None) == "Edition: n/a"

    def test_ready_short_form_and_confidence(self):
        assert chip_label("ready", "keep_both_editions", 0.99) == "Keep both · 0.99"
        assert chip_label("ready", "true_duplicate_candidate", 0.95) == "Dup candidate · 0.95"


class TestResolveDeletePaths:
    def test_honor_uncheck_never_force_adds(self):
        selected = {"/extra-checked.flac"}
        advice = {
            "/extra-checked.flac": {
                "relation": "layout_twin_extra",
                "confidence": 0.99,
            },
            "/extra-unchecked.flac": {
                "relation": "true_duplicate_candidate",
                "confidence": 0.99,
            },
        }
        result = resolve_delete_paths(
            selected_paths=selected, advice_by_path=advice, honor_uncheck=True
        )
        assert result == {"/extra-checked.flac"}
        assert "/extra-unchecked.flac" not in result

    def test_strips_keep_both_and_unclear_even_if_posted(self):
        selected = {
            "/keep-both.flac",
            "/unclear.flac",
            "/layout.flac",
        }
        advice = {
            "/keep-both.flac": {"relation": "keep_both_editions", "confidence": 0.99},
            "/unclear.flac": {"relation": "insufficient_evidence", "confidence": 0.80},
            "/layout.flac": {"relation": "layout_twin_extra", "confidence": 0.99},
        }
        result = resolve_delete_paths(
            selected_paths=selected, advice_by_path=advice, honor_uncheck=True
        )
        assert result == {"/layout.flac"}
