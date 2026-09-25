"""Config flow for Sigenergy Smart Port + AC Charger."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_DEVICE_KIND,
    DEVICE_KIND_SMART_PORT,
    DEVICE_KIND_AC_CHARGER,
    CONF_STATION_ID,
    CONF_LOAD_PATH,
    CONF_CHARGER_SN,
    CONF_BASE_URL,
    CONF_REGION,
    CONF_AUTH_HEADER,
    CONF_USER_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_PROFILE_REFRESH_DAYS,
    DEFAULT_BASE_URL,
    DEFAULT_AUTH_HEADER,
    DEFAULT_USER_DEVICE_ID,
    DEFAULT_LOAD_PATH,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PROFILE_REFRESH_DAYS,
    DEFAULT_REGION,
    MIN_SCAN_INTERVAL,
    MIN_PROFILE_REFRESH_DAYS,
    REGION_BASE_URLS,
    REGION_CHOICES,
    CUSTOM_REGION,
)
from .sigen_api import SigenSmartLoadClient, SigenAcChargerClient

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------- Smart Port
STEP_SMART_PORT_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required(CONF_STATION_ID): str,
    vol.Optional(CONF_REGION, default=DEFAULT_REGION): vol.In(REGION_CHOICES),
    vol.Optional(CONF_LOAD_PATH, default=DEFAULT_LOAD_PATH): str,
    vol.Optional(CONF_NAME, default="Sigen Smart Load"): str,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
        vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
})

# Advanced/rarely-changed fields, kept out of the main form so the common
# path (one station, pick your region) stays a compact wizard. base_url
# here is only actually used when region is set to "Custom" above - for
# any known region it's overwritten with that region's real endpoint
# before the entry is saved (see _resolve_base_url).
STEP_SMART_PORT_ADVANCED_SCHEMA = vol.Schema({
    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    vol.Optional(CONF_AUTH_HEADER, default=DEFAULT_AUTH_HEADER): str,
    vol.Optional(CONF_USER_DEVICE_ID, default=DEFAULT_USER_DEVICE_ID): str,
    vol.Optional(CONF_PROFILE_REFRESH_DAYS, default=DEFAULT_PROFILE_REFRESH_DAYS):
        vol.All(vol.Coerce(int), vol.Range(min=MIN_PROFILE_REFRESH_DAYS)),
})

# ---------------------------------------------------------------- AC Charger
# Username/password may be left blank when a Smart Port entry for the same
# station already exists - its stored credentials are reused (see
# _credentials_from_existing_entry), so they don't have to be captured twice.
STEP_AC_CHARGER_SCHEMA = vol.Schema({
    vol.Optional(CONF_USERNAME): str,
    vol.Optional(CONF_PASSWORD): str,
    vol.Required(CONF_STATION_ID): str,
    vol.Optional(CONF_REGION, default=DEFAULT_REGION): vol.In(REGION_CHOICES),
    vol.Required(CONF_CHARGER_SN): str,
    vol.Optional(CONF_NAME, default="Sigen AC Charger"): str,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL):
        vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
})

# No profile_refresh_days here - that setting is specific to Smart Port's
# Energy Profile feature, which an AC Charger entry has nothing to do with.
STEP_AC_CHARGER_ADVANCED_SCHEMA = vol.Schema({
    vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    vol.Optional(CONF_AUTH_HEADER, default=DEFAULT_AUTH_HEADER): str,
    vol.Optional(CONF_USER_DEVICE_ID, default=DEFAULT_USER_DEVICE_ID): str,
})


def _resolve_base_url(data: dict) -> dict:
    """Overwrite base_url with the selected region's real endpoint, unless
    the region is explicitly set to Custom (in which case whatever was
    typed into the Advanced step's base_url field is used as-is)."""
    region = data.get(CONF_REGION, DEFAULT_REGION)
    if region != CUSTOM_REGION and region in REGION_BASE_URLS:
        data[CONF_BASE_URL] = REGION_BASE_URLS[region]
    return data


class CannotConnect(HomeAssistantError):
    """Raised when we can't reach or authenticate against the Sigen cloud."""


async def _validate_smart_port_login(hass: HomeAssistant, data: dict) -> None:
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


async def _validate_ac_charger_login(hass: HomeAssistant, data: dict) -> None:
    """Attempt a real login + one status read to confirm the credentials work."""
    client = SigenAcChargerClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_STATION_ID],
        data[CONF_CHARGER_SN],
        data[CONF_BASE_URL],
        data[CONF_AUTH_HEADER],
        data[CONF_USER_DEVICE_ID],
    )
    ok = await hass.async_add_executor_job(client.refresh)
    if not ok:
        raise CannotConnect


class SigenSmartPortConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the setup wizard - Smart Port Load or AC Charger."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """First step: choose which kind of device to add."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["smart_port", "ac_charger"],
        )

    # --------------------------------------------------------- Smart Port
    async def async_step_smart_port(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_input = dict(user_input)
            self._user_input[CONF_DEVICE_KIND] = DEVICE_KIND_SMART_PORT
            return await self.async_step_smart_port_advanced()

        return self.async_show_form(
            step_id="smart_port", data_schema=STEP_SMART_PORT_SCHEMA, errors=errors
        )

    async def async_step_smart_port_advanced(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**self._user_input, **user_input}
            data = _resolve_base_url(data)

            # One entry per station_id + load_path, so re-adding the same
            # physical Smart Port load is blocked, but adding a second load
            # on the same station (e.g. hot water heater + pool pump) is a
            # normal "Add another device" flow using the same integration.
            unique_id = f"{data[CONF_STATION_ID]}_{data[CONF_LOAD_PATH]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _validate_smart_port_login(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="smart_port_advanced", data_schema=STEP_SMART_PORT_ADVANCED_SCHEMA, errors=errors
        )

    # --------------------------------------------------------- AC Charger
    def _credentials_from_existing_entry(self, station_id: str) -> dict | None:
        """Username/password from an existing entry on the same station, so an
        AC charger can be added without re-capturing the encoded password."""
        for entry in self._async_current_entries(include_ignore=False):
            data = entry.data
            if (str(data.get(CONF_STATION_ID)) == str(station_id)
                    and data.get(CONF_USERNAME) and data.get(CONF_PASSWORD)):
                return {CONF_USERNAME: data[CONF_USERNAME], CONF_PASSWORD: data[CONF_PASSWORD]}
        return None

    async def async_step_ac_charger(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = dict(user_input)
            if not user_input.get(CONF_USERNAME) or not user_input.get(CONF_PASSWORD):
                existing = self._credentials_from_existing_entry(user_input[CONF_STATION_ID])
                if existing:
                    user_input.update(existing)
                else:
                    errors["base"] = "missing_credentials"
            if not errors:
                self._user_input = user_input
                self._user_input[CONF_DEVICE_KIND] = DEVICE_KIND_AC_CHARGER
                return await self.async_step_ac_charger_advanced()

        return self.async_show_form(
            step_id="ac_charger", data_schema=STEP_AC_CHARGER_SCHEMA, errors=errors
        )

    async def async_step_ac_charger_advanced(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**self._user_input, **user_input}
            data = _resolve_base_url(data)

            # Separate unique_id namespace (ac_ prefix) from Smart Port
            # loads, keyed by charger serial rather than load_path - an AC
            # charger and a Smart Port load on the same station are always
            # distinct entries even if someone reused a matching identifier.
            unique_id = f"ac_{data[CONF_STATION_ID]}_{data[CONF_CHARGER_SN]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _validate_ac_charger_login(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="ac_charger_advanced", data_schema=STEP_AC_CHARGER_ADVANCED_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return SigenSmartPortOptionsFlow(config_entry)


class SigenSmartPortOptionsFlow(config_entries.OptionsFlow):
    """Lets region/poll interval/etc be changed later via 'Configure'
    without deleting and re-adding the device."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=_resolve_base_url(dict(user_input)))

        entry = self._config_entry
        is_ac_charger = entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER

        current_region = entry.options.get(CONF_REGION, entry.data.get(CONF_REGION, DEFAULT_REGION))
        current_base_url = entry.options.get(CONF_BASE_URL, entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL))
        current_scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )

        schema_dict = {
            vol.Optional(CONF_REGION, default=current_region): vol.In(REGION_CHOICES),
            vol.Optional(CONF_BASE_URL, default=current_base_url): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=current_scan_interval):
                vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL)),
        }

        # Energy Profile refresh interval only applies to Smart Port entries.
        if not is_ac_charger:
            current_profile_refresh_days = entry.options.get(
                CONF_PROFILE_REFRESH_DAYS,
                entry.data.get(CONF_PROFILE_REFRESH_DAYS, DEFAULT_PROFILE_REFRESH_DAYS),
            )
            schema_dict[vol.Optional(CONF_PROFILE_REFRESH_DAYS, default=current_profile_refresh_days)] = (
                vol.All(vol.Coerce(int), vol.Range(min=MIN_PROFILE_REFRESH_DAYS))
            )

        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema_dict))
