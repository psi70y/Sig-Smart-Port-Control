"""Constants for the Sigenergy Smart Port integration."""

from homeassistant.const import Platform

DOMAIN = "sigen_smartport"

PLATFORMS = [Platform.SWITCH, Platform.SELECT]

CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
CONF_BASE_URL = "base_url"
CONF_AUTH_HEADER = "auth_header"
CONF_USER_DEVICE_ID = "user_device_id"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_BASE_URL = "https://api-aus.sigencloud.com"
DEFAULT_AUTH_HEADER = "Basic c2lnZW46c2lnZW4="
DEFAULT_USER_DEVICE_ID = "1770954624439"
DEFAULT_LOAD_PATH = "1"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# Guard rail so the wizard/options form can't be set low enough to risk
# tripping Sigen's cloud session limits again.
MIN_SCAN_INTERVAL = 30

MODE_AUTO = "Auto (Sig Schedule)"
MODE_MANUAL = "Manual"
