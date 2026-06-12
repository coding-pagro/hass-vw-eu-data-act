# VW Group EU Data Act — Home Assistant integration

Bring your car's data into Home Assistant — no ODB dongle, no third-party
cloud, no subscription. Under the **EU Data Act**, VW Group must hand over the
data your vehicle generates, free of charge. This integration downloads the
"continuous data" datasets from the official portal
([eu-data-act.drivesomethinggreater.com](https://eu-data-act.drivesomethinggreater.com/))
and turns them into Home Assistant entities.

**Supported brands:** Volkswagen · Audi · Škoda · SEAT · CUPRA

> Unofficial community project — not affiliated with or endorsed by
> Volkswagen AG or any VW Group brand.

## How it works

1. On the portal you create a **continuous data request** for your vehicle:
   you pick the *data clusters* (which kinds of data) and the *delivery
   frequency*.
2. The portal then drops a ZIP dataset at that frequency into your vehicle's
   data-delivery list.
3. This integration logs in with your brand credentials, downloads each new
   dataset shortly after it appears, and maps the data points onto entities —
   enriched with names, units and descriptions from the official PDF data
   dictionary (bundled, 1100+ documented data points).

The polling schedule adapts automatically: the integration measures the actual
spacing of your datasets and refreshes just after the next expected drop —
whether you chose 15-minute or hourly delivery. Polling faster than the portal
publishes cannot produce fresher values.

## What you get

### Curated entities (enabled by default)

Created automatically for every data point your vehicle actually delivers,
with proper device classes, units and translations (English & German):

- **Charging & battery** — state of charge, target SoC, charge power, charge
  rate, charged energy, remaining charging time, charge state / mode / type
- **Distance & range** — odometer, electric range, combined/primary/secondary
  range, km/miles resolved per vehicle
- **Climate** — remaining climatisation time, window heating, battery
  min/max temperature, outside temperature
- **Vehicle status** — central locking, individual door locks, doors / windows
  / sunroof / hood / tailgate open-state, parking brake, parking lights, tire
  pressures, fuel/CNG/oil levels, maintenance intervals
- **Trip statistics** — distance, average consumption, average speed, travel
  time (short- and long-term)
- **Freshness** — *Last vehicle update* (when the car itself last reported)
  and *Dataset generated* (when the portal produced the newest file). A parked
  car stops sending data while the portal keeps producing datasets — these two
  sensors tell the difference.

Both vehicle generations are supported: ID./MEB models (dotted field names
like `battery_state_report.soc`) and earlier platforms (flat names like
`state_of_charge`) — the format is detected automatically.

### Diagnostic entities (disabled by default)

Every other data point in your datasets becomes a diagnostic sensor with the
official description attached. Enable the ones you care about under
*Settings → Devices & Services → your vehicle → entities*.

### Multiple vehicles

Add the integration once per VIN — each vehicle becomes its own device, and
several vehicles can share one account.

## Prerequisites — set up the portal first

The integration only *downloads* datasets; it cannot create the data request
for you. Without an active continuous request there is nothing to fetch.

1. Open <https://eu-data-act.drivesomethinggreater.com/> and **log in** with
   your brand ID (Volkswagen ID / myAudi / myŠkoda / SEAT / CUPRA — the same
   email/password you'll later enter in Home Assistant).
2. **Connect your vehicle** if it isn't listed yet (on-screen pairing/consent
   steps for your VIN).
3. Click **Get customised data** and configure a **continuous** data request:
   - **Data clusters:** choose **All Data** for full sensor coverage. If you
     prefer a narrower selection, the curated entities draw mainly on
     *Charging*, *Vehicle Status*, *Vehicle Access*, *Climatisation and
     Heating*, *Trip Statistics* and *Maintenance Related Information*.
     Entities only appear for data your request actually contains.
   - **Frequency:** any frequency works — 15 minutes gives the freshest data;
     the integration adapts its polling to whatever you pick.
4. Wait until ZIP files start appearing in the vehicle's data-delivery list.
   The first one can take a few hours after enabling the request.

> Only one customised continuous request can be active per vehicle. If you
> later change its clusters, **reload the integration** (*Settings → Devices &
> Services → VW Group EU Data Act → ⋮ → Reload*) so new entities are created.

## Installation

### Option A — HACS (recommended)

1. **HACS → ⋮ → Custom repositories**, add
   `https://github.com/mikrohard/hass-vw-eu-data-act` as type **Integration**.
2. Search for **VW Group EU Data Act**, open it and click **Download**.
3. **Restart Home Assistant**.

### Option B — Manual

1. Copy `custom_components/vw_eu_data_act/` into your Home Assistant
   `config/custom_components/` directory.
2. Restart Home Assistant.

### Add the integration

1. *Settings → Devices & Services → **Add Integration*** → search "VW Group EU
   Data Act".
2. **Select your brand** — each VW Group brand uses its own identity flow, so
   the right brand matters for the login to succeed.
3. Enter the **same email/password** as on the portal and pick your vehicle.

If your password changes later, Home Assistant prompts for re-authentication
automatically.

## Notes & limitations

- **No historical back-fill.** Sensors record from the moment the integration
  runs; the portal's past datasets are not imported into long-term statistics
  (doing so conflicts with the recorder's own statistics).
- **Sticky values.** Datasets don't include every field every cycle; a missing
  field means "no fresh reading", so entities keep their last known value
  instead of flipping to *unknown*. Use *Last vehicle update* to judge
  freshness.
- **Resilient by design.** Transient portal errors keep the previous data, and
  if you delete and recreate the data request on the portal, the integration
  picks up the new request identifier on its own — no reconfiguration needed.
- Datasets named `*_no_content_found.zip` are skipped (the vehicle produced no
  payload for that interval).
- Credentials are stored in the Home Assistant config entry and used only
  against the official portal. Nothing is sent anywhere else.

## Troubleshooting

**"Data delivery not ready yet (HTTP 400)"** — the continuous request was
enabled recently and the portal hasn't started producing files. The
integration keeps retrying; this resolves itself within a few hours.

**Expected sensors are missing** — the corresponding data cluster probably
isn't part of your portal request, or the vehicle doesn't deliver that field.
Check a downloaded ZIP on the portal for the field, adjust the clusters, then
reload the integration.

**Login fails** — first make sure you selected the **correct brand**; each
brand uses a different OIDC client. You can reproduce the login outside Home
Assistant with the bundled tester:

```bash
python3 -m venv .venv && .venv/bin/pip install aiohttp
EUDA_EMAIL='you@example.com' EUDA_PASSWORD='secret' .venv/bin/python tools/test_login.py
```

It prints each login step (priming → authorize → identifier → password →
portal callback) so you can see exactly where it stops. For the same detail
inside Home Assistant:

```yaml
logger:
  logs:
    custom_components.vw_eu_data_act: debug
```

## Development

```bash
# offline tests (no Home Assistant required)
python tests/test_offline.py

# full suite (Linux/macOS; runs in CI on every PR)
pip install -r requirements_test.txt
pytest tests/
```

`data_dictionary.json` is generated from the official *List of Continuous
Data* PDF and committed. To regenerate from a newer PDF:

```bash
pip install pdfplumber
python tools/parse_dictionary.py path/to/DataDictionary.pdf
```

The parser also reads the *List of Historical Data* dictionary (5-column
layout), though historical data — a one-off export of everything VW stored
about the vehicle — is not consumed by the integration.

Entity translations (`strings.json`, `translations/*.json`) are generated by
`tools/gen_translations.py`; the offline test suite verifies they stay
complete.

## License

Released under the [MIT License](LICENSE).
