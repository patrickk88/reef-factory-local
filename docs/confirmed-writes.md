# Confirmed writes

[← Back to the README](../README.md)

Every write this integration offers was checked on a real device: the change was sent from Home
Assistant, the device reported the new value (for pump runs: the new state and its end), and the old
value was put back. Anything that could not be confirmed this way is not offered - it stays readable
only until someone confirms it on hardware. I own no Smart Roller: its writes were tested by
Steven Downer on his device (last row).

**Nothing is filled in.** Several devices take a group of settings in one frame (Smart feeder container
values, interval and the two flags; all five Base pump settings; Smart Roller advance length and start
delay; a Reef Flare program or the list of manual presets). To change one value the integration repeats the
others exactly as the device last reported them. While one of them has not been reported yet - right after
connecting the first frame is often only the Wi-Fi signal - the entities are unavailable and the write is
refused with a message; no zero or default is sent in its place.

## The table

| Device (firmware) | Confirmed writes | Date |
|---|---|---|
| Level keeper (1.0.0) | display light, max refill time, set clock, pause refill, fill hose + stop, calibration run, calibration value and reminder | 2026-11-03 |
| Level keeper (1.0.0) | refill cycle, manual refill + stop, calibration run + stop, *Stop pump action* button | 2026-11-05 |
| Level keeper (1.0.0) | guided calibration with the buttons on the device page: *Calibration 2: Start run* (10 s run, the countdown, then waiting for the amount) and *Calibration 5: Finish* (225 mL sent, the device stores it; reminder left unchanged) | 2026-11-12 |
| Thermo control (1.0.0) | beeper, display light, thresholds (all four are one frame) | 2026-11-05 |
| Reef Flare S (1.0.0) | mode program / manual / off, active program, intensity in program mode, write the active program, acclimation start / stop, timed manual mode (levels of the active manual preset and duration; the light goes back to its program by itself), create a program (copy into a free slot), two lights in one action | 2026-11-05 |
| Reef Flare S (1.0.0) | save a manual preset (the app's timed programs: new one in a free slot or overwrite one - name, levels, intensity), delete one (as the app does), timed manual mode with a stored preset (it becomes the active one), on two lights in one action; import of the app's export files (program into the active program or as new program, timed program); delete a program (reset to the light's empty program) | 2026-11-07 |
| Smart feeder (1.1.6) | feed now, feeding mode, interval, rotations, dose per rotation, food in container, capacity, refill reminder, LED backlight, feeding button, schedule | 2026-11-05 |
| Base pump (1.4.1) | feed pause on / off, speed, feed-mode duration and speed, display, backlight | 2026-11-05 |
| Dosing pump Pro X4 (1.2.3) | dose now (1 mL asked, 0.9994 mL reported), set and clear a channel's schedule, rename a channel (also with umlauts) | 2026-11-05 |
| Smart Roller (1.1.1, Steven Downer's device) | automatic advance on / off, advance length, start delay, advance now, clear a jam, new roll - tested by Steven Downer with the 1.1.0b1 test build. Used roll by outer diameter: the same frame his own integration sends on that roller (the entities for it are new in 1.1.0) | 2026-11-10 |

## Notes on the table

<details>
<summary>Reef Flare M and L</summary>

The **Reef Flare** rows are from two Reef Flare S. The M and L models hold two and three of the same light
modules, and the manufacturer's own web interface uses one and the same page for all of them (serial numbers
`RFRFS…`, `RFRFM…`, `RFRFL…`), so the integration treats them the same way.

</details>

<details>
<summary>Smart Roller</summary>

The **Smart Roller** commands are byte for byte the ones Steven Downer's integration sends (the unit tests
compare them with his `build_message()`), and only the values his integration offers are accepted.

</details>

<details>
<summary>What is still not offered, and what came back</summary>

Still not offered because it could not be confirmed: the Reef Flare **program preview** (the light reports
nothing back) - its frame stays documented in `protocol.py` but is never sent - and finishing a calibration
of the Dosing pump Pro X4. The other Reef Flare writes that 0.7.1 removed for the same reason are back, each
confirmed on hardware (rows above): timed manual mode (0.9.0; the duration is only taken while the light is
already in manual mode, which `flare_manual` takes care of), a new program in another slot with its name
(0.9.0), manual presets with name, levels and intensity, running a stored one, and resetting a program
(0.10.0). They are actions; there is no select or number entity for manual presets and no action that
renames an existing program (create a copy under the new name, then reset the old one).

</details>
