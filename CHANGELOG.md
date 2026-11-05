# Changelog

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
