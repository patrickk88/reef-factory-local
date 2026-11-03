"""Level keeper display light."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        if kind == pr.DEVICE_LEVEL_KEEPER:
            return [ReefDisplayLight(c)]
        if kind == pr.DEVICE_THERMO:
            return [ReefThermoFlag(c, "sound", pr.frame_tc_sound), ReefThermoFlag(c, "light", pr.frame_tc_light)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeederFlag(c, "led"), ReefFeederFlag(c, "feeding_button")]
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
