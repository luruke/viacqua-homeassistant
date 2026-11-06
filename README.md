<img src="custom_components/viacqua/brand/logo.png" height="48" alt="Viacqua">

# Viacqua for Home Assistant (unofficial)

Custom integration for **Viacqua**, the water utility of Vicenza, built on the customer
area at <https://sol.viacqua.it>. Not affiliated with Viacqua.

> The portal only exposes **meter readings roughly every 6 months** and **quarterly bills**.
> There is no daily or hourly data. For live consumption, pair this with a water meter
> sensor (ESPHome pulse/reed sensor, AI-on-the-edge, ...).

## What you get

**Energy dashboard:** the full reading history (back to contract start) is imported as
the external statistic `viacqua:water_<contract>` ("Viacqua acqua …"). Add it under
*Settings → Dashboards → Energy → Water consumption*. Each reading's consumption shows up
on the day the meter was read.

**Sensors** (one device per contract):

| Sensor | Notes |
|---|---|
| Meter reading | m³, latest index; attributes: reading date/type, meter serial, allowed self-reading range |
| Last reading date | |
| Last period consumption | m³ between the last two readings |
| Daily average consumption | L/day over the last period |
| Yearly consumption | m³/year, from readings ~12 months apart, normalised to 365 days |
| Latest bill amount / due date | attributes: number, period, paid, outstanding |
| Outstanding balance | € still to pay over all bills; attribute lists unpaid bills |
| Unpaid bills | count |
| Contract annual volume, Contract status | diagnostic |

**Service** `viacqua.submit_reading` sends a self reading (*autolettura*). This is a
real submission to Viacqua. The value must fall within the range in the meter
sensor's `self_reading_min`/`self_reading_max` attributes.

```yaml
action: viacqua.submit_reading
data:
  config_entry_id: <your entry>
  reading: 870
```

Data is refreshed every 12 hours. Diagnostics download is supported, with personal data redacted.

## Install

**HACS:** *HACS → ⋮ → Custom repositories →* `https://github.com/luruke/viacqua-homeassistant`
(type *Integration*), install **Viacqua**, restart Home Assistant.

**Manual:** copy `custom_components/viacqua` into your HA `config/custom_components/` and restart.

Then go to *Settings → Devices & services → Add integration → Viacqua* and enter the username
and password of the Viacqua customer area.

## Logo

The Viacqua logo in `custom_components/viacqua/brand/` is a trademark of Viacqua S.p.A. and
is used only to identify the service this integration connects to. Home Assistant 2026.3+
shows it automatically. Older versions show a generic placeholder.

## Development

- `custom_components/viacqua/api/`: standalone async client (aiohttp + BeautifulSoup).
- `docs/API.md`: reverse-engineered map of the portal (ASP.NET WebForms, no JSON API).
- `tests/`: parser tests on redacted HTML fixtures, plus HA integration tests.

```sh
uv sync
uv run pytest
# CLI against the live portal
VIACQUA_USERNAME=... VIACQUA_PASSWORD=... uv run python -m custom_components.viacqua.api dump
VIACQUA_USERNAME=... VIACQUA_PASSWORD=... uv run python -m custom_components.viacqua.api pdf 768076 ./bills
```
