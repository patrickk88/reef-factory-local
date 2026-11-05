"""Sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfMass,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities


@dataclass(frozen=True, kw_only=True)
class ReefSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object]
    attrs_fn: Callable[[dict], dict] | None = None


def _cal_date(d: dict):
    if (v := d.get("calibration_date")) is None:
        return None
    try:
        return datetime.date(*v)
    except ValueError:
        return None


def _flare_output(d: dict):
    now = dt_util.now()
    return pr.flare_output(d, now.hour * 60 + now.minute + now.second / 60)


def _flare_attrs(d: dict) -> dict:
    out = {}
    if d.get("programs"):
        out["programs"] = [p for p in d["programs"] if p]
    if d.get("points") is not None:  # same shape the flare_program_set action accepts
        out["points"] = [{"time": p["time"], "levels": p["levels"]} for p in d["points"]]
    if d.get("acclimation") is not None:
        out["acclimation"] = d["acclimation"]
    if d.get("mode") == "manual":  # manual preset values stay in the data after manual mode ended
        for key in ("levels", "presets"):
            if d.get(key) is not None:
                out[key] = d[key]
        out["manual_duration_min"] = None if d.get("manual_time_s") is None else round(d["manual_time_s"] / 60)
    return out


def _mm_to_m(v):
    return None if v is None else v / 1000


def _date_tuple(v):
    if v is None:
        return None
    try:
        return datetime.date(*v)
    except (TypeError, ValueError):
        return None


WIFI = ReefSensorDescription(
    key="wifi_rssi", translation_key="wifi_rssi", device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT, state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
    value_fn=lambda d: d.get("wifi_rssi"),
)


def _dosing_sensors(ch: int) -> tuple[ReefSensorDescription, ...]:
    """Six sensors per channel of the Dosing pump Pro X4; keys ch<n>_*, names with a {channel} placeholder."""
    p = f"ch{ch}_"
    g = lambda key: (lambda d: d.get(p + key))
    return (
        ReefSensorDescription(
            key=p + "next_dose", translation_key="dp_next_dose", icon="mdi:calendar-clock",
            translation_placeholders={"channel": str(ch)}, value_fn=g("next_dose"),
            attrs_fn=lambda d: {k[len(p):]: d[k] for k in (p + "name", p + "next_dose_ml", p + "daily_target_ml",
                                                           p + "mode", p + "schedule") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key=p + "last_dose", translation_key="dp_last_dose", icon="mdi:history",
            translation_placeholders={"channel": str(ch)}, value_fn=g("last_dose"),
            attrs_fn=lambda d: {k[len(p):]: d[k] for k in (p + "name", p + "last_dose_ml", p + "last_dose_type",
                                                           p + "history") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key=p + "dosed_today", translation_key="dp_dosed_today", icon="mdi:water",
            translation_placeholders={"channel": str(ch)}, native_unit_of_measurement=UnitOfVolume.MILLILITERS,
            state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=2, value_fn=g("dosed_today_ml"),
            attrs_fn=lambda d: {k[len(p):]: d[k] for k in (p + "name", p + "daily_target_ml") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key=p + "container", translation_key="dp_container", icon="mdi:cup-water",
            translation_placeholders={"channel": str(ch)}, native_unit_of_measurement=UnitOfVolume.MILLILITERS,
            state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, value_fn=g("container_ml"),
            attrs_fn=lambda d: {k[len(p):]: d[k] for k in (p + "name", p + "container_size_ml", p + "container_status",
                                                           p + "reminder_days") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key=p + "days_to_replace", translation_key="dp_days_to_replace", icon="mdi:calendar-alert",
            translation_placeholders={"channel": str(ch)}, native_unit_of_measurement=UnitOfTime.DAYS,
            state_class=SensorStateClass.MEASUREMENT, value_fn=g("days_to_replace"),
        ),
        ReefSensorDescription(
            key=p + "calibration", translation_key="dp_calibration", device_class=SensorDeviceClass.DATE,
            translation_placeholders={"channel": str(ch)}, entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda d: _date_tuple(d.get(p + "calibration_date")),
            attrs_fn=lambda d: {k[len(p):]: d[k] for k in (p + "name", p + "calibration_state", p + "calibration_coeff",
                                                           p + "calibration_reminder_days", p + "days_to_next_calibration",
                                                           p + "pump_min_ml_min", p + "pump_max_ml_min") if d.get(k) is not None},
        ),
    )


def _lk_attrs(d: dict) -> dict:
    keys = ("manual_refill_done_ml", "manual_refill_target_ml", "calibration_remaining_s",
            "circuit_remaining_s", "alert_code", "level_raw")
    return {k: d[k] for k in keys if d.get(k) is not None}


SENSORS: dict[str, tuple[ReefSensorDescription, ...]] = {
    pr.DEVICE_LEVEL_KEEPER: (
        ReefSensorDescription(
            key="refilled_today", translation_key="refilled_today",
            device_class=SensorDeviceClass.VOLUME, state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfVolume.MILLILITERS,
            value_fn=lambda d: d.get("refilled_today_ml"),
        ),
        ReefSensorDescription(
            key="water_level", translation_key="water_level",
            device_class=SensorDeviceClass.ENUM, options=pr.LK_LEVEL_OPTIONS,
            value_fn=lambda d: d.get("level"), attrs_fn=_lk_attrs,
        ),
        ReefSensorDescription(
            key="refill_time", translation_key="refill_time",
            device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS,
            value_fn=lambda d: d.get("refill_time_s"),
        ),
        ReefSensorDescription(
            key="calibration_date", translation_key="calibration_date",
            device_class=SensorDeviceClass.DATE, entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_cal_date,
        ),
    ),
    pr.DEVICE_THERMO: (
        ReefSensorDescription(
            key="temperature", device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS, suggested_display_precision=1,
            value_fn=lambda d: d.get("temperature"),
        ),
        ReefSensorDescription(
            key="thermo_state", translation_key="thermo_state",
            device_class=SensorDeviceClass.ENUM, options=["heating", "cooling", "idle"],
            value_fn=lambda d: d.get("state"),
        ),
    ),
    pr.DEVICE_FLARE: (
        ReefSensorDescription(
            key="housing_temperature", translation_key="housing_temperature",
            device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            value_fn=lambda d: d.get("temperature"),
        ),
        ReefSensorDescription(
            key="intensity", translation_key="intensity",
            state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
            value_fn=lambda d: d.get("intensity"),
        ),
        ReefSensorDescription(
            key="output", translation_key="output", icon="mdi:brightness-6",
            state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
            suggested_display_precision=1,
            value_fn=lambda d: (r := _flare_output(d)) and r[0],
            attrs_fn=lambda d: (r := _flare_output(d)) and r[1] or {},
        ),
        ReefSensorDescription(
            key="light_mode", translation_key="light_mode",
            device_class=SensorDeviceClass.ENUM, options=["program", "manual", "off"],
            value_fn=lambda d: d.get("mode"),
        ),
        ReefSensorDescription(
            key="program", translation_key="program",
            value_fn=lambda d: d.get("program"), attrs_fn=_flare_attrs,
        ),
    ),
    pr.DEVICE_FEEDER: (
        ReefSensorDescription(
            key="next_feeding", translation_key="next_feeding", icon="mdi:fish",
            value_fn=lambda d: d.get("next_feeding"),
            attrs_fn=lambda d: {k: d[k] for k in ("next_feeding_g",) if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key="last_feeding", translation_key="last_feeding", icon="mdi:history",
            value_fn=lambda d: d.get("last_feeding"),
            attrs_fn=lambda d: {k: d[k] for k in ("last_feeding_type", "last_feeding_g", "history") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key="days_to_end", translation_key="days_to_end", icon="mdi:calendar-clock",
            native_unit_of_measurement=UnitOfTime.DAYS, state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda d: d.get("days_to_end"),
        ),
        ReefSensorDescription(
            key="daily_dose", translation_key="daily_dose", icon="mdi:scale",
            native_unit_of_measurement=UnitOfMass.GRAMS, state_class=SensorStateClass.TOTAL_INCREASING,
            suggested_display_precision=2, value_fn=lambda d: d.get("daily_dose_g"),
        ),
        ReefSensorDescription(
            key="schedule", translation_key="schedule", icon="mdi:calendar-check",
            value_fn=lambda d: len(d["schedule"]) if d.get("schedule") is not None else None,
            attrs_fn=lambda d: {"entries": [{"time": e["time"], "rotations": e["rotations"], "days": e["days"]}
                                           for e in d.get("schedule") or []]},
        ),
        WIFI,
    ),
    pr.DEVICE_BASE_PUMP: (
        ReefSensorDescription(
            key="bp_mode", translation_key="bp_mode", icon="mdi:pump", value_fn=lambda d: d.get("mode"),
            attrs_fn=lambda d: {k: d[k] for k in ("alert",) if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key="bp_feed_remaining", translation_key="bp_feed_remaining", icon="mdi:timer-sand",
            device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS,
            value_fn=lambda d: d.get("feed_remaining_s", 0) if d.get("mode") == "feedMode" else 0,
        ),
        WIFI,
    ),
    pr.DEVICE_DOSING_PUMP: tuple(desc for ch in range(1, pr.DOSING_CHANNELS + 1) for desc in _dosing_sensors(ch)) + (WIFI,),
    pr.DEVICE_SMART_ROLLER: (
        ReefSensorDescription(
            key="sr_state", translation_key="sr_state", icon="mdi:paper-roll",
            device_class=SensorDeviceClass.ENUM, options=pr.SR_STATE_OPTIONS,
            value_fn=lambda d: d.get("state"),
            attrs_fn=lambda d: {k: d[k] for k in ("state_raw", "reminder_raw", "report_hex") if d.get(k) is not None},
        ),
        ReefSensorDescription(
            key="sr_remaining", translation_key="sr_remaining", icon="mdi:paper-roll-outline",
            device_class=SensorDeviceClass.DISTANCE, state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfLength.METERS, suggested_display_precision=2,
            value_fn=lambda d: _mm_to_m(d.get("remaining_mm")),
        ),
        ReefSensorDescription(
            key="sr_remaining_pct", translation_key="sr_remaining_pct", icon="mdi:paper-roll-outline",
            state_class=SensorStateClass.MEASUREMENT, native_unit_of_measurement=PERCENTAGE,
            value_fn=lambda d: (round(d["remaining_mm"] * 100 / d["roll_length_mm"])
                                if d.get("roll_length_mm") and d.get("remaining_mm") is not None else None),
        ),
        ReefSensorDescription(
            key="sr_used_today", translation_key="sr_used_today", icon="mdi:counter",
            device_class=SensorDeviceClass.DISTANCE, state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfLength.METERS, suggested_display_precision=2,
            value_fn=lambda d: _mm_to_m(d.get("used_today_mm")),
        ),
        ReefSensorDescription(
            key="sr_daily_average", translation_key="sr_daily_average", icon="mdi:chart-line",
            device_class=SensorDeviceClass.DISTANCE, state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfLength.METERS, suggested_display_precision=2,
            value_fn=lambda d: _mm_to_m(d.get("daily_average_mm")),
        ),
        ReefSensorDescription(
            key="sr_roll_length", translation_key="sr_roll_length", entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.METERS,
            suggested_display_precision=1, value_fn=lambda d: _mm_to_m(d.get("roll_length_mm")),
        ),
        ReefSensorDescription(
            key="sr_shift", translation_key="sr_shift", entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DISTANCE, native_unit_of_measurement=UnitOfLength.MILLIMETERS,
            value_fn=lambda d: d.get("shift_mm"),
        ),
        ReefSensorDescription(
            key="sr_start_delay", translation_key="sr_start_delay", entity_category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS,
            value_fn=lambda d: d.get("delay_s"),
        ),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    setup_entities(hass, entry, async_add_entities,
                   lambda c: [ReefSensor(c, desc) for desc in SENSORS.get(pr.device_type(c.serial), ())])


class ReefSensor(ReefEntity, SensorEntity):
    entity_description: ReefSensorDescription

    def __init__(self, coordinator, description: ReefSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        key = self.entity_description.key
        if key.startswith("ch"):  # dosing pump channel: only once the device reported it
            return bool((self.coordinator.data or {}).get(key.split("_", 1)[0] + "_present"))
        return True

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.attrs_fn is None or self.coordinator.data is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data) or None
