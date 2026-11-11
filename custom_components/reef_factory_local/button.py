"""Level keeper: set device clock, stop any running pump action; feeder; Smart Roller."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities
from .roller import async_send_roller


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        if kind == pr.DEVICE_LEVEL_KEEPER:
            return [ReefSyncTime(c), ReefStopPump(c)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeedNow(c)]
        if kind == pr.DEVICE_SMART_ROLLER:
            return [ReefRollerAdvance(c), ReefRollerUnblock(c), ReefRollerNewRoll(c), ReefRollerUsedRoll(c)]
        return []

    setup_entities(hass, entry, async_add_entities, factory)


class _ReefButton(ReefEntity, ButtonEntity):
    async def _send(self, *frames: bytes) -> None:
        try:
            for frame in frames:
                await self.coordinator.client.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err


class ReefSyncTime(_ReefButton):
    _attr_translation_key = "sync_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sync_time")

    async def async_press(self) -> None:
        await self._send(pr.frame_set_time(self.coordinator.serial, dt_util.now()))


class ReefStopPump(_ReefButton):
    """Stops manual refill, calibration run and hose filling. Always allowed."""

    _attr_translation_key = "stop_pump"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "stop_pump")

    async def async_press(self) -> None:
        s = self.coordinator.serial
        await self._send(pr.frame_lk_manual_refill_stop(s), pr.frame_lk_calibration_stop(s),
                         pr.frame_lk_circuit_stop(s))


class ReefFeedNow(_ReefButton):
    """Smart feeder: one manual feeding (one rotation, as the button on the device)."""

    _attr_translation_key = "feed_now"
    _attr_icon = "mdi:fish"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "feed_now")

    async def async_press(self) -> None:
        d = self.coordinator.device
        await self._send(pr.frame_sf_feed(d.serial, 1, d.join_id))


class ReefRollerAdvance(ReefEntity, ButtonEntity):
    """Smart Roller: advance the fleece now by the set advance length (srExecute/manual)."""

    _attr_translation_key = "sr_advance"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_advance")

    async def async_press(self) -> None:
        length = (self.coordinator.data or {}).get("shift_mm")
        if length not in pr.SR_MANUAL_MM:
            raise HomeAssistantError("Set an advance length (3-15 cm) first, or use the action smart_roller_advance")
        await async_send_roller(self.coordinator, pr.frame_sr_manual(self.coordinator.serial, length),
                                f"advance {length} mm now")


class ReefRollerUnblock(ReefEntity, ButtonEntity):
    """Smart Roller: clear a jam (srSet/unblock) - only offered while the roller reports jammed."""

    _attr_translation_key = "sr_unblock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_unblock")

    @property
    def available(self) -> bool:
        return super().available and bool((self.coordinator.data or {}).get("jammed"))

    async def async_press(self) -> None:
        await async_send_roller(self.coordinator, pr.frame_sr_unblock(self.coordinator.serial), "clear jam")


class ReefRollerNewRoll(ReefEntity, ButtonEntity):
    """Smart Roller: a new roll was inserted (srSet/newRoll ffffffff00)."""

    _attr_translation_key = "sr_new_roll"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_new_roll")

    async def async_press(self) -> None:
        await async_send_roller(self.coordinator, pr.frame_sr_new_roll(self.coordinator.serial), "new roll")


class ReefRollerUsedRoll(ReefEntity, ButtonEntity):
    """Smart Roller: a used (partial) roll was inserted - srSet/newRoll with its outer diameter, taken from
    the number entity *Used roll diameter*. The roller works out the remaining length itself. Same two
    steps as the app and Steven Downer's integration (choose used, enter the diameter, apply)."""

    _attr_translation_key = "sr_used_roll"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_used_roll")

    async def async_press(self) -> None:
        diameter = self.coordinator.sr_used_diameter_mm
        await async_send_roller(self.coordinator, pr.frame_sr_new_roll(self.coordinator.serial, diameter),
                                f"used roll, outer diameter {diameter} mm")
