"""Shared Sigenergy Smart Port API client.

Handles token caching and the three known cloud calls:
  - GET   .../control-mode              -> read current switch + mode state
  - PATCH .../control-mode/manual/switch -> set contactor on/off
  - PATCH .../control-mode               -> set Auto/Manual mode

One client instance is shared (cached) per station_id + load_path so the
switch and select entities poll the cloud together and reuse a single token,
instead of each entity managing its own state and re-authenticating on every
action.
"""

import logging
import time

import requests

_LOGGER = logging.getLogger(__name__)

# Cache token for 25 minutes; refreshed sooner on demand if a call fails auth.
_TOKEN_TTL_SECONDS = 25 * 60

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)

# Module-level cache so switch.py and select.py share one client
# (and therefore one token + one polled state) per station/load combo.
_CLIENTS = {}


def get_client(username, password, station_id, load_path, base_url,
                auth_header, user_device_id):
    """Return a shared client instance for this station/load combination."""
    key = (base_url, station_id, load_path, username)
    client = _CLIENTS.get(key)
    if client is None:
        client = SigenSmartLoadClient(
            username, password, station_id, load_path, base_url,
            auth_header, user_device_id,
        )
        _CLIENTS[key] = client
    return client


class SigenSmartLoadClient:
    """Wraps auth + read/write calls for a single Smart Port load."""

    def __init__(self, username, password, station_id, load_path, base_url,
                 auth_header, user_device_id):
        self._username = username
        self._password = password
        self._station_id = station_id
        self._load_path = load_path
        self._base_url = base_url
        self._auth_header = auth_header
        self._user_device_id = user_device_id

        self._token = None
        self._token_expiry = 0.0

        # Last known state read from the cloud. None until first successful
        # poll. Consumers (switch/select entities) read this after calling
        # refresh().
        self.control_mode = None      # 0 = Auto (Sig Schedule), 1 = Manual
        self.manual_switch = None     # 0 = contactor open/off, 1 = closed/on
        self.available = False

    # ---------------------------------------------------------------- auth
    def _fetch_token(self):
        token_url = f"{self._base_url}/auth/oauth/token"
        headers = {
            "User-Agent": _USER_AGENT,
            "accept": "*/*",
            "auth-client-id": "sigen",
            "authorization": self._auth_header,
            "client-server": "aus",
            "lang": "en_US",
            "origin": "https://app-aus.sigencloud.com",
            "referer": "https://app-aus.sigencloud.com/",
            "sg-bui": "1",
            "sg-env": "1",
            "sg-pkg": "sigen_app",
            "version": "RELEASE",
        }
        payload = {
            "scope": "server",
            "grant_type": "password",
            "userDeviceId": self._user_device_id,
            "username": self._username,
            "password": self._password,
        }
        try:
            response = requests.post(token_url, data=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                body = response.json()
                if body.get("code") == 0:
                    token = body.get("data", {}).get("access_token")
                    if token:
                        self._token = token
                        self._token_expiry = time.monotonic() + _TOKEN_TTL_SECONDS
                        return token
            _LOGGER.error("Sigen auth failed or rejected: %s", response.text)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception during Sigen auth: %s", e)
        self._token = None
        self._token_expiry = 0.0
        return None

    def _get_token(self, force=False):
        if force or self._token is None or time.monotonic() >= self._token_expiry:
            return self._fetch_token()
        return self._token

    def _headers(self, token):
        return {
            "User-Agent": _USER_AGENT,
            "accept": "*/*",
            "auth-client-id": "sigen",
            "authorization": f"bearer {token}",
            "client-server": "aus",
            "lang": "en_US",
            "origin": "https://app-aus.sigencloud.com",
            "referer": "https://app-aus.sigencloud.com/",
            "sg-bui": "1",
            "sg-env": "1",
            "sg-pkg": "sigen_app",
            "sg-platform": "web",
            "version": "RELEASE",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _request(self, method, url, params):
        """Issue a request, retrying once with a fresh token on auth failure."""
        for attempt in (False, True):
            token = self._get_token(force=attempt)
            if not token:
                return None
            try:
                res = requests.request(
                    method, url, params=params, headers=self._headers(token), timeout=10
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Exception during Sigen %s %s: %s", method, url, e)
                return None

            if res.status_code == 401:
                # Token stale/rejected - retry once with a forced refresh.
                continue

            return res
        return None

    # ---------------------------------------------------------------- calls
    def refresh(self):
        """Read current control mode + manual switch state from the cloud."""
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode"
        params = {"stationId": self._station_id, "loadPath": self._load_path}
        res = self._request("GET", url, params)
        if res is None:
            self.available = False
            return False

        if res.status_code != 200:
            _LOGGER.error("Sigen status read failed: HTTP %s - %s", res.status_code, res.text)
            self.available = False
            return False

        try:
            body = res.json()
        except ValueError:
            _LOGGER.error("Sigen status read returned non-JSON: %s", res.text)
            self.available = False
            return False

        if body.get("code") != 0:
            _LOGGER.error("Sigen status read rejected: %s", body)
            self.available = False
            return False

        data = body.get("data", {})
        self.control_mode = data.get("controlMode")
        self.manual_switch = data.get("manualModeSwitch")
        self.available = True
        return True

    def set_manual_switch(self, on: bool):
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode/manual/switch"
        params = {
            "stationId": self._station_id,
            "loadPath": self._load_path,
            "manualSwitch": 1 if on else 0,
        }
        res = self._request("PATCH", url, params)
        if res is not None and res.status_code == 200:
            self.manual_switch = 1 if on else 0
            return True
        _LOGGER.error("Error setting Sigen manual switch: %s", res.text if res else "no response")
        return False

    def set_control_mode(self, manual: bool):
        url = f"{self._base_url}/device/tp-device/smart-loads/control-mode"
        params = {
            "stationId": self._station_id,
            "loadPath": self._load_path,
            "controlMode": 1 if manual else 0,
        }
        res = self._request("PATCH", url, params)
        if res is not None and res.status_code == 200:
            self.control_mode = 1 if manual else 0
            return True
        _LOGGER.error("Error setting Sigen control mode: %s", res.text if res else "no response")
        return False
