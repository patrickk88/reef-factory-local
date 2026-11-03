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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass, UnitOfTemperature, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

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


def _flare_attrs(d: dict) -> dict:
    out = {}
    if d.get("programs"):
        out["programs"] = [p for p in d["programs"] if p]
    if d.get("points") is not None:  # same shape the flare_program_set action accepts
        out["points"] = [{"time": p["time"], "levels": p["levels"]} for p in d["points"]]
    for key in ("levels", "presets", "acclimation"):
        if d.get(key) is not None:
            out[key] = d[key]
    if d.get("mode") == "manual":
        out["manual_duration_min"] = None if d.get("manual_time_s") is None else round(d["manual_time_s"] / 60)
    return out


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
            key="light_mode", translation_key="light_mode",
            device_class=SensorDeviceClass.ENUM, options=["program", "manual", "off", "dashboard"],
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
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.attrs_fn is None or self.coordinator.data is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data) or None
