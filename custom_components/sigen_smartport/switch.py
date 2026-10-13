"""Switch platform for Sigenergy Cloud Control (Smart Port loads / AC Charger) - config-entry based."""

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
from .entity import SigenAcChargerEntity, SigenManualControlSettingEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER:
        entities = [
            SigenAcChargerBatteryBoostSwitch(coordinator, entry),
            SigenAcChargerGridChargingSwitch(coordinator, entry),
        ]
    else:
        entities = [SigenSmartPortControlSwitch(coordinator, entry)]
    # Station-wide, so only the entry that owns the station's Energy
    # Profile creates it (see _claim_station_profile in __init__.py).
    if coordinator.owns_station_profile:
        entities.append(SigenManualControlReplaceRunningSwitch(coordinator, entry))
    async_add_entities(entities)


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


class SigenManualControlReplaceRunningSwitch(SigenManualControlSettingEntity, SwitchEntity):
    """Whether Start Manual Control may replace a manual control that's
    already running (for example one started in the mySigen app). Off by
    default: Start is refused until the running one ends or is stopped."""

    _attr_name = "Replace Running Manual Control"
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "manual_control_replace_running")

    @property
    def is_on(self) -> bool:
        return self._settings.replace_running

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)

    async def _set(self, on: bool) -> None:
        await self._settings.async_set(replace_running=on)
        self.async_write_ha_state()
        _LOGGER.info(
            "Sigenergy Cloud Control: Start Manual Control will now %s a running manual control",
            "replace" if on else "refuse to replace",
        )
