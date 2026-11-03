"""Shared platform setup: one coordinator per device entry, many per cloud entry."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_CLOUD, SIGNAL_NEW_CLOUD_DEVICE


@callback
def setup_entities(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[object], Iterable],
) -> None:
    if not entry.data.get(CONF_CLOUD):
        async_add_entities(list(factory(entry.runtime_data)))
        return
    runtime = entry.runtime_data
    for coordinator in runtime.coordinators.values():
        async_add_entities(list(factory(coordinator)))

    @callback
    def _new(coordinator) -> None:
        if coordinator.config_entry is entry:
            async_add_entities(list(factory(coordinator)))

    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_NEW_CLOUD_DEVICE, _new))
