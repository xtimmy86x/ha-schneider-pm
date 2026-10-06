"""Diagnostics without hostnames, serials, names or raw exception strings."""

from .const import entry_settings


async def async_get_config_entry_diagnostics(hass, entry):
    """Return only an allowlist of operational information."""
    settings = entry_settings(entry)
    return {
        "protocol": settings["protocol"],
        "scan_interval": settings["scan_interval"],
        "energy_interval": settings["energy_interval"],
        "meter_count": len(settings["meters"]),
        "meters": [
            {
                "unit_id": runtime.measurements.meter_config["unit_id"],
                "model": runtime.measurements.meter_config["model"],
                "measurements_available": runtime.measurements.last_update_success,
                "energy_available": runtime.energy.last_update_success,
                "last_success": runtime.measurements.last_success.isoformat()
                if runtime.measurements.last_success
                else None,
            }
            for runtime in entry.runtime_data.meters
        ],
    }
