"""Level keeper max refill time and pause, Thermo control thresholds, Reef Flare intensity."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities


@dataclass(frozen=True, kw_only=True)
class ReefNumberDescription(NumberEntityDescription):
    data_key: str
    frame_fn: Callable[[str, int], bytes]


NUMBERS: tuple[ReefNumberDescription, ...] = (
    ReefNumberDescription(
        key="max_refill_time", translation_key="max_refill_time", data_key="max_refill_time_s",
        frame_fn=pr.frame_lk_set_max_refill_time, entity_category=EntityCategory.CONFIG,
        native_min_value=0, native_max_value=pr.LK_MAX_MINUTES, native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES, mode=NumberMode.BOX,
    ),
    ReefNumberDescription(
        key="refill_pause", translation_key="refill_pause", data_key="temporary_off_s",
        frame_fn=pr.frame_lk_temporary_off,
        native_min_value=0, native_max_value=pr.LK_MAX_MINUTES, native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES, mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        if kind == pr.DEVICE_LEVEL_KEEPER:
            return [ReefNumber(c, d) for d in NUMBERS]
        if kind == pr.DEVICE_THERMO:
            return [ReefThermoThreshold(c, key) for key in THERMO_KEYS]
        if kind == pr.DEVICE_FLARE:
            return [ReefFlareIntensity(c)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeederNumber(c, key) for key in FEEDER_NUMBERS]
        if kind == pr.DEVICE_BASE_PUMP:
            return [ReefBasePumpNumber(c, key) for key in BASE_PUMP_NUMBERS]
        return []

    setup_entities(hass, entry, async_add_entities, factory)


class ReefNumber(ReefEntity, NumberEntity):
    """Value shown in whole minutes (rounded up); 0 means off / no pause."""

    entity_description: ReefNumberDescription

    def __init__(self, coordinator, description: ReefNumberDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        seconds = (self.coordinator.data or {}).get(self.entity_description.data_key)
        if seconds is None:
            return None
        return math.ceil(seconds / 60)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.async_send(
                self.entity_description.frame_fn(self.coordinator.serial, int(value))
            )
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err


# order the device expects: alarm_low < range_low < range_high < alarm_high
THERMO_KEYS = ("alarm_low", "range_low", "range_high", "alarm_high")
THERMO_LIMITS = (15.0, 35.0)  # degC, generous but sane for reef tanks


class ReefThermoThreshold(ReefEntity, NumberEntity):
    """One of the four Thermo control thresholds; all four are sent together."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value, _attr_native_max_value = THERMO_LIMITS

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        # Fahrenheit units are not supported yet: show unavailable instead of wrong values
        return super().available and data.get("fahrenheit") is False and data.get(self._key) is not None

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        data = dict(self.coordinator.data or {})
        if any(data.get(k) is None for k in THERMO_KEYS):
            raise HomeAssistantError("Thresholds not known yet")
        data[self._key] = round(value, 1)
        vals = [data[k] for k in THERMO_KEYS]
        if not all(a < b for a, b in zip(vals, vals[1:])):
            raise ServiceValidationError(translation_domain="reef_factory_local", translation_key="thermo_order")
        try:
            await self.coordinator.client.async_send(pr.frame_tc_set_settings(
                self.coordinator.serial, data["range_low"], data["range_high"],
                data["alarm_low"], data["alarm_high"], fahrenheit=False))
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err


class ReefFlareIntensity(ReefEntity, NumberEntity):
    """Intensity of the active program (program mode only).

    Rewrites the active program unchanged except for the intensity byte (the device stores
    it - avoid changing it every few minutes from automations). Changing the intensity of a
    manual preset is not offered: it was not confirmed on hardware.
    """

    _attr_translation_key = "flare_intensity"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "flare_intensity")

    def _frame(self, value: int) -> bytes | None:
        d = self.coordinator.data or {}
        s = self.coordinator.serial
        if d.get("mode") == "program" and d.get("points") and d.get("program_time_raw") is not None:
            return pr.frame_rf_precise_update(s, d.get("program_index", 0), d["program_time_raw"], d["points"], value)
        return None

    @property
    def available(self) -> bool:
        return super().available and self._frame(0) is not None

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("intensity")

    async def async_set_native_value(self, value: float) -> None:
        frame = self._frame(int(value))
        if frame is None:
            raise HomeAssistantError("Intensity can only be changed in program mode")
        try:
            await self.coordinator.client.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Device not connected: {err}") from err


# Smart feeder numbers: key -> (data key, min, max, step, unit)
FEEDER_NUMBERS: dict[str, tuple] = {
    "container": ("container_g", 0, 2000, 0.1, "g"),
    "container_size": ("container_size_g", 0, 2000, 0.1, "g"),
    "single_dose": ("single_dose_g", 0, 100, 0.01, "g"),
    "interval_minutes": ("interval_minutes", 1, 1440, 1, UnitOfTime.MINUTES),
    "interval_rotations": ("interval_rotations", 1, pr.FEEDER_MAX_ROTATIONS, 1, None),
    "reminder_days": ("reminder_days", 0, 90, 1, UnitOfTime.DAYS),
}


class ReefFeederNumber(ReefEntity, NumberEntity):
    """Container values (sent as one triple), interval (sent as one pair) and reminder of the Smart feeder."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, f"feeder_{key}")
        self._key = key
        data_key, lo, hi, step, unit = FEEDER_NUMBERS[key]
        self._data_key = data_key
        self._attr_translation_key = f"feeder_{key}"
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = lo, hi, step
        self._attr_native_unit_of_measurement = unit
        if key == "container":
            self._attr_entity_category = None
            self._attr_icon = "mdi:cup"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self._data_key)

    async def async_set_native_value(self, value: float) -> None:
        d = self.coordinator.device
        data = dict(self.coordinator.data or {})
        data[self._data_key] = value
        s = d.serial
        if self._key in ("container", "container_size", "single_dose"):
            frame = pr.frame_sf_set_container(s, data.get("container_g") or 0, data.get("container_size_g") or 0,
                                              data.get("single_dose_g") or 0, d.join_id)
        elif self._key.startswith("interval"):
            frame = pr.frame_sf_set_interval(s, int(data.get("interval_minutes") or 60),
                                             int(data.get("interval_rotations") or 1), d.join_id)
        else:
            frame = pr.frame_sf_set_reminder(s, int(value), d.join_id)
        try:
            await d.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Smart feeder not connected: {err}") from err


# Base pump numbers: key -> (data key, min, max, step, unit, config category)
BASE_PUMP_NUMBERS: dict[str, tuple] = {
    "speed": ("speed", 0, 100, 1, "%", False),
    "feed_mode_time": ("feed_mode_time", 1, 120, 1, UnitOfTime.MINUTES, True),
    "feed_speed": ("feed_speed", 0, 100, 1, "%", True),
}


class ReefBasePumpNumber(ReefEntity, NumberEntity):
    """Speed, feed-mode duration and feed-mode speed of the Base pump (bpSet/settings sends all values)."""

    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, f"bp_{key}")
        self._key = key
        data_key, lo, hi, step, unit, config = BASE_PUMP_NUMBERS[key]
        self._data_key = data_key
        self._attr_translation_key = f"bp_{key}"
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = lo, hi, step
        self._attr_native_unit_of_measurement = unit
        if config:
            self._attr_entity_category = EntityCategory.CONFIG
        else:
            self._attr_icon = "mdi:pump"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self._data_key)

    async def async_set_native_value(self, value: float) -> None:
        d = self.coordinator.device
        data = dict(self.coordinator.data or {})
        if data.get("speed") is None:
            raise HomeAssistantError("Base pump has not reported its settings yet")
        data[self._data_key] = int(value)
        frame = pr.frame_bp_set_settings(d.serial, data["speed"], data.get("feed_mode_time") or 15,
                                         data.get("feed_speed") or 20, bool(data.get("display", True)),
                                         bool(data.get("backlight", True)), d.join_id)
        try:
            await d.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Base pump not connected: {err}") from err
