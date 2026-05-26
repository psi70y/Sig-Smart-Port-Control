import logging
import requests
import json
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.switch import SwitchEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

DOMAIN = "sigen_smartport"
CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_BASE_URL = "base_url"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"

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

    def token_fetcher():
        token_url = f"{base_url}/auth/oauth/token"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0",
            "accept": "*/*",
            "auth-client-id": "sigen",
            "authorization": auth_header,
            "client-server": "aus",
            "lang": "en_US",
            "origin": "https://app-aus.sigencloud.com",
            "referer": "https://app-aus.sigencloud.com/",
            "sg-bui": "1",
            "sg-env": "1",
            "sg-pkg": "sigen_app",
            "version": "RELEASE"
        }
        payload = {
            "scope": "server",
            "grant_type": "password",
            "userDeviceId": user_device_id,
            "username": username,
            "password": password
        }
        try:
            response = requests.post(token_url, data=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                response_json = response.json()
                if response_json.get("code") == 0:
                    return response_json.get("data", {}).get("access_token")
            _LOGGER.error(f"Sigen Switch Auth failed or rejected: {response.text}")
            return None
        except Exception as e:
            _LOGGER.error(f"Exception during switch authorization loop: {e}")
            return None

    add_entities([SigenSmartPortControlSwitch(name, station_id, load_path, base_url, token_fetcher)], True)


class SigenSmartPortControlSwitch(SwitchEntity):
    """Controls manual output power state (On/Off)."""

    def __init__(self, name, station_id, load_path, base_url, token_fetcher):
        self._name = name
        self._station_id = station_id
        self._load_path = load_path
        self._base_url = base_url
        self._token_fetcher = token_fetcher
        self._state = False
        self._unique_id = f"sigen_smartport_{station_id}_load_{load_path}_switch"
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"

    @property
    def name(self): return self._name
    @property
    def is_on(self): return self._state
    @property
    def unique_id(self): return self._unique_id

    def turn_on(self, **kwargs):
        token = self._token_fetcher()
        if not token: return
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode/manual/switch"
        params = {"stationId": self._station_id, "loadPath": self._load_path, "manualSwitch": 1}
        try:
            res = requests.patch(url, params=params, headers=self._get_headers(token), timeout=10)
            if res.status_code == 200:
                self._state = True
                self.schedule_update_ha_state()
        except Exception as e: _LOGGER.error(f"Error turning on switch: {e}")

    def turn_off(self, **kwargs):
        token = self._token_fetcher()
        if not token: return
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode/manual/switch"
        params = {"stationId": self._station_id, "loadPath": self._load_path, "manualSwitch": 0}
        try:
            res = requests.patch(url, params=params, headers=self._get_headers(token), timeout=10)
            if res.status_code == 200:
                self._state = False
                self.schedule_update_ha_state()
        except Exception as e: _LOGGER.error(f"Error turning off switch: {e}")

    def _get_headers(self, token):
        return {
            "User-Agent": self._user_agent, "accept": "*/*", "auth-client-id": "sigen",
            "authorization": f"bearer {token}", "client-server": "aus", "lang": "en_US",
            "origin": "https://app-aus.sigencloud.com", "referer": "https://app-aus.sigencloud.com/",
            "sg-bui": "1", "sg-env": "1", "sg-pkg": "sigen_app", "sg-platform": "web",
            "version": "RELEASE", "Content-Type": "application/json; charset=utf-8"
        }
