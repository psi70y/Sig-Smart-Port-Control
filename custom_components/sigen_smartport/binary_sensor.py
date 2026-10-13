"""Binary sensor platform - Price Spike Export status on the station device
(only when the feature is turned on in Configure)."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import SigenPriceSpikeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if coordinator.price_spike:
        async_add_entities([
            SigenPriceSpikeActiveSensor(coordinator, entry),
            SigenPriceSpikeDischargingSensor(coordinator, entry),
        ])


class SigenPriceSpikeActiveSensor(SigenPriceSpikeEntity, BinarySensorEntity):
    """On while the price is at or above the threshold (after the start
    delay). Off during the hold time after a dip."""

    _attr_name = "Price Spike Active"
    _attr_icon = "mdi:flash-alert"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "price_spike_active")

    @property
    def is_on(self) -> bool:
        return self._controller.spike_active

    @property
    def extra_state_attributes(self):
        return self._controller.attributes


class SigenPriceSpikeDischargingSensor(SigenPriceSpikeEntity, BinarySensorEntity):
    """On only while a manual control session started by Price Spike Export
    is running - never for one you started yourself."""

    _attr_name = "Price Spike Discharging"
    _attr_icon = "mdi:home-battery-outline"

    def __init__(self, coordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry, "price_spike_discharging")

    @property
    def is_on(self) -> bool:
        return self._controller.ours

    @property
    def extra_state_attributes(self):
        return self._controller.attributes
