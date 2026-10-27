"""Constants for the Sigenergy Cloud Control integration."""

from homeassistant.const import Platform

DOMAIN = "sigen_smartport"

# Each config entry is one of these "kinds". Existing entries created before
# this distinction existed have no CONF_DEVICE_KIND stored at all - treat
# that as DEVICE_KIND_SMART_PORT for backward compatibility (see
# _get_device_kind in __init__.py).
CONF_DEVICE_KIND = "device_kind"
DEVICE_KIND_SMART_PORT = "smart_port"
DEVICE_KIND_AC_CHARGER = "ac_charger"

PLATFORMS_SMART_PORT = [
    Platform.SWITCH, Platform.SELECT, Platform.BUTTON, Platform.SENSOR, Platform.NUMBER, Platform.BINARY_SENSOR,
]
PLATFORMS_AC_CHARGER = [
    Platform.SENSOR, Platform.SELECT, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON, Platform.BINARY_SENSOR,
]

CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_CHARGER_SN = "charger_sn"
CONF_BASE_URL = "base_url"
CONF_REGION = "region"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_PROFILE_REFRESH_DAYS = "profile_refresh_days"

# Confirmed against multiple independent open-source Sigenergy projects
# (sig-cloud-control, sigenergy-cloud, sigen on PyPI, sigenergy-ha) - these
# five regional API hosts appear consistently. "Logical" regions like
# Middle East/Africa and Latin America don't get their own subdomain; they
# route through eu/us respectively.
CUSTOM_REGION = "custom"
REGION_BASE_URLS = {
    "aus": "https://api-aus.sigencloud.com",
    "apac": "https://api-apac.sigencloud.com",
    "eu": "https://api-eu.sigencloud.com",
    "cn": "https://api-cn.sigencloud.com",
    "us": "https://api-us.sigencloud.com",
}
REGION_CHOICES = list(REGION_BASE_URLS.keys()) + [CUSTOM_REGION]
DEFAULT_REGION = "aus"  # matches this fork's original hardcoded default

DEFAULT_BASE_URL = REGION_BASE_URLS[DEFAULT_REGION]
DEFAULT_AUTH_HEADER = "Basic c2lnZW46c2lnZW4="
DEFAULT_USER_DEVICE_ID = "1770954624439"
DEFAULT_LOAD_PATH = "1"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
DEFAULT_PROFILE_REFRESH_DAYS = 30

# Guard rails so the wizard/options form can't be set low enough to risk
# tripping Sigen's cloud session limits again, or hammering the profile
# list endpoint unnecessarily.
MIN_SCAN_INTERVAL = 30
MIN_PROFILE_REFRESH_DAYS = 1

MODE_AUTO = "Auto (Sig Schedule)"
MODE_MANUAL = "Manual"

# AC charger "Charging Mode" - confirmed by round-trip capture (set via UI,
# read back from /device/charge/mode/ac) against a Sigen EVAC 22 4G T2 WH.
# Sigen AI Mode (likely chargeMode=2) is deliberately excluded: selecting it
# in the app requires a one-time setup flow before it can be saved, and no
# write for it has been captured yet. See EV_CHARGING_DEVELOPMENT.md.
AC_CHARGE_MODE_FAST = "Fast Charging"
AC_CHARGE_MODE_PV_SURPLUS = "PV Surplus Charging"
AC_CHARGE_MODE_VALUES = {
    AC_CHARGE_MODE_FAST: 0,
    AC_CHARGE_MODE_PV_SURPLUS: 1,
}
AC_CHARGE_MODE_LABELS = {value: label for label, value in AC_CHARGE_MODE_VALUES.items()}

# Other /device/charge/mode/ac fields - confirmed by write + read-back
# against an EVAC 22 (EU region). Sending the full current payload with one
# field changed leaves the others untouched.
AC_FIELD_BATTERY_BOOST = "enableFromPack"
AC_FIELD_CUTOFF_SOC = "cutoffSocFromPack"
AC_FIELD_GRID_CHARGING = "enableFromGrid"
AC_FIELD_MAX_GRID_POWER = "maxPowerFromGrid"
AC_CHARGE_SETTING_FIELDS = [
    "chargeMode",
    AC_FIELD_BATTERY_BOOST,
    AC_FIELD_CUTOFF_SOC,
    AC_FIELD_GRID_CHARGING,
    AC_FIELD_MAX_GRID_POWER,
]
# Range reported by GET /device/charge/mode/soc/range.
AC_CUTOFF_SOC_MIN = 5
AC_CUTOFF_SOC_MAX = 100
AC_MAX_GRID_POWER_KW = 22.0
# Grid Charging only turns on if a max power > 0 is sent with it (otherwise
# the cloud answers success but leaves it off), and turning it off forces
# max power to 0. This is used if no earlier non-zero value is known.
AC_FALLBACK_GRID_POWER_KW = 1.0

# Instant Manual Control - confirmed by network capture of the mySigen web
# app (PUT/GET /device/energy-profile/instant/manunal). Overrides the
# station's Energy Profile for a set time, then the profile resumes.
MANUAL_ACTION_CHARGING = "Charging"
MANUAL_ACTION_DISCHARGING = "Discharging"
MANUAL_ACTION_HOLD = "Hold Battery"
MANUAL_ACTION_SELF_CONSUMPTION = "Self-Consumption"
# Label -> the "mode" string the cloud expects.
MANUAL_ACTION_MODES = {
    MANUAL_ACTION_CHARGING: "0",
    MANUAL_ACTION_DISCHARGING: "1",
    MANUAL_ACTION_HOLD: "2",
    MANUAL_ACTION_SELF_CONSUMPTION: "3",
}
MANUAL_ACTION_LABELS = {mode: label for label, mode in MANUAL_ACTION_MODES.items()}
# Keys used by the start_manual_control action (lower-case, YAML-friendly).
MANUAL_ACTION_KEYS = {
    "charging": MANUAL_ACTION_CHARGING,
    "discharging": MANUAL_ACTION_DISCHARGING,
    "hold_battery": MANUAL_ACTION_HOLD,
    "self_consumption": MANUAL_ACTION_SELF_CONSUMPTION,
}
# Only these send a power limit; the others send "" like the app does.
MANUAL_ACTIONS_WITH_POWER_LIMIT = (MANUAL_ACTION_CHARGING, MANUAL_ACTION_DISCHARGING)
MANUAL_STATE_OFF = "Off"

# The app only accepts 1-1440 minutes (24 hours).
MANUAL_DURATION_MIN = 1
MANUAL_DURATION_MAX = 1440
MANUAL_DURATION_DEFAULT = 30
# 0 means no limit. The cloud's "no limit" value is the 32-bit max / 1000,
# the same one Energy Profile settings use for uncapped powers.
MANUAL_POWER_LIMIT_MIN = 0.0
MANUAL_POWER_LIMIT_MAX = 30.0
MANUAL_POWER_LIMIT_NONE = "4294967.295"

SERVICE_START_MANUAL_CONTROL = "start_manual_control"
SERVICE_STOP_MANUAL_CONTROL = "stop_manual_control"

# Off-grid control - confirmed by network capture of the mySigen web app
# (POST /device/gateway/ongrid-state/update, GET /device/gateway/gateway-status).
# onOffGridStatus as read from gateway-status. 1 was seen for ~14s while
# the gateway synchronised back onto the grid.
GRID_STATUS_ON_GRID = 0
GRID_STATUS_RECONNECTING = 1
GRID_STATUS_OFF_GRID = 2
GRID_STATE_ON_GRID = "On-Grid"
GRID_STATE_RECONNECTING = "Reconnecting"
GRID_STATE_OFF_GRID = "Off-Grid"
GRID_STATUS_LABELS = {
    GRID_STATUS_ON_GRID: GRID_STATE_ON_GRID,
    GRID_STATUS_RECONNECTING: GRID_STATE_RECONNECTING,
    GRID_STATUS_OFF_GRID: GRID_STATE_OFF_GRID,
}
# Options-flow key: the Grid Mode select is only created after opting in,
# since it physically disconnects the home from the grid.
CONF_OFF_GRID_CONTROL = "off_grid_control_enabled"
# Unique ID suffix of the Grid Mode select (after "{station_id}_"), so it
# can be removed again when the option is turned off.
GRID_MODE_SUFFIX = "grid_mode"

# Price Spike Export - force-discharge through Instant Manual Control while a
# price entity (from any other integration) is at or above a threshold.
# Options-flow keys, set on the entry that owns the station.
CONF_SPIKE_ENABLED = "price_spike_enabled"
CONF_SPIKE_PRICE_ENTITY = "price_spike_price_entity"
CONF_SPIKE_SOC_ENTITY = "price_spike_soc_entity"
CONF_SPIKE_NOTIFY_ACTION = "price_spike_notify_action"
# Shown on the threshold when the price entity doesn't report a unit itself.
CONF_SPIKE_PRICE_UNIT = "price_spike_price_unit"
SPIKE_OPTION_KEYS = (
    CONF_SPIKE_ENABLED, CONF_SPIKE_PRICE_ENTITY, CONF_SPIKE_PRICE_UNIT, CONF_SPIKE_SOC_ENTITY,
    CONF_SPIKE_NOTIFY_ACTION,
)

# Dashboard-tunable settings: defaults and ranges.
SPIKE_THRESHOLD_DEFAULT = 1.0
SPIKE_THRESHOLD_MIN = -100000.0
SPIKE_THRESHOLD_MAX = 100000.0
SPIKE_START_DELAY_DEFAULT = 0     # minutes
SPIKE_START_DELAY_MAX = 60
SPIKE_HOLD_TIME_DEFAULT = 10      # minutes
SPIKE_HOLD_TIME_MAX = 120
SPIKE_POWER_DEFAULT = 10.0        # kW, 0 = no limit (as for manual control)
SPIKE_DURATION_DEFAULT = 30       # minutes per manual control session
SPIKE_MIN_SOC_DEFAULT = 20        # %

EVENT_SPIKE_STARTED = f"{DOMAIN}_price_spike_export_started"
EVENT_SPIKE_STOPPED = f"{DOMAIN}_price_spike_export_stopped"

# Reasons the feature stops discharging (event data and attributes).
SPIKE_STOP_PRICE = "price_below_threshold"
SPIKE_STOP_SOC = "soc_at_minimum"
SPIKE_STOP_SWITCHED_OFF = "switched_off"
SPIKE_STOP_FEATURE_DISABLED = "feature_disabled"

# Unique ID suffixes of every Price Spike Export entity (after "{station_id}_"),
# so they can be removed again when the feature is turned off in Configure.
SPIKE_ENTITY_SUFFIXES = {
    "switch": ("price_spike_export", "price_spike_take_over"),
    "number": (
        "price_spike_threshold", "price_spike_start_delay", "price_spike_hold_time",
        "price_spike_discharge_power", "price_spike_session_duration", "price_spike_min_soc",
    ),
    "binary_sensor": ("price_spike_active", "price_spike_discharging"),
}
