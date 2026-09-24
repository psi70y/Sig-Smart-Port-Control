"""Constants for the Sigenergy Smart Port integration."""

from homeassistant.const import Platform

DOMAIN = "sigen_smartport"

# Each config entry is one of these "kinds". Existing entries created before
# this distinction existed have no CONF_DEVICE_KIND stored at all - treat
# that as DEVICE_KIND_SMART_PORT for backward compatibility (see
# _get_device_kind in __init__.py).
CONF_DEVICE_KIND = "device_kind"
DEVICE_KIND_SMART_PORT = "smart_port"
DEVICE_KIND_AC_CHARGER = "ac_charger"

PLATFORMS_SMART_PORT = [Platform.SWITCH, Platform.SELECT, Platform.BUTTON]
PLATFORMS_AC_CHARGER = [Platform.SENSOR, Platform.SELECT, Platform.SWITCH, Platform.NUMBER]

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
