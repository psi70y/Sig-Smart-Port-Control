import logging
from datetime import timedelta

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.select import SelectEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD

from .sigen_api import get_client

_LOGGER = logging.getLogger(__name__)

DOMAIN = "sigen_smartport"

CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_BASE_URL = "base_url"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"

MODE_AUTO = "Auto (Sig Schedule)"
MODE_MANUAL = "Manual"

# How often HA polls the Sigen cloud for the real state. 3600 seconds = 1 hour
SCAN_INTERVAL = timedelta(seconds=3600)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_STATION_ID): cv.string,
    vol.Optional(CONF_LOAD_PATH, default="1"): cv.string,
    vol.Optional(CONF_NAME, default="Sigen Smart Load Mode"): cv.string,
    vol.Optional(CONF_BASE_URL, default="https://api-aus.sigencloud.com"): cv.string,
    vol.Optional(CONF_AUTH_HEADER, default="Basic c2lnZW46c2lnZW4="): cv.string,
    vol.Optional(CONF_USER_DEVICE_ID, default="1770954624439"): cv.string,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Sigenergy drop-down select platform."""
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    station_id = config.get(CONF_STATION_ID)
    load_path = config.get(CONF_LOAD_PATH)
    name = config.get(CONF_NAME)
    base_url = config.get(CONF_BASE_URL)
    auth_header = config.get(CONF_AUTH_HEADER)
    user_device_id = config.get(CONF_USER_DEVICE_ID)

    client = get_client(username, password, station_id, load_path, base_url,
                         auth_header, user_device_id)

    add_entities([SigenSmartPortModeSelector(name, station_id, load_path, client)], True)


class SigenSmartPortModeSelector(SelectEntity):
    """Drop-down mode selector, synced with Sigen cloud state."""

    def __init__(self, name, station_id, load_path, client):
        self._name = name
        self._station_id = station_id
        self._load_path = load_path
        self._client = client
        self._unique_id = f"sigen_smartport_{station_id}_load_{load_path}_mode_select"

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def available(self):
        return self._client.available

    @property
    def options(self):
        return [MODE_AUTO, MODE_MANUAL]

    @property
    def current_option(self):
        if self._client.control_mode == 1:
            return MODE_MANUAL
        return MODE_AUTO

    def update(self):
        """Poll the Sigen cloud for the real control mode."""
        self._client.refresh()

    def select_option(self, option: str) -> None:
        manual = option == MODE_MANUAL
        if self._client.set_control_mode(manual):
            self.schedule_update_ha_state()
            _LOGGER.info("Changed Sigen operational control mode to: %s", option)
