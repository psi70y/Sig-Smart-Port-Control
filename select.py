import logging
import requests
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.components.select import SelectEntity, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_USERNAME, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

DOMAIN = "sigen_smartport"
CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_BASE_URL = "base_url"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"

MODE_AUTO = "Auto (Sig Schedule)"
MODE_MANUAL = "Manual"

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
                res_json = response.json()
                if res_json.get("code") == 0:
                    return res_json.get("data", {}).get("access_token")
            _LOGGER.error(f"Sigen Selector Auth failed or rejected: {response.text}")
            return None
        except Exception as e:
            _LOGGER.error(f"Exception fetching selector token: {e}")
            return None

    add_entities([SigenSmartPortModeSelector(name, station_id, load_path, base_url, token_fetcher)], True)


class SigenSmartPortModeSelector(SelectEntity):
    """Drop-down mode option mapping for Sigen Smart Port."""

    def __init__(self, name, station_id, load_path, base_url, token_fetcher):
        self._name = name
        self._station_id = station_id
        self._load_path = load_path
        self._base_url = base_url
        self._token_fetcher = token_fetcher
        self._current_option = MODE_AUTO
        self._unique_id = f"sigen_smartport_{station_id}_load_{load_path}_mode_select"
        self._user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"

    @property
    def name(self): return self._name
    @property
    def unique_id(self): return self._unique_id
    @property
    def options(self): return [MODE_AUTO, MODE_MANUAL]
    @property
    def current_option(self): return self._current_option

    def select_option(self, option: str) -> None:
        token = self._token_fetcher()
        if not token: return

        mode_val = 1 if option == MODE_MANUAL else 0
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode"
        params = {"stationId": self._station_id, "loadPath": self._load_path, "controlMode": mode_val}
        
        headers = {
            "User-Agent": self._user_agent, "accept": "*/*", "auth-client-id": "sigen",
            "authorization": f"bearer {token}", "client-server": "aus", "lang": "en_US",
            "origin": "https://app-aus.sigencloud.com", "referer": "https://app-aus.sigencloud.com/",
            "sg-bui": "1", "sg-env": "1", "sg-pkg": "sigen_app", "sg-platform": "web",
            "version": "RELEASE", "Content-Type": "application/json; charset=utf-8"
        }

        try:
            res = requests.patch(url, params=params, headers=headers, timeout=10)
            if res.status_code == 200:
                self._current_option = option
                self.schedule_update_ha_state()
                _LOGGER.info(f"Changed Sigen operational control mode context to: {option}")
        except Exception as e:
            _LOGGER.error(f"Error handling mode selector patch transaction: {e}")
