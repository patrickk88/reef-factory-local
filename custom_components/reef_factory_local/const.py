"""Constants for Reef Factory Local (unofficial)."""
DOMAIN = "reef_factory_local"
CONF_SERIAL = "serial"
CONF_ALLOW_PUMP_ACTIONS = "allow_pump_actions"
MANUFACTURER = "Reef Factory"
# entities go unavailable when no data arrived for this long
STALE_SECONDS = 120
# upper limit for one manual refill started from Home Assistant
MAX_MANUAL_REFILL_ML = 1000
# cloud replacement entry
CONF_CLOUD = "cloud"
CONF_CLOUD_MODE = "cloud_mode"
CONF_UPSTREAM_IPS = "upstream_ips"
CLOUD_UNIQUE_ID = "cloud_replacement"
SIGNAL_NEW_CLOUD_DEVICE = "reef_factory_local_new_cloud_device"
