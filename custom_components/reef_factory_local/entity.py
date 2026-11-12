"""Base entity."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol as pr
from .const import DOMAIN, MANUFACTURER


def known_or_refuse(data: dict | None, *keys: str) -> list:
    """The reported values a write has to repeat - or an error for the user; nothing is sent with a guess."""
    try:
        return pr.known(data, *keys)
    except pr.UnknownValue as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="value_unknown",
                                 translation_placeholders={"values": str(err)}) from err


def all_known(data: dict | None, keys) -> bool:
    return all((data or {}).get(key) is not None for key in keys)


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
