"""Exercise actual read requests and register decoding."""

import struct
from unittest.mock import AsyncMock, Mock

import pytest
from modbus_connection import ModbusTimeoutError

from custom_components.schneider_pm.meter import PowerLogicMeter, UnsupportedMeter


def identity_responses(model="PM3255", serial=123456):
    raw = model.encode().ljust(40, b"\0")
    return [list(struct.unpack(">20H", raw)), [serial >> 16, serial & 65535]]


@pytest.mark.parametrize(
    ("reported_model", "expected_model"),
    [
        ("PM3255", "PM3255"),
        ("METSEPM3255", "PM3255"),
        ("PM3250", "PM3250"),
        ("METSEPM3250", "PM3250"),
        (" pm3250 ", "PM3250"),
    ],
)
async def test_identify_uses_zero_based_addresses(reported_model, expected_model):
    unit = Mock()
    unit.read_holding_registers = AsyncMock(
        side_effect=identity_responses(reported_model)
    )
    assert await PowerLogicMeter(unit).identify() == {
        "model": expected_model,
        "serial": "123456",
    }
    assert [call.args for call in unit.read_holding_registers.call_args_list] == [
        (49, 20),
        (129, 2),
    ]


@pytest.mark.parametrize("model", ["PM3200", "PM32500", "PM3255 unknown", ""])
async def test_reject_other_model(model):
    unit = Mock()
    unit.read_holding_registers = AsyncMock(side_effect=identity_responses(model))
    with pytest.raises(UnsupportedMeter) as raised:
        await PowerLogicMeter(unit).identify()
    assert raised.value.model == model
    assert raised.value.registers == tuple(identity_responses(model)[0])
    unit.read_holding_registers.assert_awaited_once_with(49, 20)


async def test_serial_mismatch_prevents_measurements():
    unit = Mock()
    unit.read_holding_registers = AsyncMock(side_effect=identity_responses())
    with pytest.raises(ValueError, match="different meter"):
        await PowerLogicMeter(unit, "98765").read_group("measurements")
    assert unit.read_holding_registers.call_count == 2


@pytest.mark.parametrize("serial", [0, 0xFFFFFFFF])
async def test_reject_bad_serial(serial):
    unit = Mock()
    unit.read_holding_registers = AsyncMock(
        side_effect=identity_responses(serial=serial)
    )
    with pytest.raises(ValueError, match="serial"):
        await PowerLogicMeter(unit).identify()


async def test_contiguous_energy_reads():
    unit = Mock()

    async def read(address, count):
        # 1 kWh, then 2 kWh etc within each block.
        return [w for i in range(count // 4) for w in (0, 0, 0, 1000 * (i + 1))]

    unit.read_holding_registers = AsyncMock(side_effect=read)
    values = await PowerLogicMeter(unit).read_group("energy")
    assert values["active_energy_import"] == 1
    assert values["active_energy_export"] == 2
    assert values["active_energy_tariff_4"] == 4
    assert [c.args for c in unit.read_holding_registers.call_args_list] == [
        (3203, 8),
        (3219, 8),
        (3235, 8),
        (4195, 16),
    ]


async def test_failure_does_not_return_partial_values():
    unit = Mock()
    unit.read_holding_registers = AsyncMock(
        side_effect=[[0] * 8, ModbusTimeoutError("offline")]
    )
    with pytest.raises(ModbusTimeoutError):
        await PowerLogicMeter(unit).read_group("energy")


async def test_malformed_response():
    unit = Mock()
    unit.read_holding_registers = AsyncMock(return_value=[0])
    with pytest.raises(ValueError):
        await PowerLogicMeter(unit).read(3000, 2)
