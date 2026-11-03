"""Level keeper: set device clock, stop any running pump action."""
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        if kind == pr.DEVICE_LEVEL_KEEPER:
            return [ReefSyncTime(c), ReefStopPump(c)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeedNow(c)]
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
