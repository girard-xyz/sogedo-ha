"""Shared pytest fixtures for the Sogedo integration tests."""

from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def hass_config_dir() -> str:
    """Use the repo root so HA finds our custom_components/ package."""
    return str(ROOT)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    yield
