"""The Sigenergy Cloud Control integration (domain sigen_smartport, formerly
named Sigenergy Smart Port)."""

import asyncio
import logging
import time
from datetime import datetime, timedelta

# HA 2026.9 replaced voluptuous with probatio (same API).
# Fall back so older HA versions still load.
try:
    import probatio as vol
except ImportError:  # HA < 2026.9
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, CONF_USERNAME, CONF_PASSWORD
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    PLATFORMS_SMART_PORT,
    PLATFORMS_AC_CHARGER,
    CONF_DEVICE_KIND,
    DEVICE_KIND_SMART_PORT,
    DEVICE_KIND_AC_CHARGER,
    CONF_STATION_ID,
    CONF_LOAD_PATH,
    CONF_CHARGER_SN,
    CONF_BASE_URL,
    CONF_AUTH_HEADER,
    CONF_USER_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_PROFILE_REFRESH_DAYS,
    CONF_SPIKE_ENABLED,
    CONF_SPIKE_NOTIFY_ACTION,
    CONF_SPIKE_PRICE_ENTITY,
    CONF_SPIKE_PRICE_UNIT,
    CONF_SPIKE_SOC_ENTITY,
    CONF_OFF_GRID_CONTROL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PROFILE_REFRESH_DAYS,
    DEFAULT_BASE_URL,
    GRID_MODE_SUFFIX,
    GRID_STATUS_OFF_GRID,
    GRID_STATUS_ON_GRID,
    GRID_STATUS_RECONNECTING,
    MANUAL_ACTION_KEYS,
    MANUAL_DURATION_DEFAULT,
    MANUAL_DURATION_MAX,
    MANUAL_DURATION_MIN,
    MANUAL_POWER_LIMIT_MAX,
    MANUAL_POWER_LIMIT_MIN,
    SERVICE_START_MANUAL_CONTROL,
    SERVICE_STOP_MANUAL_CONTROL,
)
from .manual_control import (
    ManualControlSettings,
    async_start_manual_control,
    async_stop_manual_control,
    manual_control_store,
)
from .price_spike import (
    PriceSpikeController,
    async_find_device,
    async_remove_spike_entities,
    async_stop_orphaned_session,
    price_spike_store,
)
from .sigen_api import SigenSmartLoadClient, SigenAcChargerClient

_LOGGER = logging.getLogger(__name__)

# Bumped only if the persisted token file's shape ever changes.
TOKEN_STORAGE_VERSION = 1
# Bumped only if the persisted AC charger settings file's shape ever changes.
AC_CHARGER_STORAGE_VERSION = 1

# hass.data key: {station_id: entry_id} of the one entry per station that
# owns the station-wide Energy Profile select + refresh button (see
# _claim_station_profile).
STATION_PROFILE_OWNERS = f"{DOMAIN}_station_profile_owners"

# Refresh this long after Instant Manual Control's end time, so its sensors
# show it ended without waiting for the next regular poll. The small delay
# gives the cloud time to report it as finished.
MANUAL_END_REFRESH_DELAY_SECONDS = 20

# Refresh this long after an off-grid / reconnect command, so the Grid
# Connection sensor shows the result without waiting for the next poll.
# In the capture, going off-grid took ~3s and reconnecting ~14s.
GRID_SWITCH_REFRESH_DELAY_SECONDS = 30

# Setup is UI-only (config entries); async_setup exists just to register
# the integration's actions.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

START_MANUAL_CONTROL_SCHEMA = vol.Schema({
    **cv.TARGET_SERVICE_FIELDS,
    vol.Required("action"): vol.In(list(MANUAL_ACTION_KEYS)),
    vol.Optional("duration", default=MANUAL_DURATION_DEFAULT): vol.All(
        vol.Coerce(int), vol.Range(min=MANUAL_DURATION_MIN, max=MANUAL_DURATION_MAX)
    ),
    vol.Optional("power_limit"): vol.All(
        vol.Coerce(float), vol.Range(min=MANUAL_POWER_LIMIT_MIN, max=MANUAL_POWER_LIMIT_MAX)
    ),
    vol.Optional("replace_running", default=False): cv.boolean,
})
STOP_MANUAL_CONTROL_SCHEMA = vol.Schema({**cv.TARGET_SERVICE_FIELDS})


def _ac_charger_store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    """Per-entry file for AC charger values the cloud can't give back to us,
    kept separate from the token file so auth storage is never touched."""
    return Store(hass, AC_CHARGER_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_ac_charger")


def _ensure_default_log_level() -> None:
    """Default this integration's loggers to INFO so login/refresh/token
    events are visible out of the box, without requiring the user to add
    a `logger:` override in configuration.yaml.

    Only applies if the user hasn't already explicitly set a level for
    these loggers - NOTSET means "never touched, just inheriting a
    parent/root default" - so a deliberate user override (e.g. silencing
    this integration, or setting it to debug) is always respected and
    never touched here. HA's own guidance discourages integrations from
    unconditionally overriding user-controlled logging preferences, hence
    the NOTSET check rather than always forcing the level.
    """
    for logger_name in (__name__, f"{__name__}.sigen_api"):
        logger = logging.getLogger(logger_name)
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


async def _async_update_station_profile(hass: HomeAssistant, client, profile_refresh_seconds: float) -> None:
    """Read the station's current Energy Profile, and periodically re-fetch
    the full list of selectable profiles/modes too.

    Deliberately not fatal to the coordinator if it has trouble - the
    device's own entities should keep working even if this optional
    station-level read fails. The list re-fetch is a safety net alongside
    the manual "Refresh Energy Profiles" button, in case new profiles were
    created via the mySigen app/web portal - infrequent by default
    (profile_refresh_seconds, default 30 days) since the list rarely changes.
    """
    await hass.async_add_executor_job(client.fetch_current_profile)
    await hass.async_add_executor_job(client.fetch_manual_control)
    await hass.async_add_executor_job(client.fetch_grid_status)

    fetched_at = client.profile_options_fetched_at
    if fetched_at is None or (time.time() - fetched_at) >= profile_refresh_seconds:
        await hass.async_add_executor_job(client.fetch_profile_options)


def _claim_station_profile(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Return True if this entry should own its station's Energy Profile
    entities, claiming them if nobody else has.

    The Energy Profile is station-wide, so with several entries on the same
    station (e.g. two Smart Port loads, or a Smart Port load plus an AC
    charger) only one of them may create the select + button - otherwise HA
    rejects the duplicates' unique IDs and every entry polls the same
    profile. The first entry set up claims it; a plain reload keeps its
    claim. The claim only moves when the owner is removed or disabled (see
    _release_station_profile), or if the owner no longer exists.
    """
    owners = hass.data.setdefault(STATION_PROFILE_OWNERS, {})
    station_id = str(entry.data[CONF_STATION_ID])
    owner_id = owners.get(station_id)
    if owner_id and owner_id != entry.entry_id:
        owner = hass.config_entries.async_get_entry(owner_id)
        if owner is not None and owner.disabled_by is None:
            return False
    owners[station_id] = entry.entry_id
    return True


def _release_station_profile(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give up this entry's Energy Profile claim (if it has one) and reload
    the other loaded entries on the same station so one of them takes over."""
    owners = hass.data.get(STATION_PROFILE_OWNERS, {})
    station_id = str(entry.data[CONF_STATION_ID])
    if owners.get(station_id) != entry.entry_id:
        return
    owners.pop(station_id)
    for other in hass.config_entries.async_entries(DOMAIN):
        if (other.entry_id != entry.entry_id
                and str(other.data.get(CONF_STATION_ID)) == station_id
                and other.state is ConfigEntryState.LOADED):
            _LOGGER.info(
                "Sigenergy Cloud Control: handing station %s Energy Profile over to entry '%s'",
                station_id, other.title,
            )
            hass.async_create_task(hass.config_entries.async_reload(other.entry_id))


class _StationCoordinatorMixin:
    """Instant Manual Control and off-grid handling shared by both
    coordinator types. Only used by the entry that owns the station's
    Energy Profile."""

    # ManualControlSettings for the owning entry, None otherwise.
    manual_settings = None
    # PriceSpikeController when this entry owns the station and Price Spike
    # Export is turned on in Configure, None otherwise.
    price_spike = None
    # True when this entry owns the station and Off-Grid Control is turned
    # on in Configure, so the Grid Mode select is created.
    off_grid_control = False
    _manual_end_unsub = None
    _manual_lock = None
    _grid_refresh_unsub = None

    @property
    def manual_lock(self) -> asyncio.Lock:
        """Held while a manual control start/stop is being sent, so only
        one runs at a time for this station."""
        if self._manual_lock is None:
            self._manual_lock = asyncio.Lock()
        return self._manual_lock

    def _manual_control_data(self) -> dict:
        return {
            "manual_enabled": self.client.manual_enabled,
            "manual_mode": self.client.manual_mode,
            "manual_end_time": self.client.manual_end_time,
        }

    @callback
    def _schedule_manual_end_refresh(self) -> None:
        """Refresh just after manual control's end time (see
        MANUAL_END_REFRESH_DELAY_SECONDS)."""
        self.cancel_manual_end_refresh()
        end_time = self.client.manual_end_time
        if not self.client.manual_enabled or not end_time:
            return
        when = end_time + MANUAL_END_REFRESH_DELAY_SECONDS
        if when <= time.time():
            # Already past - the next regular poll picks it up.
            return
        self._manual_end_unsub = async_track_point_in_utc_time(
            self.hass, self._async_manual_end_reached, dt_util.utc_from_timestamp(when)
        )
        _LOGGER.debug(
            "Sigenergy Cloud Control: will re-check manual control at %s",
            datetime.fromtimestamp(when).strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def _async_manual_end_reached(self, _now) -> None:
        self._manual_end_unsub = None
        _LOGGER.debug("Sigenergy Cloud Control: manual control end time reached, refreshing")
        await self.async_request_refresh()

    async def async_manual_control_sent(self) -> None:
        """After a start/stop, show the new state straight away from what
        was sent, then refresh to pick up the cloud's own end time. The
        refresh alone can lag up to 10s, since HA spaces out back-to-back
        refresh requests (e.g. Stop pressed right after Start)."""
        self.async_show_manual_control_state()
        await self.async_request_refresh()

    @callback
    def async_show_manual_control_state(self) -> None:
        """Pass the client's current manual control state to the entities
        now, without waiting for the next poll."""
        self.async_set_updated_data({**self.data, **self._manual_control_data()})
        self._schedule_manual_end_refresh()

    @callback
    def cancel_manual_end_refresh(self) -> None:
        if self._manual_end_unsub:
            self._manual_end_unsub()
            self._manual_end_unsub = None

    def _grid_data(self) -> dict:
        return {
            "grid_status": self.client.grid_status,
            "grid_control_supported": self.client.grid_control_supported,
        }

    async def async_set_off_grid(self, off_grid: bool) -> None:
        """Send the off-grid / reconnect command, show the expected state
        straight away, and re-check it once the switch should be done."""
        status = self.client.grid_status
        if status == GRID_STATUS_RECONNECTING:
            raise HomeAssistantError(
                "The station is still reconnecting to the grid. Try again once it's back on-grid."
            )
        if status == (GRID_STATUS_OFF_GRID if off_grid else GRID_STATUS_ON_GRID):
            _LOGGER.info(
                "Sigenergy Cloud Control: station is already %s - nothing sent",
                "off-grid" if off_grid else "on-grid",
            )
            return
        ok = await self.hass.async_add_executor_job(self.client.set_off_grid, off_grid)
        if not ok:
            raise HomeAssistantError("Sigenergy rejected the off-grid command. See the log for details.")
        # Best guess until the delayed refresh reads the real state back.
        self.client.grid_status = GRID_STATUS_OFF_GRID if off_grid else GRID_STATUS_RECONNECTING
        self.async_set_updated_data({**self.data, **self._grid_data()})
        self.cancel_grid_refresh()
        self._grid_refresh_unsub = async_call_later(
            self.hass, GRID_SWITCH_REFRESH_DELAY_SECONDS, self._async_grid_refresh_due
        )

    async def _async_grid_refresh_due(self, _now) -> None:
        self._grid_refresh_unsub = None
        await self.async_request_refresh()

    @callback
    def cancel_grid_refresh(self) -> None:
        if self._grid_refresh_unsub:
            self._grid_refresh_unsub()
            self._grid_refresh_unsub = None


class SigenCoordinator(_StationCoordinatorMixin, DataUpdateCoordinator):
    """Polls one Smart Port load (plus its station's energy profile) and
    hands the result to its entities."""

    def __init__(self, hass: HomeAssistant, client: SigenSmartLoadClient, name: str,
                 update_interval: timedelta, profile_refresh_seconds: float,
                 owns_station_profile: bool):
        super().__init__(hass, _LOGGER, name=f"sigen_smartport_{name}", update_interval=update_interval)
        self.client = client
        self.profile_refresh_seconds = profile_refresh_seconds
        # Only the station's Energy Profile owner polls it and creates its
        # entities - see _claim_station_profile.
        self.owns_station_profile = owns_station_profile

    async def _async_update_data(self):
        ok = await self.hass.async_add_executor_job(self.client.refresh)
        if not ok:
            raise UpdateFailed("Could not read status from Sigen cloud")

        if self.owns_station_profile:
            await _async_update_station_profile(self.hass, self.client, self.profile_refresh_seconds)
            self._schedule_manual_end_refresh()

        return {
            "control_mode": self.client.control_mode,
            "manual_switch": self.client.manual_switch,
            "energy_mode": self.client.current_energy_mode,
            "energy_profile_id": self.client.current_profile_id,
            **self._manual_control_data(),
            **self._grid_data(),
        }


class SigenAcChargerCoordinator(_StationCoordinatorMixin, DataUpdateCoordinator):
    """Polls one AC EV charger and hands the result to its sensors."""

    def __init__(self, hass: HomeAssistant, client: SigenAcChargerClient, name: str,
                 update_interval: timedelta, store: Store, profile_refresh_seconds: float,
                 owns_station_profile: bool, saved_grid_power=None):
        super().__init__(hass, _LOGGER, name=f"sigen_ac_charger_{name}", update_interval=update_interval)
        self.client = client
        self.profile_refresh_seconds = profile_refresh_seconds
        # Only the station's Energy Profile owner polls it and creates its
        # entities - see _claim_station_profile.
        self.owns_station_profile = owns_station_profile
        self._store = store
        self._saved_grid_power = saved_grid_power

    async def async_save_grid_power(self) -> None:
        """Persist the last non-zero Grid Charging max power, so re-enabling
        Grid Charging after an HA restart still uses it (the cloud reports 0
        while Grid Charging is off). Only writes to disk when it changed."""
        power = self.client.last_grid_power
        if power and power != self._saved_grid_power:
            await self._store.async_save({"last_grid_power": power})
            self._saved_grid_power = power
            _LOGGER.debug("Sigen AC charger: saved grid charging max power %s kW to disk", power)

    async def _async_update_data(self):
        ok = await self.hass.async_add_executor_job(self.client.refresh)
        if not ok:
            raise UpdateFailed("Could not read AC charger status from Sigen cloud")
        await self.async_save_grid_power()

        if self.owns_station_profile:
            await _async_update_station_profile(self.hass, self.client, self.profile_refresh_seconds)
            self._schedule_manual_end_refresh()

        return {
            "charge_status_code": self.client.charge_status_code,
            "charge_mode": self.client.charge_mode,
            "charge_mode_settings": self.client.charge_mode_settings,
            "last_set_current": self.client.last_set_current,
            "max_current": self.client.max_current,
            "monthly_energy": self.client.monthly_energy,
            "weekly_energy": self.client.weekly_energy,
            "lifetime_energy": self.client.lifetime_energy,
            "energy_mode": self.client.current_energy_mode,
            "energy_profile_id": self.client.current_profile_id,
            **self._manual_control_data(),
            **self._grid_data(),
        }


def _get_device_kind(entry: ConfigEntry) -> str:
    """Entries created before AC charger support have no device_kind stored -
    they are always Smart Port loads."""
    return entry.data.get(CONF_DEVICE_KIND, DEVICE_KIND_SMART_PORT)


def _get_platforms(entry: ConfigEntry) -> list:
    if _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER:
        return PLATFORMS_AC_CHARGER
    return PLATFORMS_SMART_PORT


def _coordinators_for_call(hass: HomeAssistant, call: ServiceCall) -> list:
    """Find the station coordinators an action call targets. Accepts Sigen
    Station devices, or any entity on one."""
    device_ids = set(call.data.get(ATTR_DEVICE_ID) or [])
    entity_ids = call.data.get(ATTR_ENTITY_ID) or []
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    ent_reg = er.async_get(hass)
    for entity_id in entity_ids:
        ent = ent_reg.async_get(entity_id)
        if ent and ent.device_id:
            device_ids.add(ent.device_id)
    if not device_ids:
        raise ServiceValidationError("Choose a Sigen Station device as the target")

    dev_reg = dr.async_get(hass)
    coordinators = []
    for device_id in device_ids:
        device = dev_reg.async_get(device_id)
        station_id = None
        for domain, identifier in (device.identifiers if device else ()):
            if domain == DOMAIN and identifier.startswith("station_"):
                station_id = identifier[len("station_"):]
        if station_id is None:
            raise ServiceValidationError(
                f"'{device.name if device else device_id}' is not a Sigen Station device"
            )
        coordinator = next(
            (c for c in hass.data.get(DOMAIN, {}).values()
             if c.owns_station_profile and c.client.station_id == station_id),
            None,
        )
        if coordinator is None:
            raise ServiceValidationError(f"Sigen Station {station_id} is not loaded")
        coordinators.append(coordinator)
    return coordinators


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Instant Manual Control actions."""

    async def _async_start(call: ServiceCall) -> None:
        for coordinator in _coordinators_for_call(hass, call):
            await async_start_manual_control(
                hass,
                coordinator,
                MANUAL_ACTION_KEYS[call.data["action"]],
                call.data["duration"],
                call.data.get("power_limit"),
                replace_running=call.data["replace_running"],
            )

    async def _async_stop(call: ServiceCall) -> None:
        for coordinator in _coordinators_for_call(hass, call):
            await async_stop_manual_control(hass, coordinator)

    hass.services.async_register(
        DOMAIN, SERVICE_START_MANUAL_CONTROL, _async_start, schema=START_MANUAL_CONTROL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_MANUAL_CONTROL, _async_stop, schema=STOP_MANUAL_CONTROL_SCHEMA
    )
    return True


async def _async_setup_manual_control(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    """Give the station owner its saved manual control settings, and stop
    the end-time refresh timer when the entry unloads."""
    entry.async_on_unload(coordinator.cancel_manual_end_refresh)
    if not coordinator.owns_station_profile:
        return
    settings = ManualControlSettings(hass, entry.data[CONF_STATION_ID])
    await settings.async_load()
    coordinator.manual_settings = settings


async def _async_setup_price_spike(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    """Start Price Spike Export for the station owner if it's turned on in
    Configure. If it's off, remove its entities and stop any discharge
    session it left running."""
    if not coordinator.owns_station_profile:
        return
    station_id = entry.data[CONF_STATION_ID]
    options = entry.options
    if not (options.get(CONF_SPIKE_ENABLED) and options.get(CONF_SPIKE_PRICE_ENTITY)
            and options.get(CONF_SPIKE_SOC_ENTITY)):
        async_remove_spike_entities(hass, entry.entry_id, station_id)
        await async_stop_orphaned_session(hass, coordinator, station_id)
        return
    controller = PriceSpikeController(
        hass, coordinator, station_id,
        options[CONF_SPIKE_PRICE_ENTITY], options[CONF_SPIKE_SOC_ENTITY],
        options.get(CONF_SPIKE_NOTIFY_ACTION),
        options.get(CONF_SPIKE_PRICE_UNIT),
    )
    await controller.async_load()
    coordinator.price_spike = controller


@callback
def _setup_off_grid_control(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    """Decide whether the station owner gets the Grid Mode select. With
    Off-Grid Control turned off in Configure, remove the select so it isn't
    left behind as unavailable."""
    entry.async_on_unload(coordinator.cancel_grid_refresh)
    if not coordinator.owns_station_profile:
        return
    coordinator.off_grid_control = bool(entry.options.get(CONF_OFF_GRID_CONTROL))
    if not coordinator.off_grid_control:
        ent_reg = er.async_get(hass)
        entity_id = ent_reg.async_get_entity_id(
            "select", DOMAIN, f"{entry.data[CONF_STATION_ID]}_{GRID_MODE_SUFFIX}"
        )
        if entity_id:
            ent_reg.async_remove(entity_id)


@callback
def _has_spike_device(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return async_find_device(hass, entry.entry_id, f"price_spike_{entry.data[CONF_STATION_ID]}") is not None


@callback
def _copy_station_area(hass: HomeAssistant, entry: ConfigEntry, had_spike_device: bool) -> None:
    """When the Price Spike Export device has just been created, put it in
    the station's area, so its entities keep the area they had before."""
    if had_spike_device or not entry.data.get(CONF_STATION_ID):
        return
    station_id = entry.data[CONF_STATION_ID]
    device = async_find_device(hass, entry.entry_id, f"price_spike_{station_id}")
    station = async_find_device(hass, entry.entry_id, f"station_{station_id}")
    if device and station and station.area_id and device.area_id is None:
        dr.async_get(hass).async_update_device(device.id, area_id=station.area_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Sigen Smart Port load or AC charger from a config entry."""
    _ensure_default_log_level()

    data = entry.data

    # Persist the auth token to disk, keyed to this specific config entry, so
    # a Home Assistant/Supervisor restart reuses the still-valid token
    # instead of forcing a brand new login every time. Frequent HA restarts
    # (updates, watchdog, addon restarts) were causing far more logins than
    # the ~12h token lifetime alone would suggest, which appears to be what
    # was tripping Sigen's cloud into force-logging-out the mySigen app/web
    # portal.
    store: Store = Store(hass, TOKEN_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_token")
    stored_token = await store.async_load()

    def _persist_token(token: str, expiry_epoch: float, refresh_token: str) -> None:
        # Called from the executor thread that performs the actual HTTP
        # login/refresh (see sigen_api.py) - hass.add_job is safe to call
        # from any thread and schedules the async save onto the event loop.
        hass.add_job(_save_token_to_disk(store, token, expiry_epoch, refresh_token))

    async def _save_token_to_disk(store: Store, token: str, expiry_epoch: float, refresh_token: str) -> None:
        await store.async_save({"token": token, "expiry": expiry_epoch, "refresh_token": refresh_token})
        expiry_str = datetime.fromtimestamp(expiry_epoch).strftime("%Y-%m-%d %H:%M:%S")
        _LOGGER.info(
            "Sigenergy Cloud Control: saved refreshed auth token to disk (valid until %s)", expiry_str
        )

    is_ac_charger = _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER

    if is_ac_charger:
        client = SigenAcChargerClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_STATION_ID],
            data[CONF_CHARGER_SN],
            _get_base_url(entry),
            data[CONF_AUTH_HEADER],
            data[CONF_USER_DEVICE_ID],
            on_token_change=_persist_token,
        )
    else:
        client = SigenSmartLoadClient(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_STATION_ID],
            data[CONF_LOAD_PATH],
            _get_base_url(entry),
            data[CONF_AUTH_HEADER],
            data[CONF_USER_DEVICE_ID],
            on_token_change=_persist_token,
        )

    if stored_token:
        client.restore_cached_token(
            stored_token.get("token"),
            stored_token.get("expiry"),
            stored_token.get("refresh_token"),
        )

    if is_ac_charger:
        ac_store = _ac_charger_store(hass, entry)
        saved = await ac_store.async_load() or {}
        saved_grid_power = saved.get("last_grid_power")
        # Seed the client with the saved value; the first poll overrides it
        # if Grid Charging is currently on (the cloud then reports the real one).
        client.last_grid_power = saved_grid_power
        ac_coordinator = SigenAcChargerCoordinator(
            hass,
            client,
            entry.unique_id or entry.entry_id,
            _get_scan_interval(entry),
            ac_store,
            _get_profile_refresh_seconds(entry),
            _claim_station_profile(hass, entry),
            saved_grid_power,
        )
        try:
            await ac_coordinator.async_config_entry_first_refresh()
        except Exception:
            # Don't sit on the Energy Profile claim while this entry can't load.
            _release_station_profile(hass, entry)
            raise
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ac_coordinator
        await _async_setup_manual_control(hass, entry, ac_coordinator)
        await _async_setup_price_spike(hass, entry, ac_coordinator)
        _setup_off_grid_control(hass, entry, ac_coordinator)
        had_spike_device = _has_spike_device(hass, entry)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_AC_CHARGER)
        if ac_coordinator.price_spike:
            _copy_station_area(hass, entry, had_spike_device)
            ac_coordinator.price_spike.async_start()
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        return True

    owns_station_profile = _claim_station_profile(hass, entry)

    coordinator = SigenCoordinator(
        hass,
        client,
        entry.unique_id or entry.entry_id,
        _get_scan_interval(entry),
        _get_profile_refresh_seconds(entry),
        owns_station_profile,
    )
    try:
        # The first poll also fetches the Energy Profile option list (the
        # user's saved profiles + built-in modes) if this entry owns it.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Don't sit on the claim while this entry can't load.
        _release_station_profile(hass, entry)
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await _async_setup_manual_control(hass, entry, coordinator)
    await _async_setup_price_spike(hass, entry, coordinator)
    _setup_off_grid_control(hass, entry, coordinator)
    had_spike_device = _has_spike_device(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_SMART_PORT)
    # Start reacting to prices only once its entities exist.
    if coordinator.price_spike:
        _copy_station_area(hass, entry, had_spike_device)
        coordinator.price_spike.async_start()

    # If the scan interval is changed later via the "Configure" button on
    # the integration entry, reload it so the new interval takes effect
    # immediately rather than needing a full HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _get_scan_interval(entry: ConfigEntry) -> timedelta:
    seconds = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    return timedelta(seconds=seconds)


def _get_base_url(entry: ConfigEntry) -> str:
    # Options (set later via Configure) take priority over the value saved
    # at initial setup, so changing region/base_url via Configure actually
    # takes effect on the next reload rather than being silently ignored.
    return entry.options.get(
        CONF_BASE_URL, entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    )


def _get_profile_refresh_seconds(entry: ConfigEntry) -> float:
    days = entry.options.get(
        CONF_PROFILE_REFRESH_DAYS,
        entry.data.get(CONF_PROFILE_REFRESH_DAYS, DEFAULT_PROFILE_REFRESH_DAYS),
    )
    return float(days) * 86400


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so changed options (scan interval, Price Spike
    Export settings, ...) take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator.price_spike:
        await coordinator.price_spike.async_shutdown()
    unloaded = await hass.config_entries.async_unload_platforms(entry, _get_platforms(entry))
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Disabling the entry that owns the station's Energy Profile hands
        # it to another entry on the same station. A plain reload keeps it.
        if entry.disabled_by is not None:
            _release_station_profile(hass, entry)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the persisted token file when the integration is fully removed
    (not just unloaded/reloaded)."""
    store: Store = Store(hass, TOKEN_STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_token")
    await store.async_remove()
    _release_station_profile(hass, entry)
    if _get_device_kind(entry) == DEVICE_KIND_AC_CHARGER:
        await _ac_charger_store(hass, entry).async_remove()
    # Manual control settings are per station - only remove them with the
    # station's last entry.
    station_id = str(entry.data[CONF_STATION_ID])
    if not any(
        other.entry_id != entry.entry_id and str(other.data.get(CONF_STATION_ID)) == station_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        await manual_control_store(hass, station_id).async_remove()
        await price_spike_store(hass, station_id).async_remove()
