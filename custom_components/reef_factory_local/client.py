"""Persistent WebSocket client for one Reef Factory device.

The device accepts only one WebSocket client at a time. While this client is
connected, the official app and any other local tool cannot connect.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

import aiohttp

from . import protocol as pr

_LOGGER = logging.getLogger(__name__)
CONNECT_TIMEOUT = 10
USER_POLL_SECONDS = 300  # get/user: wifi/cloud status


def _url(host: str) -> str:
    return f"ws://{host}{pr.WS_PATH}"


async def async_probe(session: aiohttp.ClientSession, host: str, timeout: float = 10) -> dict:
    """Connect once, ask for the config and return serial/firmware. Raises on failure."""
    async with asyncio.timeout(timeout):
        ws = await session.ws_connect(_url(host), protocols=(pr.WS_SUBPROTOCOL,), autoping=True)
        try:
            await ws.send_bytes(pr.frame_get_config())
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.BINARY:
                    frame = pr.parse_frame(msg.data)
                    if frame and (info := pr.parse_config(frame)):
                        return info
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            await ws.close()
    raise ConnectionError("no config answer")


class ReefClient:
    """Keeps the connection, subscribes every 15 s and pushes decoded data."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        serial: str,
        on_data: Callable[[dict], None],
        on_connection: Callable[[bool], None],
        on_config: Callable[[dict], None] | None = None,
    ) -> None:
        self._session = session
        self.host = host
        self.serial = serial
        self.kind = pr.device_type(serial)
        self._on_data = on_data
        self._on_connection = on_connection
        self._on_config = on_config
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.last_data = 0.0

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            self._on_connection(value)

    async def run(self) -> None:
        backoff = 5
        while not self._stop.is_set():
            try:
                await self._session_once()
                backoff = 5
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the loop alive whatever happens
                _LOGGER.debug("%s (%s): %s", self.serial, self.host, err)
            finally:
                self._ws = None
                self._set_connected(False)
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, 60)

    async def _session_once(self) -> None:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            ws = await self._session.ws_connect(
                _url(self.host), protocols=(pr.WS_SUBPROTOCOL,), autoping=True
            )
        self._ws = ws
        reader = asyncio.create_task(self._reader(ws))
        stopper = asyncio.create_task(self._stop.wait())
        try:
            self._set_connected(True)
            await ws.send_bytes(pr.frame_get_config())
            await ws.send_bytes(pr.frame_subscribe(self.serial))
            await ws.send_bytes(pr.frame_get_user(self.serial))
            last_sub = last_user = self.last_data = time.monotonic()
            while True:
                done, _ = await asyncio.wait({reader, stopper}, timeout=1)
                if stopper in done:
                    return
                if reader in done:
                    reader.result()  # re-raises the reader's error
                    raise ConnectionError("connection closed by device")
                now = time.monotonic()
                if now - self.last_data > pr.WATCHDOG_SECONDS:
                    raise ConnectionError(f"no data for {pr.WATCHDOG_SECONDS} s")
                if now - last_sub >= pr.RESUBSCRIBE_SECONDS:
                    await ws.send_bytes(pr.frame_subscribe(self.serial))
                    last_sub = now
                if now - last_user >= USER_POLL_SECONDS:
                    await ws.send_bytes(pr.frame_get_user(self.serial))
                    last_user = now
        finally:
            for task in (reader, stopper):
                task.cancel()
            await ws.close()

    async def _reader(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.BINARY:
                self._handle(msg.data)
            elif msg.type is aiohttp.WSMsgType.ERROR:
                raise ConnectionError(str(ws.exception()))

    def _handle(self, raw: bytes) -> None:
        frame = pr.parse_frame(raw)
        if frame is None:
            return
        if info := pr.parse_config(frame):
            if info["serial"] != self.serial:
                _LOGGER.error(
                    "Device at %s reports serial %s, configured is %s - check the IP address",
                    self.host, info["serial"], self.serial,
                )
            if self._on_config:
                self._on_config(info)
            return
        if user := pr.parse_user(frame):
            self._on_data(user)
            return
        if self.kind and (data := pr.decode(self.kind, frame)):
            self.last_data = time.monotonic()
            self._on_data(data)

    async def async_send(self, raw: bytes) -> None:
        if self._ws is None or self._ws.closed:
            raise ConnectionError("not connected")
        await self._ws.send_bytes(raw)
        # ask for fresh values right away
        await self._ws.send_bytes(pr.frame_subscribe(self.serial))

    async def async_set_lk_cycle(self, cycle: str) -> None:
        await self.async_send(pr.frame_lk_set_cycle(self.serial, cycle))

    async def async_stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            await self._ws.close()
