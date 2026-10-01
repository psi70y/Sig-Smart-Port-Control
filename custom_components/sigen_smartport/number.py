"""Number platform - AC charger Cut-Off SOC and Max Grid Power, and the
station's Instant Manual Control duration and power limit."""

import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_DEVICE_KIND,
    DEVICE_KIND_AC_CHARGER,
    AC_FIELD_CUTOFF_SOC,
    AC_FIELD_GRID_CHARGING,
    AC_FIELD_MAX_GRID_POWER,
    AC_CUTOFF_SOC_MIN,
    AC_CUTOFF_SOC_MAX,
    AC_MAX_GRID_POWER_KW,
    MANUAL_DURATION_MAX,
    MANUAL_DURATION_MIN,
    MANUAL_POWER_LIMIT_MAX,
    MANUAL_POWER_LIMIT_MIN,
)
from .entity import SigenAcChargerEntity, SigenManualControlSettingEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER:
        entities += [
            SigenAcChargerCutoffSocNumber(coordinator, entry),
            SigenAcChargerMaxGridPowerNumber(coordinator, entry),
        ]
    # Station-wide, so only the entry that owns the station's Energy
    # Profile creates them (see _claim_station_profile in __init__.py).
    if coordinator.owns_station_profile:
        entities += [
            SigenManualControlDurationNumber(coordinator, entry),
            SigenManualControlPowerLimitNumber(coordinator, entry),
        ]
    async_add_entities(entities)


class SigenAcChargerCutoffSocNumber(SigenAcChargerEntity, NumberEntity):
    """Battery Boost cut-off: the home battery SOC below which it stops
    supplying the charger."""

    _attr_name = "Battery Boost Cut-Off SOC"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = AC_CUTOFF_SOC_MIN
    _attr_native_max_value = AC_CUTOFF_SOC_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "cutoff_soc")

    @property
    def native_value(self):
        return self._settings.get(AC_FIELD_CUTOFF_SOC)

    async def async_set_native_value(self, value: float) -> None:
        await self._write(**{AC_FIELD_CUTOFF_SOC: int(value)})


class SigenAcChargerMaxGridPowerNumber(SigenAcChargerEntity, NumberEntity):
    """Max power drawn from the grid while Grid Charging is on.

    The cloud forces this to 0 whenever Grid Charging is off and ignores
    writes to it then, so while it's off a new value is only remembered (on
    disk, so it survives HA restarts) and applied the next time Grid
    Charging is switched on.
    """

    _attr_name = "Grid Charging Max Power"
    _attr_icon = "mdi:transmission-tower-import"
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = 0.5
    _attr_native_max_value = AC_MAX_GRID_POWER_KW
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "max_grid_power")

    @property
    def native_value(self):
        if self._settings.get(AC_FIELD_GRID_CHARGING):
            return self._settings.get(AC_FIELD_MAX_GRID_POWER)
        # Grid charging off: show the value that will be used when it's
        # switched back on, rather than the forced 0.
        return self.coordinator.client.last_grid_power

    async def async_set_native_value(self, value: float) -> None:
        value = round(float(value), 1)
        self.coordinator.client.last_grid_power = value
        if self._settings.get(AC_FIELD_GRID_CHARGING):
            await self._write(**{AC_FIELD_MAX_GRID_POWER: value})
        else:
            _LOGGER.info("Sigen AC charger: grid charging is off - max grid power %s kW saved for when it's enabled", value)
            await self.coordinator.async_save_grid_power()
            self.async_write_ha_state()


class SigenManualControlDurationNumber(SigenManualControlSettingEntity, NumberEntity):
    """How long Instant Manual Control runs when Start is pressed."""

    _attr_name = "Manual Control Duration"
    _attr_icon = "mdi:timer-outline"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = MANUAL_DURATION_MIN
    _attr_native_max_value = MANUAL_DURATION_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "manual_control_duration")

    @property
    def native_value(self):
        return self._settings.duration

    async def async_set_native_value(self, value: float) -> None:
        await self._settings.async_set(duration=int(value))
        self.async_write_ha_state()
        _LOGGER.info("Sigen Smart Port: manual control duration set to %d min (used on next start)", int(value))


class SigenManualControlPowerLimitNumber(SigenManualControlSettingEntity, NumberEntity):
    """Power limit for Charging / Discharging. 0 means no limit. Hold
    Battery and Self-Consumption ignore it, as in the mySigen app."""

    _attr_name = "Manual Control Power Limit"
    _attr_icon = "mdi:flash"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_min_value = MANUAL_POWER_LIMIT_MIN
    _attr_native_max_value = MANUAL_POWER_LIMIT_MAX
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "manual_control_power_limit")

    @property
    def native_value(self):
        return self._settings.power_limit

    async def async_set_native_value(self, value: float) -> None:
        value = round(value, 1)
        await self._settings.async_set(power_limit=value)
        self.async_write_ha_state()
        if value:
            _LOGGER.info("Sigen Smart Port: manual control power limit set to %.1f kW (used on next start)", value)
        else:
            _LOGGER.info("Sigen Smart Port: manual control power limit set to no limit (used on next start)")
