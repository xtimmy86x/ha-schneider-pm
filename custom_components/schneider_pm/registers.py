"""Shared PM3250/PM3255 register map, independent of Home Assistant.

Source: Schneider DOCA0006EN, Basic Meter Data and PF register format.
Numbers below are one-based *registers*. The wire address is register - 1.
Only adjacent documented registers are combined; holes are never read.
Every measurement below is documented as readable on both supported models.
"""

import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Measurement:
    """A public meter quantity and its on-wire representation."""

    key: str
    register: int
    kind: str
    unit: str | None
    device_class: str | None
    enabled: bool = True

    @property
    def count(self) -> int:
        return 4 if self.kind == "energy" else 2

    @property
    def group(self) -> str:
        return "energy" if self.kind == "energy" else "measurements"


MEASUREMENTS = (
    *(
        Measurement(f"current_l{i}", 2998 + 2 * i, "float", "A", "current")
        for i in range(1, 4)
    ),
    Measurement("current_neutral", 3006, "float", "A", "current", False),
    Measurement("current_average", 3010, "float", "A", "current", False),
    *(
        Measurement(key, reg, "float", "V", "voltage", enabled)
        for key, reg, enabled in (
            ("voltage_l1_l2", 3020, False),
            ("voltage_l2_l3", 3022, False),
            ("voltage_l3_l1", 3024, False),
            ("voltage_ll_average", 3026, False),
            ("voltage_l1_n", 3028, True),
            ("voltage_l2_n", 3030, True),
            ("voltage_l3_n", 3032, True),
            ("voltage_ln_average", 3036, False),
        )
    ),
    *(
        Measurement(
            f"{kind}_{phase}",
            start + 2 * n,
            "float",
            unit,
            cls,
            kind == "active_power" or phase == "total",
        )
        for kind, start, unit, cls in (
            ("active_power", 3054, "kW", "power"),
            ("reactive_power", 3062, "kvar", "reactive_power"),
            ("apparent_power", 3070, "kVA", "apparent_power"),
        )
        for n, phase in enumerate(("l1", "l2", "l3", "total"))
    ),
    *(
        Measurement(
            f"power_factor_{phase}",
            3078 + 2 * n,
            "pf",
            None,
            "power_factor",
            phase == "total",
        )
        for n, phase in enumerate(("l1", "l2", "l3", "total"))
    ),
    Measurement("frequency", 3110, "float", "Hz", "frequency"),
    *(
        Measurement(key, reg, "energy", unit, cls, enabled)
        for key, reg, unit, cls, enabled in (
            ("active_energy_import", 3204, "kWh", "energy", True),
            ("active_energy_export", 3208, "kWh", "energy", True),
            ("reactive_energy_import", 3220, "kvarh", None, False),
            ("reactive_energy_export", 3224, "kvarh", None, False),
            ("apparent_energy_import", 3236, "kVAh", None, False),
            ("apparent_energy_export", 3240, "kVAh", None, False),
        )
    ),
    *(
        Measurement(
            f"active_energy_tariff_{i}", 4192 + 4 * i, "energy", "kWh", "energy", False
        )
        for i in range(1, 5)
    ),
)


def read_blocks(group: str) -> tuple[tuple[int, int], ...]:
    """Return contiguous (one-based register, count) ranges, without holes."""
    blocks: list[tuple[int, int]] = []
    for item in sorted(
        (m for m in MEASUREMENTS if m.group == group), key=lambda m: m.register
    ):
        if blocks and blocks[-1][0] + blocks[-1][1] == item.register:
            start, count = blocks[-1]
            if count + item.count <= 125:
                blocks[-1] = start, count + item.count
                continue
        blocks.append((item.register, item.count))
    return tuple(blocks)


def decode(item: Measurement, registers: list[int]) -> float | None:
    """Decode big-endian words; invalid values never become zero energy."""
    if len(registers) != item.count or any(not 0 <= r <= 65535 for r in registers):
        raise ValueError("Invalid register response length or word")
    raw = struct.pack(f">{len(registers)}H", *registers)
    if item.kind == "energy":
        value = struct.unpack(">q", raw)[0]
        # Imported/exported accumulators cannot be negative. Reject sentinels.
        return None if value < 0 or value == 0x7FFFFFFFFFFFFFFF else value / 1000
    value = struct.unpack(">f", raw)[0]
    if not math.isfinite(value):
        return None
    if item.kind == "pf":
        if not -2 <= value <= 2:
            return None
        if value > 1:
            return 2 - value
        if value < -1:
            return -2 - value
    return value
