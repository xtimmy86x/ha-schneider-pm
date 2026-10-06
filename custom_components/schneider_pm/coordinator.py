"""Independent polling and availability for each meter and reading group."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import ModbusError

from .meter import PM3255

_LOGGER = logging.getLogger(__name__)


class MeterCoordinator(DataUpdateCoordinator[dict[str, float | None]]):
    """A failed meter never changes another meter's availability."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        meter: PM3255,
        config: dict,
        group: str,
        interval: int,
        measurements: MeterCoordinator | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"PM3255 {config['unit_id']} {group}",
            update_interval=timedelta(seconds=interval),
        )
        self.meter = meter
        self.meter_config = config
        self.group = group
        self.measurements = measurements
        self.last_success: datetime | None = None
        self.last_failure: datetime | None = None

    async def _async_update_data(self) -> dict[str, float | None]:
        if self.measurements is not None and not self.measurements.last_update_success:
            raise UpdateFailed("Meter measurements are unavailable")
        try:
            values = await self.meter.read_group(self.group)
        except (ModbusError, OSError, TimeoutError, ValueError) as err:
            self.last_failure = dt_util.utcnow()
            raise UpdateFailed(f"Could not read {self.group}: {err}") from err
        self.last_success = dt_util.utcnow()
        return values


@dataclass
class MeterRuntime:
    """Both polling groups share the same Modbus unit."""

    measurements: MeterCoordinator
    energy: MeterCoordinator


@dataclass
class RuntimeData:
    """Runtime owned by one gateway config entry."""

    meters: list[MeterRuntime]


type SchneiderConfigEntry = ConfigEntry[RuntimeData]
