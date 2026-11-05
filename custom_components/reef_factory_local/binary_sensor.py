"""Binary sensors: Thermo control outputs, Level keeper calibration and cloud state."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ReefConfigEntry
from . import protocol as pr
from .entity import ReefEntity
from .platform_setup import setup_entities


@dataclass(frozen=True, kw_only=True)
class ReefBinaryDescription(BinarySensorEntityDescription):
    data_key: str


CLOUD = ReefBinaryDescription(
    key="cloud_connected", translation_key="cloud_connected", data_key="cloud_connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY, entity_category=EntityCategory.DIAGNOSTIC,
)
BINARY: dict[str, tuple[ReefBinaryDescription, ...]] = {
    pr.DEVICE_THERMO: (
        ReefBinaryDescription(key="heating", translation_key="heating", data_key="heating",
                              device_class=BinarySensorDeviceClass.RUNNING),
        ReefBinaryDescription(key="cooling", translation_key="cooling", data_key="cooling",
                              device_class=BinarySensorDeviceClass.RUNNING),
        CLOUD,
    ),
    pr.DEVICE_LEVEL_KEEPER: (
        ReefBinaryDescription(key="calibration_needed", translation_key="calibration_needed",
                              data_key="calibration_needed", device_class=BinarySensorDeviceClass.PROBLEM),
        CLOUD,
    ),
    pr.DEVICE_FLARE: (CLOUD,),
    pr.DEVICE_FEEDER: (
        ReefBinaryDescription(key="container_empty", translation_key="container_empty",
                              data_key="container_empty", device_class=BinarySensorDeviceClass.PROBLEM),
    ),
    pr.DEVICE_BASE_PUMP: (
        ReefBinaryDescription(key="bp_alert", translation_key="bp_alert", data_key="alert_active",
                              device_class=BinarySensorDeviceClass.PROBLEM),
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ReefConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    def factory(c):
        kind = pr.device_type(c.serial)
        ents = [ReefBinary(c, d) for d in BINARY.get(kind, ())]
        if kind in pr.CLOUD_ONLY:
            ents.append(ReefCloudPassthrough(c))
        return ents

    setup_entities(hass, entry, async_add_entities, factory)


class ReefBinary(ReefEntity, BinarySensorEntity):
    entity_description: ReefBinaryDescription

    def __init__(self, coordinator, description: ReefBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self.entity_description.data_key)


class ReefCloudPassthrough(ReefEntity, BinarySensorEntity):
    """On while the cloud replacement forwards this device to the real Reef Factory cloud."""

    _attr_translation_key = "cloud_passthrough"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cloud_passthrough")

    @property
    def available(self) -> bool:
        return self.coordinator.device.connected

    @property
    def is_on(self) -> bool:
        return self.coordinator.device.cloud_connected
