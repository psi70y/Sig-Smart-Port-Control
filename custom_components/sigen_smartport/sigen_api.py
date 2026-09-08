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
from datetime import datetime

import requests

_LOGGER = logging.getLogger(__name__)

# Fallback cache TTL if the login response ever omits expires_in.
# Sigen's actual tokens run ~12h (expires_in: 43199 observed) - we normally
# use that real value instead, minus _TOKEN_EXPIRY_BUFFER_SECONDS.
_TOKEN_TTL_SECONDS = 25 * 60

# Refresh a bit early rather than cutting it exactly at expiry, so a slow
# request doesn't land right on the boundary and get rejected mid-flight.
_TOKEN_EXPIRY_BUFFER_SECONDS = 5 * 60

# NOTE: an earlier version of this client explicitly called
# DELETE /auth/token/logout on the outgoing token before fetching a new one,
# intended to keep concurrent Sigen cloud sessions from piling up. In
# practice this caused the mySigen app/web portal to get logged out roughly
# once a day, strongly suggesting Sigen's logout endpoint isn't scoped to
# just the token you pass it. It was removed: at ~12h token caching, we
# only log in once or twice a day anyway, so old tokens are left to expire
# naturally server-side instead of being explicitly revoked.

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
                 auth_header, user_device_id, on_token_change=None):
        self._username = username
        self._password = password
        self._station_id = station_id
        self._load_path = load_path
        self._base_url = base_url
        self._auth_header = auth_header
        self._user_device_id = user_device_id

        # Called (access_token: str, expiry_epoch: float, refresh_token: str)
        # whenever a new token pair is issued, so the caller can persist it
        # to disk and survive restarts without forcing an extra login.
        # Optional - a storage failure here must never break authentication.
        self._on_token_change = on_token_change

        self._token = None
        self._token_expiry = 0.0  # wall-clock epoch seconds, NOT monotonic -
                                   # this needs to remain meaningful after a
                                   # process restart, when restored from disk.
        self._refresh_token = None

        # Last known state read from the cloud. None until first successful
        # poll. Consumers (switch/select entities) read this after calling
        # refresh().
        self.control_mode = None      # 0 = Auto (Sig Schedule), 1 = Manual
        self.manual_switch = None     # 0 = contactor open/off, 1 = closed/on
        self.available = False

    def restore_cached_token(self, token, expiry_epoch, refresh_token=None):
        """Reload a previously-persisted token (e.g. after a restart) so we
        don't force a fresh login unless it's actually expired."""
        if token and expiry_epoch and expiry_epoch > time.time():
            self._token = token
            self._token_expiry = expiry_epoch
            expiry_str = datetime.fromtimestamp(expiry_epoch).strftime("%Y-%m-%d %H:%M:%S")
            _LOGGER.info(
                "Sigen Smart Port: reused cached auth token from disk (valid until %s) - no fresh login needed",
                expiry_str,
            )
        # The refresh_token is restored independently of whether the access
        # token itself is still valid - it's what lets us renew gently
        # instead of falling back to a full password login after a restart.
        if refresh_token:
            self._refresh_token = refresh_token

    def _auth_headers(self):
        return {
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

    def _store_new_tokens(self, data):
        """Common handling for a successful /auth/oauth/token response,
        whichever grant type produced it."""
        token = data.get("access_token")
        if not token:
            return None

        self._token = token
        self._refresh_token = data.get("refresh_token", self._refresh_token)

        # Trust Sigen's own expiry when it's provided, minus a safety
        # buffer, instead of a hardcoded guess. Falls back to the
        # conservative default if the field is ever missing or malformed.
        expires_in = data.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > _TOKEN_EXPIRY_BUFFER_SECONDS:
            ttl = expires_in - _TOKEN_EXPIRY_BUFFER_SECONDS
        else:
            ttl = _TOKEN_TTL_SECONDS
        self._token_expiry = time.time() + ttl

        if self._on_token_change:
            try:
                self._on_token_change(self._token, self._token_expiry, self._refresh_token)
            except Exception as e:  # noqa: BLE001
                # Persisting the token is a nice-to-have; never let a
                # storage problem break a login that already succeeded.
                _LOGGER.debug("Could not persist Sigen token (non-fatal): %s", e)

        return token

    # ---------------------------------------------------------------- auth
    def _refresh_with_token(self):
        """Renew using the refresh_token grant - this is what Sigen's own
        mySigen app does near expiry, rather than a full password re-login.
        Returns the new access token, or None if the refresh_token itself
        was rejected (expired/invalid), in which case the caller should
        fall back to a full password login."""
        if not self._refresh_token:
            return None

        token_url = f"{self._base_url}/auth/oauth/token"
        payload = {
            "scope": "server",
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        try:
            response = requests.post(token_url, data=payload, headers=self._auth_headers(), timeout=10)
            if response.status_code == 200:
                body = response.json()
                if body.get("code") == 0:
                    token = self._store_new_tokens(body.get("data", {}))
                    if token:
                        expiry_str = datetime.fromtimestamp(self._token_expiry).strftime("%Y-%m-%d %H:%M:%S")
                        _LOGGER.info(
                            "Sigen Smart Port: renewed session via refresh token (valid until %s)",
                            expiry_str,
                        )
                        return token
            _LOGGER.debug("Sigen refresh_token grant rejected, will fall back to full login: %s", response.text)
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Exception during Sigen token refresh (will fall back to full login): %s", e)
        # A rejected/failed refresh means the refresh_token is no longer
        # usable - clear it so we don't keep retrying a dead token.
        self._refresh_token = None
        return None

    def _password_login(self):
        """Full password-grant login. Used only on first-ever setup or when
        a refresh_token isn't available/valid - Sigen's own app appears to
        treat this as a new sign-in, which is the behaviour suspected of
        forcing other active sessions (the mySigen app/web portal) to log
        out, so this is deliberately the fallback path, not the primary one."""
        token_url = f"{self._base_url}/auth/oauth/token"
        payload = {
            "scope": "server",
            "grant_type": "password",
            "userDeviceId": self._user_device_id,
            "username": self._username,
            "password": self._password,
        }
        try:
            response = requests.post(token_url, data=payload, headers=self._auth_headers(), timeout=10)
            if response.status_code == 200:
                body = response.json()
                if body.get("code") == 0:
                    token = self._store_new_tokens(body.get("data", {}))
                    if token:
                        expiry_str = datetime.fromtimestamp(self._token_expiry).strftime("%Y-%m-%d %H:%M:%S")
                        _LOGGER.info(
                            "Sigen Smart Port: logged in with a fresh password-grant token (valid until %s)",
                            expiry_str,
                        )
                        return token
            _LOGGER.error("Sigen auth failed or rejected: %s", response.text)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Exception during Sigen auth: %s", e)
        self._token = None
        self._token_expiry = 0.0
        return None

    def _fetch_token(self):
        """Get a new access token, preferring the gentle refresh_token grant
        (what Sigen's own app uses) and only falling back to a full
        password login if that's not possible."""
        token = self._refresh_with_token()
        if token:
            return token
        return self._password_login()

    def _get_token(self, force=False):
        if force or self._token is None or time.time() >= self._token_expiry:
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
