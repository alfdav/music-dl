"""Tests for the deterministic LibraryDB performance probe."""

import ast
import inspect
import json
import math
import textwrap

import pytest

from scripts.qa_performance import (
    ABSOLUTE_MS,
    build_fixture,
    classify,
    main,
    measure,
    percentile_95,
    run_probe,
)


def test_ci_runner_ceilings_match_enforced_qa_budget():
    assert ABSOLUTE_MS == {
        "pagination": 150.0,
        "search": 250.0,
        "artists": 280.0,
    }


def test_absolute_ceiling_blocks():
    result = classify(
        {"pagination": 151.0, "search": 4.0, "artists": 6.0},
        baseline=None,
    )

    assert result.status == "fail"


def test_missing_baseline_is_calibrating_but_passes_absolute_limits():
    result = classify(
        {"pagination": 8.0, "search": 4.0, "artists": 6.0},
        baseline=None,
    )

    assert result.status == "pass"
    assert result.relative_status == "calibrating"


def test_material_relative_regression_requires_percent_and_delta():
    result = classify(
        {"pagination": 11.0, "search": 4.0, "artists": 6.0},
        baseline={"pagination": 8.0, "search": 4.0, "artists": 6.0},
    )

    assert result.status == "regression"
    assert result.relative_status == "regression"


def test_relative_change_under_two_ms_does_not_regress():
    result = classify(
        {"pagination": 5.5, "search": 4.0, "artists": 6.0},
        baseline={"pagination": 4.0, "search": 4.0, "artists": 6.0},
    )

    assert result.status == "pass"
    assert result.relative_status == "pass"


def test_percentile_95_uses_nearest_rank_for_25_samples():
    assert percentile_95(range(1, 26)) == 24.0


def test_measure_warms_once_then_times_25_calls():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1

    p95 = measure(operation)

    assert calls == 26
    assert math.isfinite(p95)
    assert p95 >= 0


def test_build_fixture_inserts_searchable_tracks(tmp_path):
    db = build_fixture(tmp_path / "library.db", tracks=12)
    try:
        _, total = db.tracks_page(limit=50, offset=0)
        rows, matched = db.tracks_page(query="Track 11", limit=50, offset=0)
        assert total == 12
        assert matched == 1
        assert [row["title"] for row in rows] == ["Track 11"]
    finally:
        db.close()


def test_run_probe_returns_three_finite_positive_measurements():
    measurements = run_probe()

    assert set(measurements) == {"pagination", "search", "artists"}
    assert all(math.isfinite(value) and value > 0 for value in measurements.values())


def test_run_probe_keeps_required_query_contract():
    tree = ast.parse(textwrap.dedent(inspect.getsource(run_probe)))
    calls = {
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"tracks_page", "artists_page"}
    }

    assert calls == {
        "db.tracks_page(limit=50, offset=5000)",
        "db.tracks_page(query='Track 9999', limit=50, offset=0)",
        "db.artists_page(limit=50, offset=0)",
    }


def test_main_writes_metrics_without_fixture_paths(tmp_path):
    output = tmp_path / "performance.json"

    exit_code = main(["--output", str(output)])

    serialized = output.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    assert set(payload) == {"status", "relative_status", "p95_ms", "ceilings_ms"}
    assert set(payload["p95_ms"]) == {"pagination", "search", "artists"}
    assert exit_code == (1 if payload["status"] == "fail" else 0)
    assert payload["relative_status"] == "calibrating"
    assert "fixture://" not in serialized
    assert "library.db" not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize(
    "payload",
    [
        {"pagination": 8.0, "search": 4.0},
        {"pagination": 8.0, "search": 4.0, "artists": 6.0, "extra": 1.0},
        {"pagination": 8.0, "search": "fast", "artists": 6.0},
        {"pagination": 0.0, "search": 4.0, "artists": 6.0},
        {"pagination": -1.0, "search": 4.0, "artists": 6.0},
    ],
)
def test_invalid_baseline_exits_two_before_output(tmp_path, capsys, payload):
    baseline = tmp_path / "baseline.json"
    output = tmp_path / "performance.json"
    baseline.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(["--baseline", str(baseline), "--output", str(output)])

    assert exit_code == 2
    assert capsys.readouterr().err == "error: invalid performance baseline\n"
    assert not output.exists()
