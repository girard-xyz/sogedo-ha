# Sogedo Water for Home Assistant

Home Assistant integration that reads your daily water consumption from
[mon-compte.sogedo.fr](https://mon-compte.sogedo.fr) and exposes it to the
Energy Dashboard.

## Features

- **Daily consumption** sensor (`sensor.sogedo_water_daily`) — water used on the
  most recent completed day (J-1), in m³.
- **Cumulative consumption** sensor (`sensor.sogedo_water_cumulative`) — total
  meter index, `total_increasing`.
- **Water history** (`sensor.sogedo_water_consumption`) — a statistics-only
  history series backfilled with your full consumption history. Connect this
  one to the Energy Dashboard's **mains water** source.
- **Water cost history** (`sensor.sogedo_water_cost`) — a statistics-only cost
  series (consumption × your Energy Dashboard water price, read automatically
  at backfill time). Set it as the water source's **Coût** (`stat_cost`).
- **Refresh history** button (`button.sogedo_actualiser_l_historique`) — re-run
  the backfill on demand (idempotent, safe to press any time).
- Backfills your full water history on first setup (best-effort; a failure
  never breaks the integration).
- Updates every 6 hours (Sogedo publishes data daily).
- Auto-triggers an in-place re-auth if the token expires (entities preserved).

## Installation

1. Add this repository to HACS (Custom repositories → `https://github.com/girard-xyz/sogedo-ha` → Integration) and install.
2. Restart Home Assistant.
3. Add the **Sogedo Water** integration via Settings → Devices & Services.
4. Follow the authorization flow: click the link, log in to Sogedo, copy the
   `code=...` value from the redirect URL, and paste it back.

## Energy Dashboard

Settings → Energy → Water sources → **mains water** → select
`sensor.sogedo_water_consumption`, and set the **Coût** statistic to
`sensor.sogedo_water_cost`.

The backfill writes running cumulatives of the daily consumption and cost as
statistics `sum`, so the Energy Dashboard shows one coherent consumption (and
cost) value per day — including backfilled history. The water price is read
from your Energy Dashboard water source config (`number_energy_price`) at
backfill time. To re-run the backfill (e.g. after changing the price), press
the **Actualiser l'historique** button.

## Notes

Sogedo uses Azure AD B2C and disables device-code and username/password
(ROPC) flows, so setup requires the one-time interactive authorization-code
flow described above. Your Sogedo password is never stored — only a refresh
token in Home Assistant's config entry.
