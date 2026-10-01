"""Instant Manual Control - saved settings plus the start/stop logic shared
by the Start/Stop buttons and the start/stop_manual_control actions.

The Action, Duration and Power Limit entities only hold settings for the
next start; nothing is sent to the cloud until Start is pressed. The cloud
doesn't give these settings back, so they're saved to disk with HA's Store
(one file per station) and survive restarts.
"""

import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MANUAL_ACTION_LABELS,
    MANUAL_ACTION_MODES,
    MANUAL_ACTION_SELF_CONSUMPTION,
    MANUAL_ACTIONS_WITH_POWER_LIMIT,
    MANUAL_DURATION_DEFAULT,
    MANUAL_DURATION_MAX,
    MANUAL_DURATION_MIN,
    MANUAL_POWER_LIMIT_MAX,
    MANUAL_POWER_LIMIT_MIN,
    MANUAL_POWER_LIMIT_NONE,
)

_LOGGER = logging.getLogger(__name__)

# Bumped only if the persisted settings file's shape ever changes.
MANUAL_CONTROL_STORAGE_VERSION = 1


def manual_control_store(hass: HomeAssistant, station_id) -> Store:
    """Per-station file, so the settings stay put if another entry on the
    same station takes over the station's entities."""
    return Store(hass, MANUAL_CONTROL_STORAGE_VERSION, f"{DOMAIN}_station_{station_id}_manual_control")


class ManualControlSettings:
    """Action / duration / power limit used by the next Start."""

    def __init__(self, hass: HomeAssistant, station_id):
        self._store = manual_control_store(hass, station_id)
        self.action = MANUAL_ACTION_SELF_CONSUMPTION
        self.duration = MANUAL_DURATION_DEFAULT
        self.power_limit = MANUAL_POWER_LIMIT_MIN  # 0 = no limit

    async def async_load(self) -> None:
        saved = await self._store.async_load()
        if not saved:
            return
        if saved.get("action") in MANUAL_ACTION_MODES:
            self.action = saved["action"]
        try:
            self.duration = _clamp(int(saved.get("duration")), MANUAL_DURATION_MIN, MANUAL_DURATION_MAX)
        except (TypeError, ValueError):
            pass
        try:
            self.power_limit = _clamp(float(saved.get("power_limit")), MANUAL_POWER_LIMIT_MIN, MANUAL_POWER_LIMIT_MAX)
        except (TypeError, ValueError):
            pass
        _LOGGER.info(
            "Sigen Smart Port: restored manual control settings from disk (%s, %d min, %s)",
            self.action, self.duration, describe_power_limit(self.action, self.power_limit),
        )

    async def async_set(self, **changes) -> None:
        """Change one or more settings and save them to disk straight away."""
        for key, value in changes.items():
            setattr(self, key, value)
        await self._store.async_save({
            "action": self.action,
            "duration": self.duration,
            "power_limit": self.power_limit,
        })
        _LOGGER.debug("Sigen Smart Port: saved manual control settings to disk: %s", changes)


def _clamp(value, low, high):
    return max(low, min(high, value))


def describe_power_limit(action: str, power_limit: float | None) -> str:
    if action not in MANUAL_ACTIONS_WITH_POWER_LIMIT:
        return "no power limit used"
    if not power_limit:
        return "no power limit"
    return f"power limit {power_limit:.1f} kW"


async def async_start_manual_control(hass: HomeAssistant, coordinator, action: str,
                                     duration: int, power_limit: float | None) -> None:
    """Validate, send the start request, then refresh so the sensors update.

    Raises an error HA shows to the user (a toast for buttons, a failed
    step for automations) instead of failing silently.
    """
    if action not in MANUAL_ACTION_MODES:
        raise ServiceValidationError(f"Unknown manual control action: {action}")
    if not MANUAL_DURATION_MIN <= duration <= MANUAL_DURATION_MAX:
        raise ServiceValidationError(
            f"Duration must be between {MANUAL_DURATION_MIN} and {MANUAL_DURATION_MAX} minutes, got {duration}"
        )
    if power_limit is not None and not MANUAL_POWER_LIMIT_MIN <= power_limit <= MANUAL_POWER_LIMIT_MAX:
        raise ServiceValidationError(
            f"Power limit must be between {MANUAL_POWER_LIMIT_MIN:g} and {MANUAL_POWER_LIMIT_MAX:g} kW, got {power_limit}"
        )

    if action in MANUAL_ACTIONS_WITH_POWER_LIMIT:
        power_limitation = f"{power_limit:.1f}" if power_limit else MANUAL_POWER_LIMIT_NONE
    else:
        power_limitation = ""

    client = coordinator.client
    # Refuse to start over a running manual control - stop it first. Re-read
    # the status first, so manual control started in the mySigen app since
    # the last poll is caught too. If the read fails, use the last known state.
    await hass.async_add_executor_job(client.fetch_manual_control)
    coordinator.async_show_manual_control_state()
    if client.manual_enabled and (client.manual_end_time or 0) > time.time():
        running = MANUAL_ACTION_LABELS.get(client.manual_mode, "Manual control")
        end_str = dt_util.as_local(dt_util.utc_from_timestamp(client.manual_end_time)).strftime("%H:%M")
        _LOGGER.warning(
            "Sigen Smart Port: not starting %s - %s is already running until %s. Stop it first",
            action, running, end_str,
        )
        raise ServiceValidationError(
            f"Manual control is already running ({running} until {end_str}). Stop it first."
        )

    ok = await hass.async_add_executor_job(
        client.start_manual_control, MANUAL_ACTION_MODES[action], duration, power_limitation
    )
    if not ok:
        raise HomeAssistantError("Sigen cloud rejected the manual control start - see the log for details")

    end_str = dt_util.as_local(dt_util.utc_from_timestamp(client.manual_end_time)).strftime("%H:%M")
    _LOGGER.info(
        "Sigen Smart Port: started Instant Manual Control - %s for %d min, %s (until about %s)",
        action, duration, describe_power_limit(action, power_limit), end_str,
    )
    await coordinator.async_manual_control_sent()


async def async_stop_manual_control(hass: HomeAssistant, coordinator) -> None:
    client = coordinator.client
    ok = await hass.async_add_executor_job(client.stop_manual_control)
    if not ok:
        raise HomeAssistantError("Sigen cloud rejected the manual control stop - see the log for details")
    _LOGGER.info("Sigen Smart Port: stopped Instant Manual Control - station is back on its Energy Profile")
    await coordinator.async_manual_control_sent()
