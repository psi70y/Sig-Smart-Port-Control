"""Switch platform for Sigenergy Smart Port - config-entry based."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_STATION_ID, CONF_LOAD_PATH

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SigenSmartPortControlSwitch(coordinator, entry)])


class SigenSmartPortControlSwitch(CoordinatorEntity, SwitchEntity):
    """Controls and reflects the manual output power state (On/Off)."""

    _attr_has_entity_name = True
    _attr_name = "Power"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_switch"
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
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("manual_switch"))

    async def async_turn_on(self, **kwargs):
        client = self.coordinator.client
        ok = await self.hass.async_add_executor_job(client.set_manual_switch, True)
        if ok:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        client = self.coordinator.client
        ok = await self.hass.async_add_executor_job(client.set_manual_switch, False)
        if ok:
            await self.coordinator.async_request_refresh()
