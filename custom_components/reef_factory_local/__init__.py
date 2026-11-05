"""Reef Factory Local (unofficial): local control of Reef Factory devices."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import protocol as pr
from .client import ReefClient
from .cloud import MODE_PASSTHROUGH, CloudDevice, ReefCloudServer
from .const import (
    CONF_CLOUD, CONF_CLOUD_MODE, CONF_DEVICE_TYPE, CONF_SERIAL, CONF_UPSTREAM_IPS, DOMAIN, SIGNAL_NEW_CLOUD_DEVICE,
)
from .coordinator import CloudCoordinator, ReefCoordinator
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: dict[str, list[Platform]] = {
    pr.DEVICE_LEVEL_KEEPER: [
        Platform.SENSOR, Platform.SELECT, Platform.BINARY_SENSOR,
        Platform.NUMBER, Platform.SWITCH, Platform.BUTTON,
    ],
    pr.DEVICE_THERMO: [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH],
    pr.DEVICE_SMART_ROLLER: [Platform.SENSOR, Platform.BINARY_SENSOR],  # read only until writes are confirmed
    pr.DEVICE_FLARE: [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.NUMBER],
    pr.DEVICE_FEEDER: [
        Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT,
        Platform.NUMBER, Platform.SWITCH, Platform.BUTTON,
    ],
}
# the cloud replacement entry hosts any cloud-only device, so it loads every platform
CLOUD_PLATFORMS = [
    Platform.SENSOR, Platform.SELECT, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH, Platform.BUTTON,
]

type ReefConfigEntry = ConfigEntry


class CloudRuntime:
    """Runtime data of the cloud replacement entry."""

    def __init__(self, server: ReefCloudServer) -> None:
        self.server = server
        self.coordinators: dict[str, CloudCoordinator] = {}


def is_cloud_entry(entry: ConfigEntry) -> bool:
    return bool(entry.data.get(CONF_CLOUD))


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ReefConfigEntry) -> bool:
    if is_cloud_entry(entry):
        return await _async_setup_cloud(hass, entry)
    serial = entry.data[CONF_SERIAL]
    if kind := entry.data.get(CONF_DEVICE_TYPE):
        pr.register_device_type(serial, kind)
    coordinator = ReefCoordinator(hass, entry)
    coordinator.client = ReefClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        serial,
        on_data=coordinator.handle_data,
        on_connection=coordinator.handle_connection,
        on_config=coordinator.handle_config,
    )
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS[pr.device_type(serial)])
    entry.async_create_background_task(hass, coordinator.client.run(), f"reef_factory_local {serial}")
    return True


async def _async_setup_cloud(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    runtime = CloudRuntime(ReefCloudServer(
        hass.config.config_dir,
        mode=entry.options.get(CONF_CLOUD_MODE, MODE_PASSTHROUGH),
        upstream_ips=[ip.strip() for ip in entry.options.get(CONF_UPSTREAM_IPS, "").split(",") if ip.strip()],
        on_new_device=lambda device: _async_new_cloud_device(hass, entry, runtime, device),
    ))
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, CLOUD_PLATFORMS)
    await runtime.server.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_cloud_options_changed))
    return True


@callback
def _async_new_cloud_device(hass: HomeAssistant, entry: ConfigEntry, runtime: CloudRuntime, device: CloudDevice) -> None:
    if device.kind not in pr.CLOUD_ONLY:
        return  # locally served devices (Level keeper, Thermo, Flare) are only passed through
    coordinator = CloudCoordinator(hass, entry, device)
    runtime.coordinators[device.serial] = coordinator
    async_dispatcher_send(hass, SIGNAL_NEW_CLOUD_DEVICE, coordinator)


async def _async_cloud_options_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ReefConfigEntry) -> bool:
    if is_cloud_entry(entry):
        await entry.runtime_data.server.async_stop()
        return await hass.config_entries.async_unload_platforms(entry, CLOUD_PLATFORMS)
    await entry.runtime_data.client.async_stop()
    return await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS[pr.device_type(entry.data[CONF_SERIAL])]
    )
