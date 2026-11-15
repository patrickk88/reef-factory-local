# Troubleshooting

[← Back to the README](../README.md)

**On this page:** [Stuck web server (HTTP 429)](#stuck-web-server-http-429) ·
[Device lost its Wi-Fi?](#device-lost-its-wi-fi) · [Cloud and Smart Reef account](#cloud-and-smart-reef-account) ·
[New IP address](#new-ip-address) · [Network notes](#network-notes) · [Known quirks](#known-quirks) ·
[Diagnostics](#diagnostics)

## Stuck web server (HTTP 429)

The web server of the Reef Flare, Level keeper and Thermo control (firmware 1.0.0) can get stuck: it then
answers every new request with HTTP 429 until the device restarts. An open connection may keep working for a
while, but once it drops, Home Assistant cannot connect again and the device's entities become unavailable.
The device itself keeps running its program, refill or heating.

The integration notices this through its own connection: when the device refuses Home Assistant's
connection attempts with 429 three times in a row over half a minute, it is treated as stuck. It sends no
extra request to find out, and as long as Home Assistant is connected nothing is reported. Then:

- **Device connected through the cloud replacement:** the cloud replacement stops answering that device for
  up to two and a half minutes. A stuck device restarts by itself when its cloud does not answer (seen on
  stuck Reef Flare S, Level keeper and Thermo control; a device that is not stuck just waits), and Home
  Assistant reconnects. Only the device's network part starts over: nothing is noticeable at the tank -
  light, refill and heating keep running, settings and programs are kept (seen on Reef Flare S, Level keeper
  and Thermo control). A repair message says that this is happening and disappears when the device takes
  requests again. If the device is still stuck after five minutes, the message asks for a power cycle.
- **Without the cloud replacement:** a repair message asks you to unplug the device for 10 seconds.

The automatic restart can be switched off in the options of the cloud replacement entry (*Restart stuck
devices automatically*, on by default); then only the repair message is shown. Like every repair message,
it can be ignored in Home Assistant.

**Recommended for all devices: let their cloud connection run through the integration's
[cloud replacement](cloud-replacement.md)**, also for the devices with a local port. Then a stuck device
is fixed without anyone having to pull a plug, and the official app keeps working in passthrough mode.

**Keep local connections few.** The devices accept more than one local connection at a time, but several
app instances or device pages left open at the same time have coincided with a stuck web server.

<details>
<summary>What is known about the cause</summary>

Seen on two Reef Flare S on 2026-11-15:

- Something fills up on the device over its uptime. Before the web server is stuck for good, it already
  refuses a request whenever one more connection than Home Assistant's is open. After a power cycle the
  same light answered normally with nine more connections open.
- What fills it up is not known. Ten reloads of the entry in a row and two rounds of the automatic
  restart did not.
- Many connections at once are too much for the device: with nine more connections open, the other
  Reef Flare S restarted completely - its light went off for a second.
- Versions 1.3.0 to 1.3.2 asked the device for its start page every ten minutes to look for the stuck
  state. On a device that was close to its limit this gave false alarms, so 1.3.3 no longer does it.

</details>

## Device lost its Wi-Fi?

It then opens its own hotspot named after its serial number (e.g. `RFLK0123…`, WPA2, password:
the default printed in the manufacturer's manual). **Do not factory reset** - that also erases
configuration and calibration.

- With the Smart Reef app, as long as the cloud exists, or
- without app and cloud: connect a computer to the hotspot and run
  `python3 tools/reef_provision.py connect --ssid "YourNetwork"` (asks for the Wi-Fi password;
  the device answers on `10.32.54.1`).

The device's own setup page is at `http://10.32.54.1` in the hotspot and at `http://<device-ip>`
in your network. Close it when you are done - pages left open have coincided with a stuck web server.

## Cloud and Smart Reef account

The integration needs neither the cloud nor an account. After a local Wi-Fi setup the app shows the
device offline until the device is logged into your account again: open `http://<device-ip>` and log in
on the device page. If the page does not load, disable the integration entry for that moment.

What the devices send to the cloud, and how safe that is: see the
[security note](cloud-replacement.md#security-note).

## New IP address

*Settings -> Devices & services -> Reef Factory Local -> device entry -> menu -> Reconfigure*. The device
is checked by its serial number. Reef Factory devices offer no network discovery, so a fixed address (DHCP
reservation) is still the best choice - see the network notes below.

## Network notes

- **Devices always use DHCP.** There is no static IP setting on the devices. Give every device a
  DHCP reservation ("always assign the same IP") in your router, otherwise its address can change.
- **2.4 GHz only.**
- **Few local connections at a time** (see [Stuck web server](#stuck-web-server-http-429)).
- Setup needs only the IP address; serial number and type are read from the device.
- Devices use the DNS and NTP server they get via DHCP (usually your router). The clock keeps
  running without the cloud; the *Set clock* button is only a fallback.

## Known quirks

<details>
<summary><b>Thermo control</b></summary>

- Thermo control thresholds can only be changed when the device is set to °C.

</details>

<details>
<summary><b>Level keeper</b></summary>

- *Next calibration* is the date the device reminds you to calibrate again (calibration time + chosen
  reminder period), not the date of the last calibration. Logging the device into a Smart Reef account
  sets it to "today / not due" without any calibration. Without calibration the mL values are estimates.
- Calibration (tested 03.11.2026): put the refill hose into a measuring cup, *fill hose* until water comes,
  stop, empty the cup, run the calibration (default 10 s, as on the device page), enter the measured mL.
  Both work while refilling is paused - pause first so the device does not refill into the cup.
  Step by step: [Guided calibration](pump-actions.md#guided-calibration-level-keeper).

</details>

<details>
<summary><b>Reef Flare</b></summary>

- Reef Flare writing uses exactly the frames of the device's own web page, checked byte for byte
  against what the device sends (see [Confirmed writes](confirmed-writes.md) for what is offered).
- Reef Flare stores programs in its flash. Do not change intensity or programs every few minutes from
  an automation.
- The device only reports the points of the *active* program, so `flare_program_set` only
  writes the active program. To change another one, select it first (*Program* select), then write it.
  `flare_program_create` and `flare_program_delete` select the other slot for a moment themselves.

</details>

<details>
<summary><b>Smart feeder, Base pump, Dosing pump Pro X4 (cloud devices)</b></summary>

- Cloud devices (Smart feeder) never reconnect after a *WebSocket close frame* from the server - they
  stay offline until power cycled. The cloud replacement therefore never closes a device connection
  politely; it drops it with a TCP reset, after which the device reconnects by itself. Keep that in mind
  if you put a proxy in front of the ports (it must not send close frames either).

</details>

## Diagnostics

*Menu -> Download diagnostics* on an entry gives a JSON file with the decoded values (tokens, keys, e-mail
and Wi-Fi data removed). Please attach it when you open an issue.

For a device that is not supported yet, a debug log helps - see
[CONTRIBUTING](../CONTRIBUTING.md).
