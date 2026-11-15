# Contributing

Bug reports, captures of unsupported devices and pull requests are welcome.

## A device that is not supported yet

The integration logs frames of unknown devices at debug level. To help:

1. Enable debug logging for `custom_components.reef_factory_local` (Settings → Devices & services →
   Reef Factory Local → Enable debug logging), let the device run for a few minutes, disable it again
   and attach the downloaded log to an issue.
2. Say what the device is (name, firmware from the app) and what you did meanwhile (changed a
   setting, pressed a button) with the time.

Use version 1.2.3 or newer for this: account and Wi-Fi data are never written to the log since then
(older versions wrote the login of Level keeper, Thermo control and Reef Flare). The serial number is logged.

## Rules

- Only original code. No firmware, app files, certificates or keys from the manufacturer.
- Anything that adds water or additives to the tank (refill pump, dosing pump) must stay opt-in.
  A single feeding, like the button on the feeder itself, is available without it.
