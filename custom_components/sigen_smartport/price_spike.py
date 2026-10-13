"""Price Spike Export - force-discharge the battery through Instant Manual
Control while a price entity is at or above a threshold, then hand control
back when the spike is over.

The price (and battery SOC) come from entities of any other integration,
chosen in Configure, so nothing here is tied to a market or retailer.

How a spike runs:
  - Price reaches the threshold. After the start delay (0 = straight away)
    the spike is "active".
  - While active, a Discharging manual control session is started at the
    set power for the set session duration. When the session runs out and
    the spike is still on, a new one is started ("re-arm"). The session
    duration is the safety backstop: if Home Assistant stops, discharging
    ends by itself when the session does.
  - A price dip doesn't stop it straight away. Only when the price has
    stayed below the threshold for the hold time does the spike end and
    our session get stopped. If the price comes back during the hold, the
    spike carries on without a new start delay.
  - It also stops when SOC reaches the minimum (no restart until the next
    spike), or when the Price Spike Export switch is turned off.

Whose session is it: only a Discharging session whose end time matches the
one we started (within SESSION_MATCH_TOLERANCE_SECONDS) is treated as ours,
and only ours is ever stopped. That flag is saved to disk, so after a
restart a session we started is picked up again, and anything else is left
alone. A manual control the user started is waited out, or replaced only if
the Price Spike Take Over Manual Control switch is on. If the user stops or
replaces our session, we leave it for the rest of that spike.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_SPIKE_STARTED,
    EVENT_SPIKE_STOPPED,
    MANUAL_ACTION_DISCHARGING,
    MANUAL_ACTION_MODES,
    MANUAL_DURATION_MAX,
    MANUAL_DURATION_MIN,
    MANUAL_POWER_LIMIT_MAX,
    MANUAL_POWER_LIMIT_MIN,
    SPIKE_DURATION_DEFAULT,
    SPIKE_ENTITY_SUFFIXES,
    SPIKE_HOLD_TIME_DEFAULT,
    SPIKE_HOLD_TIME_MAX,
    SPIKE_MIN_SOC_DEFAULT,
    SPIKE_POWER_DEFAULT,
    SPIKE_START_DELAY_DEFAULT,
    SPIKE_START_DELAY_MAX,
    SPIKE_STOP_FEATURE_DISABLED,
    SPIKE_STOP_PRICE,
    SPIKE_STOP_SOC,
    SPIKE_STOP_SWITCHED_OFF,
    SPIKE_THRESHOLD_DEFAULT,
    SPIKE_THRESHOLD_MAX,
    SPIKE_THRESHOLD_MIN,
)
from .manual_control import async_start_manual_control, describe_running, is_manual_running

_LOGGER = logging.getLogger(__name__)

# Bumped only if the persisted file's shape ever changes.
PRICE_SPIKE_STORAGE_VERSION = 1

# How far the cloud's end time may be from the one we expected for the
# session to still count as ours (the cloud sets its own, a few seconds off).
SESSION_MATCH_TOLERANCE_SECONDS = 120

# Never send starts closer together than this. A safety net so a cloud that
# reports something unexpected can't make us send start after start.
MIN_START_INTERVAL_SECONDS = 60

_DISCHARGING_MODE = MANUAL_ACTION_MODES[MANUAL_ACTION_DISCHARGING]

# Dashboard settings: name -> (default, min, max, type).
_SETTINGS = {
    "enabled": (False, None, None, bool),
    "take_over": (False, None, None, bool),
    "threshold": (SPIKE_THRESHOLD_DEFAULT, SPIKE_THRESHOLD_MIN, SPIKE_THRESHOLD_MAX, float),
    "start_delay": (SPIKE_START_DELAY_DEFAULT, 0, SPIKE_START_DELAY_MAX, int),
    "hold_time": (SPIKE_HOLD_TIME_DEFAULT, 0, SPIKE_HOLD_TIME_MAX, int),
    "power": (SPIKE_POWER_DEFAULT, MANUAL_POWER_LIMIT_MIN, MANUAL_POWER_LIMIT_MAX, float),
    "duration": (SPIKE_DURATION_DEFAULT, MANUAL_DURATION_MIN, MANUAL_DURATION_MAX, int),
    "min_soc": (SPIKE_MIN_SOC_DEFAULT, 0, 100, int),
}


_SETTING_LABELS = {
    "enabled": "Price Spike Export switch",
    "take_over": "take over manual control",
    "threshold": "threshold",
    "start_delay": "start delay (min)",
    "hold_time": "hold time (min)",
    "power": "discharge power (kW, 0 = no limit)",
    "duration": "session duration (min)",
    "min_soc": "minimum SOC (%)",
}


def price_spike_store(hass: HomeAssistant, station_id) -> Store:
    """Per-station file holding the dashboard settings and whether the
    running manual control session is ours."""
    return Store(hass, PRICE_SPIKE_STORAGE_VERSION, f"{DOMAIN}_station_{station_id}_price_spike")


@callback
def async_remove_spike_entities(hass: HomeAssistant, station_id) -> None:
    """Remove the feature's entities from the registry, so turning it off in
    Configure doesn't leave them behind as unavailable."""
    ent_reg = er.async_get(hass)
    for platform, suffixes in SPIKE_ENTITY_SUFFIXES.items():
        for suffix in suffixes:
            entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, f"{station_id}_{suffix}")
            if entity_id:
                ent_reg.async_remove(entity_id)


async def async_stop_orphaned_session(hass: HomeAssistant, coordinator, station_id) -> None:
    """With the feature turned off in Configure, stop a session it left
    running (only if it's still ours), so it isn't left to run out."""
    store = price_spike_store(hass, station_id)
    saved = await store.async_load()
    state = (saved or {}).get("state") or {}
    if not state.get("ours"):
        return
    client = coordinator.client
    await hass.async_add_executor_job(client.fetch_manual_control)
    if _session_matches(client, state.get("session_end")):
        _LOGGER.info(
            "Sigenergy Cloud Control: Price Spike Export was turned off in Configure - stopping its discharge session"
        )
        async with coordinator.manual_lock:
            ok = await hass.async_add_executor_job(client.stop_manual_control)
        if not ok:
            _LOGGER.error("Sigenergy Cloud Control: couldn't stop the price spike session - it ends by itself at its end time")
        await coordinator.async_manual_control_sent()
    saved["state"] = {**state, "ours": False, "session_end": None, "last_stop_reason": SPIKE_STOP_FEATURE_DISABLED}
    await store.async_save(saved)


def _session_matches(client, session_end) -> bool:
    """True if the running manual control is the Discharging session we
    started (see SESSION_MATCH_TOLERANCE_SECONDS)."""
    return bool(
        session_end
        and is_manual_running(client)
        and client.manual_mode == _DISCHARGING_MODE
        and abs(client.manual_end_time - session_end) <= SESSION_MATCH_TOLERANCE_SECONDS
    )


def _local_hm(epoch: float) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).strftime("%H:%M")


class PriceSpikeController:
    """Runs Price Spike Export for one station. Event-driven: it reacts to
    the price and SOC entities, the station coordinator's updates, its own
    timers and the dashboard settings - it never polls."""

    def __init__(self, hass: HomeAssistant, coordinator, station_id, price_entity: str,
                 soc_entity: str, notify_action: str | None, price_unit: str | None = None):
        self.hass = hass
        self.coordinator = coordinator
        self.station_id = str(station_id)
        self.price_entity = price_entity
        self.soc_entity = soc_entity
        self.notify_action = notify_action or None
        self._store = price_spike_store(hass, station_id)

        self.settings = {name: spec[0] for name, spec in _SETTINGS.items()}

        # Saved run state.
        self.ours = False               # the running session is one we started
        self.session_end = None         # its expected end (epoch seconds)
        self.spike_started = None       # when the current spike became active
        self.last_stop_reason = None

        # Live state, worked out again from the entities after a restart.
        self.price = None
        # The price entity's own unit wins; the one set in Configure is the
        # fallback for entities that don't report one.
        self.price_unit = price_unit or None
        self.soc = None
        self.spike_active = False       # price at/above threshold, start delay done
        self.hold_ends = None           # set while in the hold time after a dip
        self._soc_latched = False       # stopped at minimum SOC - wait for next spike
        self._override_latched = False  # user stopped/replaced ours - leave this spike
        self._notified_start = False    # notify once per spike, not on every re-arm
        self._end_reason = None         # stop reason set when the spike itself ends
        self._waiting_logged = None     # last "not starting because ..." logged
        self._price_warned = False
        self._soc_warned = False

        self._last_start = 0.0
        self._retry_unsub = None
        self._confirm_unsub = None
        self._hold_unsub = None
        self._unsubs = []
        self._listeners = []
        self._lock = asyncio.Lock()
        self._eval_task = None
        self._eval_requested = False
        self._eval_running = False
        self._closed = False

    # ------------------------------------------------------------ lifecycle
    async def async_load(self) -> None:
        saved = await self._store.async_load() or {}
        for name, value in (saved.get("settings") or {}).items():
            spec = _SETTINGS.get(name)
            if spec is None:
                continue
            default, low, high, kind = spec
            try:
                value = kind(value)
            except (TypeError, ValueError):
                continue
            if low is not None:
                value = max(low, min(high, value))
            self.settings[name] = value
        state = saved.get("state") or {}
        self.ours = bool(state.get("ours"))
        self.session_end = state.get("session_end")
        self.spike_started = state.get("spike_started")
        self.last_stop_reason = state.get("last_stop_reason")
        _LOGGER.info(
            "Sigenergy Cloud Control: Price Spike Export loaded - %s, threshold %s, start delay %d min, "
            "hold %d min, %s, sessions of %d min, minimum SOC %d%%, take over manual control %s, "
            "price from %s, SOC from %s",
            "armed" if self.settings["enabled"] else "switched off",
            self.settings["threshold"], self.settings["start_delay"], self.settings["hold_time"],
            self._describe_power(), self.settings["duration"], self.settings["min_soc"],
            "on" if self.settings["take_over"] else "off", self.price_entity, self.soc_entity,
        )

    @callback
    def async_start(self) -> None:
        """Start listening, and work out where things stand right now."""
        self._unsubs.append(async_track_state_change_event(
            self.hass, [self.price_entity, self.soc_entity], self._async_state_changed
        ))
        self._unsubs.append(self.coordinator.async_add_listener(self._request_evaluate))

        self._read_soc()
        self._read_price()
        if self.ours:
            # Restarted mid-spike while our session runs: carry on without a
            # new start delay. If the price is already back down, a fresh
            # hold time starts now.
            self.spike_active = True
            self._notified_start = True
            if not self._price_above():
                self._price_dropped()
        else:
            self.spike_started = None
            self._update_spike_state()
        self._request_evaluate()

    async def async_shutdown(self) -> None:
        """Stop listening on unload. A running session is left alone - it's
        still ours after a reload or restart, and it ends by itself."""
        self._closed = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_confirm()
        self._cancel_hold()
        if self._retry_unsub:
            self._retry_unsub()
            self._retry_unsub = None
        if self._eval_task and not self._eval_task.done():
            await self._eval_task

    @callback
    def async_add_listener(self, update_callback) -> Callable[[], None]:
        """Entities register here to be told when to write their state."""
        self._listeners.append(update_callback)

        def remove() -> None:
            self._listeners.remove(update_callback)
        return remove

    @callback
    def _notify_listeners(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    # ------------------------------------------------------------- settings
    async def async_set(self, **changes) -> None:
        """Change dashboard settings, save them, and re-evaluate."""
        for name, value in changes.items():
            old = self.settings[name]
            self.settings[name] = value
            if old != value:
                if isinstance(value, bool):
                    value = "on" if value else "off"
                _LOGGER.info("Sigenergy Cloud Control: Price Spike Export setting changed - %s: %s",
                             _SETTING_LABELS[name], value)
        await self._async_save()
        if "threshold" in changes or "start_delay" in changes:
            # A new start delay applies from the next time the price rises.
            self._update_spike_state()
        self._notify_listeners()
        self._request_evaluate()

    async def _async_save(self) -> None:
        await self._store.async_save({
            "settings": self.settings,
            "state": {
                "ours": self.ours,
                "session_end": self.session_end,
                "spike_started": self.spike_started,
                "last_stop_reason": self.last_stop_reason,
            },
        })

    # ------------------------------------------------- price and SOC input
    @callback
    def _async_state_changed(self, event) -> None:
        if event.data["entity_id"] == self.soc_entity:
            self._read_soc()
        if event.data["entity_id"] == self.price_entity:
            self._read_price()
            self._update_spike_state()
        self._notify_listeners()
        self._request_evaluate()

    def _read_number(self, entity_id: str) -> tuple[float | None, str | None]:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None, None
        try:
            return float(state.state), state.attributes.get("unit_of_measurement")
        except ValueError:
            return None, None

    @callback
    def _read_price(self) -> None:
        self.price, unit = self._read_number(self.price_entity)
        if unit:
            self.price_unit = unit
        if self.price is None:
            if not self._price_warned:
                _LOGGER.warning(
                    "Sigenergy Cloud Control: price entity %s has no usable number (%s) - treated as no spike",
                    self.price_entity, self._raw_state(self.price_entity),
                )
                self._price_warned = True
        elif self._price_warned:
            _LOGGER.info("Sigenergy Cloud Control: price entity %s is back (%s)", self.price_entity, self.price)
            self._price_warned = False

    @callback
    def _read_soc(self) -> None:
        self.soc, _unit = self._read_number(self.soc_entity)
        if self.soc is None:
            if not self._soc_warned:
                _LOGGER.warning(
                    "Sigenergy Cloud Control: SOC entity %s has no usable number (%s) - Price Spike Export won't start until it does",
                    self.soc_entity, self._raw_state(self.soc_entity),
                )
                self._soc_warned = True
        elif self._soc_warned:
            _LOGGER.info("Sigenergy Cloud Control: SOC entity %s is back (%s%%)", self.soc_entity, self.soc)
            self._soc_warned = False

    def _raw_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.state if state else "entity not found"

    def _price_above(self) -> bool:
        return self.price is not None and self.price >= self.settings["threshold"]

    # ------------------------------------------------- spike state machine
    @callback
    def _update_spike_state(self) -> None:
        """Move the spike on from the latest price: start delay, active,
        hold time after a dip, ended."""
        if self._price_above():
            self._cancel_hold()
            if self.spike_active:
                return
            if self.hold_ends is not None:
                # Back up during the hold time: the spike carries on.
                self.hold_ends = None
                self.spike_active = True
                _LOGGER.info("Sigenergy Cloud Control: price spike continues - %s", self._context())
                return
            if self._confirm_unsub is not None:
                return  # start delay already counting
            delay = self.settings["start_delay"]
            if delay <= 0:
                self._activate()
            else:
                _LOGGER.info(
                    "Sigenergy Cloud Control: price at/above threshold - waiting %d min before the spike counts (%s)",
                    delay, self._context(),
                )
                self._confirm_unsub = async_call_later(self.hass, delay * 60, self._confirm_elapsed)
        else:
            if self._confirm_unsub is not None:
                _LOGGER.info(
                    "Sigenergy Cloud Control: price fell back below threshold during the start delay - no spike (%s)",
                    self._context(),
                )
                self._cancel_confirm()
            if self.spike_active:
                self._price_dropped()

    @callback
    def _confirm_elapsed(self, _now) -> None:
        self._confirm_unsub = None
        if self._price_above():
            self._activate()
            self._notify_listeners()
            self._request_evaluate()

    @callback
    def _activate(self) -> None:
        self.spike_active = True
        if self.spike_started is None:
            self.spike_started = time.time()
        _LOGGER.info("Sigenergy Cloud Control: price spike active - %s", self._context())

    @callback
    def _price_dropped(self) -> None:
        """Price below threshold while a spike is on: start the hold time."""
        self.spike_active = False
        hold = self.settings["hold_time"]
        if hold <= 0:
            self._end_spike()
            return
        self.hold_ends = time.time() + hold * 60
        _LOGGER.info(
            "Sigenergy Cloud Control: price dipped below threshold - holding until %s unless it comes back (%s)",
            _local_hm(self.hold_ends), self._context(),
        )
        self._hold_unsub = async_call_later(self.hass, hold * 60, self._hold_elapsed)

    @callback
    def _hold_elapsed(self, _now) -> None:
        self._hold_unsub = None
        self._end_spike()
        self._notify_listeners()
        self._request_evaluate()

    @callback
    def _end_spike(self) -> None:
        self.hold_ends = None
        self.spike_active = False
        self.spike_started = None
        self._soc_latched = False
        self._override_latched = False
        self._notified_start = False
        self._waiting_logged = None
        self._end_reason = SPIKE_STOP_PRICE
        _LOGGER.info("Sigenergy Cloud Control: price spike over - %s", self._context())

    @callback
    def _cancel_confirm(self) -> None:
        if self._confirm_unsub:
            self._confirm_unsub()
            self._confirm_unsub = None

    @callback
    def _cancel_hold(self) -> None:
        if self._hold_unsub:
            self._hold_unsub()
            self._hold_unsub = None

    @property
    def wants_export(self) -> bool:
        """Spike active, or in its hold time."""
        return self.spike_active or self.hold_ends is not None

    # ------------------------------------------------------------ decisions
    @callback
    def _request_evaluate(self) -> None:
        """Ask for a decision. Requests are run one at a time by a single
        task (and under self._lock), so overlapping triggers can never
        double-start or double-stop; any that arrive while one runs are
        handled straight after it."""
        if self._closed:
            return
        self._eval_requested = True
        if self._eval_running:
            return
        # Marked before the task is created: HA may start running the task
        # straight away, and a trigger in between must not start a second.
        self._eval_running = True
        self._eval_task = self.hass.async_create_task(self._async_evaluate_loop())

    async def _async_evaluate_loop(self) -> None:
        try:
            while self._eval_requested and not self._closed:
                self._eval_requested = False
                try:
                    async with self._lock:
                        await self._async_evaluate()
                except Exception:  # noqa: BLE001 - never let one bad pass stop the feature
                    _LOGGER.exception("Sigenergy Cloud Control: Price Spike Export decision failed")
                self._notify_listeners()
        finally:
            self._eval_running = False

    async def _async_evaluate(self) -> None:
        client = self.coordinator.client

        if self.ours and not _session_matches(client, self.session_end):
            await self._async_session_gone(client)

        if self.ours:
            if not self.settings["enabled"]:
                await self._async_stop(SPIKE_STOP_SWITCHED_OFF)
            elif not self.wants_export:
                await self._async_stop(self._end_reason or SPIKE_STOP_PRICE)
            elif self.soc is not None and self.soc <= self.settings["min_soc"]:
                self._soc_latched = True
                await self._async_stop(SPIKE_STOP_SOC)
            return

        if not (self.settings["enabled"] and self.wants_export):
            return
        if self._soc_latched or self._override_latched:
            return
        if self.soc is None:
            self._log_waiting("no usable SOC reading")
            return
        if self.soc <= self.settings["min_soc"]:
            self._log_waiting(f"SOC is at or below the {self.settings['min_soc']}% minimum")
            return

        replace = False
        if is_manual_running(client):
            running, end_str = describe_running(client)
            if not self.settings["take_over"]:
                self._log_waiting(f"manual control you started ({running} until {end_str}) is running - "
                                  "waiting for it to end")
                return
            _LOGGER.info(
                "Sigenergy Cloud Control: Price Spike Export taking over %s (until %s) - %s",
                running, end_str, self._context(),
            )
            replace = True

        await self._async_start(replace)

    @callback
    def _retry_start(self, _now) -> None:
        self._retry_unsub = None
        self._request_evaluate()

    async def _async_session_gone(self, client) -> None:
        """Our session isn't running any more: it ran out, or the user
        stopped or replaced it."""
        if is_manual_running(client):
            running, end_str = describe_running(client)
            _LOGGER.info(
                "Sigenergy Cloud Control: our discharge session was replaced (%s until %s is running now) - "
                "leaving it alone for the rest of this spike",
                running, end_str,
            )
            self._override_latched = True
        elif self.session_end and time.time() < self.session_end - SESSION_MATCH_TOLERANCE_SECONDS:
            _LOGGER.info(
                "Sigenergy Cloud Control: our discharge session was stopped early (in the mySigen app?) - "
                "not restarting it for the rest of this spike"
            )
            self._override_latched = True
        else:
            _LOGGER.info("Sigenergy Cloud Control: our discharge session has run out")
        self.ours = False
        self.session_end = None
        await self._async_save()

    def _log_waiting(self, why: str) -> None:
        """Log why we're not starting, once per reason (it's re-checked often)."""
        if self._waiting_logged != why:
            self._waiting_logged = why
            _LOGGER.info("Sigenergy Cloud Control: Price Spike Export not starting - %s (%s)", why, self._context())

    async def _async_start(self, replace: bool) -> None:
        wait = self._last_start + MIN_START_INTERVAL_SECONDS - time.time()
        if wait > 0:
            self._log_waiting("the last start was less than a minute ago - trying again shortly")
            if self._retry_unsub is None:
                self._retry_unsub = async_call_later(self.hass, wait, self._retry_start)
            return
        previous_start, self._last_start = self._last_start, time.time()
        rearm = self._notified_start
        _LOGGER.info(
            "Sigenergy Cloud Control: Price Spike Export %s discharging at %s for %d min - %s",
            "re-arming:" if rearm else "starting:", self._describe_power(),
            self.settings["duration"], self._context(),
        )
        try:
            await async_start_manual_control(
                self.hass, self.coordinator, MANUAL_ACTION_DISCHARGING,
                self.settings["duration"], self.settings["power"], replace_running=replace,
            )
        except ServiceValidationError as err:
            # Refused before anything was sent (a manual control started
            # since the last poll), so it doesn't count as a start.
            self._last_start = previous_start
            self._log_waiting(f"start refused: {err}")
            return
        except HomeAssistantError as err:
            # Sigenergy rejected it. Tried again on the next price, SOC or
            # station update, but not within MIN_START_INTERVAL_SECONDS.
            self._log_waiting(f"start failed: {err}")
            return

        self.ours = True
        self.session_end = self.coordinator.client.manual_end_time
        self._waiting_logged = None
        self._end_reason = None
        await self._async_save()

        data = self._event_data()
        data["rearm"] = rearm
        self.hass.bus.async_fire(EVENT_SPIKE_STARTED, data)
        if not rearm:
            self._notified_start = True
            await self._async_notify(
                "Price spike export started",
                f"Discharging at {self._describe_power()} - price {self._fmt_price(self.price)}, "
                f"threshold {self._fmt_price(self.settings['threshold'])}, SOC {self._fmt_soc()}.",
            )

    async def _async_stop(self, reason: str) -> None:
        """Stop the session - only after checking with the cloud that it's
        still ours."""
        client = self.coordinator.client
        _LOGGER.info("Sigenergy Cloud Control: Price Spike Export stopping (%s) - %s", reason, self._context())
        async with self.coordinator.manual_lock:
            await self.hass.async_add_executor_job(client.fetch_manual_control)
            still_ours = _session_matches(client, self.session_end)
            if still_ours:
                ok = await self.hass.async_add_executor_job(client.stop_manual_control)
        if not still_ours:
            # Ended or replaced since the last check - not ours to stop.
            await self._async_session_gone(client)
            return
        if not ok:
            _LOGGER.error(
                "Sigenergy Cloud Control: couldn't stop the price spike session - will try again on the next "
                "update; it ends by itself at %s anyway", _local_hm(self.session_end),
            )
            return
        self.ours = False
        self.session_end = None
        self.last_stop_reason = reason
        await self._async_save()
        await self.coordinator.async_manual_control_sent()

        data = self._event_data()
        data["reason"] = reason
        self.hass.bus.async_fire(EVENT_SPIKE_STOPPED, data)
        await self._async_notify(
            "Price spike export stopped",
            f"Reason: {reason.replace('_', ' ')} - price {self._fmt_price(self.price)}, SOC {self._fmt_soc()}.",
        )

    async def _async_notify(self, title: str, message: str) -> None:
        if not self.notify_action:
            return
        domain, _, service = self.notify_action.partition(".")
        try:
            await self.hass.services.async_call(domain, service, {"title": title, "message": message})
        except Exception as err:  # noqa: BLE001 - a broken notifier mustn't stop the feature
            _LOGGER.warning("Sigenergy Cloud Control: notify action %s failed: %s", self.notify_action, err)

    # ------------------------------------------------------------- display
    def _event_data(self) -> dict:
        return {
            "station_id": self.station_id,
            "price": self.price,
            "threshold": self.settings["threshold"],
            "soc": self.soc,
            "power_kw": self.settings["power"],
            "duration_min": self.settings["duration"],
        }

    def _describe_power(self) -> str:
        power = self.settings["power"]
        return f"{power:.1f} kW" if power else "no power limit"

    def _fmt_price(self, value) -> str:
        if value is None:
            return "unknown"
        return f"{value:g} {self.price_unit}" if self.price_unit else f"{value:g}"

    def _fmt_soc(self) -> str:
        return "unknown" if self.soc is None else f"{self.soc:g}%"

    def _context(self) -> str:
        return (f"price {self._fmt_price(self.price)}, threshold {self._fmt_price(self.settings['threshold'])}, "
                f"SOC {self._fmt_soc()}")

    @property
    def attributes(self) -> dict:
        def ts(epoch):
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat() if epoch else None
        return {
            "current_price": self.price,
            "threshold": self.settings["threshold"],
            "soc": self.soc,
            "spike_started": ts(self.spike_started),
            "hold_ends": ts(self.hold_ends),
            "last_stop_reason": self.last_stop_reason,
        }
