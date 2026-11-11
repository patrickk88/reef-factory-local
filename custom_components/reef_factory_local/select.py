"""Level keeper refill cycle and calibration reminder; Reef Flare mode and program; feeder mode; Smart Roller."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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
            return [ReefRefillCycle(c), ReefCalibrationReminder(c)]
        if kind == pr.DEVICE_FLARE:
            return [ReefFlareMode(c), ReefFlareProgram(c)]  # manual presets: not confirmed on hardware yet
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeederMode(c)]
        if kind == pr.DEVICE_SMART_ROLLER:
            return [ReefRollerSetting(c, "sr_shift"), ReefRollerSetting(c, "sr_delay")]
        return []

    setup_entities(hass, entry, async_add_entities, factory)


class ReefRefillCycle(ReefEntity, SelectEntity):
    _attr_translation_key = "refill_cycle"
    _attr_options = list(pr.LK_CYCLES.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refill_cycle")

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get("cycle")

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.async_set_lk_cycle(option)
        except ConnectionError as err:
            raise HomeAssistantError(f"Level keeper not connected: {err}") from err


class ReefFlareMode(ReefEntity, SelectEntity):
    """Program / manual / off."""

    _attr_translation_key = "flare_mode"
    _attr_options = list(pr.FLARE_MODE_CMD)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "flare_mode")

    @property
    def current_option(self) -> str | None:
        mode = (self.coordinator.data or {}).get("mode")
        return mode if mode in pr.FLARE_MODE_CMD else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.async_send(pr.frame_rf_mode(self.coordinator.serial, option))
        except ConnectionError as err:
            raise HomeAssistantError(f"Reef Flare not connected: {err}") from err


class ReefFlareProgram(ReefEntity, SelectEntity):
    """Active stored program. Selecting one switches the light to program mode."""

    _attr_translation_key = "flare_program"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "flare_program")

    @property
    def options(self) -> list[str]:
        return [p for p in (self.coordinator.data or {}).get("programs") or [] if p]

    @property
    def available(self) -> bool:
        return super().available and bool(self.options)

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        return data.get("program") if data.get("mode") == "program" else None

    async def async_select_option(self, option: str) -> None:
        programs = (self.coordinator.data or {}).get("programs") or []
        if option not in programs:
            raise HomeAssistantError(f"Unknown program {option!r}")
        frames = []
        if (self.coordinator.data or {}).get("mode") != "program":
            frames.append(pr.frame_rf_mode(self.coordinator.serial, "program"))
        frames.append(pr.frame_rf_select_program(self.coordinator.serial, programs.index(option)))
        try:
            for frame in frames:
                await self.coordinator.client.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Reef Flare not connected: {err}") from err


class ReefFeederMode(ReefEntity, SelectEntity):
    """Smart feeder: schedule (fixed times) or interval (every n minutes)."""

    _attr_translation_key = "feeder_mode"
    _attr_options = list(pr.FEEDER_MODES.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "feeder_mode")

    @property
    def current_option(self) -> str | None:
        return (self.coordinator.data or {}).get("mode")

    async def async_select_option(self, option: str) -> None:
        d = self.coordinator.device
        try:
            await d.async_send(pr.frame_sf_set_mode(d.serial, option, d.join_id))
        except ConnectionError as err:
            raise HomeAssistantError(f"Smart feeder not connected: {err}") from err


class ReefRollerSetting(ReefEntity, SelectEntity):
    """Smart Roller advance length / start delay. srSet/settings always carries both plus the
    reminder byte, so the other two values come from the roller's last report."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key
        values = pr.SR_SHIFT_MM if key == "sr_shift" else pr.SR_DELAY_S
        self._attr_options = [str(v) for v in values]

    @property
    def _field(self) -> str:
        return "shift_mm" if self._key == "sr_shift" else "delay_s"

    @property
    def current_option(self) -> str | None:
        value = (self.coordinator.data or {}).get(self._field)
        return str(value) if value is not None and str(value) in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        data = self.coordinator.data or {}
        if data.get("shift_mm") is None or data.get("delay_s") is None:
            raise HomeAssistantError("No report from the Smart Roller yet - try again in a few seconds")
        shift = int(option) if self._key == "sr_shift" else data["shift_mm"]
        delay = int(option) if self._key == "sr_delay" else data["delay_s"]
        reminder = data.get("reminder_raw", pr.SR_REMINDER_DEFAULT)
        await async_send_roller(self.coordinator, pr.frame_sr_settings(self.coordinator.serial, shift, delay, reminder),
                                f"settings advance {shift} mm, delay {delay} s, reminder {reminder}")


class ReefCalibrationReminder(ReefEntity, SelectEntity, RestoreEntity):
    """Level keeper guided calibration: when the device should ask for the next calibration. The device does
    not report the period, so the choice is kept in Home Assistant and sent with *Finish calibration*; while
    nothing is chosen, the reminder is left as it is."""

    _attr_translation_key = "calibration_reminder"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(pr.LK_REMINDER)
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calibration_reminder")

    @property
    def available(self) -> bool:
        return True  # a local value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in pr.LK_REMINDER:
            self.coordinator.lk_reminder = last.state

    @property
    def current_option(self) -> str | None:
        return self.coordinator.lk_reminder

    async def async_select_option(self, option: str) -> None:
        self.coordinator.lk_reminder = option
        self.async_write_ha_state()

