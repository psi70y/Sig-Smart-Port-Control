"""Constants for the Sigenergy Smart Port integration."""

from homeassistant.const import Platform

DOMAIN = "sigen_smartport"

PLATFORMS = [Platform.SWITCH, Platform.SELECT, Platform.BUTTON]

CONF_STATION_ID = "station_id"
CONF_LOAD_PATH = "load_path"
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
