"""Schneider PowerLogic meters over a shared Modbus connection."""

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from modbus_connection import ModbusTcpParams

from .const import (
    CONF_ENERGY_INTERVAL,
    CONF_METERS,
    CONF_PROTOCOL,
    DOMAIN,
    entry_settings,
)
from .coordinator import (
    MeterCoordinator,
    MeterRuntime,
    RuntimeData,
    SchneiderConfigEntry,
)
from .meter import PowerLogicMeter

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


def connection_params(settings: dict) -> ModbusTcpParams:
    """Use the framing configured on the gateway, with HA-owned timeouts."""
    return ModbusTcpParams(
        host=settings[CONF_HOST],
        port=settings[CONF_PORT],
        framer="rtu" if settings[CONF_PROTOCOL] == "rtuovertcp" else "socket",
    )


async def async_setup_entry(hass: HomeAssistant, entry: SchneiderConfigEntry) -> bool:
    """Load even if a previously configured meter is temporarily offline."""
    settings = entry_settings(entry)
    params = connection_params(settings)
    devices = dr.async_get(hass)
    devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=settings["name"],
        manufacturer="Modbus",
        model="TCP/RS485 gateway",
    )
    meters = []
    for config in settings[CONF_METERS]:
        unit = async_get_unit(hass, entry, params, config["unit_id"])
        meter = PowerLogicMeter(unit, config["serial"])
        fast = MeterCoordinator(
            hass, entry, meter, config, "measurements", settings[CONF_SCAN_INTERVAL]
        )
        slow = MeterCoordinator(
            hass, entry, meter, config, "energy", settings[CONF_ENERGY_INTERVAL], fast
        )
        # async_refresh reports failure without aborting setup for healthy siblings.
        await fast.async_refresh()
        await slow.async_refresh()
        meters.append(MeterRuntime(fast, slow))
    entry.runtime_data = RuntimeData(meters)
    _remove_deleted_meters(hass, entry, {m["serial"] for m in settings[CONF_METERS]})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_deleted_meters(
    hass: HomeAssistant, entry: SchneiderConfigEntry, serials: set[str]
) -> None:
    """Detach removed meters and their entities only from this config entry."""
    entities = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entities, entry.entry_id):
        if entity.unique_id.split("_", 1)[0] not in serials:
            entities.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if (DOMAIN, entry.entry_id) in device.identifiers:
            continue
        if not any((DOMAIN, serial) in device.identifiers for serial in serials):
            devices.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: SchneiderConfigEntry) -> bool:
    """Unload entities; HA releases all shared Modbus units on entry unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
