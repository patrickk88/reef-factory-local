# Changelog

## 1.2.0 - unreleased
- Level keeper: guided calibration on the device page (*Configuration*): number *Calibration run time*, button
  *Start calibration run* (needs *Allow pump actions*), number *Measured amount*, select *Calibration
  reminder*, button *Finish calibration*, sensor *Calibration run time left*. The buttons send the same
  frames as the actions `calibration_start` / `calibration_value`; the values are kept in Home Assistant.
  Suggested by Steven Downer.
- Cloud replacement: finds the real cloud again by itself. If the cloud did not answer when a device connected,
  the device was served locally until Home Assistant restarted and the official app showed it offline. Now the
  cloud is tried again every two minutes and the device is reconnected through it; the cloud's addresses are
  looked up again after a failed attempt (they change).
- Cloud replacement: reloading the entry or changing its options could hang ("unloading") when a connection
  was open that had not sent anything yet - every open connection is reset now and stopping has a time limit.

## 1.1.0 - 2026-11-11
- Smart Roller: control. Switch *Automatic advance*, selects *Advance length* and *Start delay*, buttons
  *Advance now*, *Clear jam* (only while the roller reports jammed), *New roll inserted* and *Used roll
  inserted* with the number *Used roll diameter* (45-140 mm, kept in Home Assistant; the roller works out the
  length left - as in the app). Actions `smart_roller_advance` and `smart_roller_new_roll`. The frames are
  byte-identical to Steven Downer's ha-reef-factory-smartroller 1.0.1 (the tests compare them with his
  `build_message()`), only the values his integration offers are accepted, and every command is logged at
  info level with its bytes. Tested by Steven Downer on his roller - thank you!
- All seven languages have the Smart Roller texts.

## 1.0.0 - 2026-11-07
- Same code as 0.10.0 - first 1.x version number (0.10.0 was easily read as 0.1).

## 0.10.0 - 2026-11-07
- Events: *Feeding* (Smart feeder, from the device's own log message: type and grams), *Refill* (Level keeper,
  every rise of the daily counter: mL and today's total), *Dose* (Dosing pump Pro X4, from the device's dose
  log: channel, name, mL). Nothing fires at start-up for things that happened before.
- **Changed:** next / last feeding (Smart feeder) and next / last dose (X4 channels) are now timestamp sensors
  in Home Assistant's time zone instead of text - usable in time triggers (with an offset). Templates that
  parsed the old text (`YYYY-MM-DD HH:MM`) need updating.
- Reef Flare: sensor *Timed manual mode ends* (from the seconds left the light reports; also when started from
  the app). Small jitter between reports does not change the state.
- Reef Flare: actions *Save manual preset* (`flare_preset_save`, the app's timed programs): overwrite one by
  name or fill the first free slot - name, levels, intensity. The light goes to manual mode for a few seconds
  to report its list, then back to its previous mode. *Timed manual mode* takes `preset`: runs a stored one
  (it becomes the active preset). *Delete manual preset* (`flare_preset_delete`) clears one the way the
  app does. The *Program* sensor has the presets in the attribute `manual_presets` at
  all times; the last known list is kept over a restart (the light reports it only in manual mode).
- Reef Flare: *Delete program* (`flare_program_delete`): resets a stored program (not the active one) to the
  light's empty program - the app itself can only set a program up again.
- Reef Flare: *Import app file* (`flare_import`) and *Export app file* (`flare_export`, returns the JSON) for
  the app's export files - programs and timed programs, byte for byte the app's format.
- Every device: diagnostic sensor *Last report* (to the minute, readable while the device is away; disabled
  by default).

## 0.9.3 - 2026-11-07
- Cloud replacement, app passthrough: if a port is already taken on one address of the host (e.g. Tailscale
  Funnel or Serve on 443 of the tailnet address), the passthrough now listens on the LAN addresses instead of
  giving up - the official app works at home again. The message is now a warning, so it shows in the log.
- Device page: the firmware version is no longer blanked for a moment when a device reconnects.

## 0.9.2 - 2026-11-05
- Reef Flare *Current output*: two decimals (a light that is nearly off showed 0.0 %).

## 0.9.1 - 2026-11-05
- Reef Flare: sensor *Current output* - the mean of the 7 channels times the intensity, right now: in
  program mode from the points of the active program (linear between points, as the light fades), in
  manual mode from the active preset, 0 when off. Attributes: each channel after intensity. Computed, the
  light itself does not report it.
- Reef Flare *Program* sensor: the attributes `levels` and `presets` only in manual mode (they stayed from
  the last manual mode before).
- README: every row of the confirmed-writes table names its device.

## 0.9.0 - 2026-11-05
- Reef Flare: action `flare_manual` - timed manual mode (the app's *timer mode*): manual mode, optional new
  levels for the active manual preset, duration 1-360 min; the light goes back to its program by itself.
  Confirmed on both lights: the duration is only taken while the light is already in manual mode.
- Reef Flare: action `flare_program_create` - new program in the first free slot, a copy of the active
  program or the given points; the light stays on its program unless `activate`. Confirmed on both lights
  (select the slot, write the points, name it, select back).
- All Reef Flare actions take one or more lights (two lights programmed together); `flare_program_set`
  checks every light before writing to any.

## 0.8.2 - 2026-11-05
- Dosing pump Pro X4: action `dosing_pump_set_name` renames a channel (`dpSettings/set` with `name`, captured
  from the app). Confirmed on the device, also with umlauts (sent as UTF-8 like the app). Not a pump action.

## 0.8.1 - 2026-11-05
- Switch "Allow pump actions (10 min)" on the Level keeper and the Dosing pump Pro X4: unlocks the pump
  actions of that entry for ten minutes without changing the option (not stored, off after a restart) -
  e.g. for a dashboard that edits the X4 dosing schedule.

## 0.8.0 - 2026-11-05
- Smart Roller (read only, untested - testers welcome): state, fleece left (m and %), used today, daily
  average, roll length, advance length, start delay, jammed, automatic advance. Report layout from Steven
  Downer's ha-reef-factory-smartroller (MIT), re-implemented. No command is sent to the roller.
- Setup recognises devices whose serial prefix is not known yet by their answer to the subscription
  (only the join request is sent); the result is stored in the entry. So far: Smart Roller.
- README: Smart Roller testers, credits and related projects.

## 0.7.1 - 2026-11-05
- Only writes confirmed on real hardware are offered (review of the HACS default-list submission). The
  README lists every confirmed write per device and firmware.
- Removed until confirmed: Reef Flare actions `flare_manual`, `flare_preset_set`, `flare_program_rename`,
  `flare_preview_start`, `flare_preview_stop`, the manual-preset select and the intensity in manual mode.
  `flare_program_set` now only writes the active program (writing another one switched the light to it).
- Reef Flare: mode and intensity no longer flicker to unknown / unavailable - the dashboard frame the light
  sends in every refresh cycle was read as a mode.

## 0.7.0 - 2026-11-05
- Binary sensors "container low" for each Dosing pump Pro X4 channel and the Smart feeder, threshold in days
  as an option of the cloud replacement entry (default 14).
- Reconfigure: change the address of a device entry (checked against the serial number).
- Diagnostics download for device entries and the cloud replacement entry (secrets redacted); local devices
  now also keep their firmware version on the coordinator (shown in diagnostics).
- Translations: Dutch, French, Spanish, Italian, Polish.

## 0.6.2 - 2026-11-05
- Base pump: feed pause as a switch (`bpSet/mode feedMode` / `auto`) with the remaining time as a sensor
  (`bpReport/feed` countdown); the mode follows `bpLog/mode`.

## 0.6.1 - 2026-11-05
- Dosing pump Pro X4: unit fix - the device counts in 1/10000 ml (0.6.0 showed ten times too much).
- Dosing pump Pro X4: actions `dosing_pump_dose` (manual dose) and `dosing_pump_set_schedule`, behind the
  new "Allow pump actions" option of the cloud replacement entry. Calibration frames documented, not exposed.
- Dosing pump Pro X4: `dpLog/dose` (a dose finished) decoded as `ch<n>_dose_event_ml`.

## 0.6.0 - 2026-11-05
- Base pump (`RFBP…`, via the cloud replacement): mode, alert, speed, feed-mode duration and speed,
  display, backlight - reading and writing (`bpSet/settings`), Wi-Fi signal.
- Dosing pump Pro X4 (`RFDQ…`, via the cloud replacement, reading): per channel next / last dose,
  dosed today, container, days until empty, calibration, schedule and history as attributes.
- Cloud replacement: debug logging shows the (secret-free) JSON of every frame - the way to capture
  the protocol of a device the integration does not decode yet.

## 0.5.1 - 2026-11-05
- Cloud replacement: device connections are dropped with a TCP reset instead of a WebSocket close
  handshake (Home Assistant stop / reload, loss of the real cloud). The Smart feeder never reconnects
  after a close frame; after a reset it is back within ~15 s - no more power cycle after a restart.
- CI: HACS check only runs on public repositories.
- Reef Flare: program write (intensity) verified on a real light; the other write paths stay experimental.

## 0.5.0 - 2026-11-03
- Cloud replacement: Home Assistant stands in for `api.reeffactory.com` (ports 442/444), devices
  without a local port show up by themselves. Passthrough to the real cloud with automatic local
  fallback; app ports 80/443/445/446 passed through.
- Smart feeder: sensors, feeding mode, schedule and interval, container values, LED, feeding button,
  feed now, actions `feeder_feed` and `feeder_set_schedule`.
- Reef Flare: intensity, manual presets, programs (write / rename), acclimation, preview - experimental.
- Level keeper: "Next calibration" instead of "Calibration date"; calibration run default 10 s.

## 0.3.0 - 2026-10-29
- Thermo control: temperature, heating / cooling, all four thresholds, beeper, display light.
- Reef Flare S/M/L (reading): mode, programs, light schedule, intensity, acclimation.
- Local Wi-Fi provisioning tool (`tools/reef_provision.py`).

## 0.2.0 - 2026-10-29
- Level keeper: all settings, pump actions behind an option.

## 0.1.0 - 2026-10-29
- First version: Level keeper reading and refill cycle.
