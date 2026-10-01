"""Button platform for Sigenergy Smart Port - manual energy profile list
refresh, and Instant Manual Control start/stop."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_STATION_ID
from .entity import station_device_info
from .manual_control import async_start_manual_control, async_stop_manual_control

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Station-wide, so only the entry that owns the station's Energy
    # Profile creates it (see _claim_station_profile in __init__.py).
    if coordinator.owns_station_profile:
        async_add_entities([
            SigenRefreshProfilesButton(coordinator, entry),
            SigenStartManualControlButton(coordinator, entry),
            SigenStopManualControlButton(coordinator, entry),
        ])


class SigenRefreshProfilesButton(ButtonEntity):
    """Manually re-fetch the list of selectable Energy Profiles/modes.

    Useful right after creating a new custom profile in the mySigen app -
    the coordinator also refreshes this list automatically on a schedule
    (see CONF_PROFILE_REFRESH_DAYS, default 30 days), but this button gives
    instant control instead of waiting for the next automatic check or
    reloading the whole integration.
    """

    _attr_has_entity_name = True
    _attr_name = "Refresh Energy Profiles"

    def __init__(self, coordinator, entry: ConfigEntry):
        self.coordinator = coordinator
        self._entry = entry
        station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"{station_id}_refresh_energy_profiles"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"station_{station_id}")},
            name=f"Sigen Station {station_id}",
            manufacturer="Sigenergy",
            model="Energy Storage System",
        )

    async def async_press(self) -> None:
        client = self.coordinator.client
        ok = await self.hass.async_add_executor_job(client.fetch_profile_options)
        if ok:
            _LOGGER.info(
                "Sigen Smart Port: manually refreshed energy profile list (%d options found)",
                len(client.profile_options),
            )
            # Also refresh current state so a just-created profile's active
            # status (if you switched to it in the app) shows up right away
            # too, not just its availability as an option.
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Sigen Smart Port: manual energy profile list refresh failed")


class _SigenManualControlButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, unique_suffix: str):
        self.coordinator = coordinator
        station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"{station_id}_{unique_suffix}"
        self._attr_device_info = station_device_info(station_id)


class SigenStartManualControlButton(_SigenManualControlButton):
    """Start Instant Manual Control with the current Action, Duration and
    Power Limit settings."""

    _attr_name = "Start Manual Control"
    _attr_icon = "mdi:play"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "start_manual_control")

    async def async_press(self) -> None:
        settings = self.coordinator.manual_settings
        await async_start_manual_control(
            self.hass, self.coordinator, settings.action, settings.duration, settings.power_limit
        )


class SigenStopManualControlButton(_SigenManualControlButton):
    """End Instant Manual Control now; the station goes back to its
    Energy Profile."""

    _attr_name = "Stop Manual Control"
    _attr_icon = "mdi:stop"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "stop_manual_control")

    async def async_press(self) -> None:
        await async_stop_manual_control(self.hass, self.coordinator)
