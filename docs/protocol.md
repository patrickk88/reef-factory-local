# Protocol notes

[← Back to the README](../README.md)

## How the protocol was found

I worked the protocol out from the devices' own web pages and from what my devices send on the network.
I also read out the flash of two of my own devices (a Reef Flare and the Smart feeder) and searched it for
readable text such as the cloud host name. I did not decompile or change any firmware, and no keys or
manufacturer files are included.

This repository contains only original code: no firmware, app files, certificates or keys from the
manufacturer. The Smart Roller report layout and commands come from Steven Downer's MIT-licensed
[ha-reef-factory-smartroller](https://github.com/downerhouse/ha-reef-factory-smartroller).

## Local port

`ws://<ip>/controler`, subprotocol `arduino`, no authentication. Frames are NUL-separated:
`<clientid>\0<topic>\0<subtopic>\0<joinid>\0<data>\0`. Values are sent only to subscribed clients
(`lkConnect`/`tcConnect`/`rfConnect` `join`), one frame per subscription - re-subscribe every 15 s.

## Cloud channel

<details open>
<summary><b>Smart feeder, firmware 1.1.6</b></summary>

Same framing, JSON payload:

- device `geConnect/login` `{key, token, email, version}`,
- cloud `geReport/login {"status":"success","pingInterval":20}` and `geSet/time`,
- client `sfConnect/join` + `sfGet/all`, device `sfReport/all` (mode, periods, sequence, nextFeeding,
  container, history, dailyDose, ledStatus, feedingButton; weights in 0.01 g, times in minutes of the day,
  days as a bit mask with bit 0 = Monday),
- commands `sfExecute/manual`, `sfSet/mode|settings|container`,
- events `sfLog/dose`, `sfLog/container`.

</details>

See `custom_components/reef_factory_local/protocol.py` and `cloud.py`.
