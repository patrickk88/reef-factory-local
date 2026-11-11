"""Smart Roller writes: one place that sends and logs every frame."""
from __future__ import annotations

import logging

from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


async def async_send_roller(coordinator, frame: bytes, what: str) -> None:
    """Send one Smart Roller command (logged at info level with its bytes)."""
    _LOGGER.info("Smart Roller %s: %s", what, frame.hex())
    try:
        await coordinator.client.async_send(frame)
    except ConnectionError as err:
        raise HomeAssistantError(f"Smart Roller not connected: {err}") from err
