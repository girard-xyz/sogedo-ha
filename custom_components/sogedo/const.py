"""Constants for the Sogedo water integration."""

from homeassistant.const import Platform

DOMAIN = "sogedo"
PLATFORMS = [Platform.SENSOR]

# Config entry keys
CONF_REFRESH_TOKEN = "refresh_token"
CONF_SUBSCRIPTION_ID = "subscription_id"
CONF_SUBSCRIPTION_NAME = "subscription_name"

# Poll interval: Sogedo updates consumption daily (J-1)
SCAN_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours

# Backfill range on first run
BACKFILL_DAYS = 365

# Default Home Assistant timezone date offset
UPDATE_DATE_OFFSET = 1  # data is published for the previous day (J-1)
