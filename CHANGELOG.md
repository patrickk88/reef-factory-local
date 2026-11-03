# Changelog

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
