"""PowerLogic measurement and energy sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MeterCoordinator, SchneiderConfigEntry
from .entity import MeterEntity
from .registers import MEASUREMENTS, Measurement


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchneiderConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Expose all supported readings and a diagnostic timestamp per meter."""
    entities = []
    for runtime in entry.runtime_data.meters:
        for item in MEASUREMENTS:
            coordinator = (
                runtime.energy if item.group == "energy" else runtime.measurements
            )
            entities.append(PowerLogicSensor(coordinator, entry.entry_id, item))
        entities.append(LastSuccessSensor(runtime.measurements, entry.entry_id))
    async_add_entities(entities)


class PowerLogicSensor(MeterEntity, SensorEntity):
    """A quantity read from a documented register."""

    def __init__(
        self, coordinator: MeterCoordinator, entry_id: str, item: Measurement
    ) -> None:
        super().__init__(coordinator, entry_id, item.key)
        self.item = item
        self._attr_translation_key = item.key
        self._attr_native_unit_of_measurement = item.unit
        self._attr_device_class = (
            SensorDeviceClass(item.device_class) if item.device_class else None
        )
        self._attr_state_class = (
            SensorStateClass.TOTAL_INCREASING
            if item.group == "energy"
            else SensorStateClass.MEASUREMENT
        )
        self._attr_entity_registry_enabled_default = item.enabled
        self._attr_suggested_display_precision = (
            3 if item.kind in {"energy", "pf"} or "power" in item.key else 2
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.measurements is not None:
            self.async_on_remove(
                self.coordinator.measurements.async_add_listener(
                    self.async_write_ha_state
                )
            )

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        fast = self.coordinator.measurements
        if fast is not None:
            if not fast.last_update_success:
                return False
            # Old energy must not reappear after a failed fast poll until it is reread.
            if self.coordinator.last_success is None or (
                fast.last_failure is not None
                and self.coordinator.last_success <= fast.last_failure
            ):
                return False
        return self.native_value is not None

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self.item.key)


class LastSuccessSensor(MeterEntity, SensorEntity):
    """Keep the timestamp visible even when communication is down."""

    _attr_translation_key = "last_success"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: MeterCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "last_success")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        return self.coordinator.last_success
