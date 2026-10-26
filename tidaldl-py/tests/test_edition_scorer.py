"""Sidecar CLI wrapper for typesafe-music-edition."""

import json
from types import SimpleNamespace

import pytest

from tidal_dl.gui.services.edition_scorer import (
    EditionScorerError,
    EditionScorerUnavailable,
    score_pair,
    scorer_status,
)


FIXTURE = {
    "relation": "keep_both_editions",
    "confidence": 0.99,
    "probabilities": {"keep_both_editions": 0.99},
    "same_isrc_misleading": True,
    "clarity": "high",
    "model": "jev-test",
    "usage": {"tokens": 8},
}


def _item(name="A"):
    return {
        "artist": "Artist",
        "album": f"Album {name}",
        "title": "Song",
        "path": f"/music/{name}.flac",
        "codec": "flac",
        "format": "FLAC",
        "quality": "44100Hz/16bit",
        "isrc": "US123",
        "album_artist": "Artist",
    }


def test_score_pair_parses_cli_json(monkeypatch):
    calls = {}

    def fake_run(cmd, capture_output, text, timeout, env, check=False):
        calls["cmd"] = cmd
        calls["env"] = env
        return SimpleNamespace(returncode=0, stdout=json.dumps(FIXTURE), stderr="")

    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer.subprocess.run", fake_run
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: "/usr/bin/typesafe-music-edition",
    )
    result = score_pair(_item("A"), _item("B"), timeout_s=12)
    assert result["relation"] == "keep_both_editions"
    assert result["confidence"] == 0.99
    assert result["same_isrc_misleading"] is True
    assert calls["cmd"][0] == "/usr/bin/typesafe-music-edition"
    assert "--a" in calls["cmd"] and "--b" in calls["cmd"]
    dumped_a = json.loads(calls["cmd"][calls["cmd"].index("--a") + 1])
    assert dumped_a["path"] == "/music/A.flac"
    assert calls["env"].get("TYPESAFE_API_KEY") != "logged"


def test_missing_binary_raises_unavailable(monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: None,
    )
    with pytest.raises(EditionScorerUnavailable):
        score_pair(_item("A"), _item("B"))


def test_bad_json_raises_scorer_error(monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: "/usr/bin/typesafe-music-edition",
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    with pytest.raises(EditionScorerError):
        score_pair(_item("A"), _item("B"))


def test_nonzero_exit_raises_scorer_error(monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: "/usr/bin/typesafe-music-edition",
    )
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
    )
    with pytest.raises(EditionScorerError, match="boom"):
        score_pair(_item("A"), _item("B"))


def test_scorer_status_ready_when_binary_found(monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: "/usr/bin/typesafe-music-edition",
    )
    assert scorer_status() == "ready"


def test_scorer_status_missing_when_binary_absent(monkeypatch):
    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        lambda: None,
    )
    assert scorer_status() == "missing"


def test_scorer_status_na_on_lookup_error(monkeypatch):
    def boom():
        raise RuntimeError("cannot probe")

    monkeypatch.setattr(
        "tidal_dl.gui.services.edition_scorer._resolve_binary",
        boom,
    )
    assert scorer_status() == "n/a"
