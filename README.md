# Reef Factory Local (unofficial)

Local control of Reef Factory aquarium devices in Home Assistant - no cloud.

> **Unofficial community project. Not affiliated with, endorsed by or supported by Reef Factory.**
> "Reef Factory", "Smart Reef", "Level keeper", "Thermo control", "Reef Flare", "Smart feeder",
> "Base pump" and "Dosing pump Pro X4" are the manufacturer's product names and are used only to
> describe which devices this integration works with.

Reef Factory went insolvent in 2025; the cloud keeps running for now but may disappear.
The devices below already speak a local WebSocket protocol, which this integration uses.

## Supported devices (v1.0)

| Device | Read | Control | Tested firmware |
|---|---|---|---|
| Level keeper (`RFLK…`) | refilled today, state (ok / refilling / water high / water low / paused / calibrating / filling hose / manual refill), current refill time, calibration date, calibration due, cloud connected | refill cycle, max refill time (safety limit), pause refill, display light, set clock; **opt-in pump actions:** manual refill (max 1000 mL), calibration run, fill hose, plus stop | 1.0.0 |
| Thermo control (`RFTC…`) | temperature, heating/cooling, all four thresholds, beeper, display light, cloud connected | thresholds (alarm below / target range low / target range high / alarm above, always sent together, order checked), beeper, display light (°C units only so far) | 1.0.0 |
| Reef Flare S/M/L (`RFRFS…`, `RFRFM…`, `RFRFL…`) | housing temperature, mode, active program with its light schedule (points per channel), list of programs, intensity, current output (computed), acclimation, manual presets, cloud connected | mode (program / manual / off), active program, intensity (program mode); actions: write the active program, create or delete a program, timed manual mode (also with a stored manual preset), save a manual preset, acclimation start / stop (one or more lights) | 1.0.0 |
| Smart feeder (`RFSF…`) - via the **cloud replacement** | next / last feeding, days until empty, fed today, schedule, container empty, real-cloud status, Wi-Fi signal | feed now, feeding mode (schedule / interval), schedule (action), interval, container values, dose per rotation, LED backlight, feeding button, refill reminder | 1.1.6 |
| Base pump (`RFBP…`) - via the **cloud replacement** | mode, feed pause remaining, alert, speed, feed-mode duration and speed, display, backlight, real-cloud status, Wi-Fi signal | feed pause (switch), speed, feed-mode duration and speed, display, backlight (settings always sent together, like the app does) | 1.4.1 |
| Dosing pump Pro X4 (`RFDQ…`) - via the **cloud replacement** | per channel: next dose, last dose, dosed today, container, days until empty, calibration date; schedule, history and calibration details as attributes; real-cloud status, Wi-Fi signal | **opt-in pump actions** (cloud entry options): dose now, replace a channel's schedule (actions); rename a channel (action, not a pump action) | 1.2.3 |
| Smart Roller (serial prefix not known yet - recognised during setup) | state (automatic advance on / off, jammed), fleece left (m and %), used today, daily average, roll length, advance length, start delay, cloud connected | **none - read only** | **untested** - report layout from Steven Downer's [ha-reef-factory-smartroller](https://github.com/downerhouse/ha-reef-factory-smartroller); testers welcome |

## Only confirmed writes are sent

Every write this integration offers was checked on a real device: the change was sent from Home
Assistant, the device reported the new value (for pump runs: the new state and its end), and the old
value was put back. Anything that could not be confirmed this way is not offered - it stays readable
only until someone confirms it on hardware.

| Device (firmware) | Confirmed writes | Date |
|---|---|---|
| Level keeper (1.0.0) | display light, max refill time, set clock, pause refill, fill hose + stop, calibration run, calibration value and reminder | 2026-11-03 |
| Level keeper (1.0.0) | refill cycle, manual refill + stop, calibration run + stop, *Stop pump action* button | 2026-11-05 |
| Thermo control (1.0.0) | beeper, display light, thresholds (all four are one frame) | 2026-11-05 |
| Reef Flare M (1.0.0) | mode program / manual / off, active program, intensity in program mode, write the active program, acclimation start / stop, timed manual mode (levels of the active manual preset and duration; the light goes back to its program by itself), create a program (copy into a free slot), two lights in one action | 2026-11-05 |
| Reef Flare M (1.0.0) | save a manual preset (the app's timed programs: new one in a free slot or overwrite one - name, levels, intensity), delete one (as the app does), timed manual mode with a stored preset (it becomes the active one), on two lights in one action; import of the app's export files (program into the active program or as new program, timed program); delete a program (reset to the light's empty program) | 2026-11-07 |
| Smart feeder (1.1.6) | feed now, feeding mode, interval, rotations, dose per rotation, food in container, capacity, refill reminder, LED backlight, feeding button, schedule | 2026-11-05 |
| Base pump (1.4.1) | feed pause on / off, speed, feed-mode duration and speed, display, backlight | 2026-11-05 |
| Dosing pump Pro X4 (1.2.3) | dose now (1 mL asked, 0.9994 mL reported), set and clear a channel's schedule, rename a channel (also with umlauts) | 2026-11-05 |

Removed in 0.7.1 because they could not be confirmed: Reef Flare manual-preset select, the intensity in
manual mode, renaming a program (the light switched to the renamed program), program preview (the light
reports nothing back), and writing a program other than the active one. Manual mode with a timer and the
levels of the active manual preset are back since 0.9.0 (confirmed: the duration is only taken while the
light is already in manual mode, which `flare_manual` takes care of). Their frames stay documented in `protocol.py` but are never sent.

The **Smart Roller** is read only: nobody has checked this integration on one yet. Its commands (automatic
advance, advance length, start delay, advance now, clear a jam, new roll) are known from Steven Downer's
integration but will only be offered once an owner has confirmed them on a real device.

## Use at your own risk

This software is provided "as is", without warranty of any kind (see the MIT license). It talks to
devices that run pumps, heaters, lights and dosing pumps. A bug, a wrong automation or a lost network
connection can flood a room, overdose a tank or cook or freeze its inhabitants. **You alone are
responsible for your tank.** Keep the devices' own safety limits, watch the tank after installing or
updating, and do not let automations dose or refill without a limit you have checked. The authors are
not liable for any damage to equipment, livestock or property.

The protocol was reverse engineered from the devices' own web pages and from what the devices send on
the network (no firmware was decompiled, no keys or manufacturer files are included). Using it may void
your warranty; check your contract with the manufacturer or dealer if that matters to you.

## Important

- **One connection per device.** While Home Assistant is connected, the Smart Reef app and other
  local tools cannot connect to that device locally (the cloud keeps working).
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
- Reef Flare writing uses exactly the frames of the device's own web page, checked byte for byte
  against what the device sends (see *Only confirmed writes are sent* for what is offered).
- Reef Flare stores programs in its flash. Do not change intensity or programs every few minutes from
  an automation.
- Reef Flare: the device only reports the points of the *active* program, so only the active program
  can be written. To change another one, select it first (*Program* select), then write it.
- *Next calibration* is the date the device reminds you to calibrate again (calibration time + chosen
  reminder period), not the date of the last calibration. Logging the device into a Smart Reef account
  sets it to "today / not due" without any calibration. Without calibration the mL values are estimates.
- Calibration (tested 03.11.2026): put the refill hose into a measuring cup, *fill hose* until water comes,
  stop, empty the cup, run the calibration (default 10 s, as on the device page), enter the measured mL.
  Both work while refilling is paused - pause first so the device does not refill into the cup.

## Container warnings, new address, diagnostics

- **Container low:** every Dosing pump Pro X4 channel and the Smart feeder have a binary sensor
  (*Channel n container low*, *Food running low*). It turns on when the days left - as the device itself
  calculates them - reach the threshold in the options of the *cloud replacement* entry (default 14 days).
  Channels without a schedule have no days-left value, their sensor stays unknown.
- **New IP address:** *Settings -> Devices & services -> Reef Factory Local -> device entry -> menu ->
  Reconfigure*. The device is checked by its serial number. Reef Factory devices offer no network discovery,
  so a fixed address (DHCP reservation) is still the best choice - see *Network notes*.
- **Diagnostics:** *menu -> Download diagnostics* on an entry gives a JSON file with the decoded values
  (tokens, keys, e-mail and Wi-Fi data removed). Please attach it when you open an issue.
- The interface is available in English, German, Dutch, French, Spanish, Italian and Polish.

## Pump actions are off by default

Level keeper: manual refill, calibration run and filling the hose run the refill pump. Dosing pump Pro X4:
dosing now and replacing a channel's schedule put additives into the tank. These are only available as
actions (no dashboard button) and only after enabling *Allow pump actions* - for the Level keeper in its
own entry's options, for the Dosing pump in the options of the *cloud replacement* entry
(*Settings -> Devices & services -> Reef Factory Local -> Configure*). Stopping the Level keeper always
works (button *Stop pump action* or the stop actions). Factory reset is deliberately not offered.

Instead of leaving the option on, the Level keeper and the Dosing pump Pro X4 have a switch *Allow pump
actions (10 min)*: it unlocks the actions of that entry for ten minutes and then turns itself off (it is
not stored - after a restart it is off). A dashboard script can turn it on, call the action and turn it
off again. Nothing is sent to the device by the switch itself.

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

## Events and times

- **Events** (for automations and the logbook): *Feeding* (Smart feeder; type and grams), *Refill* (Level keeper;
  mL of this refill and today's total), *Dose* (Dosing pump Pro X4; channel, name and mL). An event fires when
  the device reports something new while Home Assistant is running - nothing is replayed after a restart.
- **Times are timestamps:** next / last feeding and next / last dose per X4 channel. A time trigger can use them
  directly, e.g. a feed pause 30 seconds before the next feeding:

```yaml
triggers:
  - trigger: time
    at:
      entity_id: sensor.<your feeder>_next_feeding
      offset: "-00:00:30"
```

- **Reef Flare:** *Timed manual mode ends* - when the light goes back to its program (also when the manual
  mode was started from the app).
- **Last report** (diagnostic, every device, disabled by default): when the device last sent anything, to
  the minute. Stays readable while the device is away.

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

All Reef Flare actions take one or more lights - handy if two lights are programmed together (each light
must have a program of that name active when `program` is given, otherwise nothing is written).

A new program goes into the first free slot (the light stores 8). Without `points` it is a copy of the
active program; the light stays on its current program unless `activate` is on:

```yaml
action: reef_factory_local.flare_program_create
data:
  device_id: [<Reef Flare 1>, <Reef Flare 2>]
  name: Summer
  activate: true
```

The app cannot really delete a program, only set it up again; `flare_program_delete` sets a stored program
(not the active one) back to what the light puts into a free slot - 08:00-20:00 at 40/35/30/25/20/15/10 %,
intensity 100 %, no name (the app lists it as empty). The light briefly selects it and goes back.

Timed manual mode (the app's *timer mode*): the light switches to manual mode with the given levels for the
active manual preset and goes back to its program by itself when the time is up (1 to 360 minutes). To end
it earlier, set the *Mode* select back to *Program*.

```yaml
action: reef_factory_local.flare_manual
data:
  device_id: [<Reef Flare 1>, <Reef Flare 2>]
  levels: [0, 30, 30, 40, 0, 0, 10]
  duration_min: 30
```

The light stores 8 manual presets - the *timed programs* of the app, with name, levels and intensity. They are
in the attribute `manual_presets` of the *Program* sensor. The light reports them only in manual mode, so the
last known list is kept over a restart; writing always reads it fresh. Run a stored one (it becomes the
active preset; its levels stay as they are):

```yaml
action: reef_factory_local.flare_manual
data:
  device_id: [<Reef Flare 1>, <Reef Flare 2>]
  preset: Moonlight
  duration_min: 60
```

Save one - without `preset` a new one goes into the first free slot, with `preset` that one is overwritten
(and renamed if `name` differs). The light goes to manual mode for a few seconds to report its list and then
back to its previous mode:

```yaml
action: reef_factory_local.flare_preset_save
data:
  device_id: [<Reef Flare 1>, <Reef Flare 2>]
  name: Moonlight
  levels: [0, 10, 10, 30, 0, 0, 0]
  intensity: 50
```

`flare_preset_delete` (with `preset`) deletes one the way the app does: the name is cleared and all
channels go to 10 %; the slot is free again.

The app can export a program or a timed program as a small JSON file. `flare_import` takes the content of
such a file (paste the text): a program file overwrites the active program (with `name` it becomes a new
program instead), a timed program file is saved as manual preset. `flare_export` returns the active program
(or, with `preset`, a manual preset) in the same format - the result can be imported in the app again.

```yaml
action: reef_factory_local.flare_import
data:
  device_id: [<Reef Flare 1>, <Reef Flare 2>]
  file: '{"n":"Grün","s":true,"l":[0.1,0.1,0.1,0.54,1,0.1,0.1],"intensity":63}'
```

## Installation

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=patrickk88&repository=reef-factory-local&category=integration)

The button adds this repository to HACS in your own Home Assistant (as a custom repository,
category *Integration*); then download *Reef Factory Local* in HACS and restart Home Assistant.
Without the button: HACS -> menu -> *Custom repositories* -> `https://github.com/patrickk88/reef-factory-local`,
type *Integration*. Or copy `custom_components/reef_factory_local` into your Home Assistant
`config/custom_components/` and restart.
Then *Settings -> Devices & services -> Add integration -> Reef Factory Local (unofficial)*, or:

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=reef_factory_local)

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

## Smart Roller testers wanted

The Smart Roller is recognised during setup: its serial number prefix is not known yet, so when a device
answers with an unknown serial, the setup sends it the Smart Roller subscription and waits a few seconds
for its report (nothing is written). If you own one, please set it up, compare the values with the app and
open an issue with the *Download diagnostics* file (it contains the raw report, `report_hex`, which lets us
check every value).

## Credits and related projects

- **Steven Downer** - the Smart Roller report layout comes from his
  [ha-reef-factory-smartroller](https://github.com/downerhouse/ha-reef-factory-smartroller) (MIT License,
  Copyright (c) 2026 Steven Downer), re-implemented here. He also wrote a local
  [Level keeper integration](https://github.com/downerhouse/ha-reef-factory-level-keeper); both offer
  controls for these devices.
- Other Home Assistant integrations for Reef Factory devices this one does not cover:
  [ha-reeffactory-ph](https://github.com/dominikhartl/ha-reeffactory-ph) (pH meters, local),
  [reef-factory-kh](https://github.com/realiztw/reef-factory-kh) (KH Keeper Plus, via the Smart Reef cloud),
  [ha-reeffactory](https://github.com/patrick2724/ha-reeffactory) (several devices).

## Support the project

This is a hobby project, free for everyone. If it saved your tank's cloud-dependent gear, you can
buy me a coffee - it goes into test hardware (a spare Reef Flare board, dosing pump parts) and time.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-%E2%98%95-yellow?style=for-the-badge)](https://buymeacoffee.com/patrical)

## License

MIT - see `LICENSE`. This repository contains only original code: no firmware, app files, certificates
or keys from the manufacturer. Protocol knowledge comes from the devices' own web pages (served by the
devices themselves) and from network captures of the author's own devices; the Smart Roller report layout
comes from Steven Downer's MIT-licensed integration (see *Credits*).
