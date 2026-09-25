"""The Sigenergy Smart Port integration."""

import logging
import time
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    PLATFORMS_SMART_PORT,
    PLATFORMS_AC_CHARGER,
    CONF_DEVICE_KIND,
    DEVICE_KIND_SMART_PORT,
    DEVICE_KIND_AC_CHARGER,
    CONF_STATION_ID,
    CONF_LOAD_PATH,
    CONF_CHARGER_SN,
    CONF_BASE_URL,
    CONF_AUTH_HEADER,
    CONF_USER_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_PROFILE_REFRESH_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PROFILE_REFRESH_DAYS,
    DEFAULT_BASE_URL,
)
from .sigen_api import SigenSmartLoadClient, SigenAcChargerClient

_LOGGER = logging.getLogger(__name__)

# Bumped only if the persisted token file's shape ever changes.
TOKEN_STORAGE_VERSION = 1
# Bumped only if the persisted AC charger settings file's shape ever changes.
AC_CHARGER_STORAGE_VERSION = 1

# hass.data key: {station_id: entry_id} of the one entry per station that
# owns the station-wide Energy Profile select + refresh button (see
# _claim_station_profile).
STATION_PROFILE_OWNERS = f"{DOMAIN}_station_profile_owners"


def _ac_charger_store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    """Per-entry file for AC charger values the cloud can't give back to us,
    kept separate from the token file so auth storage is never touched."""
    return Store(hass, AC_CHARGER_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_ac_charger")


def _ensure_default_log_level() -> None:
    """Default this integration's loggers to INFO so login/refresh/token
    events are visible out of the box, without requiring the user to add
    a `logger:` override in configuration.yaml.

    Only applies if the user hasn't already explicitly set a level for
    these loggers - NOTSET means "never touched, just inheriting a
    parent/root default" - so a deliberate user override (e.g. silencing
    this integration, or setting it to debug) is always respected and
    never touched here. HA's own guidance discourages integrations from
    unconditionally overriding user-controlled logging preferences, hence
    the NOTSET check rather than always forcing the level.
    """
    for logger_name in (__name__, f"{__name__}.sigen_api"):
        logger = logging.getLogger(logger_name)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


async def _async_update_station_profile(hass: HomeAssistant, client, profile_refresh_seconds: float) -> None:
    """Read the station's current Energy Profile, and periodically re-fetch
    the full list of selectable profiles/modes too.

    Deliberately not fatal to the coordinator if it has trouble - the
    device's own entities should keep working even if this optional
    station-level read fails. The list re-fetch is a safety net alongside
    the manual "Refresh Energy Profiles" button, in case new profiles were
    created via the mySigen app/web portal - infrequent by default
    (profile_refresh_seconds, default 30 days) since the list rarely changes.
    """
    await hass.async_add_executor_job(client.fetch_current_profile)

    fetched_at = client.profile_options_fetched_at
    if fetched_at is None or (time.time() - fetched_at) >= profile_refresh_seconds:
        await hass.async_add_executor_job(client.fetch_profile_options)


def _claim_station_profile(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return True if this entry should own its station's Energy Profile
    entities, claiming them if nobody else has.

    The Energy Profile is station-wide, so with several entries on the same
    station (e.g. two Smart Port loads, or a Smart Port load plus an AC
    charger) only one of them may create the select + button - otherwise HA
    rejects the duplicates' unique IDs and every entry polls the same
    profile. The first entry set up claims it; a plain reload keeps its
    claim. The claim only moves when the owner is removed or disabled (see
    _release_station_profile), or if the owner no longer exists.
    """
    owners = hass.data.setdefault(STATION_PROFILE_OWNERS, {})
    station_id = str(entry.data[CONF_STATION_ID])
    owner_id = owners.get(station_id)
    if owner_id and owner_id != entry.entry_id:
        owner = hass.config_entries.async_get_entry(owner_id)
        if owner is not None and owner.disabled_by is None:
            return False
    owners[station_id] = entry.entry_id
    return True


def _release_station_profile(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give up this entry's Energy Profile claim (if it has one) and reload
    the other loaded entries on the same station so one of them takes over."""
    owners = hass.data.get(STATION_PROFILE_OWNERS, {})
    station_id = str(entry.data[CONF_STATION_ID])
    if owners.get(station_id) != entry.entry_id:
        return
    owners.pop(station_id)
    for other in hass.config_entries.async_entries(DOMAIN):
        if (other.entry_id != entry.entry_id
                and str(other.data.get(CONF_STATION_ID)) == station_id
                and other.state is ConfigEntryState.LOADED):
            _LOGGER.info(
                "Sigen Smart Port: handing station %s Energy Profile over to entry '%s'",
                station_id, other.title,
            )
            hass.async_create_task(hass.config_entries.async_reload(other.entry_id))


class SigenCoordinator(DataUpdateCoordinator):
    """Polls one Smart Port load (plus its station's energy profile) and
    hands the result to its entities."""

    def __init__(self, hass: HomeAssistant, client: SigenSmartLoadClient, name: str,
                 update_interval: timedelta, profile_refresh_seconds: float,
                 owns_station_profile: bool):
        super().__init__(hass, _LOGGER, name=f"sigen_smartport_{name}", update_interval=update_interval)
        self.client = client
        self.profile_refresh_seconds = profile_refresh_seconds
        # Only the station's Energy Profile owner polls it and creates its
        # entities - see _claim_station_profile.
        self.owns_station_profile = owns_station_profile

    async def _async_update_data(self):
        ok = await self.hass.async_add_executor_job(self.client.refresh)
        if not ok:
            raise UpdateFailed("Could not read status from Sigen cloud")

        if self.owns_station_profile:
            await _async_update_station_profile(self.hass, self.client, self.profile_refresh_seconds)

        return {
            "control_mode": self.client.control_mode,
            "manual_switch": self.client.manual_switch,
            "energy_mode": self.client.current_energy_mode,
            "energy_profile_id": self.client.current_profile_id,
        }


class SigenAcChargerCoordinator(DataUpdateCoordinator):
    """Polls one AC EV charger and hands the result to its sensors."""

    def __init__(self, hass: HomeAssistant, client: SigenAcChargerClient, name: str,
                 update_interval: timedelta, store: Store, saved_grid_power=None):
        super().__init__(hass, _LOGGER, name=f"sigen_ac_charger_{name}", update_interval=update_interval)
        self.client = client
        self._store = store
        self._saved_grid_power = saved_grid_power

    async def async_save_grid_power(self) -> None:
        """Persist the last non-zero Grid Charging max power, so re-enabling
        Grid Charging after an HA restart still uses it (the cloud reports 0
        while Grid Charging is off). Only writes to disk when it changed."""
        power = self.client.last_grid_power
        if power and power != self._saved_grid_power:
            await self._store.async_save({"last_grid_power": power})
            self._saved_grid_power = power
            _LOGGER.debug("Sigen AC charger: saved grid charging max power %s kW to disk", power)

    async def _async_update_data(self):
        ok = await self.hass.async_add_executor_job(self.client.refresh)
        if not ok:
            raise UpdateFailed("Could not read AC charger status from Sigen cloud")
        await self.async_save_grid_power()

        return {
            "charge_status_code": self.client.charge_status_code,
            "charge_mode": self.client.charge_mode,
            "charge_mode_settings": self.client.charge_mode_settings,
            "last_set_current": self.client.last_set_current,
            "max_current": self.client.max_current,
            "monthly_energy": self.client.monthly_energy,
            "weekly_energy": self.client.weekly_energy,
            "lifetime_energy": self.client.lifetime_energy,
        }


def _get_device_kind(entry: ConfigEntry) -> str:
    """Entries created before AC charger support have no device_kind stored -
    they are always Smart Port loads."""
    return entry.data.get(CONF_DEVICE_KIND, DEVICE_KIND_SMART_PORT)


def _get_platforms(entry: ConfigEntry) -> list:
    if _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER:
        return PLATFORMS_AC_CHARGER
    return PLATFORMS_SMART_PORT


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Sigen Smart Port load or AC charger from a config entry."""
    _ensure_default_log_level()

    data = entry.data

    # Persist the auth token to disk, keyed to this specific config entry, so
    # a Home Assistant/Supervisor restart reuses the still-valid token
    # instead of forcing a brand new login every time. Frequent HA restarts
    # (updates, watchdog, addon restarts) were causing far more logins than
    # the ~12h token lifetime alone would suggest, which appears to be what
    # was tripping Sigen's cloud into force-logging-out the mySigen app/web
    # portal.
    store: Store = Store(hass, TOKEN_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_token")
    stored_token = await store.async_load()

    def _persist_token(token: str, expiry_epoch: float, refresh_token: str) -> None:
        # Called from the executor thread that performs the actual HTTP
        # login/refresh (see sigen_api.py) - hass.add_job is safe to call
        # from any thread and schedules the async save onto the event loop.
        hass.add_job(_save_token_to_disk(store, token, expiry_epoch, refresh_token))

    async def _save_token_to_disk(store: Store, token: str, expiry_epoch: float, refresh_token: str) -> None:
        await store.async_save({"token": token, "expiry": expiry_epoch, "refresh_token": refresh_token})
        expiry_str = datetime.fromtimestamp(expiry_epoch).strftime("%Y-%m-%d %H:%M:%S")
        _LOGGER.info(
            "Sigen Smart Port: saved refreshed auth token to disk (valid until %s)", expiry_str
        )

    is_ac_charger = _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER

    if is_ac_charger:
        client = SigenAcChargerClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_STATION_ID],
            data[CONF_CHARGER_SN],
            _get_base_url(entry),
            data[CONF_AUTH_HEADER],
            data[CONF_USER_DEVICE_ID],
            on_token_change=_persist_token,
        )
    else:
        client = SigenSmartLoadClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_STATION_ID],
            data[CONF_LOAD_PATH],
            _get_base_url(entry),
            data[CONF_AUTH_HEADER],
            data[CONF_USER_DEVICE_ID],
            on_token_change=_persist_token,
        )

    if stored_token:
        client.restore_cached_token(
            stored_token.get("token"),
            stored_token.get("expiry"),
            stored_token.get("refresh_token"),
        )

    if is_ac_charger:
        ac_store = _ac_charger_store(hass, entry)
        saved = await ac_store.async_load() or {}
        saved_grid_power = saved.get("last_grid_power")
        # Seed the client with the saved value; the first poll overrides it
        # if Grid Charging is currently on (the cloud then reports the real one).
        client.last_grid_power = saved_grid_power
        ac_coordinator = SigenAcChargerCoordinator(
            hass,
            client,
            entry.unique_id or entry.entry_id,
            _get_scan_interval(entry),
            ac_store,
            saved_grid_power,
        )
        await ac_coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ac_coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_AC_CHARGER)
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        return True

    owns_station_profile = _claim_station_profile(hass, entry)

    coordinator = SigenCoordinator(
        hass,
        client,
        entry.unique_id or entry.entry_id,
        _get_scan_interval(entry),
        _get_profile_refresh_seconds(entry),
        owns_station_profile,
    )
    try:
        # The first poll also fetches the Energy Profile option list (the
        # user's saved profiles + built-in modes) if this entry owns it.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Don't sit on the claim while this entry can't load.
        _release_station_profile(hass, entry)
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_SMART_PORT)

    # If the scan interval is changed later via the "Configure" button on
    # the integration entry, reload it so the new interval takes effect
    # immediately rather than needing a full HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _get_scan_interval(entry: ConfigEntry) -> timedelta:
    seconds = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    return timedelta(seconds=seconds)


def _get_base_url(entry: ConfigEntry) -> str:
    # Options (set later via Configure) take priority over the value saved
    # at initial setup, so changing region/base_url via Configure actually
    # takes effect on the next reload rather than being silently ignored.
    return entry.options.get(
        CONF_BASE_URL, entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    )


def _get_profile_refresh_seconds(entry: ConfigEntry) -> float:
    days = entry.options.get(
        CONF_PROFILE_REFRESH_DAYS,
        entry.data.get(CONF_PROFILE_REFRESH_DAYS, DEFAULT_PROFILE_REFRESH_DAYS),
    )
    return float(days) * 86400


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so a changed scan interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, _get_platforms(entry))
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Disabling the entry that owns the station's Energy Profile hands
        # it to another entry on the same station. A plain reload keeps it.
        if entry.disabled_by is not None:
            _release_station_profile(hass, entry)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the persisted token file when the integration is fully removed
    (not just unloaded/reloaded)."""
    store: Store = Store(hass, TOKEN_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_token")
    await store.async_remove()
    _release_station_profile(hass, entry)
    if _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER:
        await _ac_charger_store(hass, entry).async_remove()
