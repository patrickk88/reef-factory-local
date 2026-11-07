"""Events: Smart feeder feedings, Level keeper refills, Dosing pump Pro X4 doses.

An event fires when the device reports something new after Home Assistant already knew the previous
value - nothing fires at start-up or after a reconnect for things that happened before.
"""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities

_UNSET = object()


def _feeding(data: dict, last) -> tuple[object, list[tuple[str, dict]]]:
    ev = data.get("last_dose_event") or {}
    sig = ev.get("at")
    if last is _UNSET or sig is None or sig == last:
        return sig, []
    return sig, [("feeding", {"feeding_type": ev.get("type"), "grams": ev.get("grams")})]


def _refill(data: dict, last) -> tuple[object, list[tuple[str, dict]]]:
    today = data.get("refilled_today_ml")
    if last is _UNSET or today is None or last is None or today <= last:
        return today, []  # first value, unknown, unchanged, or the daily counter was reset
    return today, [("refill", {"ml": today - last, "today_ml": today})]


def _dose(data: dict, last) -> tuple[object, list[tuple[str, dict]]]:
    sig = tuple(data.get(f"ch{ch}_dose_event_at") for ch in range(1, pr.DOSING_CHANNELS + 1))
    if last is _UNSET:
        return sig, []
    events = []
    for ch, (new, old) in enumerate(zip(sig, last), start=1):
        if new is not None and new != old:
            events.append(("dose", {"channel": ch, "channel_name": data.get(f"ch{ch}_name"),
                                    "ml": data.get(f"ch{ch}_dose_event_ml")}))
    return sig, events


KINDS: dict[str, tuple[str, str, Callable]] = {
    pr.DEVICE_FEEDER: ("feeding_event", "feeding", _feeding),
    pr.DEVICE_LEVEL_KEEPER: ("refill_event", "refill", _refill),
    pr.DEVICE_DOSING_PUMP: ("dose_event", "dose", _dose),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = KINDS.get(pr.device_type(c.serial))
        return [ReefEvent(c, *kind)] if kind else []

    setup_entities(hass, entry, async_add_entities, factory)


class ReefEvent(ReefEntity, EventEntity):
    def __init__(self, coordinator, key: str, event_type: str, extract: Callable) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_event_types = [event_type]
        self._extract = extract
        self._last = _UNSET

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._last, _ = self._extract(self.coordinator.data or {}, _UNSET)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._last, events = self._extract(self.coordinator.data or {}, self._last)
        for event_type, attributes in events:
            self._trigger_event(event_type, attributes)
            self.async_write_ha_state()
        super()._handle_coordinator_update()
