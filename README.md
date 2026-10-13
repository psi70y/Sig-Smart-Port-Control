# Sigenergy Cloud Control for Home Assistant

A custom Home Assistant integration that controls your Sigenergy system through Sigenergy's cloud, using the same API as the mySigen app. It gives full two-way control, and shows the *real* state in HA, not just whatever was last written:

- **Smart Port loads**: switch them on and off, and between Manual and Auto (Sig Schedule)
- **Energy Profile**: read and switch your system's overall profile (built-in modes and your own saved custom profiles)
- **Instant Manual Control**: charge, discharge, hold or self-consume for a set time (see [Instant Manual Control](#instant-manual-control))
- **Sigenergy AC EV Charger**: monitor it and change its charging settings (see [AC EV Charger](#ac-ev-charger))

> **Formerly "Sigenergy Smart Port".** It was renamed in version 2.9.0 because it now does much more than control Smart Ports. Nothing changes for existing installs: it's the same HACS repository, and your devices, entity IDs and automations stay as they are.

> **Credit where it's due:** this is a fork of [CDSSBR/Sig-Smart-Port-Control](https://github.com/CDSSBR/Sig-Smart-Port-Control), which did the hard work of reverse-engineering the Sigen cloud auth and write endpoints in the first place. This fork adds read/sync, safer session handling, energy profile control, and a proper HACS + UI setup flow on top of that foundation.

## Why This Integration Exists

The official Sigenergy OpenAPI restricts or completely locks out remote control commands for Smart Port relays for regular consumer tiers. This integration works by mimicking the exact request sequences used by the official **mySigen Web App** (`api-aus.sigencloud.com`) — the same endpoints the app itself calls, not a published developer API.

⚠️ **A note on Sigenergy's Terms & Conditions:** this relies on Sigenergy's private app API rather than an official developer API. Their T&Cs grant a fairly narrow personal-use license and reserve the right to suspend cloud account access at their discretion. This hasn't caused issues in testing, but there's a real, likely low, risk if it gets flagged on their end. Use at your own risk.

---

## What's New in This Fork

- **Two-way sync** — the original wrote commands but never read anything back, so HA's state was just "whatever we last told the cloud to do." This fork polls the cloud every 60 seconds (configurable) and reflects the *actual* switch state and mode — including correctly after a Home Assistant restart, instead of resetting to defaults.
- **Energy Profile control** — read and switch your system's overall operation mode/profile (Maximum Self-Powered, TOU, Fully Fed to Grid, or one of your own saved custom profiles), available with a Smart Port load, an AC EV Charger, or both — only ever one per station. The option list stays in sync automatically (see below).
- **Session handling that doesn't log you out of the mySigen app** — token and refresh token persist to disk across restarts, and renewal uses Sigen's own `refresh_token` grant instead of a full password re-login. There's no explicit logout call; tokens simply expire naturally.
- **Configurable poll interval** — defaults to 300 seconds (5 minutes), adjustable at setup or later via the integration's **Configure** button, without needing to remove and re-add the device.
- **No more YAML** — setup is now a guided UI wizard (Settings → Integrations → Add Integration). No editing `configuration.yaml`, no restart-to-apply-changes for adding a device.
- **HACS-installable** — add as a HACS custom repository instead of manually copying files.
- **Instant Manual Control** — start Charging, Discharging, Hold Battery or Self-Consumption for 1–1440 minutes, from the UI, a dashboard button or an automation, and see what's running and when it ends. See [Instant Manual Control](#instant-manual-control).
- **Price Spike Export** — discharge the battery to the grid while a price entity from any other integration is at or above a threshold, and hand control back when the spike ends. Off by default. See [Price Spike Export](#price-spike-export).
- **AC EV Charger support** — read charging status, current and energy totals, and change Charging Mode, Battery Boost, Grid Charging and their limits from HA.
- **Devices, not loose entities** — the switch and mode selector for each Smart Port load are grouped together as one Device in the HA UI; the Energy Profile selector gets its own Station-level device.

---

## Features

- **Power switch**: turn a Smart Port load (e.g. hot water system, pool pump, EV charger) on or off manually, with state that reflects reality.
- **Mode selector**: switch between **Manual** and **Auto (Sig Schedule)**, synced with the cloud.
- **Energy Profile selector**: switch between built-in system modes and your own saved custom profiles, synced with the cloud.
- **Instant Manual Control**: start or stop the mySigen app's Instant Manual Control, with a status sensor that also shows manual control started from the app, plus actions for automations — see [Instant Manual Control](#instant-manual-control).
- **Price Spike Export** (optional): force-discharge during price spikes, using any price entity — see [Price Spike Export](#price-spike-export).
- **Refresh Energy Profiles button**: manually re-fetch the profile/mode option list on demand — useful right after creating a new custom profile in the mySigen app.
- **Configurable poll interval**: how often HA checks the cloud for real state, adjustable per device.
- **Configurable Energy Profile list refresh**: how often the full list of selectable profiles/modes is automatically re-checked in the background (default 30 days) — a safety net alongside the manual button.
- **AC EV Charger** (optional): status, current and energy sensors, plus Charging Mode, Battery Boost and Grid Charging controls — see [AC EV Charger](#ac-ev-charger).
- **Automatic, restart-safe token management**: tokens (and refresh tokens) persist to disk and renew gently via a refresh grant, entirely behind the scenes — no re-authentication prompts, and no forced logouts of the mySigen app/web portal.

---

## Installation

Requires Home Assistant 2024.1 or later. It's ready for Home Assistant 2026.9 and later, which validate with probatio instead of voluptuous.

### Option A — HACS (recommended)

1. In HA: **HACS → ⋮ (top right) → Custom repositories**
2. Add this repository's URL, category **Integration**
3. Find "Sigenergy Cloud Control" in HACS and install it
4. Restart Home Assistant

### Option B — Manual

Copy the `custom_components/sigen_smartport/` folder from this repo into your HA `config/custom_components/` directory, then restart Home Assistant.

---

## Setup

Once installed, **all setup happens in the UI** — there's no `configuration.yaml` editing.

1. Go to **Settings → Devices & Services → Add Integration**, search for **"Sigenergy Cloud Control"**, and pick the device type: **Smart Port Load** or **AC EV Charger** (the charger steps are described in [AC EV Charger](#ac-ev-charger))
2. For a Smart Port Load you'll be asked for:
   - **Username** — your mySigen account email
   - **Password** — see note below, this is *not* simply your plaintext account password
   - **Station ID** — your 15-digit inverter station ID
   - **Region** — the Sigen cloud region your account lives in (`aus`, `apac`, `eu`, `cn`, `us`, or `custom` to enter an API base URL yourself in the Advanced step)
   - **Load Path** — leave as `1` unless you have multiple Smart Port loads (see [Multiple Devices](#multiple-devices) below)
   - **Name** — a friendly name for this device
   - **Poll interval** — how often (in seconds) HA checks the cloud for real state; defaults to `300` (5 minutes)
3. An **Advanced** step follows with pre-filled defaults (API base URL, auth header, device ID, and how often the full Energy Profile list is auto-refreshed — default `30` days) — only change these if you know you need to.
4. The wizard performs a real login and status check before finishing, so bad credentials are caught immediately with a clear error instead of a silently broken entity.

The poll interval and Energy Profile refresh interval can both be changed later at any time via **Settings → Devices & Services → Sigenergy Cloud Control → Configure → Connection settings**, without needing to remove and re-add the device. On the entry that owns the station's Energy Profile, Configure also has a **Price Spike Export** page.

### Capturing your credentials

Because this talks to private app endpoints, you need to capture a few values from a browser's network inspector rather than just typing your normal login:

1. On a desktop browser, open **DevTools → Network tab**, filter for `/token`
2. Log into `app-aus.sigencloud.com` (or your region's equivalent) normally
3. Click the `token` request, open its **Payload/Body** tab, and note:
   - `username` — your account email
   - `password` — the **raw string** sent in the payload (this is what the app itself sends, not necessarily your literal typed password — copy it exactly as shown)
   - `userDeviceId`
4. From the request **Headers**, note the `Authorization` header value (looks like `Basic c2lnZW46c2lnZW4=`)
5. Find your `station_id` by filtering for `stationId` in the network log — it'll appear as a query parameter on several requests

---

## Session Handling, In Detail

- **Token + refresh token are persisted to disk**, tied to each device's config entry. A Home Assistant or Supervisor restart reuses the still-valid session instead of forcing a fresh login every time.
- **Renewal uses the `refresh_token` grant**, the same mechanism Sigen's own mySigen web app uses to extend a session near its ~12-hour expiry, rather than a full username/password login.
- **A full password login only happens** on first-ever setup, or as a fallback if a refresh token is ever rejected outright (e.g. after an extended period offline).
- **There's no explicit logout call.** Tokens are simply left to expire naturally rather than being proactively revoked.

If the mySigen app or web portal gets logged out unexpectedly, please open an issue with your Home Assistant logs (filter for "Sigenergy Cloud Control", or "Sigen Smart Port" on versions before 2.9.0) covering that period — the integration logs every login and refresh event at `info` level to help diagnose it.

---

## Energy Profile

Whether you've set up a Smart Port load, an AC EV Charger, or both, this integration reads and controls your system's overall **Energy Profile** — the same setting shown when you tap the current mode/profile name in the mySigen app.

- Appears as a **separate select entity** on its own device (**"Sigen Station {your station ID}"**), since this is a station-wide setting rather than something tied to a specific Smart Port load or charger.
- The list of options is pulled directly from your account — Sigenergy's built-in system modes (e.g. Maximum Self-Powered, TOU, Fully Fed to Grid) plus **any custom profiles you've saved yourself**, exactly as labeled in the mySigen app. Nothing is hardcoded, so labels stay accurate even if Sigen changes their wording.
- The current selection is polled on the same schedule as the entry that provides it (governed by that entry's poll interval setting).
- **One Energy Profile per station.** You get exactly one Energy Profile select and one Refresh button per station, however many entries you add for it (several Smart Port loads, a Smart Port load plus an AC charger, or an AC charger on its own). The first entry set up for the station provides them; the others skip them.
- If the entry providing them is deleted or disabled, another entry on the same station takes over automatically. The entity IDs stay the same, so automations and dashboards keep working.

### Keeping the profile list up to date

The list of *selectable* profiles/modes (as opposed to which one is currently active) is deliberately not re-fetched on every poll, since it rarely changes. Two ways it stays current:

- **Automatically**, on the interval set by the Energy Profile refresh setting (default 30 days, configurable at setup or via Configure).
- **On demand**, via the **"Refresh Energy Profiles"** button on the Station device — press this right after creating a new custom profile in the mySigen app to make it available in HA immediately, without waiting for the automatic check or reloading the integration.

---

## Instant Manual Control

The same feature as **Instant Manual Control** in the mySigen app: tell the battery to do one thing for a set time, then go back to your Energy Profile automatically.

| Action | What the battery does | Power limit |
|---|---|---|
| Charging | Charges the battery | Optional |
| Discharging | Discharges | Optional |
| Hold Battery | Neither charges nor discharges | Not used |
| Self-Consumption | Runs in self-consumption mode | Not used |

Your Energy Profile isn't changed. Manual control runs on top of it, and the profile takes over again when the time is up or you stop it.

### Entities

These are added to the **Sigen Station** device, next to the Energy Profile select. Like the Energy Profile, there's only one set per station, however many entries you have for it.

| Entity | Type | What it does |
|---|---|---|
| Manual Control Action | Select | Charging, Discharging, Hold Battery or Self-Consumption |
| Manual Control Duration | Number (min) | How long to run, 1–1440 minutes (24 hours). Default 30 |
| Manual Control Power Limit | Number (kW) | Maximum charge or discharge power, 0–30 kW. **0 means no limit.** Only used for Charging and Discharging |
| Start Manual Control | Button | Starts manual control with the three settings above |
| Replace Running Manual Control | Switch | Off (default): Start is refused while manual control is already running. On: Start stops the running one and replaces it |
| Stop Manual Control | Button | Ends manual control now |
| Manual Control | Sensor | `Off`, or the action that's running. The raw mode code is in the `mode_code` attribute |
| Manual Control Ends | Sensor (timestamp) | When the running manual control ends (shown as e.g. "in 23 minutes"). Unknown while it's off |

- **Action, Duration, Power Limit and Replace Running Manual Control are settings for the next start.** Changing them sends nothing to Sigenergy. Press **Start Manual Control** to send them.
- **These settings are saved to disk** and survive Home Assistant restarts. Sigenergy doesn't give them back, so the integration keeps its own copy.
- **The two sensors read the real state from Sigenergy**, so manual control started or stopped in the mySigen app shows up too, at the next poll.
- **It changes to Off when the time is up.** Shortly after the end time, the integration checks again so the sensors update, instead of waiting for the next regular poll.

### Actions for automations

Two actions let an automation or script start and stop manual control in one step, without touching the settings entities:

```yaml
action: sigen_smartport.start_manual_control
target:
  device_id: <your Sigen Station device>
data:
  action: charging        # charging, discharging, hold_battery or self_consumption
  duration: 120           # minutes, 1-1440 (optional, default 30)
  power_limit: 5.0        # kW (optional - leave out or use 0 for no limit)
  replace_running: true   # optional, default false - see "Good to know"
```

```yaml
action: sigen_smartport.stop_manual_control
target:
  device_id: <your Sigen Station device>
```

The target can be the Sigen Station device or any entity on it, for example `sensor.sigen_station_1234567890_manual_control`. In the automation editor, search for **"Start manual control"** and pick the device from the list.

Example: charge from the grid for two hours whenever the price goes negative.

```yaml
alias: Charge battery when the price is negative
triggers:
  - trigger: numeric_state
    entity_id: sensor.your_electricity_price
    below: 0
actions:
  - action: sigen_smartport.start_manual_control
    target:
      entity_id: sensor.sigen_station_1234567890_manual_control
    data:
      action: charging
      duration: 120
```

### Dashboard card

The integration doesn't add dashboard cards itself, but here's a card with one-tap buttons, like the presets in the app. Add a **Manual** card to a dashboard, paste this in, and replace `1234567890` with your station ID:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Battery manual control
    entities:
      - entity: sensor.sigen_station_1234567890_manual_control
        name: Status
      - entity: sensor.sigen_station_1234567890_manual_control_ends
        name: Ends
  - type: grid
    columns: 4
    square: false
    cards:
      - type: button
        name: Charge 1 h
        icon: mdi:battery-charging
        tap_action:
          action: perform-action
          perform_action: sigen_smartport.start_manual_control
          target:
            entity_id: sensor.sigen_station_1234567890_manual_control
          data:
            action: charging
            duration: 60
      - type: button
        name: Discharge 30 min
        icon: mdi:battery-arrow-down
        tap_action:
          action: perform-action
          perform_action: sigen_smartport.start_manual_control
          target:
            entity_id: sensor.sigen_station_1234567890_manual_control
          data:
            action: discharging
            duration: 30
      - type: button
        name: Hold 2 h
        icon: mdi:battery-lock
        tap_action:
          action: perform-action
          perform_action: sigen_smartport.start_manual_control
          target:
            entity_id: sensor.sigen_station_1234567890_manual_control
          data:
            action: hold_battery
            duration: 120
      - type: button
        name: Stop
        icon: mdi:stop
        tap_action:
          action: perform-action
          perform_action: sigen_smartport.stop_manual_control
          target:
            entity_id: sensor.sigen_station_1234567890_manual_control
          confirmation:
            text: Stop manual control and go back to the Energy Profile?
```

For full control with your own action, duration and power limit, use an Entities card with the five control entities instead:

```yaml
type: entities
title: Manual control settings
entities:
  - select.sigen_station_1234567890_manual_control_action
  - number.sigen_station_1234567890_manual_control_duration
  - number.sigen_station_1234567890_manual_control_power_limit
  - button.sigen_station_1234567890_start_manual_control
  - button.sigen_station_1234567890_stop_manual_control
```

`perform-action` needs Home Assistant 2024.8 or later. On older versions, use `action: call-service` and `service:` instead.

### Good to know

- **Charging with no power limit can draw a lot from the grid.** Set a power limit if that matters for your tariff or connection.
- **Starting while manual control is already running:**
  - **By default, Start is refused**, from the button and from the action, with a message saying what's running and until when. This protects manual control you started in the mySigen app.
  - **To replace it instead**, turn on the **Replace Running Manual Control** switch (for the button), or add `replace_running: true` (for the action). The integration then stops the running one, checks with Sigenergy that it has stopped (a few seconds), then starts the new one. If Sigenergy doesn't confirm the stop in time, the new one isn't started, the station stays on its Energy Profile, and Home Assistant shows an error.
  - Just before starting, the integration re-checks the status with Sigenergy, so this also catches manual control started in the mySigen app since the last poll.
- **If Sigenergy rejects a start or stop**, Home Assistant shows an error and the details are logged.
- **Don't combine this with Remote EMS** from a local Modbus integration. See [Using it alongside a local Modbus integration](#using-it-alongside-a-local-modbus-integration).

---

## Price Spike Export

Discharges the battery to the grid while electricity prices spike, then hands control back when the spike is over. It uses [Instant Manual Control](#instant-manual-control) under the hood: when the price reaches your threshold, it starts **Discharging** at the power you set, and stops it again afterwards.

**It's off by default.** Nothing changes for existing users until it's turned on in **Configure**.

### What you need

- **A price entity from another integration.** Any numeric sensor works. This integration doesn't read prices itself, so it works with any market or retailer. For example:
  - **Australia:** [AEMO NEM](https://github.com/cabberley/HA_AemoNemData) wholesale spot price, or Amber Electric
  - **Europe / UK:** Nord Pool, ENTSO-E, EPEX Spot, Tibber or Octopus Energy
- **A battery SOC entity (%)**, for example from a [local Modbus integration](#using-it-alongside-a-local-modbus-integration). The Sigenergy cloud API this integration uses doesn't provide SOC, so it has to come from somewhere else. Price Spike Export won't start without a valid SOC reading.

**The threshold is in your price entity's own unit and currency.** If the entity reports $/kWh, a threshold of `1.0` means $1.00/kWh. If it reports EUR/MWh, use EUR/MWh.

> **A price threshold is a proxy, not an official signal.** Retailer events such as critical peak, VPP or demand response are often triggered by high wholesale prices, but your retailer decides when they happen and what they pay. Compare your threshold with your retailer's actual event records (for example, which intervals your bill credited) and adjust it until they match.

### Turning it on

1. Go to **Settings → Devices & Services → Sigenergy Cloud Control → Configure → Price Spike Export**. On a station with several entries (for example two Smart Port loads), it's on the entry that owns the station's Energy Profile.
2. Tick **Turn on Price Spike Export**, choose the **price entity** and the **battery SOC entity**, and optionally a **notify action** (for example `notify.mobile_app_your_phone`).
3. Submit. The entities below appear on the **Sigen Station** device. Turning the feature off in Configure removes them again, and stops a discharge session it started.
4. Check the settings, then turn on the **Price Spike Export** switch to arm it.

### Entities

All settings can be changed from a dashboard at any time, and are saved to disk so they survive restarts.

| Entity | Type | Default | What it does |
|---|---|---|---|
| Price Spike Export | Switch | Off | Arms the feature. Turning it off stops a discharge session it started |
| Price Spike Take Over Manual Control | Switch | Off | What to do if you've started manual control yourself (in the app or HA) when a spike starts. **Off: leave it alone** and start once it ends, if the spike is still on. On: stop it and start discharging |
| Price Spike Threshold | Number | 1.0 | Price at or above which a spike starts, in the price entity's unit |
| Price Spike Start Delay | Number (min) | 0 | How long the price must stay at or above the threshold before discharging starts. 0 = straight away |
| Price Spike Hold Time | Number (min) | 10 | How long the price must stay below the threshold before discharging stops. Keeps it going through short dips |
| Price Spike Discharge Power | Number (kW) | 10 | Discharge power limit, 0–30 kW. **0 means no limit** |
| Price Spike Session Duration | Number (min) | 30 | Length of each manual control session. Also the safety backstop, see below |
| Price Spike Minimum SOC | Number (%) | 20 | Stops at or below this SOC, and doesn't start again until the next spike |
| Price Spike Active | Binary sensor | | On while the price is at or above the threshold (after the start delay) |
| Price Spike Discharging | Binary sensor | | On only while a session started by Price Spike Export is running, never for one you started |

Both binary sensors have these attributes: `current_price`, `threshold`, `soc`, `spike_started`, `hold_ends` and `last_stop_reason`.

### How it behaves

- **Start:** when the price reaches the threshold (and stays there for the start delay), the switch is on and SOC is above the minimum, it starts Discharging for the session duration.
- **Short dips don't stop it.** When the price falls below the threshold, the hold time starts. If the price comes back up before it ends, discharging just carries on. Real spikes are often choppy, with high and low 5-minute intervals alternating.
- **Long spikes:** when a session runs out and the spike is still on (or in its hold time), a new session starts. There can be a gap of up to about a minute between sessions.
- **Stop:** when the hold time ends, SOC reaches the minimum, or you turn the switch off. It only ever stops a session it started itself.
- **Your own manual control is respected.** If you stop or replace a Price Spike Export session in the mySigen app, it's left alone for the rest of that spike.
- **When it takes over** your manual control (Take Over switch on), your session isn't brought back afterwards. When the spike ends, the station goes back to its Energy Profile.
- **Unavailable price or SOC** counts as "no spike" (price) or "don't start" (SOC), and a warning is logged once.
- **Restarts:** it remembers whether the running session is its own, so after a restart it carries on, and never stops a session it didn't start.
- **Safety backstop:** every session has a fixed length (the session duration), so if Home Assistant stops, discharging ends by itself when the session does.
- Every decision is logged at INFO level with the price, threshold, SOC and reason.

### Events and notifications

- `sigen_smartport_price_spike_export_started` fires when discharging starts. Data: `station_id`, `price`, `threshold`, `soc`, `power_kw`, `duration_min` and `rearm` (true for the follow-on sessions of a long spike).
- `sigen_smartport_price_spike_export_stopped` fires when it stops, with the same data plus `reason`: `price_below_threshold`, `soc_at_minimum` or `switched_off`.
- If you set a notify action, it's called with a title and message when discharging starts (once per spike) and stops.

### Test it safely

You can test with your real price and SOC sensors. Move the threshold to force a spike instead of waiting for a real one:

1. Turn the feature on in Configure with your real price and SOC entities.
2. Set **Discharge Power** to `1` kW, **Session Duration** to `5` min and **Hold Time** to `2` min, then turn on the **Price Spike Export** switch.
3. **Force a spike:** set **Threshold** below the current price, for example `-1000`. Within a few seconds, **Price Spike Discharging** turns on, the **Manual Control** sensor shows Discharging, and the mySigen app shows the manual control.
4. **End it:** set **Threshold** far above any real price, for example `100000`. After the hold time, it stops and the station goes back to its Energy Profile.
5. When you're happy, set your real threshold, power, session duration and hold time.

If you'd rather not touch real sensors, two **Number** helpers (**Settings → Devices & Services → Helpers**) also work as the price and SOC entities.

---

## AC EV Charger

If you have a Sigenergy AC EV Charger on the same station, it can be added as its own device. Tested so far with an EVAC 22 on the EU region.

### Adding the charger

1. **Settings → Devices & Services → Add Integration → "Sigenergy Cloud Control" → AC EV Charger**
2. Enter:
   - **Username / Password** — the same captured values as for a Smart Port load (see [Capturing your credentials](#capturing-your-credentials)). **If you already have a Smart Port entry for the same station, leave both blank** and its credentials are reused, so you don't need to capture them again.
   - **Station ID** and **Region** — as for a Smart Port load
   - **Charger Serial Number** — shown in the mySigen app on the charger's Device Info screen
   - **Name** and **Poll interval**
3. The **Advanced** step (API base URL, auth header, device ID, Energy Profile list refresh interval) works the same as for a Smart Port load.

A charger-only setup also gets the station's **Energy Profile** select and **Refresh Energy Profiles** button (see [Energy Profile](#energy-profile)). If you already have a Smart Port entry on the same station, the charger doesn't add a second one.

The charger gets its own login session and its own token file, so it follows the same restart-safe session handling described below.

### Entities

All of these are grouped under one **AC EV Charger** device.

| Entity | Type | What it does |
|---|---|---|
| Charge Status Code | Sensor | Raw plug/charge status from the cloud. `0` = not plugged in; other codes are shown as-is (e.g. `3` has been seen while charging) until they are confirmed |
| Charging Mode | Sensor | Current mode as a label |
| Charging Current | Sensor (A) | Last set charging current; the charger's maximum current is an attribute |
| Energy This Week / This Month / Lifetime Energy | Sensor (kWh) | Energy delivered by the charger, usable in the Energy dashboard |
| Charging Mode | Select | Switch between **Fast Charging** and **PV Surplus Charging**. Sigen AI Mode isn't offered yet; if it's selected in the app, this shows as unknown |
| Battery Boost | Switch | Let the home battery supply the charger |
| Battery Boost Cut-Off SOC | Number (%) | Home battery level (5–100 %) below which Battery Boost stops |
| Grid Charging | Switch | Let the charger draw from the grid |
| Grid Charging Max Power | Number (kW) | Maximum grid power while Grid Charging is on (0.5–22 kW) |

### Good to know

- **Every change is read back from the cloud.** The Sigen cloud can report success for a change it ignored, so HA always re-reads the charger after a write. The state you see is what the cloud actually applied.
- **Grid Charging Max Power while Grid Charging is off.** The cloud forces max grid power to 0 whenever Grid Charging is off. While it's off, the number entity shows the value that will be used next time instead, and a value you set then is saved and applied when Grid Charging is switched back on. This value is saved to disk, so it survives Home Assistant restarts. If no earlier value is known at all, 1 kW is used and a warning is logged.
- **Changes made close together are applied in order.** Several changes at once (for example from one automation) are sent one after another, so they can't overwrite each other.

---

## Using it alongside a local Modbus integration

Many Sigenergy owners also run a local Modbus integration, such as [Sigenergy ESS (Local Modbus)](https://github.com/TypQxQ/Sigenergy-Local-Modbus). The two complement each other. Modbus gives fast local readings of power, energy and battery state, and some local controls. This integration does things that are only available through Sigenergy's cloud.

| Feature in this integration | Fine to use alongside a Modbus integration? |
|---|---|
| Smart Port loads (on/off, Manual/Auto) | ✅ Yes. Modbus only reads smart load consumption |
| AC EV Charger settings (Charging Mode, Battery Boost, Grid Charging) | ✅ Yes. Modbus covers different charger controls (start/stop, output current) |
| Energy Profile, Instant Manual Control and Price Spike Export | ⚠️ Not together with Remote EMS (see below) |

**Recommendation: use only one thing to control what the plant does.** Don't use this integration's **Energy Profile** or **Instant Manual Control** while **Remote EMS** is enabled through a Modbus integration. Both tell the battery and inverter what to do, so they would override each other. Remote EMS takes the plant off its Energy Profile until Remote EMS is switched off again. Instant Manual Control expects the Energy Profile to take over again when it ends.

- **If you control the plant with Remote EMS**, leave this integration's Energy Profile and manual control entities alone. You can disable them in Home Assistant so they can't be used by accident. Smart Port and AC charger control from this integration still work fine.
- **If you control the plant with this integration**, keep Remote EMS switched off in the Modbus integration. Reading sensors from Modbus is fine.

---

## Multiple Devices

If your Sigen setup has more than one Smart Port load (e.g. a hot water heater *and* a pool pump), **add the integration again** via Settings → Devices & Services → Add Integration, using the same credentials but a different **Load Path** for each device. Each one becomes its own Device with its own switch + mode selector.

Finding the correct `load_path` for a second device requires digging through the network tab the same way as above — there's no automatic device-listing/discovery.

---

## Migrating from the YAML-based version

If you were using an earlier version of this integration configured via `configuration.yaml`:

1. Remove the `switch:` and `select:` platform entries for `sigen_smartport` from your YAML
2. Restart Home Assistant
3. Add the integration fresh via **Settings → Devices & Services → Add Integration**, entering your credentials as above

Existing automations/dashboards referencing the old entity IDs will need to be pointed at the new entities after setup.

---

## Disclaimer

This is an unofficial, community-maintained integration and is not affiliated with or endorsed by Sigenergy. It relies on reverse-engineered private API endpoints that could change or break without notice. Use at your own risk.
