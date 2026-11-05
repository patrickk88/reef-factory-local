# Reef Factory Local (unofficial)

Local control of Reef Factory aquarium devices in Home Assistant - no cloud.

> **Unofficial community project. Not affiliated with, endorsed by or supported by Reef Factory.**
> "Reef Factory", "Smart Reef", "Level keeper", "Thermo control" and "Reef Flare" are used only to
> describe which devices this integration works with.

Reef Factory went insolvent in 2025; the cloud keeps running for now but may disappear.
The devices below already speak a local WebSocket protocol, which this integration uses.

## Supported devices (v0.5)

| Device | Read | Control | Tested firmware |
|---|---|---|---|
| Level keeper (`RFLK…`) | refilled today, state (ok / refilling / water high / water low / paused / calibrating / filling hose / manual refill), current refill time, calibration date, calibration due, cloud connected | refill cycle, max refill time (safety limit), pause refill, display light, set clock; **opt-in pump actions:** manual refill (max 1000 mL), calibration run, fill hose, plus stop | 1.0.0 |
| Thermo control (`RFTC…`) | temperature, heating/cooling, all four thresholds, beeper, display light, cloud connected | thresholds (alarm below / target range low / target range high / alarm above, always sent together, order checked), beeper, display light (°C units only so far) | 1.0.0 |
| Reef Flare S/M/L (`RFRFS…`, `RFRFM…`, `RFRFL…`) | housing temperature, mode, active program with its light schedule (points per channel), list of programs, intensity, acclimation, manual presets, cloud connected | mode (program / manual / off), active program, active manual preset, intensity; actions: manual mode with timer, change manual preset, write / rename program, acclimation start / stop, program preview — **experimental, see below** | 1.0.0 |

| Smart feeder (`RFSF…`) - via the **cloud replacement** | next / last feeding, days until empty, fed today, schedule, container empty, real-cloud status | feed now, feeding mode (schedule / interval), schedule (action), interval, container values, dose per rotation, LED backlight, feeding button, refill reminder | 1.1.6 |

Base pump and Dosing pump Pro X4 are cloud-only like the feeder and will very likely work the same way
(same platform) - not tested yet.

## Important

- **One connection per device.** While Home Assistant is connected, the Smart Reef app and other
  local tools cannot connect to that device locally (the cloud keeps working).
- **No warranty.** These devices run pumps and heaters. A bug can harm livestock. Watch your tank
  after installing and keep the device's own safety settings.
- Setup needs only the IP address; serial number and type are read from the device.
  Give the device a fixed IP in your router.

## Network notes

- **Devices always use DHCP.** There is no static IP setting on the devices. Give every device a
  DHCP reservation ("always assign the same IP") in your router, otherwise its address can change.
- **2.4 GHz only.**
- **One local connection per device** (see above).
- Devices use the DNS and NTP server they get via DHCP (usually your router). The clock keeps
  running without the cloud; the *Set clock* button is only a fallback.

## Device lost its Wi-Fi?

It then opens its own hotspot named after its serial number (e.g. `RFLK0123…`, WPA2, password:
the default printed in the manufacturer's manual). **Do not factory reset** - that also erases
configuration and calibration.

- With the Smart Reef app, as long as the cloud exists, or
- without app and cloud: connect a computer to the hotspot and run
  `python3 tools/reef_provision.py connect --ssid "YourNetwork"` (asks for the Wi-Fi password;
  the device answers on `10.32.54.1`).

The device's own setup page is at `http://10.32.54.1` in the hotspot and at `http://<device-ip>`
in your network. Because of the one-connection limit, disable the integration entry while you use it.

## Cloud and Smart Reef account

The integration needs neither the cloud nor an account. After a local Wi-Fi setup the app shows the
device offline until the device is logged into your account again: disable the integration entry,
open `http://<device-ip>`, log in on the device page, enable the entry again.

**Security note:** these devices talk to the cloud unencrypted (WebSocket on port 442; the
cloud-only pumps use TLS on port 444), and the device sends the Smart Reef login as plain text.
Use a password for Smart Reef that you use nowhere else.

## Known quirks

- Thermo control thresholds can only be changed when the device is set to °C.
- Cloud devices (Smart feeder) never reconnect after a *WebSocket close frame* from the server - they
  stay offline until power cycled. The cloud replacement therefore never closes a device connection
  politely; it drops it with a TCP reset, after which the device reconnects by itself. Keep that in mind
  if you put a proxy in front of the ports (it must not send close frames either).
- Reef Flare writing uses exactly the frames of the device's own web page and was checked byte for
  byte against what the device sends. Rewriting the active program (intensity, points) is **tested on a
  real Reef Flare M** (firmware 1.0.0, 2026-11-05: the light echoed each change within a second, program
  unchanged). Manual presets, manual mode with duration, acclimation, preview and renaming are built the
  same way but still **untested on hardware** - treat them as experimental.
- Reef Flare stores programs and presets in its flash. Do not change intensity or programs every few
  minutes from an automation; for short changes use *manual mode with a duration*.
- Reef Flare: the program list only contains the points of the *active* program. Writing another
  program therefore makes it the active one first.
- *Next calibration* is the date the device reminds you to calibrate again (calibration time + chosen
  reminder period), not the date of the last calibration. Logging the device into a Smart Reef account
  sets it to "today / not due" without any calibration. Without calibration the mL values are estimates.
- Calibration (tested 03.11.2026): put the refill hose into a measuring cup, *fill hose* until water comes,
  stop, empty the cup, run the calibration (default 10 s, as on the device page), enter the measured mL.
  Both work while refilling is paused - pause first so the device does not refill into the cup.

## Pump actions are off by default

Manual refill, calibration run and filling the hose run the refill pump. They are only available as actions
(no dashboard button) and only after enabling *Allow pump actions* in the integration options
(*Settings -> Devices & services -> Reef Factory Local -> Configure*). Stopping always works
(button *Stop pump action* or the stop actions). Factory reset is deliberately not offered.

## Cloud replacement (devices without a local port)

The Smart feeder (and probably the pumps) have no local interface at all: they only talk to
`api.reeffactory.com` (TLS on port 444, ESP8266 devices plain text on 442). They do **not** check the
server certificate, so Home Assistant can take the cloud's place. Add the integration a second time
and choose **Cloud replacement** - no IP, no serial number; every device that connects shows up by
itself with all its entities.

Two modes:
- **Passthrough** (default): everything is forwarded to the real cloud and read along. The official
  app keeps working, Home Assistant can still send commands. When the real cloud cannot be reached,
  the device is served locally instead - automatically.
- **Local**: Home Assistant answers alone; the app does not see the device any more.

### The one thing you have to do yourself: DNS

The devices must resolve `api.reeffactory.com` to the Home Assistant host **inside your network**.
Home Assistant cannot do that for you. Examples:

- **AdGuard Home**: Filters → DNS rewrites → add `api.reeffactory.com` → `<HA IP>`.
- **Pi-hole**: Local DNS → DNS Records → `api.reeffactory.com` → `<HA IP>`.
- **FRITZ!Box** (in addition, if your devices use the box as DNS server): Home Network → Network →
  Network Settings → *DNS Rebind Protection* → add `api.reeffactory.com` as an exception. Without it
  the box swallows the answer and the devices get nothing.
- Routers that let you set a DNS override per host work the same way.

Then restart the devices once (power off/on) - they keep their old connection to the real cloud
otherwise. After that they follow Home Assistant on their own: a restart or reload drops them with a
TCP reset and they reconnect about 15 s later (checked with the Smart feeder, firmware 1.1.6).

Home Assistant must be able to open ports 442, 444 and (for the app passthrough) 80 and 443. That is
the case on Home Assistant OS and in Docker with host networking. If a port is taken (a reverse proxy
on 80/443, say), the log says so; the devices still work, only the official app will not work from
inside your network.

Everyone in your network who looks up `api.reeffactory.com` now gets Home Assistant - including the
phone with the official app. Ports 80/443 are passed through untouched (end-to-end TLS with the real
cloud), so the app works at home as well; from outside your network nothing changes.

### Security note

The devices send their account token and e-mail to whatever answers as `api.reeffactory.com` - the
cloud replacement never logs or stores them, but anyone who controls your DNS could read them. That
is a property of the devices, not of this integration.

### Advanced: no DNS at all (firmware patch)

The cloud host name is a plain string in the device firmware. With a serial adapter you can read the
flash, replace the name by the Home Assistant IP and write it back; `tools/` will get a script for
that. Only for people who are comfortable with soldering and esptool - a mistake can brick the device.

## Reef Flare programs

A program is a list of 2 to 31 points `{time: "HH:MM", levels: [7 × 0–100]}`. The first point must be
`00:00`, the last `24:00`, times strictly increasing (the same rules as the device's web page).
The light fades linearly between points; *intensity* scales the whole program. The current points are
in the attributes of the *Program* sensor, so a program can be copied, changed and written back:

```yaml
action: reef_factory_local.flare_program_set
data:
  device_id: <your Reef Flare>
  points:
    - {time: "00:00", levels: [0, 0, 0, 0, 0, 0, 0]}
    - {time: "11:00", levels: [100, 100, 100, 100, 50, 50, 80]}
    - {time: "20:00", levels: [60, 65, 65, 100, 40, 35, 10]}
    - {time: "24:00", levels: [0, 0, 0, 0, 0, 0, 0]}
```

The 7 levels are, in this order (names from the device's own web page):
**UV, violet, indigo, blue, green, red, white**.

## Installation

HACS -> custom repository -> category *Integration*, or copy `custom_components/reef_factory_local`
into your Home Assistant `config/custom_components/` and restart.
Then *Settings -> Devices & services -> Add integration -> Reef Factory Local (unofficial)*.

## Protocol notes

`ws://<ip>/controler`, subprotocol `arduino`, no authentication. Frames are NUL-separated:
`<clientid>\0<topic>\0<subtopic>\0<joinid>\0<data>\0`. Values are sent only to subscribed clients
(`lkConnect`/`tcConnect`/`rfConnect` `join`), one frame per subscription - re-subscribe every 15 s.
Cloud channel (Smart feeder, firmware 1.1.6): same framing, JSON payload - device `geConnect/login`
`{key, token, email, version}`, cloud `geReport/login {"status":"success","pingInterval":20}` and
`geSet/time`; client `sfConnect/join` + `sfGet/all`, device `sfReport/all` (mode, periods, sequence,
nextFeeding, container, history, dailyDose, ledStatus, feedingButton; weights in 0.01 g, times in
minutes of the day, days as a bit mask with bit 0 = Monday); commands `sfExecute/manual`,
`sfSet/mode|settings|container`; events `sfLog/dose`, `sfLog/container`.
See `custom_components/reef_factory_local/protocol.py` and `cloud.py`.

## License

MIT. This repository contains only original code - no firmware, app files or keys from the manufacturer.
