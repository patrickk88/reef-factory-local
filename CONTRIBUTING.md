# Contributing

Bug reports, captures of unsupported devices and pull requests are welcome.

## A device that is not supported yet

**With a local port (it shows its own page at `http://<device-ip>`):** from version 1.4.0 on, add it like
any other device by its IP address. It appears as *Unknown Reef Factory device*: read only, nothing is
subscribed or written, the integration only asks it for its config (and once, at setup, whether it is a
Smart Roller).

**Without a local port (cloud only):** set up the [cloud replacement](docs/cloud-replacement.md) in
passthrough mode. A device of an unknown type that connects is passed through to the real cloud as usual
and gets no entities, but what it sends to the cloud and what the cloud sends to it is kept.

Then, in both cases:

1. Let it run for a few minutes and change a few settings in the Smart Reef app or on the device's own
   page - one at a time, and write down what you changed and when. The diagnostics keep the last ten
   different contents of every kind of message with their times, so a change shows as before and after;
   through the cloud replacement the app's command itself is in there too.
2. *Menu -> Download diagnostics* on the entry (for a cloud-only device: on the cloud replacement entry,
   section `unknown_devices`) and attach the file to an issue, together with your notes.

The content of messages that may carry account or Wi-Fi data is left out (they are only counted) - still,
have a look through the file before you post it.

**If that shows too little:** the integration also logs frames of unknown devices at debug level.

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
