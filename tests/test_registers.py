"""Verify Schneider addressing, byte order and special encodings."""

import math
import struct

import pytest

from custom_components.schneider_pm.registers import MEASUREMENTS, decode, read_blocks

ITEMS = {m.key: m for m in MEASUREMENTS}


def words(fmt, value):
    raw = struct.pack(fmt, value)
    return list(struct.unpack(f">{len(raw) // 2}H", raw))


def test_float_and_signed_power():
    assert decode(ITEMS["voltage_l1_n"], [0x4366, 0]) == 230
    assert decode(ITEMS["active_power_total"], words(">f", -12.5)) == -12.5


@pytest.mark.parametrize(
    ("encoded", "expected"),
    [
        (0.8, 0.8),
        (1.2, 0.8),
        (-0.8, -0.8),
        (-1.2, -0.8),
        (0, 0),
        (2, 0),
        (-2, 0),
        (1, 1),
        (-1, -1),
    ],
)
def test_all_pf_quadrants(encoded, expected):
    assert decode(ITEMS["power_factor_total"], words(">f", encoded)) == pytest.approx(
        expected
    )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_is_unavailable(value):
    assert decode(ITEMS["voltage_l1_n"], words(">f", value)) is None


def test_invalid_pf():
    assert decode(ITEMS["power_factor_total"], words(">f", 2.1)) is None


def test_int64_energy_and_scaling():
    # Above the UInt32 range: all four words must participate.
    assert (
        decode(ITEMS["active_energy_import"], words(">q", 1234567890123))
        == 1234567890.123
    )
    assert decode(ITEMS["active_energy_export"], [0, 0, 0, 0]) == 0


@pytest.mark.parametrize("value", [-1, -(2**63), 2**63 - 1])
def test_invalid_energy_not_zero(value):
    assert decode(ITEMS["active_energy_import"], words(">q", value)) is None


@pytest.mark.parametrize("invalid", [[], [0], [0, 0, 0], [-1, 0], [65536, 0]])
def test_malformed_word_data(invalid):
    with pytest.raises(ValueError):
        decode(ITEMS["voltage_l1_n"], invalid)


def test_documented_addresses_and_no_reserved_holes():
    assert ITEMS["voltage_l1_n"].register == 3028
    assert ITEMS["active_power_total"].register == 3060
    assert ITEMS["active_energy_import"].register == 3204
    assert ITEMS["active_energy_tariff_4"].register == 4208
    for group in ("measurements", "energy"):
        expected = {
            r
            for m in MEASUREMENTS
            if m.group == group
            for r in range(m.register, m.register + m.count)
        }
        actual = [
            r
            for start, count in read_blocks(group)
            for r in range(start, start + count)
        ]
        assert set(actual) == expected
        assert len(actual) == len(set(actual))
        assert all(count <= 125 for _, count in read_blocks(group))
