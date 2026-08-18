# Sogedo Water for Home Assistant

Home Assistant integration that reads your daily water consumption from
[mon-compte.sogedo.fr](https://mon-compte.sogedo.fr) and exposes it to the
Energy Dashboard.

## Features

- **Daily consumption** sensor (`sensor.sogedo_water_daily`) — water used on the
  most recent completed day (J-1), in m³.
- **Cumulative consumption** sensor (`sensor.sogedo_water_cumulative`) — total
  meter index, `total_increasing`. Connect this one to the Energy Dashboard's
  **mains water** source.
- Backfills up to 365 days of history on first setup so the Energy Dashboard
  shows prior consumption.
- Updates every 6 hours (Sogedo publishes data daily).

## Installation

1. Add this repository to HACS (Custom repositories → `https://github.com/girard-xyz/sogedo-ha` → Integration) and install.
2. Restart Home Assistant.
3. Add the **Sogedo Water** integration via Settings → Devices & Services.
4. Follow the authorization flow: click the link, log in to Sogedo, copy the
   `code=...` value from the redirect URL, and paste it back.

## Energy Dashboard

Settings → Energy → Water sources → **mains water** → select
`sensor.sogedo_water_cumulative`.

## Notes

Sogedo uses Azure AD B2C and disables device-code and username/password
(ROPC) flows, so setup requires the one-time interactive authorization-code
flow described above. Your Sogedo password is never stored — only a refresh
token in Home Assistant's config entry.
