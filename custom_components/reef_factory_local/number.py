"""Level keeper max refill time and pause, Thermo control thresholds, Reef Flare intensity, Smart Roller used roll,
Level keeper guided calibration (run time, measured amount)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity, all_known, known_or_refuse
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
            return [*(ReefNumber(c, d) for d in NUMBERS), ReefCalibrationRunTime(c), ReefCalibrationMeasured(c)]
        if kind == pr.DEVICE_THERMO:
            return [ReefThermoThreshold(c, key) for key in THERMO_KEYS]
        if kind == pr.DEVICE_FLARE:
            return [ReefFlareIntensity(c)]
        if kind == pr.DEVICE_FEEDER:
            return [ReefFeederNumber(c, key) for key in FEEDER_NUMBERS]
        if kind == pr.DEVICE_BASE_PUMP:
            return [ReefBasePumpNumber(c, key) for key in BASE_PUMP_NUMBERS]
        if kind == pr.DEVICE_SMART_ROLLER:
            return [ReefRollerUsedDiameter(c)]
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
    it - avoid changing it every few minutes from automations). The intensity of a manual
    preset is set with the action flare_preset_save.
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
        if d.get("mode") == "program" and all_known(d, pr.FLARE_PROGRAM_KEYS):
            return pr.frame_rf_precise_update(s, d["program_index"], d["program_time_raw"], d["points"], value)
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
    def _group(self) -> tuple[str, ...]:
        """The values that travel in the same frame as this one."""
        if self._data_key in pr.FEEDER_CONTAINER_KEYS:
            return pr.FEEDER_CONTAINER_KEYS
        if self._data_key in pr.FEEDER_INTERVAL_KEYS:
            return pr.FEEDER_INTERVAL_KEYS
        return (self._data_key,)

    @property
    def available(self) -> bool:
        # not before the feeder has reported every value of the frame (the first frame is often only Wi-Fi)
        return super().available and all_known(self.coordinator.data, self._group)

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get(self._data_key)

    async def async_set_native_value(self, value: float) -> None:
        d = self.coordinator.device
        data = dict(self.coordinator.data or {})
        known_or_refuse(data, *self._group)  # refuse instead of sending 0 or a default for an unknown value
        data[self._data_key] = value
        s = d.serial
        if self._group is pr.FEEDER_CONTAINER_KEYS:
            frame = pr.frame_sf_set_container(s, *known_or_refuse(data, *pr.FEEDER_CONTAINER_KEYS), d.join_id)
        elif self._group is pr.FEEDER_INTERVAL_KEYS:
            minutes, rotations = known_or_refuse(data, *pr.FEEDER_INTERVAL_KEYS)
            frame = pr.frame_sf_set_interval(s, int(minutes), int(rotations), d.join_id)
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

    @property
    def available(self) -> bool:
        return super().available and all_known(self.coordinator.data, pr.BASE_PUMP_KEYS)

    async def async_set_native_value(self, value: float) -> None:
        d = self.coordinator.device
        data = dict(self.coordinator.data or {})
        known_or_refuse(data, *pr.BASE_PUMP_KEYS)  # all five settings are one frame - none of them is guessed
        data[self._data_key] = int(value)
        frame = pr.frame_bp_set_settings(d.serial, *known_or_refuse(data, *pr.BASE_PUMP_KEYS), d.join_id)
        try:
            await d.async_send(frame)
        except ConnectionError as err:
            raise HomeAssistantError(f"Base pump not connected: {err}") from err


class ReefRollerUsedDiameter(ReefEntity, RestoreNumber):
    """Smart Roller: outer diameter of a used roll, for the button *Used roll inserted*. The value lives in
    Home Assistant only (kept over restarts) - nothing is sent until the button is pressed."""

    _attr_translation_key = "sr_used_diameter"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = pr.SR_USED_ROLL_MM[0]
    _attr_native_max_value = pr.SR_USED_ROLL_MM[1]
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:tape-measure"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "sr_used_diameter")

    @property
    def available(self) -> bool:
        return True  # a local value - can be set while the roller is away

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            lo, hi = pr.SR_USED_ROLL_MM
            if lo <= last.native_value <= hi:
                self.coordinator.sr_used_diameter_mm = int(last.native_value)

    @property
    def native_value(self) -> int:
        return self.coordinator.sr_used_diameter_mm

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.sr_used_diameter_mm = int(value)
        self.async_write_ha_state()


class ReefCalibrationRunTime(ReefEntity, RestoreNumber):
    """Level keeper guided calibration, step 1: how long the pump runs. Kept in Home Assistant (over restarts);
    sent together with the button *Start calibration run*."""

    _attr_translation_key = "calibration_run_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = pr.LK_CALIBRATION_S[0]
    _attr_native_max_value = pr.LK_CALIBRATION_S[1]
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-cog-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calibration_run_time")

    @property
    def available(self) -> bool:
        return True  # a local value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            lo, hi = pr.LK_CALIBRATION_S
            if lo <= last.native_value <= hi:
                self.coordinator.lk_calibration_s = int(last.native_value)

    @property
    def native_value(self) -> int:
        return self.coordinator.lk_calibration_s

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.lk_calibration_s = int(value)
        self.async_write_ha_state()


class ReefCalibrationMeasured(ReefEntity, NumberEntity):
    """Level keeper guided calibration, step 2: what the measuring cup shows. Empty until entered and emptied
    again by a new run and by saving, so an old value is never saved by accident. Sent with *Finish
    calibration*."""

    _attr_translation_key = "calibration_measured"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = pr.LK_MEASURED_ML[0]
    _attr_native_max_value = pr.LK_MEASURED_ML[1]
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfVolume.MILLILITERS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calibration_measured")

    @property
    def available(self) -> bool:
        return True  # a local value

    @property
    def native_value(self) -> int | None:
        return self.coordinator.lk_measured_ml

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.lk_measured_ml = int(value)
        self.async_write_ha_state()

