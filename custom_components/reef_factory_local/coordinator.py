"""Push coordinator: the client delivers data, entities listen."""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import protocol as pr
from .client import ReefClient
from .cloud import CloudDevice
from .const import CONF_AUTO_RESTART, CONF_CLOUD, CONF_SERIAL, DOMAIN, RECOVER_SILENCE_SECONDS, RECOVER_WAIT_SECONDS, STALE_SECONDS

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
        self._busy_timer = None
        self.sr_used_diameter_mm: int = pr.SR_USED_ROLL_DEFAULT_MM  # Smart Roller: kept in HA, sent with the button
        # Level keeper guided calibration: kept in HA, sent with the two buttons
        self.lk_calibration_s: int = pr.LK_CALIBRATION_DEFAULT_S
        self.lk_measured_ml: int | None = None
        self.lk_reminder: str | None = None
        # Reef Flare: the light reports its manual presets (timed programs of the app) only in manual mode;
        # the last known list is kept so it can be shown after a restart. Writes always read it fresh.
        self._preset_store: Store | None = (
            Store(hass, PRESET_STORE_VERSION, preset_store_key(self.serial))
            if pr.device_type(self.serial) == pr.DEVICE_FLARE else None
        )

    # --- stuck web server (HTTP 429) ------------------------------------------------------------------
    @property
    def _issue_id(self) -> str:
        return f"busy_{self.serial}"

    def _cloud_server(self):
        """The running cloud replacement, if its option *Restart stuck devices automatically* is on."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_CLOUD) and entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data.server if entry.options.get(CONF_AUTO_RESTART, True) else None
        return None

    def _issue(self, key: str) -> None:
        ir.async_create_issue(
            self.hass, DOMAIN, self._issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders={"name": self.device_name, "host": self.config_entry.data.get("host", "")},
        )

    @callback
    def handle_busy(self, busy: bool) -> None:
        if not busy:
            _LOGGER.info("%s takes requests again", self.device_name)
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            if self._busy_timer:
                self._busy_timer()
                self._busy_timer = None
            self.async_update_listeners()
            return
        server = self._cloud_server()
        if server is not None and server.silence(self.serial, RECOVER_SILENCE_SECONDS):
            _LOGGER.warning("%s (%s): web server stuck (HTTP 429) - restarting it through the cloud replacement",
                            self.device_name, self.serial)
            self._issue("device_busy_restarting")
            self._busy_timer = async_call_later(self.hass, RECOVER_WAIT_SECONDS, self._still_busy)
        else:
            _LOGGER.warning("%s (%s): web server stuck (HTTP 429) - power cycle the device", self.device_name,
                            self.serial)
            self._issue("device_busy")
        self.async_update_listeners()

    @callback
    def _still_busy(self, _now) -> None:
        self._busy_timer = None
        if self.client.busy:
            self._issue("device_busy")

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
