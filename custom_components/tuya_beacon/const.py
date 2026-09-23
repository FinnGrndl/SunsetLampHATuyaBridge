"""Constants for Tuya Beacon."""

from homeassistant.const import Platform

DOMAIN = "tuya_beacon"
CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"
DEFAULT_BASE_URL = "http://127.0.0.1:8099"
PLATFORMS = [Platform.LIGHT]
