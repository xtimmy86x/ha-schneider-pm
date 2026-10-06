"""Common meter entity identity."""

from homeassistant.helpers.device_registry import (
    DeviceInfo,
    async_get_device_id_by_identifier,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MeterCoordinator


class MeterEntity(CoordinatorEntity[MeterCoordinator]):
    """Entities retain identity when the gateway IP or meter name changes."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MeterCoordinator, entry_id: str, key: str) -> None:
        super().__init__(coordinator)
        config = coordinator.meter_config
        self._attr_unique_id = f"{config['serial']}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config["serial"])},
            name=config["name"],
            manufacturer="Schneider Electric",
            model=config["model"],
            serial_number=config["serial"],
            via_device_id=async_get_device_id_by_identifier(
                coordinator.hass, (DOMAIN, entry_id), config_entry_id=entry_id
            ),
        )
