# Contributing

Bug reports, captures of unsupported devices and pull requests are welcome.

## A device that is not supported yet

**With a local port (it shows its own page at `http://<device-ip>`):** from version 1.4.0 on, add it like
any other device by its IP address. It appears as *Unknown Reef Factory device*: read only, nothing is
subscribed or written, the integration only asks it for its config (and once, at setup, whether it is a
Smart Roller). Let it run for a few minutes, use the
device's own page or the app meanwhile (change a setting, press a button), then *menu -> Download
diagnostics* on the entry and attach the file to an issue. It holds the device's messages as they came;
the content of messages that may carry account or Wi-Fi data is left out - still, have a look through
the file before you post it.

**Without a local port (cloud only), or if the above shows too little:** the integration logs frames of
unknown devices at debug level. To help:

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
