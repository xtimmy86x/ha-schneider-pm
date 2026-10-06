# Schneider PowerLogic for Home Assistant

Custom integration for **Schneider Electric PM3255** meters connected through an
Ethernet/RS485 gateway. Configure the gateway once, then add each meter by its
Modbus address. No YAML is required.

**Version 0.1.1 — initial implementation, awaiting real PM3255 field validation.**
Automated tests use Home Assistant 2026.9.4 and a local Modbus TCP simulator;
they do not replace checking readings against your meter display.

[Guida in italiano](README.it.md)

## Requirements

- Home Assistant **2026.9.4 or newer**. The automated compatibility baseline is
  2026.9.4; later releases are not yet separately tested.
- One or more PM3255 meters; each must have a different RS485 address (1–247).
- A reachable Modbus TCP ↔ RTU gateway, or a transparent RTU-over-TCP bridge.
- Serial settings must match on every meter and the gateway. These are set on
  the hardware, not in the integration.

The integration uses Home Assistant's shared Modbus connection API. Requests to
one endpoint are serialized and the connection is released when unloaded.
Other clients outside Home Assistant still depend on the gateway's multi-client
capabilities. Prefer a DHCP reservation or a fixed gateway IP.

## Installation

### Manual, including testing the pull request

1. Download the ZIP of the branch you want to test from GitHub (**Code → Download ZIP**).
2. Copy `custom_components/schneider_pm` into your Home Assistant
   `/config/custom_components/` directory.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration → Schneider PowerLogic**.

While development is on a pull-request branch, select that branch before
clicking Download ZIP. A default-branch download does not include unmerged work.

### HACS (after the implementation is merged)

Add `https://github.com/xtimmy86x/ha-schneider-pm` as a **custom repository**, category
**Integration**, install Schneider PowerLogic, then restart Home Assistant.
This repository is prepared for HACS custom-repository use; it is not in the
default HACS catalog and no GitHub release has been published yet.

## Setup

Enter a gateway name, hostname/IP, TCP port (usually 502), protocol and polling
intervals. Choose:

| Gateway mode | Integration protocol |
| --- | --- |
| TCP server with Modbus TCP to RTU conversion | Modbus TCP → RTU |
| TCP server forwarding raw RTU frames | Modbus RTU over TCP |

For a Waveshare configured as **TCP Server / Modbus TCP to RTU**, select **Modbus TCP → RTU**.
Do not select transparent RTU framing for a gateway performing protocol conversion.

Next add each meter: address, friendly name, and optionally **Add another meter**.
The integration reads the model and serial number before saving. This version
accepts PM3255 only; other Schneider meters must not reuse its register map
without verification. Invalid addresses, duplicate addresses and duplicate
serial numbers are rejected.

For two meters on the same gateway, add addresses **1** and **2**. To expand to
five, use **Configure → Add meter** three times with the addresses actually
configured on those instruments. There is no five-meter software limit.

## Measurements

Each meter exposes **40 measurement/energy sensors**, a connectivity binary
sensor and the timestamp of the last successful measurement read. Secondary
quantities start disabled to keep the initial view compact; enable them from
the device's entity list when needed.

| Category | Quantities |
| --- | --- |
| Current | L1, L2, L3, neutral, average |
| Voltage | Three line-to-neutral, three line-to-line, both averages |
| Power | Active, reactive and apparent, per phase and total |
| Power factor | Each phase and total; Schneider quadrant encoding is decoded |
| Frequency | Network frequency |
| Energy | Imported/exported active, reactive and apparent energy |
| Tariffs | Four imported active-energy tariff counters |

Active energy is reported in **kWh** using the meter's signed Int64 Wh registers,
with `device_class: energy` and `state_class: total_increasing`. Add **Active energy
import** and, if applicable, **Active energy export** to the Energy dashboard.
Do not add both total imported energy and its tariff counters as separate sources
for the same load: that would count the same consumption twice.

The factor of power is a signed ratio, not a percentage. Active/reactive power
can be negative. Values are already scaled by the instrument's CT/VT settings;
no extra transformer multiplier is applied.

## Polling and availability

- Default instantaneous measurements: **10 seconds**, minimum 5 seconds.
- Default energy readings: **60 seconds**, at least the measurement interval.
- Six contiguous documented register blocks per measurement poll and four per
  energy poll, per meter. Reserved gaps are never included in a request.
- The full supported map is polled even when some entities are disabled.
- Each meter has independent measurement and energy coordinators. A failed meter
  does not mark its siblings unavailable, although its timeout can delay their
  queued requests on the shared physical bus.
- A configured gateway loads even when meters are offline. Polling recovers
  automatically when communication returns. Serial numbers are checked before
  the first measurements after setup/reload, preventing attribution to a wrong
  meter after an endpoint/address change.
- A failed measurement poll makes that meter's readings unavailable, including
  energy. Energy stays unavailable after recovery until a new energy read succeeds.
  A failed energy poll alone does not hide healthy instantaneous measurements.
- Invalid floating-point values and invalid energy sentinels become unavailable;
  they are never replaced with zero.
- **Connection** indicates success of the latest instantaneous measurement poll.
  **Last successful read** refers to that same measurement group and is not
  persisted across HA restarts.

Transport timeouts and reconnection are managed by Home Assistant's Modbus
connection layer; this version does not provide a separate timeout option.

## Manage meters

Use **Configure** on the integration entry to add, edit or remove meters, or
change gateway settings. Saving options reloads this gateway entry. Removing a
meter removes its entity/device association; other meters keep their identities.
To remove the last meter, delete the gateway integration entry.

Serial numbers are used for entity identity, so changing the gateway IP, a
meter's name or its Modbus address preserves entity IDs. Moving an existing
meter to another address requires the same serial number to respond there.
For a physical replacement, remove the old meter and add the replacement.
Home Assistant device names explicitly overridden by the user take precedence
over the name entered in this integration.

## Diagnostics and limits

Download diagnostics from the integration entry: it includes protocol, polling
intervals, unit IDs, availability and timestamps. Host, friendly names, serial
numbers and raw exception strings are excluded. Normal HA debug logs can contain
network addresses, so inspect logs before sharing them.

This first version is read-only: no counter resets, tariff switching, CT/VT
configuration, alarm programming or digital-output writes. Historical meter logs
are not imported; HA records readings from installation onward. There is no
side panel or automatic scan of every Modbus address.

If setup fails, first verify the gateway mode and port, serial parameters and
unit address. Compare voltage, current, power and cumulative energy with the
meter display before using them in dashboards. If one read group fails, attach
its diagnostics and the HA integration error to a GitHub issue.

## Development

Use Python 3.14:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
ruff check custom_components tests
ruff format --check custom_components tests
pytest -q --cov=custom_components.schneider_pm --cov-report=term-missing
```

Tests cover raw addressing/decoding, all four power-factor quadrants, malformed
responses, config/options flows, duplicate handling, shared TCP transport,
offline startup, recovery, entity availability, removal and diagnostic redaction.
No access to a real gateway is needed.

## References

- [Schneider PM3200 user manual and register map](https://productinfo.se.com/pm3200/)
  (DOCA0006EN, PM3255 basic meter data and power-factor register format).
- [Home Assistant shared Modbus API](https://developers.home-assistant.io/docs/modbus/introduction/).
- [Waveshare RS485 TO ETH (B)](https://www.waveshare.com/wiki/RS485_TO_ETH_(B)).

Independent community integration, not an official Schneider Electric product.
