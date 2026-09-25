# Sigenergy Smart Port Integration for Home Assistant

A custom Home Assistant integration that provides full two-way control of your **Sigenergy Smart Port** — toggle manual load switching, switch between Manual and Auto (Sig Schedule) modes, and see the *real* state reflected in HA, not just whatever was last written. Also supports reading and switching your system's overall **Energy Profile** (built-in modes and your own saved custom profiles), and monitoring and controlling a **Sigenergy AC EV Charger** (see [AC EV Charger](#ac-ev-charger)).

> **Credit where it's due:** this is a fork of [CDSSBR/Sig-Smart-Port-Control](https://github.com/CDSSBR/Sig-Smart-Port-Control), which did the hard work of reverse-engineering the Sigen cloud auth and write endpoints in the first place. This fork adds read/sync, safer session handling, energy profile control, and a proper HACS + UI setup flow on top of that foundation.

## Why This Integration Exists

The official Sigenergy OpenAPI restricts or completely locks out remote control commands for Smart Port relays for regular consumer tiers. This integration works by mimicking the exact request sequences used by the official **mySigen Web App** (`api-aus.sigencloud.com`) — the same endpoints the app itself calls, not a published developer API.

⚠️ **A note on Sigenergy's Terms & Conditions:** this relies on Sigenergy's private app API rather than an official developer API. Their T&Cs grant a fairly narrow personal-use license and reserve the right to suspend cloud account access at their discretion. This hasn't caused issues in testing, but there's a real, likely low, risk if it gets flagged on their end. Use at your own risk.

---

## What's New in This Fork

- **Two-way sync** — the original wrote commands but never read anything back, so HA's state was just "whatever we last told the cloud to do." This fork polls the cloud every 60 seconds (configurable) and reflects the *actual* switch state and mode — including correctly after a Home Assistant restart, instead of resetting to defaults.
- **Energy Profile control** — read and switch your system's overall operation mode/profile (Maximum Self-Powered, TOU, Fully Fed to Grid, or one of your own saved custom profiles), not just the Smart Port load. The option list stays in sync automatically (see below).
- **Session handling that doesn't log you out of the mySigen app** — token and refresh token persist to disk across restarts, and renewal uses Sigen's own `refresh_token` grant instead of a full password re-login. There's no explicit logout call; tokens simply expire naturally.
- **Configurable poll interval** — defaults to 300 seconds (5 minutes), adjustable at setup or later via the integration's **Configure** button, without needing to remove and re-add the device.
- **No more YAML** — setup is now a guided UI wizard (Settings → Integrations → Add Integration). No editing `configuration.yaml`, no restart-to-apply-changes for adding a device.
- **HACS-installable** — add as a HACS custom repository instead of manually copying files.
- **AC EV Charger support** — read charging status, current and energy totals, and change Charging Mode, Battery Boost, Grid Charging and their limits from HA.
- **Devices, not loose entities** — the switch and mode selector for each Smart Port load are grouped together as one Device in the HA UI; the Energy Profile selector gets its own Station-level device.

---

## Features

- **Power switch**: turn a Smart Port load (e.g. hot water system, pool pump, EV charger) on or off manually, with state that reflects reality.
- **Mode selector**: switch between **Manual** and **Auto (Sig Schedule)**, synced with the cloud.
- **Energy Profile selector**: switch between built-in system modes and your own saved custom profiles, synced with the cloud.
- **Refresh Energy Profiles button**: manually re-fetch the profile/mode option list on demand — useful right after creating a new custom profile in the mySigen app.
- **Configurable poll interval**: how often HA checks the cloud for real state, adjustable per device.
- **Configurable Energy Profile list refresh**: how often the full list of selectable profiles/modes is automatically re-checked in the background (default 30 days) — a safety net alongside the manual button.
- **AC EV Charger** (optional): status, current and energy sensors, plus Charging Mode, Battery Boost and Grid Charging controls — see [AC EV Charger](#ac-ev-charger).
- **Automatic, restart-safe token management**: tokens (and refresh tokens) persist to disk and renew gently via a refresh grant, entirely behind the scenes — no re-authentication prompts, and no forced logouts of the mySigen app/web portal.

---

## Installation

### Option A — HACS (recommended)

1. In HA: **HACS → ⋮ (top right) → Custom repositories**
2. Add this repository's URL, category **Integration**
3. Find "Sigenergy Smart Port" in HACS and install it
4. Restart Home Assistant

### Option B — Manual

Copy the `custom_components/sigen_smartport/` folder from this repo into your HA `config/custom_components/` directory, then restart Home Assistant.

---

## Setup

Once installed, **all setup happens in the UI** — there's no `configuration.yaml` editing.

1. Go to **Settings → Devices & Services → Add Integration**, search for **"Sigenergy Smart Port"**, and pick the device type: **Smart Port Load** or **AC EV Charger** (the charger steps are described in [AC EV Charger](#ac-ev-charger))
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

The poll interval and Energy Profile refresh interval can both be changed later at any time via **Settings → Devices & Services → Sigenergy Smart Port → Configure**, without needing to remove and re-add the device.

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

If the mySigen app or web portal gets logged out unexpectedly, please open an issue with your Home Assistant logs (filter for "Sigen Smart Port") covering that period — the integration logs every login and refresh event at `info` level to help diagnose it.

---

## Energy Profile

In addition to the per-load Smart Port switch, this integration reads and controls your system's overall **Energy Profile** — the same setting shown when you tap the current mode/profile name in the mySigen app.

- Appears as a **separate select entity** on its own device (**"Sigen Station {your station ID}"**), since this is a station-wide setting rather than something tied to a specific Smart Port load.
- The list of options is pulled directly from your account — Sigenergy's built-in system modes (e.g. Maximum Self-Powered, TOU, Fully Fed to Grid) plus **any custom profiles you've saved yourself**, exactly as labeled in the mySigen app. Nothing is hardcoded, so labels stay accurate even if Sigen changes their wording.
- The current selection is polled on the same schedule as the Smart Port status (governed by the poll interval setting).
- If you have more than one Smart Port load configured on the same station, each config entry creates its own Energy Profile entity, but Home Assistant's device registry merges them under the same Station device rather than creating duplicates.

### Keeping the profile list up to date

The list of *selectable* profiles/modes (as opposed to which one is currently active) is deliberately not re-fetched on every poll, since it rarely changes. Two ways it stays current:

- **Automatically**, on the interval set by the Energy Profile refresh setting (default 30 days, configurable at setup or via Configure).
- **On demand**, via the **"Refresh Energy Profiles"** button on the Station device — press this right after creating a new custom profile in the mySigen app to make it available in HA immediately, without waiting for the automatic check or reloading the integration.

---

## AC EV Charger

If you have a Sigenergy AC EV Charger on the same station, it can be added as its own device. Tested so far with an EVAC 22 on the EU region.

### Adding the charger

1. **Settings → Devices & Services → Add Integration → "Sigenergy Smart Port" → AC EV Charger**
2. Enter:
   - **Username / Password** — the same captured values as for a Smart Port load (see [Capturing your credentials](#capturing-your-credentials)). **If you already have a Smart Port entry for the same station, leave both blank** and its credentials are reused, so you don't need to capture them again.
   - **Station ID** and **Region** — as for a Smart Port load
   - **Charger Serial Number** — shown in the mySigen app on the charger's Device Info screen
   - **Name** and **Poll interval**
3. The **Advanced** step (API base URL, auth header, device ID) works the same as for a Smart Port load.

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
