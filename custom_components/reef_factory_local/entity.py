"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol as pr
from .const import DOMAIN, MANUFACTURER


class ReefEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.serial
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            model=pr.MODEL_NAME.get(pr.device_type(serial) or "", "Reef Factory device"),
            name=coordinator.device_name,
            serial_number=serial,
            configuration_url=coordinator.configuration_url,
        )
        if coordinator.firmware:  # unknown right after a reconnect - do not blank the stored version
            self._attr_device_info["sw_version"] = coordinator.firmware

    @property
    def available(self) -> bool:
        return self.coordinator.fresh
