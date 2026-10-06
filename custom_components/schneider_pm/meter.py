"""Read-only PM3255 protocol implementation."""

import struct

from modbus_connection import ModbusUnit

from .registers import MEASUREMENTS, decode, read_blocks


class UnsupportedMeter(ValueError):
    """The responding unit is not a supported PM3255."""

    def __init__(self, model: str, registers: list[int] | None = None) -> None:
        super().__init__(model)
        self.model = model
        self.registers = tuple(registers or ())


class PM3255:
    """Read one meter through a unit on a shared connection."""

    def __init__(self, unit: ModbusUnit, expected_serial: str | None = None) -> None:
        self.unit = unit
        self.expected_serial = expected_serial
        self._identity_verified = expected_serial is None
        self.unit.set_message_spacing(0.05)

    async def read(self, register: int, count: int) -> list[int]:
        """Translate Schneider's register number exactly once."""
        words = await self.unit.read_holding_registers(register - 1, count)
        if len(words) != count or any(
            not isinstance(w, int) or not 0 <= w <= 65535 for w in words
        ):
            raise ValueError("Malformed Modbus register response")
        return words

    async def identify(self) -> dict[str, str]:
        """Validate model and read a stable serial number."""
        words = await self.read(50, 20)
        model = struct.pack(">20H", *words).split(b"\x00", 1)[0].decode("utf-8").strip()
        if model.upper() not in {"PM3255", "METSEPM3255"}:
            raise UnsupportedMeter(model, words)
        words = await self.read(130, 2)
        serial = (words[0] << 16) | words[1]
        if serial in (0, 0xFFFFFFFF):
            raise ValueError("Invalid serial number")
        return {"model": "PM3255", "serial": str(serial)}

    async def read_group(self, group: str) -> dict[str, float | None]:
        """Return an atomic group snapshot; do not expose partial stale data."""
        if not self._identity_verified:
            identity = await self.identify()
            if identity["serial"] != self.expected_serial:
                raise ValueError(
                    "The configured address now belongs to a different meter"
                )
            self._identity_verified = True
        result: dict[str, float | None] = {}
        for start, count in read_blocks(group):
            words = await self.read(start, count)
            for item in MEASUREMENTS:
                if item.group == group and start <= item.register < start + count:
                    offset = item.register - start
                    result[item.key] = decode(item, words[offset : offset + item.count])
        return result
