"""Meter communication status."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .entity import MeterEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Create one connectivity sensor for each meter."""
    async_add_entities(
        ConnectivitySensor(runtime.measurements, entry.entry_id)
        for runtime in entry.runtime_data.meters
    )


class ConnectivitySensor(MeterEntity, BinarySensorEntity):
    """Indicate successful meter reads, not just an open TCP socket."""

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator, entry_id, "connection")

    @property
    def available(self):
        return True

    @property
    def is_on(self):
        return self.coordinator.last_update_success
