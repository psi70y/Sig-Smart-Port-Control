"""Config flow for Sigenergy Smart Port."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_STATION_ID,
    CONF_LOAD_PATH,
    CONF_BASE_URL,
    CONF_AUTH_HEADER,
    CONF_USER_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_AUTH_HEADER,
    DEFAULT_USER_DEVICE_ID,
    DEFAULT_LOAD_PATH,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .sigen_api import SigenSmartLoadClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required(CONF_STATION_ID): str,
    vol.Optional(CONF_LOAD_PATH, default=DEFAULT_LOAD_PATH): str,
    vol.Optional(CONF_NAME, default="Sigen Smart Load"): str,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
        vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
})

# Advanced/rarely-changed fields, kept out of the main form so the common
# path (one station, default region endpoint) stays a 3-field wizard.
STEP_ADVANCED_SCHEMA = vol.Schema({
    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    vol.Optional(CONF_AUTH_HEADER, default=DEFAULT_AUTH_HEADER): str,
    vol.Optional(CONF_USER_DEVICE_ID, default=DEFAULT_USER_DEVICE_ID): str,
})


class CannotConnect(HomeAssistantError):
    """Raised when we can't reach or authenticate against the Sigen cloud."""


async def _validate_login(hass: HomeAssistant, data: dict) -> None:
    """Attempt a real login + one status read to confirm the credentials work."""
    client = SigenSmartLoadClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_STATION_ID],
        data[CONF_LOAD_PATH],
        data[CONF_BASE_URL],
        data[CONF_AUTH_HEADER],
        data[CONF_USER_DEVICE_ID],
    )
    ok = await hass.async_add_executor_job(client.refresh)
    if not ok:
        raise CannotConnect


class SigenSmartPortConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the setup wizard for a single Smart Port load."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_input = dict(user_input)
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_advanced(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**self._user_input, **user_input}

            # One entry per station_id + load_path, so re-adding the same
            # physical Smart Port load is blocked, but adding a second load
            # on the same station (e.g. hot water heater + pool pump) is a
            # normal "Add another device" flow using the same integration.
            unique_id = f"{data[CONF_STATION_ID]}_{data[CONF_LOAD_PATH]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _validate_login(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="advanced", data_schema=STEP_ADVANCED_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SigenSmartPortOptionsFlow(config_entry)


class SigenSmartPortOptionsFlow(config_entries.OptionsFlow):
    """Lets the poll interval be changed later via 'Configure' without
    deleting and re-adding the device."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        schema = vol.Schema({
            vol.Optional(CONF_SCAN_INTERVAL, default=current):
                vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
