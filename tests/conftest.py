"""Home Assistant fixtures for a two-meter gateway."""

from copy import deepcopy

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schneider_pm.const import DOMAIN

SETTINGS = {
    "name": "Test gateway",
    "host": "192.0.2.10",
    "port": 502,
    "protocol": "tcp",
    "scan_interval": 10,
    "energy_interval": 60,
    "meters": [
        {"name": "Main", "unit_id": 1, "serial": "123456", "model": "PM3255"},
        {"name": "Workshop", "unit_id": 2, "serial": "234567", "model": "PM3255"},
    ],
}


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Make the integration discoverable by HA's loader."""


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test gateway", data=deepcopy(SETTINGS), version=1
    )
    entry.add_to_hass(hass)
    return entry
