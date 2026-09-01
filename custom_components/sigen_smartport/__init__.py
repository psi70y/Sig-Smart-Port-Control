"""The Sigenergy Smart Port integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
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
    data = entry.data

    client = SigenSmartLoadClient(
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_STATION_ID],
        data[CONF_LOAD_PATH],
        data[CONF_BASE_URL],
        data[CONF_AUTH_HEADER],
        data[CONF_USER_DEVICE_ID],
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
