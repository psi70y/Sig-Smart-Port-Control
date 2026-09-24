# EV Charging Support — Terms of Reference

## 1. Purpose

This document sets out how AC/DC EV charging support will be developed for
the Sigenergy Smart Port integration, and the working arrangement between
the project Maintainer and the Contributor assisting with network capture
and device access.

## 2. Parties

- **Maintainer:** psi70y (repository owner)
- **Contributor:** blablazzzLT (network capture and hardware access)

## 3. Scope

The objective is to extend the integration to read and, where feasible,
control Sigenergy EV charging (AC and DC), mirroring the existing Smart
Port and Energy Profile capabilities: real state read from the cloud,
control written back to the cloud, all endpoints confirmed against actual
captured traffic before any code is written.

Given the likely breadth of EV charging functionality (status, start/stop,
charging strategy, power/current limits, scheduling), work will proceed
capability-by-capability rather than as a single release.

## 4. Roles and Responsibilities

### 4.1 Maintainer (psi70y)
- Owns the repository and the `feature/ev-charging` branch
- Writes and reviews all integration code
- Maintains the GitHub tracking issue and this document
- Decides when a capability is ready to merge into `main` and release

### 4.2 Contributor (blablazzzLT)
- Has access to Sigenergy EV charging hardware (AC and/or DC) that the
  Maintainer does not
- Performs network captures of the mySigen app/web portal per the format
  in Section 6
- Installs and tests development builds of `feature/ev-charging` directly
  against their own hardware, and reports results

**All integration code is written by the Maintainer.** The Contributor's
role is capture and testing only - this keeps a single, consistent
authorship and review path for code entering the repository.

## 5. Working Method

All coordination happens on GitHub, via a single tracking issue on the
repository (e.g. "EV Charging Support — Capture & Design Thread"). This
keeps the full history of captures, decisions, and test results in one
place.

The cycle for each capability is:

1. Contributor captures the relevant network traffic (Section 6) and
   posts it to the tracking issue
2. Maintainer implements against the captured data
3. Maintainer pushes the change to `feature/ev-charging`
4. Contributor installs the updated branch (Section 8) and tests against
   real hardware
5. Results are reported on the tracking issue; the cycle repeats until the
   capability is confirmed working
6. Once confirmed, the capability is considered complete and work moves to
   the next one

## 6. Capture Format

Each capture posted to the tracking issue should include:

```
Action performed: (e.g. "opened the EV charger status screen",
                    "changed charging strategy from X to Y")

Method: GET / POST / PUT / PATCH
URL: (full path, including any stationId/deviceId in the path or query)

Request payload (if any):
(full JSON body, or "none" if it's a GET)

Response:
(full JSON response body)
```

Where a single screen or action triggers multiple requests, all of them
should be captured together. Where a setting has an enumerated set of
values (a mode, a strategy, etc.), round-trip confirmation - setting each
value via the UI and reading it back - is preferred over inferring values
from list order or field position.

## 7. Data Handling

Before any capture is posted to the (public) tracking issue, the following
must be redacted:

- `access_token`, `refresh_token`, and the `Authorization` header value
- `stationId`, account email/username, and any device serial numbers

Endpoint URLs, field names, response structure, and non-identifying
values (mode numbers, power limits, timestamps) do not need to be
redacted.

## 8. Branching and Installation

All EV charging work takes place on `feature/ev-charging`, kept separate
from `main` until each capability is confirmed working. `main` remains the
stable branch that existing HACS users install; it is not affected by
work-in-progress on the feature branch.

The Contributor installs development builds by copying the
`custom_components/sigen_smartport` folder from `feature/ev-charging`
directly into their Home Assistant instance, in place of the existing
installation, and reloading the integration. The Contributor has agreed
that this is acceptable for the duration of this work, including the
possibility of temporary instability while a given capability is still
under test.

## 9. Architecture Decisions

### 9.1 Multiple ownership scenarios

Users may have a Smart Port load only, an EV charger only, or both, on the
same or different stations. No configuration path may assume one implies
the other.

### 9.2 EV Charger as its own config entry type

An EV charger is identified by `stationId` + `snCode`, not `loadPath`, and
is a physically distinct device from any Smart Port load. Rather than
attaching EV charger entities to an existing Smart Port config entry (as
Energy Profile currently does, for expedience), EV Charger setup will be
its own config entry type, offered as a separate option in the setup
wizard, requiring only username/password/station ID/charger serial - no
dependency on a Smart Port load existing.

### 9.3 New `sensor.py` platform

No existing platform in this integration (`switch`, `select`, `button`)
fits read-only telemetry (plug status, live current, energy totals). EV
charging introduces this integration's first `sensor.py` platform.

### 9.4 External reference: solidfox/sigenergy-cloud

An independent open-source client library,
[solidfox/sigenergy-cloud](https://github.com/solidfox/sigenergy-cloud),
and a companion Home Assistant integration built on it
(`homeassistant-sigenergy-cloud`), appear to already implement DC EV
charger ("EVDC") support, based on their published release notes. This is
a useful reference for narrowing down what to look for when DC charging
capture begins, but is not a substitute for the process in Section 5 -
anything drawn from it is treated as a hypothesis to be confirmed against
real captured traffic, the same as any other lead. Licensing terms should
be checked before adapting anything beyond general endpoint knowledge.

## 10. Confirmed Findings — AC Charging

Recorded here as they're locked in, so they don't need to be dug out of
issue history later. Hardware: Sigen EVAC 22 4G T2 WH, firmware
V100R001C10SPC114, EU region.

### Charging Mode

Write: `POST /device/charge/mode/ac` with body
`{"stationId": ..., "snCode": ..., "chargeMode": <int>}` →
`{"code":0,"data":true}` on success. Read back via the *same* endpoint
(`GET /device/charge/mode/ac`), not `/device/acevse/charge/mode`, which
uses a different, non-matching enum for the same-looking field name.

| UI Label | `chargeMode` value | Status |
|---|---|---|
| Fast Charging | `0` | Confirmed (round-trip) |
| PV Surplus Charging | `1` | Confirmed (round-trip) |
| Sigen AI Mode | likely `2` | **Not confirmed** - selecting it in the UI requires a one-time setup flow before it can be saved; no write has been captured yet |

### Other confirmed fields on `/device/charge/mode/ac`

| Field | UI control |
|---|---|
| `enableFromPack` | Battery Boost toggle |
| `cutoffSocFromPack` | Cut-Off SOC (range from `/device/charge/mode/soc/range`: 5-100) |
| `enableFromGrid` | Grid Charging toggle |
| `maxPowerFromGrid` | Max power from grid (kW) |

**Writes confirmed** (EVAC 22, EU region) by POSTing the full current
payload with one field changed, then reading back: all four fields change
and the others stay untouched. Quirks:

- Turning `enableFromGrid` off forces `maxPowerFromGrid` to `0`, and a
  `maxPowerFromGrid` sent while grid charging is off is ignored.
- Turning `enableFromGrid` on only works if a `maxPowerFromGrid` > 0 is sent
  in the same request - with `0` or the field omitted the cloud still
  answers `{"code":0,"data":true}` but leaves grid charging off. The
  integration remembers the last non-zero value and sends it on re-enable.
- Because each write carries the full payload, concurrent writes overwrite
  each other; the client serialises them with a lock.

### Session expiry

An expired or revoked token is answered with **HTTP 424**,
`{"code":1,"msg":"用户凭证已过期"}` ("user credentials expired"), not 401.
It is now retried like a 401; before that, an entry stayed unavailable until
the next HA restart.

### Still open

- `/device/acevse/charge/status`: `0` confirmed as "not plugged in"; `3`
  observed during an active session; other values and their meanings not
  yet mapped. Plan: ship as a raw status code sensor initially, refine the
  enum as more states are naturally observed through use.
- `/device/acevse/charge/mode`'s own fields (`minKeepChargeTime`,
  `maxGridChargePower`, `pvEnergyStartPower`) have no known UI control -
  left unexposed until a use is identified.
- Sigen AI Mode's write value and its one-time setup flow.

## 11. Notes on Scope and Pace

Given the asynchronous, remote nature of this arrangement, progress is
expected to be incremental. Shipping a small, confirmed-working capability
is preferred over holding back for broader feature completeness.
