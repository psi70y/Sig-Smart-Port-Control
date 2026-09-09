"""The Sigenergy Smart Port integration."""

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_STATION_ID,
    CONF_LOAD_PATH,
    CONF_BASE_URL,
    CONF_AUTH_HEADER,
    CONF_USER_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)
from .sigen_api import SigenSmartLoadClient

_LOGGER = logging.getLogger(__name__)

# Bumped only if the persisted token file's shape ever changes.
TOKEN_STORAGE_VERSION = 1


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


class SigenCoordinator(DataUpdateCoordinator):
    """Polls one Smart Port load and hands the result to its entities."""

    def __init__(self, hass: HomeAssistant, client: SigenSmartLoadClient, name: str, update_interval: timedelta):
        super().__init__(hass, _LOGGER, name=f"sigen_smartport_{name}", update_interval=update_interval)
        self.client = client

    async def _async_update_data(self):
        ok = await self.hass.async_add_executor_job(self.client.refresh)
        if not ok:
            raise UpdateFailed("Could not read status from Sigen cloud")
        return {
            "control_mode": self.client.control_mode,
            "manual_switch": self.client.manual_switch,
        }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sigen Smart Port from a config entry."""
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

    client = SigenSmartLoadClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_STATION_ID],
        data[CONF_LOAD_PATH],
        data[CONF_BASE_URL],
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

    coordinator = SigenCoordinator(
        hass,
        client,
        entry.unique_id or entry.entry_id,
        _get_scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so a changed scan interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the persisted token file when the integration is fully removed
    (not just unloaded/reloaded)."""
    store: Store = Store(hass, TOKEN_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_token")
    await store.async_remove()
