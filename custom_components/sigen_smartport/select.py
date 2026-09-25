"""Select platform for Sigenergy Smart Port / AC Charger - config-entry based."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
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
    MODE_AUTO,
    MODE_MANUAL,
    AC_CHARGE_MODE_VALUES,
    AC_CHARGE_MODE_LABELS,
)

_LOGGER = logging.getLogger(__name__)

_UNKNOWN_PROFILE = "Unknown"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if entry.data.get(CONF_DEVICE_KIND) == DEVICE_KIND_AC_CHARGER:
        entities = [SigenAcChargerModeSelector(coordinator, entry)]
        if coordinator.owns_station_profile:
            entities.append(SigenEnergyProfileSelector(coordinator, entry))
        async_add_entities(entities)
        return
    entities = [SigenSmartPortModeSelector(coordinator, entry)]
    if coordinator.owns_station_profile:
        entities.append(SigenEnergyProfileSelector(coordinator, entry))
    async_add_entities(entities)


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
    than the per-load device the switch/mode selector above use. Only one
    entry per station creates it (see _claim_station_profile in
    __init__.py), so several entries on the same station still give a
    single Energy Profile entity.
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


class SigenAcChargerModeSelector(CoordinatorEntity, SelectEntity):
    """AC charger Charging Mode (Fast Charging / PV Surplus Charging).

    Only the two round-trip-confirmed values are offered; Sigen AI Mode is
    left out until its write is captured (see EV_CHARGING_DEVELOPMENT.md).
    The rest of the /device/charge/mode/ac payload (Battery Boost, grid
    charging, cut-off SOC, ...) is exposed read-only as attributes.
    """

    _attr_has_entity_name = True
    _attr_name = "Charging Mode"
    _attr_options = list(AC_CHARGE_MODE_VALUES)

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._entry = entry
        station_id = entry.data[CONF_STATION_ID]
        charger_sn = entry.data[CONF_CHARGER_SN]
        self._attr_unique_id = f"{station_id}_{charger_sn}_charge_mode_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"ac_charger_{station_id}_{charger_sn}")},
            name=entry.title,
            manufacturer="Sigenergy",
            model="AC EV Charger",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def current_option(self) -> str | None:
        # None (shown as unknown) for a mode outside the offered options,
        # e.g. Sigen AI Mode selected in the app.
        return AC_CHARGE_MODE_LABELS.get(self.coordinator.data.get("charge_mode"))

    @property
    def extra_state_attributes(self):
        settings = dict(self.coordinator.data.get("charge_mode_settings") or {})
        settings.pop("snCode", None)
        settings.pop("stationId", None)
        return settings

    async def async_select_option(self, option: str) -> None:
        mode = AC_CHARGE_MODE_VALUES[option]
        client = self.coordinator.client
        ok = await self.hass.async_add_executor_job(client.set_charge_mode, mode)
        if ok:
            _LOGGER.info("Changed Sigen AC charger charging mode to: %s", option)
        await self.coordinator.async_request_refresh()
