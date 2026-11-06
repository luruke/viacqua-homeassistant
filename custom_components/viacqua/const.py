"""Constants for the Viacqua integration."""

from datetime import timedelta

DOMAIN = "viacqua"
MANUFACTURER = "Viacqua S.p.A."

# Data changes a few times a year (semi-annual readings, quarterly bills).
UPDATE_INTERVAL = timedelta(hours=12)

SERVICE_SUBMIT_READING = "submit_reading"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_READING = "reading"
