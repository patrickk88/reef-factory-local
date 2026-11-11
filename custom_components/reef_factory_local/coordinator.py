"""Push coordinator: the client delivers data, entities listen."""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import protocol as pr
from .client import ReefClient
from .cloud import CloudDevice
from .const import CONF_SERIAL, DOMAIN, STALE_SECONDS

PRESET_STORE_VERSION = 1

_LOGGER = logging.getLogger(__name__)


def preset_store_key(serial: str) -> str:
    return f"{DOMAIN}.{serial}.manual_presets"


class ReefCoordinator(DataUpdateCoordinator[dict]):
    """Holds the latest decoded values of one device."""

    client: ReefClient

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.data[CONF_SERIAL]}",
            update_interval=None,
        )
        self.serial: str = entry.data[CONF_SERIAL]
        self.device_name: str = entry.title
        self.configuration_url: str | None = f"http://{entry.data.get('host')}" if entry.data.get("host") else None
        self.firmware: str | None = None
        self.sr_used_diameter_mm: int = pr.SR_USED_ROLL_DEFAULT_MM  # Smart Roller: kept in HA, sent with the button
        # Reef Flare: the light reports its manual presets (timed programs of the app) only in manual mode;
        # the last known list is kept so it can be shown after a restart. Writes always read it fresh.
        self._preset_store: Store | None = (
            Store(hass, PRESET_STORE_VERSION, preset_store_key(self.serial))
            if pr.device_type(self.serial) == pr.DEVICE_FLARE else None
        )

    async def async_restore(self) -> None:
        if self._preset_store is None:
            return
        stored = await self._preset_store.async_load()
        if stored and stored.get("manual_presets") and not (self.data or {}).get("manual_presets"):
            self.data = {**(self.data or {}), "manual_presets": stored["manual_presets"]}

    @callback
    def handle_data(self, data: dict) -> None:
        new = {**(self.data or {}), **data}
        presets = data.get("manual_presets")
        if self._preset_store is not None and presets and presets != (self.data or {}).get("manual_presets"):
            self._preset_store.async_delay_save(lambda: {"manual_presets": presets}, 5)
        self.async_set_updated_data(new)

    @callback
    def handle_connection(self, connected: bool) -> None:
        self.async_update_listeners()

    @callback
    def handle_config(self, info: dict) -> None:
        fw = info.get("firmware")
        if not fw or self.config_entry is None:
            return
        self.firmware = fw
        reg = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(reg, self.config_entry.entry_id):
            if (DOMAIN, self.serial) in device.identifiers and device.sw_version != fw:
                reg.async_update_device(device.id, sw_version=fw)

    @property
    def fresh(self) -> bool:
        return (
            self.client.connected
            and self.data is not None
            and time.monotonic() - self.client.last_data < STALE_SECONDS
        )


class CloudCoordinator(DataUpdateCoordinator[dict]):
    """Values of one device served by the cloud replacement (push from the server)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: CloudDevice) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {device.serial}", update_interval=None)
        self.device = device
        self.serial = device.serial
        self.device_name = f"{pr.MODEL_NAME.get(device.kind or '', 'Reef Factory device')} {device.serial[-4:]}"
        self.configuration_url = None
        device.listeners.append(self._on_device)
        if device.data:
            self.async_set_updated_data(dict(device.data))

    @property
    def client(self):  # same interface as ReefCoordinator for the services
        return self.device

    @property
    def firmware(self) -> str | None:
        return self.device.firmware

    @callback
    def _on_device(self, device: CloudDevice) -> None:
        if device.data:
            self.async_set_updated_data(dict(device.data))
        else:
            self.async_update_listeners()
        fw = device.firmware
        if fw and self.config_entry is not None:
            reg = dr.async_get(self.hass)
            for dev in dr.async_entries_for_config_entry(reg, self.config_entry.entry_id):
                if (DOMAIN, self.serial) in dev.identifiers and dev.sw_version != fw:
                    reg.async_update_device(dev.id, sw_version=fw)

    @property
    def fresh(self) -> bool:
        d = self.device
        return d.connected and bool(d.data) and time.monotonic() - d.last_seen < STALE_SECONDS
