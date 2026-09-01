# Sigenergy Smart Port Integration for Home Assistant

A custom Home Assistant integration that provides full two-way control of your **Sigenergy Smart Port** — toggle manual load switching, switch between Manual and Auto (Sig Schedule) modes, and see the *real* state reflected in HA, not just whatever was last written.

> **Credit where it's due:** this is a fork of [CDSSBR/Sig-Smart-Port-Control](https://github.com/CDSSBR/Sig-Smart-Port-Control), which did the hard work of reverse-engineering the Sigen cloud auth and write endpoints in the first place. This fork adds read/sync, safer session handling, and a proper HACS + UI setup flow on top of that foundation.

## Why This Integration Exists

The official Sigenergy OpenAPI restricts or completely locks out remote control commands for Smart Port relays for regular consumer tiers. This integration works by mimicking the exact request sequences used by the official **mySigen Web App** (`api-aus.sigencloud.com`) — the same endpoints the app itself calls, not a published developer API.

⚠️ **A note on Sigenergy's Terms & Conditions:** this relies on Sigenergy's private app API rather than an official developer API. Their T&Cs grant a fairly narrow personal-use license and reserve the right to suspend cloud account access at their discretion. This hasn't caused issues in testing, but there's a real, likely low, risk if it gets flagged on their end. Use at your own risk.

---

## What's New in This Fork

- **Two-way sync** — the original wrote commands but never read anything back, so HA's state was just "whatever we last told the cloud to do." This fork polls the cloud every 60 seconds and reflects the *actual* switch state and mode — including correctly after a Home Assistant restart, instead of resetting to defaults.
- **Safer session handling** — logins are cached for their real ~12-hour lifetime (read from Sigen's own token response) instead of logging in fresh on every single command, and old sessions are cleanly logged out when a token rotates. This avoids tripping Sigen's cloud session limits, which can otherwise force-log you out of the mySigen app.
- **No more YAML** — setup is now a guided UI wizard (Settings → Integrations → Add Integration). No editing `configuration.yaml`, no restart-to-apply-changes for adding a device.
- **HACS-installable** — add as a HACS custom repository instead of manually copying files.
- **Devices, not loose entities** — the switch and mode selector for each Smart Port load are now grouped together as one Device in the HA UI.

---

## Features

- **Power switch**: turn a Smart Port load (e.g. hot water system, pool pump, EV charger) on or off manually, with state that reflects reality.
- **Mode selector**: switch between **Manual** and **Auto (Sig Schedule)**, synced with the cloud.
- **Automatic token/session management**: handled entirely behind the scenes.

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

1. Go to **Settings → Devices & Services → Add Integration**, search for **"Sigenergy Smart Port"**
2. You'll be asked for:
   - **Username** — your mySigen account email
   - **Password** — see note below, this is *not* simply your plaintext account password
   - **Station ID** — your 15-digit inverter station ID
   - **Load Path** — leave as `1` unless you have multiple Smart Port loads (see [Multiple Devices](#multiple-devices) below)
   - **Name** — a friendly name for this device
3. An **Advanced** step follows with pre-filled defaults (API base URL, auth header, device ID) — only change these if you know you need to.
4. The wizard performs a real login and status check before finishing, so bad credentials are caught immediately with a clear error instead of a silently broken entity.

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
