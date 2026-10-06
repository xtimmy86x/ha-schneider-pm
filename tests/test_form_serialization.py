"""Exercise the UI serialization boundary that flow-manager tests do not cover."""

import json

import pytest
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list

from custom_components.schneider_pm.config_flow import gateway_schema, meter_schema


@pytest.mark.parametrize(
    "schema", [gateway_schema(), meter_schema(), meter_schema(initial=True)]
)
def test_form_schema_serializes_to_json(schema):
    fields = to_field_list(schema, custom_serializer=cv.custom_serializer)
    assert json.loads(json.dumps(fields))


async def test_start_and_submit_config_over_http(hass, hass_client):
    """Reproduce the user's HTTP endpoint, including schema JSON serialization."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    response = await client.post(
        "/api/config/config_entries/flow", json={"handler": "schneider_pm"}
    )
    assert response.status == 200
    form = await response.json()
    assert form["step_id"] == "user"
    assert {field["name"] for field in form["data_schema"]} >= {"name", "host", "port"}
    url = f"/api/config/config_entries/flow/{form['flow_id']}"
    response = await client.post(
        url,
        json={
            "name": " ",
            "host": "http://bad-host",
            "port": 502,
            "protocol": "tcp",
            "scan_interval": 10,
            "energy_interval": 60,
        },
    )
    assert response.status == 200
    form = await response.json()
    assert form["errors"] == {"name": "invalid_name", "host": "invalid_host"}
    response = await client.post(
        url,
        json={
            "name": "Gateway",
            "host": "192.0.2.10",
            "port": 502,
            "protocol": "tcp",
            "scan_interval": 10,
            "energy_interval": 60,
        },
    )
    assert response.status == 200
    form = await response.json()
    assert form["step_id"] == "meter"
    assert {field["name"] for field in form["data_schema"]} >= {"name", "unit_id"}
    response = await client.post(url, json={"name": "  ", "unit_id": 1})
    assert response.status == 200
    assert (await response.json())["errors"] == {"name": "invalid_name"}


@pytest.mark.parametrize(
    "step", ["gateway", "add_meter", "select_meter", "remove_meter", "edit_meter"]
)
async def test_all_options_forms_serialize(hass, entry, step):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "select_meter" if step == "edit_meter" else step},
    )
    if step == "edit_meter":
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"meter": "123456"}
        )
    assert result["step_id"] == step
    assert json.loads(
        json.dumps(
            to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
        )
    )


@pytest.mark.parametrize("step", ["gateway", "add_meter", "edit_meter"])
async def test_invalid_option_text_returns_form_error(hass, entry, step):
    from unittest.mock import AsyncMock, patch

    from .conftest import SETTINGS

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"next_step_id": "select_meter" if step == "edit_meter" else step},
    )
    if step == "edit_meter":
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"meter": "123456"}
        )
    data = (
        {k: v for k, v in SETTINGS.items() if k != "meters"}
        if step == "gateway"
        else {"unit_id": 1}
    )
    data["name"] = "  "
    with patch(
        "custom_components.schneider_pm.config_flow.probe_meter", AsyncMock()
    ) as probe:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], data
        )
    probe.assert_not_called()
    assert result["errors"] == {"name": "invalid_name"}
    assert not entry.options
    assert to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
