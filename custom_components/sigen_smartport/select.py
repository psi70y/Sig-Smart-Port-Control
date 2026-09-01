"""Select platform for Sigenergy Smart Port - config-entry based."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_AUTO, MODE_MANUAL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SigenSmartPortModeSelector(coordinator, entry)])


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
