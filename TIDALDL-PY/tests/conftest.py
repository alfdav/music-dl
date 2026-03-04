"""Shared pytest fixtures."""

import pytest

from tidal_dl.helper.decorator import SingletonMeta


@pytest.fixture(autouse=False)
def clear_singletons():
    """Reset all singletons before and after each test that requests this fixture."""
    SingletonMeta._instances.clear()
    yield
    SingletonMeta._instances.clear()
