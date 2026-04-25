"""Bot-facing API tests — auth, resolve, playable source, download status."""

import pytest


@pytest.fixture(autouse=True)
def _set_bot_token(monkeypatch):
    """Ensure MUSIC_DL_BOT_TOKEN is set for all tests in this module."""
    monkeypatch.setenv("MUSIC_DL_BOT_TOKEN", "test-token")


def test_bot_route_rejects_missing_bearer_token(client):
    response = client.post(
        "/api/bot/play/resolve",
        headers={"host": "localhost:8765"},
        json={"query": "test"},
    )
    assert response.status_code == 401


def test_bot_route_rejects_wrong_bearer_token(client):
    response = client.post(
        "/api/bot/play/resolve",
        headers={"host": "localhost:8765", "authorization": "Bearer wrong-token"},
        json={"query": "test"},
    )
    assert response.status_code == 401


def test_bot_route_accepts_valid_bearer_token(client):
    response = client.post(
        "/api/bot/play/resolve",
        headers={"host": "localhost:8765", "authorization": "Bearer test-token"},
        json={"query": "test"},
    )
    assert response.status_code == 200


def test_bot_route_rejects_non_bearer_scheme(client):
    response = client.post(
        "/api/bot/play/resolve",
        headers={"host": "localhost:8765", "authorization": "Basic test-token"},
        json={"query": "test"},
    )
    assert response.status_code == 401
