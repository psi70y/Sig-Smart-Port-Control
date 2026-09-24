"""Sensor platform for Sigenergy AC EV Charger - read-only telemetry.

First sensor.py in this integration; Smart Port/Energy Profile use
switch/select/button instead since they're user-controllable settings,
not pure telemetry.
"""

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_STATION_ID, CONF_CHARGER_SN, AC_CHARGE_MODE_LABELS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        SigenAcChargerStatusSensor(coordinator, entry),
        SigenAcChargerModeSensor(coordinator, entry),
        SigenAcChargerCurrentSensor(coordinator, entry),
        SigenAcChargerMonthlyEnergySensor(coordinator, entry),
        SigenAcChargerWeeklyEnergySensor(coordinator, entry),
        SigenAcChargerLifetimeEnergySensor(coordinator, entry),
    ])


class _SigenAcChargerSensorBase(CoordinatorEntity, SensorEntity):
    """Shared device grouping for all AC charger sensors on one entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, unique_suffix: str):
        super().__init__(coordinator)
        self._entry = entry
        station_id = entry.data[CONF_STATION_ID]
        charger_sn = entry.data[CONF_CHARGER_SN]
        self._attr_unique_id = f"{station_id}_{charger_sn}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"ac_charger_{station_id}_{charger_sn}")},
            name=entry.title,
            manufacturer="Sigenergy",
            model="AC EV Charger",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class SigenAcChargerStatusSensor(_SigenAcChargerSensorBase):
    """Raw plug/charge status code.

    Only 0 ("not plugged in") is confirmed. Other values (3 observed while
    actively charging) are surfaced as-is rather than mapped to a guessed
    label - see EV_CHARGING_DEVELOPMENT.md for what's known so far.
    """

    _attr_name = "Charge Status Code"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "charge_status_code")

    @property
    def native_value(self):
        return self.coordinator.data.get("charge_status_code")


class SigenAcChargerModeSensor(_SigenAcChargerSensorBase):
    """Current Charging Mode label (Fast Charging / PV Surplus Charging).

    Read-only for now; see switch-over point once set_charge_mode is wired
    up to a select entity in a later pass.
    """

    _attr_name = "Charging Mode"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "charge_mode")

    @property
    def native_value(self):
        mode = self.coordinator.data.get("charge_mode")
        return AC_CHARGE_MODE_LABELS.get(mode, mode)


class SigenAcChargerCurrentSensor(_SigenAcChargerSensorBase):
    """Live charging current, as last set by the charger/EV negotiation."""

    _attr_name = "Charging Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "charge_current")

    @property
    def native_value(self):
        return self.coordinator.data.get("last_set_current")

    @property
    def extra_state_attributes(self):
        return {"max_current": self.coordinator.data.get("max_current")}


class SigenAcChargerMonthlyEnergySensor(_SigenAcChargerSensorBase):
    _attr_name = "Energy This Month"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "energy_monthly")

    @property
    def native_value(self):
        return self.coordinator.data.get("monthly_energy")


class SigenAcChargerWeeklyEnergySensor(_SigenAcChargerSensorBase):
    _attr_name = "Energy This Week"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "energy_weekly")

    @property
    def native_value(self):
        return self.coordinator.data.get("weekly_energy")


class SigenAcChargerLifetimeEnergySensor(_SigenAcChargerSensorBase):
    _attr_name = "Lifetime Energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "energy_lifetime")

    @property
    def native_value(self):
        return self.coordinator.data.get("lifetime_energy")
