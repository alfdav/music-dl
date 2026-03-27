"""Shared pytest fixtures."""

import pytest

from tidal_dl.helper.decorator import SingletonMeta


@pytest.fixture(autouse=False)
def clear_singletons():
    """Reset all singletons before and after each test that requests this fixture."""
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()


import re

@pytest.fixture
def client():
    """FastAPI TestClient with CSRF support."""
    from tidal_dl.gui import create_app
    from fastapi.testclient import TestClient
    c = TestClient(create_app(port=8765))
    c._host_header = {"host": "localhost:8765"}
    index = c.get("/", headers=c._host_header)
    match = re.search(r'name="csrf-token" content="([^"]+)"', index.text)
    c._csrf = match.group(1) if match else ""
    c._headers = {**c._host_header, "X-CSRF-Token": c._csrf}
    return c
