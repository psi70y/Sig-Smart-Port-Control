import logging
from datetime import timedelta

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.switch import SwitchEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD

from .sigen_api import get_client

_LOGGER = logging.getLogger(__name__)

DOMAIN = "sigen_smartport"

CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_BASE_URL = "base_url"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"

# How often HA polls the Sigen cloud for the real state. 600 seconds = 10 minutes
SCAN_INTERVAL = timedelta(seconds=600)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_STATION_ID): cv.string,
    vol.Optional(CONF_LOAD_PATH, default="1"): cv.string,
    vol.Optional(CONF_NAME, default="Sigen Smart Load"): cv.string,
    vol.Optional(CONF_BASE_URL, default="https://api-aus.sigencloud.com"): cv.string,
    vol.Optional(CONF_AUTH_HEADER, default="Basic c2lnZW46c2lnZW4="): cv.string,
    vol.Optional(CONF_USER_DEVICE_ID, default="1770954624439"): cv.string,
})


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the Sigenergy power switch platform."""
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

    add_entities([SigenSmartPortControlSwitch(name, station_id, load_path, client)], True)


class SigenSmartPortControlSwitch(SwitchEntity):
    """Controls and reflects the manual output power state (On/Off)."""

    def __init__(self, name, station_id, load_path, client):
        self._name = name
        self._station_id = station_id
        self._load_path = load_path
        self._client = client
        self._unique_id = f"sigen_smartport_{station_id}_load_{load_path}_switch"

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
    def is_on(self):
        return bool(self._client.manual_switch)

    def update(self):
        """Poll the Sigen cloud for the real contactor state."""
        self._client.refresh()

    def turn_on(self, **kwargs):
        if self._client.set_manual_switch(True):
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        if self._client.set_manual_switch(False):
            self.schedule_update_ha_state()
