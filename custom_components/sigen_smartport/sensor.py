"""Sensor platform - read-only AC EV Charger telemetry, and the station's
Instant Manual Control status (for whichever entry owns the station).
"""

import logging
from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_STATION_ID,
    CONF_CHARGER_SN,
    CONF_DEVICE_KIND,
    DEVICE_KIND_AC_CHARGER,
    AC_CHARGE_MODE_LABELS,
    MANUAL_ACTION_LABELS,
    MANUAL_ACTION_MODES,
    MANUAL_STATE_OFF,
)
from .entity import station_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    if entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER:
        entities += [
            SigenAcChargerStatusSensor(coordinator, entry),
            SigenAcChargerModeSensor(coordinator, entry),
            SigenAcChargerCurrentSensor(coordinator, entry),
            SigenAcChargerMonthlyEnergySensor(coordinator, entry),
            SigenAcChargerWeeklyEnergySensor(coordinator, entry),
            SigenAcChargerLifetimeEnergySensor(coordinator, entry),
        ]
    # Station-wide, so only the entry that owns the station's Energy
    # Profile creates them (see _claim_station_profile in __init__.py).
    if coordinator.owns_station_profile:
        entities += [
            SigenManualControlStatusSensor(coordinator, entry),
            SigenManualControlEndsSensor(coordinator, entry),
        ]
    async_add_entities(entities)


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


class _SigenManualControlSensorBase(CoordinatorEntity, SensorEntity):
    """Instant Manual Control state as read from the cloud, so it also
    reflects manual control started or stopped in the mySigen app."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, unique_suffix: str):
        super().__init__(coordinator)
        station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"{station_id}_{unique_suffix}"
        self._attr_device_info = station_device_info(station_id)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class SigenManualControlStatusSensor(_SigenManualControlSensorBase):
    """Off, or the action that's running (Charging, Hold Battery, ...)."""

    _attr_name = "Manual Control"
    _attr_icon = "mdi:battery-sync"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [MANUAL_STATE_OFF, *MANUAL_ACTION_MODES]

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "manual_control_status")

    @property
    def native_value(self):
        enabled = self.coordinator.data.get("manual_enabled")
        if enabled is None:
            return None  # not read yet
        if not enabled:
            return MANUAL_STATE_OFF
        mode = self.coordinator.data.get("manual_mode")
        label = MANUAL_ACTION_LABELS.get(mode)
        if label is None:
            # A mode the app didn't offer when this was written - show it
            # as unknown rather than guessing; the raw code is an attribute.
            _LOGGER.debug("Sigenergy Cloud Control: unrecognised manual control mode %r", mode)
        return label

    @property
    def extra_state_attributes(self):
        return {"mode_code": self.coordinator.data.get("manual_mode")}


class SigenManualControlEndsSensor(_SigenManualControlSensorBase):
    """When the running manual control finishes. Unknown while it's off."""

    _attr_name = "Manual Control Ends"
    _attr_icon = "mdi:timer-sand"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "manual_control_ends")

    @property
    def native_value(self):
        end_time = self.coordinator.data.get("manual_end_time")
        if not self.coordinator.data.get("manual_enabled") or not end_time:
            return None
        return datetime.fromtimestamp(end_time, tz=timezone.utc)
