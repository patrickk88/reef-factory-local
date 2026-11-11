"""Switches: device settings, plus the temporary "allow pump actions" unlock."""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .const import CONF_ALLOW_PUMP_ACTIONS, DOMAIN, PUMP_UNLOCK_SECONDS
from .entity import ReefEntity
from .platform_setup import setup_entities
from .roller import async_send_roller


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        if kind == pr.DEVICE_LEVEL_KEEPER:
            return [ReefDisplayLight(c), ReefPumpUnlock(c)]
        if kind == pr.DEVICE_DOSING_PUMP:
            return [ReefPumpUnlock(c)]
        if kind == pr.DEVICE_THERMO:
            return [ReefThermoFlag(c, "sound", pr.frame_tc_sound), ReefThermoFlag(c, "light", pr.frame_tc_light)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeederFlag(c, "led"), ReefFeederFlag(c, "feeding_button")]
        if kind == pr.DEVICE_BASE_PUMP:
            return [ReefBasePumpFeed(c), ReefBasePumpFlag(c, "display"), ReefBasePumpFlag(c, "backlight")]
        if kind == pr.DEVICE_SMART_ROLLER:
            return [ReefRollerAuto(c)]
        return []

    setup_entities(hass, entry, async_add_entities, factory)


class ReefDisplayLight(ReefEntity, SwitchEntity):
    _attr_translation_key = "display_light"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "display_light")

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("light")

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.client.async_send(pr.frame_lk_set_light(self.coordinator.serial, on))
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class ReefThermoFlag(ReefEntity, SwitchEntity):
    """Thermo control beeper / display light (tcSound, tcLight on|off)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str, frame_fn) -> None:
        super().__init__(coordinator, f"tc_{key}")
        self._key = key
        self._frame_fn = frame_fn
        self._attr_translation_key = f"tc_{key}"

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get(self._key) is not None

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self._key)

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.client.async_send(self._frame_fn(self.coordinator.serial, on))
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class ReefFeederFlag(ReefEntity, SwitchEntity):
    """Smart feeder LED backlight / feeding button. Both flags are always sent together."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, f"feeder_{key}")
        self._key = key
        self._attr_translation_key = f"feeder_{key}"

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self._key)

    async def _set(self, on: bool) -> None:
        d = self.coordinator.device
        data = self.coordinator.data or {}
        led = on if self._key == "led" else bool(data.get("led", True))
        button = on if self._key == "feeding_button" else bool(data.get("feeding_button", True))
        try:
            await d.async_send(pr.frame_sf_set_flags(d.serial, led, button, d.join_id))
        except ConnectionError as err:
            raise HomeAssistantError(f"Smart feeder not connected: {err}") from err

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class ReefBasePumpFlag(ReefEntity, SwitchEntity):
    """Base pump display / backlight (bpSet/settings always carries all settings)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, f"bp_{key}")
        self._key = key
        self._attr_translation_key = f"bp_{key}"

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get("speed") is not None

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self._key)

    async def _set(self, on: bool) -> None:
        d = self.coordinator.device
        data = dict(self.coordinator.data or {})
        data[self._key] = on
        frame = pr.frame_bp_set_settings(d.serial, data.get("speed") or 0, data.get("feed_mode_time") or 15,
                                         data.get("feed_speed") or 20, bool(data.get("display", True)),
                                         bool(data.get("backlight", True)), d.join_id)
        try:
            await d.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Base pump not connected: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class ReefBasePumpFeed(ReefEntity, SwitchEntity):
    """Feed pause of the Base pump: on = bpSet/mode feedMode (pump at feed speed for the feed time), off = auto."""

    _attr_translation_key = "bp_feed_mode"
    _attr_icon = "mdi:fish"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "bp_feed_mode")

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get("mode") is not None

    @property
    def is_on(self) -> bool | None:
        mode = (self.coordinator.data or {}).get("mode")
        return None if mode is None else mode == "feedMode"

    @property
    def extra_state_attributes(self) -> dict | None:
        d = self.coordinator.data or {}
        return {k: d[k] for k in ("feed_remaining_s", "feed_mode_time", "feed_speed") if d.get(k) is not None} or None

    async def _set(self, on: bool) -> None:
        d = self.coordinator.device
        try:
            await d.async_send(pr.frame_bp_set_mode(d.serial, "feedMode" if on else "auto", d.join_id))
        except ConnectionError as err:
            raise HomeAssistantError(f"Base pump not connected: {err}") from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)


class ReefPumpUnlock(ReefEntity, SwitchEntity):
    """Temporary "allow pump actions" for the entry of this device (10 min, nothing is sent to the device).

    Lets a dashboard script enable the pump actions just for one call instead of leaving the option on.
    Not stored: after a restart it is off. Turning it off ends the unlock; the entry option is not changed.
    """

    _attr_translation_key = "pump_actions_unlock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:lock-open-variant-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "pump_actions_unlock")
        self._cancel = None

    @property
    def _store(self) -> dict:
        return self.hass.data.setdefault(DOMAIN, {}).setdefault("pump_unlock", {})

    @property
    def _entry_id(self) -> str:
        return self.coordinator.config_entry.entry_id

    @property
    def available(self) -> bool:
        return True  # a local flag, independent of the device connection

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.config_entry.options.get(CONF_ALLOW_PUMP_ACTIONS)) or (
            self._store.get(self._entry_id, 0) > time.monotonic())

    @property
    def extra_state_attributes(self) -> dict:
        left = self._store.get(self._entry_id, 0) - time.monotonic()
        return {"permanent": bool(self.coordinator.config_entry.options.get(CONF_ALLOW_PUMP_ACTIONS)),
                "remaining_s": max(0, round(left))}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._store[self._entry_id] = time.monotonic() + PUMP_UNLOCK_SECONDS
        if self._cancel:
            self._cancel()
        self._cancel = async_call_later(self.hass, PUMP_UNLOCK_SECONDS + 1, self._expired)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._store.pop(self._entry_id, None)
        if self._cancel:
            self._cancel()
            self._cancel = None
        self.async_write_ha_state()

    @callback
    def _expired(self, _now) -> None:
        self._cancel = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._cancel:
            self._cancel()
        await super().async_will_remove_from_hass()


class ReefRollerAuto(ReefEntity, SwitchEntity):
    """Smart Roller automatic advance: srSet/mode 01 / 00."""

    _attr_translation_key = "sr_auto"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_auto")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        return None if "auto" not in data else bool(data["auto"])

    async def async_turn_on(self, **kwargs: Any) -> None:
        await async_send_roller(self.coordinator, pr.frame_sr_mode(self.coordinator.serial, True), "automatic advance on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_send_roller(self.coordinator, pr.frame_sr_mode(self.coordinator.serial, False), "automatic advance off")
