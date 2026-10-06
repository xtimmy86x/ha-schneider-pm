"""Full HA setup against an in-process Modbus TCP meter simulator."""

import asyncio
import struct
from contextlib import asynccontextmanager

import pytest
from homeassistant.components.sensor import SensorStateClass
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.schneider_pm.const import DOMAIN
from custom_components.schneider_pm.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.schneider_pm.registers import MEASUREMENTS


def register_map(serial, model="PM3255"):
    """Return independently encoded meter responses, indexed from zero."""
    result = {}

    def put(register, raw):
        for offset, word in enumerate(struct.unpack(f">{len(raw) // 2}H", raw)):
            result[register - 1 + offset] = word

    put(50, model.encode().ljust(40, b"\0"))
    put(130, struct.pack(">I", serial))
    for item in MEASUREMENTS:
        if item.kind == "energy":
            put(item.register, struct.pack(">q", 123456789))
        else:
            value = 1.2 if item.kind == "pf" else 230.0
            if item.key == "frequency":
                value = 50.0
            put(item.register, struct.pack(">f", value))
    return result


class ModbusServer:
    """Minimal FC03-only TCP server; any unexpected write fails the test."""

    def __init__(self):
        self.registers = {1: register_map(123456), 2: register_map(234567)}
        self.offline = set()
        self.requests = []
        self.clients = set()
        self.connections = 0

    async def handle(self, reader, writer):
        self.clients.add(writer)
        self.connections += 1
        try:
            while True:
                header = await reader.readexactly(7)
                transaction, protocol, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                self.requests.append((unit, *struct.unpack(">BHH", pdu)))
                function, address, count = struct.unpack(">BHH", pdu)
                assert protocol == 0
                assert function == 3
                await asyncio.sleep(0)  # Let simultaneous coordinators contend.
                if unit in self.offline:
                    response = bytes([0x83, 0x0B])
                elif any(
                    r not in self.registers[unit]
                    for r in range(address, address + count)
                ):
                    response = bytes([0x83, 0x02])
                else:
                    words = [
                        self.registers[unit][r] for r in range(address, address + count)
                    ]
                    response = bytes([3, count * 2]) + struct.pack(f">{count}H", *words)
                writer.write(
                    struct.pack(">HHHB", transaction, 0, len(response) + 1, unit)
                    + response
                )
                await writer.drain()
        except asyncio.IncompleteReadError, ConnectionError:
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            await writer.wait_closed()


@asynccontextmanager
async def simulator():
    meter = ModbusServer()
    server = await asyncio.start_server(meter.handle, "127.0.0.1", 0)
    try:
        yield meter, server.sockets[0].getsockname()[1]
    finally:
        server.close()
        await server.wait_closed()
        for writer in list(meter.clients):
            writer.close()
            await writer.wait_closed()
        await asyncio.sleep(0)


def entity_id(hass, serial, key, platform="sensor"):
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{serial}_{key}")


async def setup_gateway(hass, entry, port):
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "host": "127.0.0.1", "port": port}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_two_meters_shared_socket_states_and_unload(hass, entry, socket_enabled):
    async with simulator() as (server, port):
        await setup_gateway(hass, entry, port)
        assert (
            len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
            == 84
        )
        for serial in ("123456", "234567"):
            voltage = hass.states.get(entity_id(hass, serial, "voltage_l1_n"))
            assert float(voltage.state) == 230
            energy = hass.states.get(entity_id(hass, serial, "active_energy_import"))
            assert float(energy.state) == 123456.789
            assert energy.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING
            assert energy.attributes["device_class"] == "energy"
            assert energy.attributes["unit_of_measurement"] == "kWh"
            factor = hass.states.get(entity_id(hass, serial, "power_factor_total"))
            assert float(factor.state) == pytest.approx(0.8)
        await asyncio.gather(
            *(r.measurements.async_refresh() for r in entry.runtime_data.meters)
        )
        assert server.connections == 1
        assert {request[0] for request in server.requests} == {1, 2}
        assert all(request[1] == 3 for request in server.requests)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        await asyncio.sleep(0.05)
        assert not server.clients


async def test_add_pm3250_to_running_pm3255_gateway(hass, entry, socket_enabled):
    """Reproduce adding unit 2 through options while unit 1 is polling."""
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "meters": entry.data["meters"][:1]}
    )
    async with simulator() as (server, port):
        server.registers[2] = register_map(234567, "PM3250")
        await setup_gateway(hass, entry, port)
        first_energy = entity_id(hass, "123456", "active_energy_import")
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "add_meter"}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 2, "name": "Workshop"}
        )
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert entry.options["meters"][1]["model"] == "PM3250"
        await hass.async_block_till_done()

        assert entity_id(hass, "123456", "active_energy_import") == first_energy
        devices = dr.async_get(hass)
        for serial, model in [("123456", "PM3255"), ("234567", "PM3250")]:
            device = devices.async_get_device_by_identifier(
                (DOMAIN, serial), entry.entry_id
            )
            assert device.model == model
            voltage = hass.states.get(entity_id(hass, serial, "voltage_l1_n"))
            energy = hass.states.get(entity_id(hass, serial, "active_energy_import"))
            assert float(voltage.state) == 230
            assert float(energy.state) == 123456.789
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert [meter["model"] for meter in diagnostics["meters"]] == [
            "PM3255",
            "PM3250",
        ]
        assert entry.runtime_data.meters[1].energy.data["active_energy_tariff_4"] == (
            123456.789
        )
        assert all(request[1] == 3 for request in server.requests)
        await hass.config_entries.async_unload(entry.entry_id)


async def test_offline_meter_startup_and_recovery(hass, entry, socket_enabled):
    async with simulator() as (server, port):
        server.offline.add(1)
        await setup_gateway(hass, entry, port)
        first, second = entry.runtime_data.meters
        assert (
            hass.states.get(entity_id(hass, "123456", "voltage_l1_n")).state
            == "unavailable"
        )
        assert (
            hass.states.get(entity_id(hass, "123456", "active_energy_import")).state
            == "unavailable"
        )
        assert (
            hass.states.get(
                entity_id(hass, "123456", "connection", "binary_sensor")
            ).state
            == "off"
        )
        assert (
            float(hass.states.get(entity_id(hass, "234567", "voltage_l1_n")).state)
            == 230
        )
        server.offline.clear()
        await first.measurements.async_refresh()
        await first.energy.async_refresh()
        await hass.async_block_till_done()
        assert (
            hass.states.get(
                entity_id(hass, "123456", "connection", "binary_sensor")
            ).state
            == "on"
        )
        assert (
            float(
                hass.states.get(entity_id(hass, "123456", "active_energy_import")).state
            )
            == 123456.789
        )
        assert second.measurements.last_update_success
        await hass.config_entries.async_unload(entry.entry_id)


async def test_outage_marks_energy_unavailable_until_new_read(
    hass, entry, socket_enabled
):
    async with simulator() as (server, port):
        await setup_gateway(hass, entry, port)
        first = entry.runtime_data.meters[0]
        energy_id = entity_id(hass, "123456", "active_energy_import")
        server.offline.add(1)
        await first.measurements.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(energy_id).state == "unavailable"
        server.offline.clear()
        await first.measurements.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(energy_id).state == "unavailable"
        await first.energy.async_refresh()
        await hass.async_block_till_done()
        assert float(hass.states.get(energy_id).state) == 123456.789
        await hass.config_entries.async_unload(entry.entry_id)


async def test_removed_meter_cleanup_and_diagnostics(hass, entry, socket_enabled):
    async with simulator() as (server, port):
        await setup_gateway(hass, entry, port)
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        text = str(diagnostics)
        assert all(
            private not in text
            for private in ["127.0.0.1", "123456", "234567", "Workshop", "Main"]
        )
        assert diagnostics["meter_count"] == 2
        registry = dr.async_get(hass)
        removed_device = registry.async_get_device_by_identifier(
            (DOMAIN, "234567"), entry.entry_id
        )
        assert removed_device is not None
        first_entity = entity_id(hass, "123456", "active_energy_import")
        await hass.config_entries.async_unload(entry.entry_id)
        hass.config_entries.async_update_entry(
            entry, options={**entry.data, "meters": [entry.data["meters"][0]]}
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entity_id(hass, "234567", "active_energy_import") is None
        assert (
            registry.async_get_device_by_identifier((DOMAIN, "234567"), entry.entry_id)
            is None
        )
        assert entity_id(hass, "123456", "active_energy_import") == first_entity
        await hass.config_entries.async_unload(entry.entry_id)


async def test_five_meters_share_connection(hass, entry, socket_enabled):
    async with simulator() as (server, port):
        meters = list(entry.data["meters"])
        for unit_id in (3, 4, 5):
            serial = unit_id * 111111
            server.registers[unit_id] = register_map(serial)
            meters.append(
                {
                    "unit_id": unit_id,
                    "serial": str(serial),
                    "name": f"Meter {unit_id}",
                    "model": "PM3255",
                }
            )
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, "meters": meters}
        )
        await setup_gateway(hass, entry, port)
        assert len(entry.runtime_data.meters) == 5
        assert server.connections == 1
        assert {request[0] for request in server.requests} == {1, 2, 3, 4, 5}
        assert all(
            runtime.measurements.last_update_success
            for runtime in entry.runtime_data.meters
        )
        assert (
            len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
            == 210
        )
        await hass.config_entries.async_unload(entry.entry_id)


async def test_reconnect_after_tcp_socket_closes(hass, entry, socket_enabled):
    async with simulator() as (server, port):
        await setup_gateway(hass, entry, port)
        for writer in list(server.clients):
            writer.close()
            await writer.wait_closed()
        await asyncio.sleep(0.05)
        first = entry.runtime_data.meters[0]
        await first.measurements.async_refresh()
        assert first.measurements.last_update_success
        assert server.connections == 2
        await hass.config_entries.async_unload(entry.entry_id)
