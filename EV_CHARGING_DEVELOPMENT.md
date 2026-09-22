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
- Not expected to write code, though contributions are welcome if desired

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
should be captured together.

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

## 9. Release

Once a capability (or a coherent group of capabilities) is confirmed
working, the Maintainer merges `feature/ev-charging` into `main` and cuts
a standard tagged release, with accompanying README and changelog updates.

## 10. Notes on Scope and Pace

Given the asynchronous, remote nature of this arrangement, progress is
expected to be incremental. Shipping a small, confirmed-working capability
is preferred over holding back for broader feature completeness.
