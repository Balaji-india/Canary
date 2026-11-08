"""Shared test settings."""
import pytest

from canary import separation


@pytest.fixture(autouse=True)
def fewer_bootstrap_draws(monkeypatch):
    """400 draws instead of 2000 keeps the suite under 30 s. Seeds are fixed, so results stay deterministic; tests
    check interval logic, not the third decimal of a real result."""
    monkeypatch.setattr(separation, "BOOTSTRAP_DRAWS", 400)
