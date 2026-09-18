"""Select platform for Sigenergy Smart Port - config-entry based."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_STATION_ID, MODE_AUTO, MODE_MANUAL

_LOGGER = logging.getLogger(__name__)

_UNKNOWN_PROFILE = "Unknown"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SigenSmartPortModeSelector(coordinator, entry),
        SigenEnergyProfileSelector(coordinator, entry),
    ])


class SigenSmartPortModeSelector(CoordinatorEntity, SelectEntity):
    """Drop-down mode selector (Auto / Manual), synced with Sigen cloud state."""

    _attr_has_entity_name = True
    _attr_name = "Control Mode"
    _attr_options = [MODE_AUTO, MODE_MANUAL]

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_mode_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.title,
            manufacturer="Sigenergy",
            model="Smart Port Load",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def current_option(self) -> str:
        if self.coordinator.data.get("control_mode") == 1:
            return MODE_MANUAL
        return MODE_AUTO

    async def async_select_option(self, option: str) -> None:
        client = self.coordinator.client
        manual = option == MODE_MANUAL
        ok = await self.hass.async_add_executor_job(client.set_control_mode, manual)
        if ok:
            await self.coordinator.async_request_refresh()
            _LOGGER.info("Changed Sigen operational control mode to: %s", option)


class SigenEnergyProfileSelector(CoordinatorEntity, SelectEntity):
    """Select the Sigen system-wide energy/operation profile - one of the
    built-in modes (Maximum Self-Powered, TOU, etc.) or one of the user's
    own saved custom profiles.

    This is a station-wide setting, not specific to a single Smart Port
    load, so it's grouped under its own device keyed by station_id rather
    than the per-load device the switch/mode selector above use. If the
    same station has more than one Smart Port load configured, each config
    entry creates its own entity here, but HA's device registry merges
    them under the same device since the identifier is the same.
    """

    _attr_has_entity_name = True
    _attr_name = "Energy Profile"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"{self._station_id}_energy_profile"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"station_{self._station_id}")},
            name=f"Sigen Station {self._station_id}",
            manufacturer="Sigenergy",
            model="Energy Storage System",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self.coordinator.client.profile_options)

    @property
    def options(self) -> list[str]:
        labels = [label for (label, _mode, _pid) in self.coordinator.client.profile_options]
        return labels or [_UNKNOWN_PROFILE]

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.data.get("energy_mode")
        profile_id = self.coordinator.data.get("energy_profile_id")
        for label, opt_mode, opt_profile_id in self.coordinator.client.profile_options:
            if opt_mode != mode:
                continue
            # Built-in modes (profile_id -1) match on mode alone; Custom
            # mode (9) can have several saved profiles, so also match the
            # specific profile_id.
            if opt_mode != 9 or opt_profile_id == profile_id:
                return label
        return None

    async def async_select_option(self, option: str) -> None:
        for label, mode, profile_id in self.coordinator.client.profile_options:
            if label == option:
                client = self.coordinator.client
                ok = await self.hass.async_add_executor_job(client.set_profile, mode, profile_id)
                if ok:
                    await self.coordinator.async_request_refresh()
                    _LOGGER.info("Changed Sigen energy profile to: %s", option)
                return
