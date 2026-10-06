"""Configure a gateway and manage its meters without YAML."""

import ipaddress
from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from modbus_connection import ModbusError

from . import connection_params
from .const import (
    DEFAULT_ENERGY_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    entry_settings,
)
from .meter import PM3255, UnsupportedMeter


def normalize_host(host: str) -> str:
    """Use a consistent endpoint key and reject URLs and empty values."""
    host = host.strip().lower().rstrip(".")
    if not host or any(c.isspace() for c in host) or "/" in host or "@" in host:
        raise vol.Invalid("invalid_host")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        if ":" in host:
            raise vol.Invalid("invalid_host") from None
        return host


def nonempty_name(value: str) -> str:
    """Require a meaningful display name."""
    value = value.strip()
    if not value:
        raise vol.Invalid("invalid_name")
    return value


def normalize_text_fields(data: dict) -> tuple[dict, dict[str, str]]:
    """Validate submitted text, keeping callables out of the UI schema."""
    data = dict(data)
    errors = {}
    for key, validator, error in (
        ("name", nonempty_name, "invalid_name"),
        ("host", normalize_host, "invalid_host"),
    ):
        if key in data:
            try:
                data[key] = validator(data[key])
            except vol.Invalid:
                errors[key] = error
    return data, errors


def gateway_schema(defaults: dict | None = None) -> vol.Schema:
    """Connection framing and polling are user choices."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "PowerLogic")): str,
            vol.Required("host", default=d.get("host", "")): str,
            vol.Required("port", default=d.get("port", 502)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(
                "protocol", default=d.get("protocol", "tcp")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["tcp", "rtuovertcp"], translation_key="protocol"
                )
            ),
            vol.Required(
                "scan_interval", default=d.get("scan_interval", DEFAULT_SCAN_INTERVAL)
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
            vol.Required(
                "energy_interval",
                default=d.get("energy_interval", DEFAULT_ENERGY_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=86400)),
        }
    )


def meter_schema(defaults: dict | None = None, *, initial: bool = False) -> vol.Schema:
    """One meter at a time; names can also be changed through HA devices."""
    d = defaults or {}
    fields = {
        vol.Required("unit_id", default=d.get("unit_id", 1)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=247)
        ),
        vol.Required("name", default=d.get("name", "PM3255")): str,
    }
    if initial:
        fields[vol.Optional("add_another", default=False)] = bool
    return vol.Schema(fields)


def endpoint_in_use(hass, settings: dict, exclude: str | None = None) -> bool:
    """Do not create competing entries for the same gateway."""
    return any(
        entry.entry_id != exclude
        and entry_settings(entry)["host"] == settings["host"]
        and entry_settings(entry)["port"] == settings["port"]
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


def serial_in_use(hass, serial: str, exclude: str | None = None) -> bool:
    """Keep physical devices unique even through gateway aliases."""
    return any(
        entry.entry_id != exclude
        and any(m["serial"] == serial for m in entry_settings(entry)["meters"])
        for entry in hass.config_entries.async_entries(DOMAIN)
    )


async def probe_meter(hass, settings: dict, unit_id: int) -> dict[str, str]:
    """Validate using HA's connection pool and release the temporary unit."""
    async with async_get_temporary_unit(
        hass, connection_params(settings), unit_id
    ) as unit:
        return await PM3255(unit).identify()


async def validate_meter(hass, settings, data, *, exclude=None, editing=None):
    """Return stored identity and a form error, without changing configuration."""
    others = [m for m in settings["meters"] if m["serial"] != editing]
    if any(m["unit_id"] == data["unit_id"] for m in others):
        return None, "duplicate_address"
    try:
        identity = await probe_meter(hass, settings, data["unit_id"])
    except UnsupportedMeter:
        return None, "unsupported_model"
    except HomeAssistantError:
        return None, "connection_conflict"
    except ModbusError, OSError, TimeoutError, ValueError:
        return None, "cannot_connect"
    if editing and identity["serial"] != editing:
        return None, "different_meter"
    if any(m["serial"] == identity["serial"] for m in others) or serial_in_use(
        hass, identity["serial"], exclude
    ):
        return None, "already_configured"
    return {"unit_id": data["unit_id"], "name": data["name"], **identity}, None


class PowerLogicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up a gateway and at least one responding PM3255."""

    VERSION = 1

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PowerLogicOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input = gateway_schema()(user_input)
            user_input, errors = normalize_text_fields(user_input)
            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=gateway_schema(user_input),
                    errors=errors,
                )
            if endpoint_in_use(self.hass, user_input):
                return self.async_abort(reason="already_configured")
            if user_input["energy_interval"] < user_input["scan_interval"]:
                errors["energy_interval"] = "invalid_interval"
            else:
                self._settings = {**user_input, "meters": []}
                return await self.async_step_meter()
        return self.async_show_form(
            step_id="user", data_schema=gateway_schema(user_input), errors=errors
        )

    async def async_step_meter(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input = meter_schema(initial=True)(user_input)
            user_input, errors = normalize_text_fields(user_input)
            if errors:
                return self.async_show_form(
                    step_id="meter",
                    data_schema=meter_schema(user_input, initial=True),
                    errors=errors,
                )
            meter, error = await validate_meter(self.hass, self._settings, user_input)
            if error:
                errors["base"] = error
            else:
                self._settings["meters"].append(meter)
                if not user_input.get("add_another"):
                    return self.async_create_entry(
                        title=self._settings["name"], data=self._settings
                    )
                user_input = {
                    "unit_id": min(user_input["unit_id"] + 1, 247),
                    "name": "PM3255",
                }
        return self.async_show_form(
            step_id="meter",
            data_schema=meter_schema(user_input, initial=True),
            errors=errors,
        )


class PowerLogicOptionsFlow(config_entries.OptionsFlowWithReload):
    """Manage devices and gateway settings with automatic reload on save."""

    def __init__(self) -> None:
        self._editing: str | None = None

    @property
    def settings(self):
        return deepcopy(entry_settings(self.config_entry))

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_meter", "select_meter", "remove_meter", "gateway"],
        )

    async def async_step_add_meter(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input = meter_schema()(user_input)
            user_input, errors = normalize_text_fields(user_input)
            if errors:
                return self.async_show_form(
                    step_id="add_meter",
                    data_schema=meter_schema(user_input),
                    errors=errors,
                )
            settings = self.settings
            meter, error = await validate_meter(
                self.hass, settings, user_input, exclude=self.config_entry.entry_id
            )
            if error:
                errors["base"] = error
            else:
                settings["meters"].append(meter)
                return self.async_create_entry(title="", data=settings)
        return self.async_show_form(
            step_id="add_meter", data_schema=meter_schema(user_input), errors=errors
        )

    def selection_schema(self):
        return vol.Schema(
            {
                vol.Required("meter"): vol.In(
                    {
                        m["serial"]: f"{m['name']} (ID {m['unit_id']})"
                        for m in self.settings["meters"]
                    }
                )
            }
        )

    async def async_step_select_meter(self, user_input=None):
        if user_input is not None:
            self._editing = self.selection_schema()(user_input)["meter"]
            return await self.async_step_edit_meter()
        return self.async_show_form(
            step_id="select_meter", data_schema=self.selection_schema()
        )

    async def async_step_edit_meter(self, user_input=None):
        settings = self.settings
        previous = next(m for m in settings["meters"] if m["serial"] == self._editing)
        errors = {}
        if user_input is not None:
            user_input = meter_schema()(user_input)
            user_input, errors = normalize_text_fields(user_input)
            if errors:
                return self.async_show_form(
                    step_id="edit_meter",
                    data_schema=meter_schema(user_input),
                    errors=errors,
                )
            if user_input["unit_id"] == previous["unit_id"]:
                meter, error = {**previous, "name": user_input["name"]}, None
            else:
                meter, error = await validate_meter(
                    self.hass,
                    settings,
                    user_input,
                    exclude=self.config_entry.entry_id,
                    editing=self._editing,
                )
            if error:
                errors["base"] = error
            else:
                settings["meters"] = [
                    meter if m["serial"] == self._editing else m
                    for m in settings["meters"]
                ]
                return self.async_create_entry(title="", data=settings)
        return self.async_show_form(
            step_id="edit_meter",
            data_schema=meter_schema(user_input or previous),
            errors=errors,
        )

    async def async_step_remove_meter(self, user_input=None):
        if len(self.settings["meters"]) == 1:
            return self.async_abort(reason="last_meter")
        if user_input is not None:
            selected = self.selection_schema()(user_input)["meter"]
            settings = self.settings
            settings["meters"] = [
                m for m in settings["meters"] if m["serial"] != selected
            ]
            return self.async_create_entry(title="", data=settings)
        return self.async_show_form(
            step_id="remove_meter", data_schema=self.selection_schema()
        )

    async def async_step_gateway(self, user_input=None):
        errors = {}
        if user_input is not None:
            user_input = gateway_schema()(user_input)
            user_input, errors = normalize_text_fields(user_input)
            if errors:
                return self.async_show_form(
                    step_id="gateway",
                    data_schema=gateway_schema(user_input),
                    errors=errors,
                )
            if endpoint_in_use(self.hass, user_input, self.config_entry.entry_id):
                errors["base"] = "already_configured"
            elif user_input["energy_interval"] < user_input["scan_interval"]:
                errors["energy_interval"] = "invalid_interval"
            else:
                # Read-only identity checks on reload prevent misattributing another meter.
                return self.async_create_entry(
                    title="", data={**self.settings, **user_input}
                )
        return self.async_show_form(
            step_id="gateway",
            data_schema=gateway_schema(user_input or self.settings),
            errors=errors,
        )
