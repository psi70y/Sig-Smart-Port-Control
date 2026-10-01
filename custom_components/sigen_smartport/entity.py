"""Shared entity bases: AC charger entities that read the charge-mode
settings, and the station-wide Instant Manual Control entities."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_STATION_ID, CONF_CHARGER_SN


class SigenAcChargerEntity(CoordinatorEntity):
    """Groups an entity under the AC charger device and exposes its
    /device/charge/mode/ac settings."""

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

    @property
    def _settings(self) -> dict:
        return self.coordinator.data.get("charge_mode_settings") or {}

    async def _write(self, **changes) -> None:
        client = self.coordinator.client
        await self.hass.async_add_executor_job(lambda: client.set_charge_settings(**changes))
        # Always read back - the cloud reports success even for ignored writes.
        await self.coordinator.async_request_refresh()


def station_device_info(station_id) -> DeviceInfo:
    """The station-wide "Sigen Station" device the Energy Profile select
    and the manual control entities live on."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"station_{station_id}")},
        name=f"Sigen Station {station_id}",
        manufacturer="Sigenergy",
        model="Energy Storage System",
    )


class SigenManualControlSettingEntity:
    """Base for the Action / Duration / Power Limit entities. They hold
    settings for the next Start (saved to disk by ManualControlSettings),
    not cloud state, so they don't follow the coordinator."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator, entry: ConfigEntry, unique_suffix: str):
        self.coordinator = coordinator
        station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"{station_id}_{unique_suffix}"
        self._attr_device_info = station_device_info(station_id)

    @property
    def _settings(self):
        return self.coordinator.manual_settings
