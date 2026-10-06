"""Configuration shared by the PowerLogic integration."""

DOMAIN = "schneider_pm"
CONF_METERS = "meters"
CONF_UNIT_ID = "unit_id"
CONF_SERIAL = "serial"
CONF_PROTOCOL = "protocol"
CONF_ENERGY_INTERVAL = "energy_interval"
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_ENERGY_INTERVAL = 60
DEFAULT_PORT = 502


def entry_settings(entry):
    """Options contain a complete replacement of the initial settings."""
    return dict(entry.options or entry.data)
