# Automations: events, times, container warnings

[← Back to the README](../README.md)

## Events

For automations and the logbook:

| Event | Device | Data |
|---|---|---|
| *Feeding* | Smart feeder | type and grams |
| *Refill* | Level keeper | mL of this refill and today's total |
| *Dose* | Dosing pump Pro X4 | channel, name and mL |

An event fires when the device reports something new while Home Assistant is running - nothing is replayed
after a restart.

## Times are timestamps

Next / last feeding and next / last dose per X4 channel are timestamps. A time trigger can use them
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

## Container low

Every Dosing pump Pro X4 channel and the Smart feeder have a binary sensor (*Channel n container low*,
*Food running low*). It turns on when the days left - as the device itself calculates them - reach the
threshold in the options of the *cloud replacement* entry (default 14 days). Channels without a schedule
have no days-left value, their sensor stays unknown.

## Pump actions from a script

Refilling and dosing are opt-in. A script can unlock them for a moment: turn on the switch *Allow pump
actions (10 min)*, call the action, turn the switch off again - see
[Pump actions](pump-actions.md#unlock-for-ten-minutes-instead).

## Reef Flare

All light actions with examples are on their own page: [Reef Flare programs and actions](reef-flare.md).
