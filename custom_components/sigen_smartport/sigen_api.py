"""Shared Sigenergy Cloud API clients.

_SigenBaseClient holds everything common to any Sigen device: token
caching, the refresh_token-preferred renewal flow, and the low-level
authenticated request helper. Two concrete clients build on it:

  - SigenSmartLoadClient: Smart Port load control/mode + Energy Profile
    GET   .../control-mode                 -> read switch + mode state
    PATCH .../control-mode/manual/switch   -> set contactor on/off
    PATCH .../control-mode                 -> set Auto/Manual mode
    GET/PUT .../energy-profile/mode/...    -> station-wide operation mode

  - SigenAcChargerClient: AC EV charger status + charging mode
    GET  .../acevse/charge/status          -> plug/charge status code
    GET  .../acevse/charge/read/current    -> live charge current
    GET/POST .../charge/mode/ac            -> charging mode (Fast/PV Surplus)
    GET  .../data-process/acevse/energy    -> energy totals

Each config entry (one Smart Port load, or one AC charger) gets its own
client instance with its own token cache, so a restart or a token refresh
on one entry never affects another.
"""

import logging
import threading
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


class _SigenBaseClient:
    """Auth + low-level request handling shared by every Sigen client."""

    def __init__(self, username, password, station_id, base_url,
                 auth_header, user_device_id, on_token_change=None):
        self._username = username
        self._password = password
        self._station_id = station_id
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
                _LOGGER.debug("Could not persist Sigen token (non-fatal): %s", e)

        return token

    # ---------------------------------------------------------------- auth
    def _refresh_with_token(self):
        """Renew using the refresh_token grant - what Sigen's own app does
        near expiry, rather than a full password re-login."""
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
        self._refresh_token = None
        return None

    def _password_login(self):
        """Full password-grant login - fallback path only, see module docstring."""
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

    def _request(self, method, url, params=None, json_body=None):
        """Issue a request, retrying once with a fresh token on auth failure."""
        for attempt in (False, True):
            token = self._get_token(force=attempt)
            if not token:
                return None
            try:
                res = requests.request(
                    method, url, params=params, json=json_body,
                    headers=self._headers(token), timeout=10
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Exception during Sigen %s %s: %s", method, url, e)
                return None

            # The cloud answers an expired/revoked token with HTTP 424 and
            # code 1, msg "user credentials expired" (in Chinese) - seen in
            # practice - so treat it like 401 and retry with a new token.
            if res.status_code in (401, 424):
                continue

            return res
        return None


class SigenSmartLoadClient(_SigenBaseClient):
    """Wraps read/write calls for a single Smart Port load, plus its
    station's Energy Profile."""

    def __init__(self, username, password, station_id, load_path, base_url,
                 auth_header, user_device_id, on_token_change=None):
        super().__init__(username, password, station_id, base_url,
                          auth_header, user_device_id, on_token_change)
        self._load_path = load_path

        self.control_mode = None      # 0 = Auto (Sig Schedule), 1 = Manual
        self.manual_switch = None     # 0 = contactor open/off, 1 = closed/on

        self.profile_options = []     # list of (label, mode, profile_id)
        self.profile_options_fetched_at = None
        self.current_energy_mode = None
        self.current_profile_id = None

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

    # ------------------------------------------------------ energy profile
    def fetch_profile_options(self):
        """Fetch the list of selectable modes/profiles. Called once at setup
        rather than every poll, since this rarely changes."""
        url = f"{self._base_url}/device/energy-profile/mode/all/{self._station_id}"
        res = self._request("GET", url)
        if res is None or res.status_code != 200:
            _LOGGER.error("Sigen profile options read failed: %s", res.text if res else "no response")
            return False
        try:
            body = res.json()
        except ValueError:
            _LOGGER.error("Sigen profile options read returned non-JSON: %s", res.text)
            return False
        if body.get("code") != 0:
            _LOGGER.error("Sigen profile options read rejected: %s", body)
            return False

        data = body.get("data", {})
        options = []
        for item in data.get("defaultWorkingModes", []):
            label = item.get("label")
            try:
                mode = int(item.get("value"))
            except (TypeError, ValueError):
                continue
            if label:
                options.append((label, mode, -1))
        for item in data.get("energyProfileItems", []):
            label = item.get("name")
            profile_id = item.get("profileId")
            if label and profile_id is not None:
                options.append((label, 9, profile_id))

        self.profile_options = options
        self.profile_options_fetched_at = time.time()
        return True

    def fetch_current_profile(self):
        """Read which mode/profile is currently active."""
        url = f"{self._base_url}/device/energy-profile/mode/current/{self._station_id}"
        res = self._request("GET", url)
        if res is None or res.status_code != 200:
            _LOGGER.debug("Sigen current profile read failed: %s", res.text if res else "no response")
            return False
        try:
            body = res.json()
        except ValueError:
            return False
        if body.get("code") != 0:
            return False

        data = body.get("data", {})
        self.current_energy_mode = data.get("currentMode")
        self.current_profile_id = data.get("currentProfileId")
        return True

    def set_profile(self, mode: int, profile_id: int):
        """Switch to a built-in mode (profile_id=-1) or one of the user's
        saved custom profiles (mode=9, profile_id=<their profile's id>)."""
        url = f"{self._base_url}/device/energy-profile/mode"
        body = {
            "stationId": int(self._station_id),
            "operationMode": mode,
            "profileId": profile_id,
            "fromPlatform": 1,
        }
        res = self._request("PUT", url, json_body=body)
        if res is not None and res.status_code == 200:
            try:
                ok = res.json().get("data") is True
            except ValueError:
                ok = False
            if ok:
                self.current_energy_mode = mode
                self.current_profile_id = profile_id
                return True
        _LOGGER.error("Error setting Sigen energy profile: %s", res.text if res else "no response")
        return False


class SigenAcChargerClient(_SigenBaseClient):
    """Wraps read/write calls for a single AC EV charger.

    Endpoints confirmed by network capture against a Sigen EVAC 22 4G T2 WH
    (EU region) - see EV_CHARGING_DEVELOPMENT.md for the full capture log
    and what remains unconfirmed (Sigen AI Mode's write value, the full
    charge/status enum beyond 0="not plugged in").
    """

    def __init__(self, username, password, station_id, charger_sn, base_url,
                 auth_header, user_device_id, on_token_change=None):
        super().__init__(username, password, station_id, base_url,
                          auth_header, user_device_id, on_token_change)
        self._charger_sn = charger_sn

        self.charge_status_code = None
        self.charge_mode = None       # 0=Fast Charging, 1=PV Surplus, (2=Sigen AI, unconfirmed)
        self.charge_mode_settings = {}  # full /device/charge/mode/ac payload (Battery Boost, grid charging, ...)
        self.last_grid_power = None   # last non-zero maxPowerFromGrid, reused when Grid Charging is re-enabled
        # Each settings write sends the full payload, so concurrent writes
        # (e.g. two automations) would overwrite each other - serialise them.
        self._settings_lock = threading.Lock()
        self.last_set_current = None  # amps
        self.max_current = None       # amps
        self.monthly_energy = None    # kWh
        self.weekly_energy = None     # kWh
        self.lifetime_energy = None   # kWh

    def _params(self, **extra):
        params = {"stationId": self._station_id, "snCode": self._charger_sn}
        params.update(extra)
        return params

    def refresh(self):
        """Read all AC charger telemetry + settings in one poll cycle.

        Each sub-read is independent - a hiccup on one (e.g. the energy
        totals endpoint) doesn't block the others from updating, and
        doesn't mark the whole device unavailable. Only a hard failure of
        the primary status read does that.
        """
        status_ok = self._fetch_charge_status()
        self.available = status_ok
        if not status_ok:
            return False

        self._fetch_charge_current()
        self._fetch_charge_mode()
        self._fetch_energy_totals()
        return True

    def _fetch_charge_status(self):
        url = f"{self._base_url}/device/acevse/charge/status"
        res = self._request("GET", url, self._params())
        if res is None or res.status_code != 200:
            _LOGGER.error("Sigen AC charger status read failed: %s", res.text if res else "no response")
            return False
        try:
            body = res.json()
        except ValueError:
            _LOGGER.error("Sigen AC charger status read returned non-JSON: %s", res.text)
            return False
        if body.get("code") != 0:
            _LOGGER.error("Sigen AC charger status read rejected: %s", body)
            return False
        self.charge_status_code = body.get("data")
        return True

    def _fetch_charge_current(self):
        url = f"{self._base_url}/device/acevse/charge/read/current"
        res = self._request("GET", url, self._params())
        if res is None or res.status_code != 200:
            _LOGGER.debug("Sigen AC charger current read failed: %s", res.text if res else "no response")
            return
        try:
            data = res.json().get("data", {}) or {}
        except ValueError:
            return
        self.last_set_current = data.get("lastSetCurrent")
        self.max_current = data.get("maxCurrent")

    def _fetch_charge_mode(self):
        # Read from /device/charge/mode/ac, NOT /device/acevse/charge/mode -
        # the two endpoints use different, non-matching chargeMode enums
        # for a same-looking field name. This is the one that matches the
        # write endpoint below. See EV_CHARGING_DEVELOPMENT.md Section 10.
        url = f"{self._base_url}/device/charge/mode/ac"
        res = self._request("GET", url, self._params())
        if res is None or res.status_code != 200:
            _LOGGER.debug("Sigen AC charger mode read failed: %s", res.text if res else "no response")
            return
        try:
            data = res.json().get("data", {}) or {}
        except ValueError:
            return
        self.charge_mode = data.get("chargeMode")
        self.charge_mode_settings = data
        if data.get("maxPowerFromGrid"):
            self.last_grid_power = data["maxPowerFromGrid"]

    def _fetch_energy_totals(self):
        url = f"{self._base_url}/data-process/acevse/energy"
        res = self._request("GET", url, self._params())
        if res is None or res.status_code != 200:
            _LOGGER.debug("Sigen AC charger energy read failed: %s", res.text if res else "no response")
            return
        try:
            data = res.json().get("data", {}) or {}
        except ValueError:
            return
        self.monthly_energy = data.get("monthlyEnergy")
        self.weekly_energy = data.get("weeklyEnergy")
        self.lifetime_energy = data.get("lifetimeEnergy")

    def set_charge_mode(self, mode: int):
        """Set the Charging Mode (0=Fast Charging, 1=PV Surplus Charging).

        Sigen AI Mode (likely 2) is deliberately not offered here - see the
        class docstring.

        Goes through set_charge_settings so it shares its lock and cached
        payload: a mode change followed quickly by another settings write
        (e.g. in one automation) can't send the old mode back.
        """
        return self.set_charge_settings(chargeMode=mode)

    def set_charge_settings(self, **changes):
        """Change one or more /device/charge/mode/ac fields (enableFromPack,
        cutoffSocFromPack, enableFromGrid, maxPowerFromGrid).

        Sends the full current payload with the changes merged in, which is
        confirmed not to disturb the other fields. The cloud answers
        {"data": true} even for writes it silently ignores (e.g. enabling
        grid charging with maxPowerFromGrid 0), so callers should refresh
        and read the real state back afterwards.
        """
        fields = ("chargeMode", "enableFromPack", "cutoffSocFromPack",
                  "enableFromGrid", "maxPowerFromGrid")
        with self._settings_lock:
            body = {"stationId": int(self._station_id), "snCode": self._charger_sn}
            body.update({k: self.charge_mode_settings[k] for k in fields
                         if self.charge_mode_settings.get(k) is not None})
            body.update(changes)
            url = f"{self._base_url}/device/charge/mode/ac"
            res = self._request("POST", url, json_body=body)
            if res is not None and res.status_code == 200:
                try:
                    ok = res.json().get("data") is True
                except ValueError:
                    ok = False
                if ok:
                    self.charge_mode_settings = {**self.charge_mode_settings, **changes}
                    if "chargeMode" in changes:
                        self.charge_mode = changes["chargeMode"]
                    return True
            _LOGGER.error("Error writing Sigen AC charger settings %s: %s", changes, res.text if res else "no response")
            return False
