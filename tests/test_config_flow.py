"""Drive the actual HA config and options flow managers."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from modbus_connection import ModbusTimeoutError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schneider_pm.config_flow import normalize_host
from custom_components.schneider_pm.const import DOMAIN
from custom_components.schneider_pm.meter import UnsupportedMeter

from .conftest import SETTINGS


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.schneider_pm.async_setup_entry", return_value=True):
        yield


async def test_configure_two_meters(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    data = {k: v for k, v in SETTINGS.items() if k != "meters"}
    data["host"] = "  GATEWAY.EXAMPLE. "
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == "meter"
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(
            side_effect=[
                {"model": "PM3255", "serial": "123456"},
                {"model": "PM3255", "serial": "234567"},
            ]
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"unit_id": 1, "name": "Main", "add_another": True}
        )
        assert result["step_id"] == "meter"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"unit_id": 2, "name": "Workshop"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == "gateway.example"
    assert len(result["data"]["meters"]) == 2
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (ModbusTimeoutError("offline"), "cannot_connect"),
        (UnsupportedMeter("Other"), "unsupported_model"),
    ],
)
async def test_probe_errors(hass, exc, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={k: v for k, v in SETTINGS.items() if k != "meters"},
    )
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(side_effect=exc),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"unit_id": 1, "name": "Main"}
        )
    assert result["errors"] == {"base": error}


async def test_duplicate_gateway_and_invalid_interval(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={k: v for k, v in SETTINGS.items() if k != "meters"},
    )
    assert result["reason"] == "already_configured"
    data = {
        **SETTINGS,
        "host": "192.0.2.11",
        "energy_interval": 10,
        "scan_interval": 30,
    }
    data.pop("meters")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=data
    )
    assert result["errors"] == {"energy_interval": "invalid_interval"}


async def options_step(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_add_meter_and_reject_duplicate_address(hass, entry):
    result = await options_step(hass, entry, "add_meter")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"unit_id": 2, "name": "Duplicate"}
    )
    assert result["errors"] == {"base": "duplicate_address"}
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(return_value={"model": "PM3255", "serial": "345678"}),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 3, "name": "Third"}
        )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert len(entry.options["meters"]) == 3


async def test_serial_duplicate_across_gateways(hass, entry):
    other = deepcopy(SETTINGS)
    other["host"] = "192.0.2.11"
    other["meters"] = [
        {"unit_id": 5, "name": "Other", "serial": "999", "model": "PM3255"}
    ]
    MockConfigEntry(domain=DOMAIN, data=other).add_to_hass(hass)
    result = await options_step(hass, entry, "add_meter")
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(return_value={"model": "PM3255", "serial": "999"}),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 3, "name": "Third"}
        )
    assert result["errors"] == {"base": "already_configured"}


async def test_remove_meter_and_last_meter(hass, entry):
    result = await options_step(hass, entry, "remove_meter")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"meter": "123456"}
    )
    assert [m["unit_id"] for m in entry.options["meters"]] == [2]
    result = await options_step(hass, entry, "remove_meter")
    assert result["reason"] == "last_meter"


async def test_edit_name_offline_preserves_identity(hass, entry):
    result = await options_step(hass, entry, "select_meter")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"meter": "123456"}
    )
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter", AsyncMock()
    ) as probe:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 1, "name": "Renamed"}
        )
    probe.assert_not_called()
    assert entry.options["meters"][0]["serial"] == "123456"
    assert entry.options["meters"][0]["name"] == "Renamed"


async def test_edit_address_checks_serial(hass, entry):
    result = await options_step(hass, entry, "select_meter")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"meter": "123456"}
    )
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(return_value={"model": "PM3255", "serial": "999"}),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 3, "name": "Main"}
        )
    assert result["errors"] == {"base": "different_meter"}
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter",
        AsyncMock(return_value={"model": "PM3255", "serial": "123456"}),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"unit_id": 3, "name": "Main"}
        )
    assert entry.options["meters"][0]["unit_id"] == 3


async def test_gateway_change_keeps_meter_identity(hass, entry):
    result = await options_step(hass, entry, "gateway")
    data = {k: v for k, v in SETTINGS.items() if k != "meters"}
    data.update(host="192.0.2.12", scan_interval=15, energy_interval=120)
    result = await hass.config_entries.options.async_configure(result["flow_id"], data)
    assert entry.options["host"] == "192.0.2.12"
    assert entry.options["meters"] == SETTINGS["meters"]


@pytest.mark.parametrize(
    "value", ["", "http://gateway", "gate way", "user@gateway", "gateway:502"]
)
def test_invalid_hosts(value):
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        normalize_host(value)


async def test_options_reject_conflicting_endpoint(hass, entry):
    other = deepcopy(SETTINGS)
    other["host"] = "192.0.2.99"
    MockConfigEntry(domain=DOMAIN, data=other).add_to_hass(hass)
    result = await options_step(hass, entry, "gateway")
    settings = {k: v for k, v in other.items() if k != "meters"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], settings
    )
    assert result["errors"] == {"base": "already_configured"}
    assert not entry.options


def test_protocol_framing():
    from custom_components.schneider_pm import connection_params

    assert connection_params(SETTINGS).framer == "socket"
    assert connection_params({**SETTINGS, "protocol": "rtuovertcp"}).framer == "rtu"
