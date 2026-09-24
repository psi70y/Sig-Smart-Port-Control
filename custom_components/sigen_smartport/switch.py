"""Switch platform for Sigenergy Smart Port / AC Charger - config-entry based."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_DEVICE_KIND,
    DEVICE_KIND_AC_CHARGER,
    AC_FIELD_BATTERY_BOOST,
    AC_FIELD_GRID_CHARGING,
    AC_FIELD_MAX_GRID_POWER,
    AC_FALLBACK_GRID_POWER_KW,
)
from .entity import SigenAcChargerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER:
        async_add_entities([
            SigenAcChargerBatteryBoostSwitch(coordinator, entry),
            SigenAcChargerGridChargingSwitch(coordinator, entry),
        ])
        return
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


class SigenAcChargerBatteryBoostSwitch(SigenAcChargerEntity, SwitchEntity):
    """Battery Boost - let the home battery supply the charger (down to the
    Cut-Off SOC)."""

    _attr_name = "Battery Boost"
    _attr_icon = "mdi:home-battery"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "battery_boost")

    @property
    def is_on(self):
        return self._settings.get(AC_FIELD_BATTERY_BOOST)

    async def async_turn_on(self, **kwargs):
        await self._write(**{AC_FIELD_BATTERY_BOOST: True})

    async def async_turn_off(self, **kwargs):
        await self._write(**{AC_FIELD_BATTERY_BOOST: False})


class SigenAcChargerGridChargingSwitch(SigenAcChargerEntity, SwitchEntity):
    """Grid Charging - let the charger draw from the grid (up to the Grid
    Charging Max Power)."""

    _attr_name = "Grid Charging"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "grid_charging")

    @property
    def is_on(self):
        return self._settings.get(AC_FIELD_GRID_CHARGING)

    async def async_turn_on(self, **kwargs):
        # Must be sent with a non-zero max power or the cloud ignores it.
        power = self.coordinator.client.last_grid_power
        if not power:
            power = AC_FALLBACK_GRID_POWER_KW
            _LOGGER.warning(
                "Sigen AC charger: no previous grid charging power known, using %s kW", power
            )
        await self._write(**{AC_FIELD_GRID_CHARGING: True, AC_FIELD_MAX_GRID_POWER: power})

    async def async_turn_off(self, **kwargs):
        await self._write(**{AC_FIELD_GRID_CHARGING: False})
