"""Persistent WebSocket client for one Reef Factory device.

The devices' web server can get stuck: it then answers every new request with HTTP 429 (Retry-After 5)
until the device restarts, while an already open connection may keep working (seen 2026-11 on Reef Flare S,
Level keeper and Thermo control, firmware 1.0.0). The client reports that state through on_busy.

"Stuck" is only what Home Assistant itself runs into: its own connection attempts refused with 429,
BUSY_CONFIRM_HITS times in a row over BUSY_CONFIRM_SECONDS (while that goes on, and while waiting for the
device to restart, it tries every RETRY_BUSY_SECONDS). There is no extra request to look for it - 1.3.0 to 1.3.2 asked for the start
page, and that gave false alarms: something fills up on the device over its uptime, and before it is really
stuck it already refuses a request whenever one more connection is open (2026-11-15, Reef Flare S: Home
Assistant plus one more connection and every further request got 429, for minutes also after a reload; after
a power cycle the same light took nine more connections). While our own connection works, nothing is wrong
for Home Assistant, and every extra request only uses up what is left. A refused WebSocket connection is
another matter: that light took every WebSocket connection even while it refused the start page.

The stuck state has a second face (2026-11-17, Level keeper 1.0.0): the start page is refused with 429 at
once, but the WebSocket request gets no answer at all - the attempt runs into its timeout. So after an
attempt of our own that got no answer - and only then, never while connected - the client asks for the start
page once: a 429 there counts like a refused attempt. The same device an hour later took connections and
answered nothing at all, neither the WebSocket request nor the start page: that counts too, but only when
it stays like that for SILENT_CONFIRM_SECONDS. The start page coming, or the device not taking the
connection (off, no Wi-Fi, restarting), ends the row.
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
UNKNOWN_POLL_SECONDS = 30  # unknown device type: ask for the config again (the only thing ever sent to it)
RETRY_SECONDS = 5  # first wait after a failed connection attempt ...
RETRY_MAX_SECONDS = 60  # ... doubling up to this
RETRY_BUSY_SECONDS = 10  # wait between attempts while they are refused with 429 or the device is restarting ...
RETRY_BUSY_FOR_SECONDS = 300  # ... for this long after the first refusal; then the usual waits again
BUSY_CONFIRM_HITS = 3  # stuck = at least this many connection attempts refused with 429 in a row ...
BUSY_CONFIRM_SECONDS = 30  # ... over at least this long, with nothing else in between
SILENT_CONFIRM_SECONDS = 180  # ... or this long when the device took connections but answered nothing at all
HTTP_BUSY = 429
START_PAGE_TIMEOUT = 5  # the one request after a WebSocket attempt without answer


def _url(host: str) -> str:
    return f"ws://{host}{pr.WS_PATH}"


async def async_probe(
    session: aiohttp.ClientSession, host: str, timeout: float = 10, probe_timeout: float = 8
) -> dict:
    """Connect once, ask for the config and return serial/firmware. Raises on failure.

    A serial without known prefix is tried against PROBE_TYPES: only the subscription request of that type
    is sent; if the device answers with its own report topic, info["device_type"] is set.
    """
    ws = None
    try:
        async with asyncio.timeout(timeout):
            ws = await session.ws_connect(_url(host), protocols=(pr.WS_SUBPROTOCOL,), autoping=True)
            await ws.send_bytes(pr.frame_get_config())
            info = await _next(ws, pr.parse_config)
        if info is None:
            raise ConnectionError("no config answer")
        if info["device_type"] is None:
            for kind, prefix in pr.PROBE_TYPES.items():
                await ws.send_bytes(pr.frame_probe(info["serial"], kind))
                try:
                    async with asyncio.timeout(probe_timeout):
                        hit = await _next(ws, lambda f, p=prefix: f.topic.startswith(p) or None)
                except TimeoutError:
                    hit = None
                if hit:
                    info["device_type"] = kind
                    info["probed"] = True
                    break
        return info
    finally:
        if ws is not None:
            await ws.close()


async def _next(ws: aiohttp.ClientWebSocketResponse, pick: Callable) -> object:
    """First non-empty pick(frame) of the incoming binary frames, None when the socket closes."""
    async for msg in ws:
        if msg.type is aiohttp.WSMsgType.BINARY:
            frame = pr.parse_frame(msg.data)
            if frame and (res := pick(frame)):
                return res
        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
            break
    return None


class _NoAnswer(Exception):
    """The WebSocket request got no answer within CONNECT_TIMEOUT."""


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
        on_busy: Callable[[bool], None] | None = None,
    ) -> None:
        self._session = session
        self.host = host
        self.serial = serial
        self.kind = pr.device_type(serial)
        self._on_data = on_data
        self._on_connection = on_connection
        self._on_config = on_config
        self._on_busy = on_busy
        self.busy = False  # web server answers new requests with 429 (stuck until the device restarts)
        self._busy_hits = 0  # refusals in a row
        self._busy_first = 0.0  # when the first of them was seen
        self._busy_silent = False  # the row holds attempts without any answer: the longer time applies
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.last_data = 0.0
        self._productive = False  # diese Sitzung wurde angenommen -> Wartezeit zuruecksetzen
        self.last_error: str | None = None  # letzter Verbindungsfehler, fuer die Diagnose
        self.last_error_at: float | None = None
        self.raw = pr.RawLog()  # unknown device type: what it sends, for the diagnostics

    def _set_busy(self, value: bool) -> None:
        if value != self.busy:
            self.busy = value
            if self._on_busy:
                self._on_busy(value)

    def _note_busy(self, refused: bool, silent: bool = False) -> None:
        """How a connection attempt ended: refused with 429 (or, silent, taken without any answer), or taken.
        A taken connection ends the state at once; refusals only count when they went on long enough (see
        the module docstring)."""
        if not refused:
            self._end_row()
            self._set_busy(False)
            return
        now = time.monotonic()
        if self._busy_hits == 0:
            self._busy_first = now
        self._busy_hits += 1
        self._busy_silent = self._busy_silent or silent
        need = SILENT_CONFIRM_SECONDS if self._busy_silent else BUSY_CONFIRM_SECONDS
        if self._busy_hits >= BUSY_CONFIRM_HITS and now - self._busy_first >= need:
            self._set_busy(True)

    def _end_row(self) -> None:
        self._busy_hits = 0
        self._busy_silent = False

    def _set_connected(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            if value:
                self._productive = True
                self.last_error = None
            self._on_connection(value)

    async def run(self) -> None:
        backoff = RETRY_SECONDS
        while not self._stop.is_set():
            self._productive = False
            try:
                await self._session_once()
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as err:
                if err.status == HTTP_BUSY:
                    self._note_busy(True)
                else:
                    self._end_row()
                self.last_error = f"HTTP {err.status}" if err.status else str(err)
                self.last_error_at = time.monotonic()
                _LOGGER.debug("%s (%s): %s", self.serial, self.host, err)
            except _NoAnswer:
                page = await self._start_page()
                if page == "refused":
                    self._note_busy(True)
                    self.last_error = "no answer to the WebSocket request, start page HTTP 429"
                elif page == "silent":
                    self._note_busy(True, silent=True)
                    self.last_error = "connection taken, but no answer to the WebSocket request or the start page"
                else:
                    self._end_row()  # the page came, or the device does not take connections: not stuck
                    self.last_error = "no answer to the WebSocket request"
                self.last_error_at = time.monotonic()
                _LOGGER.debug("%s (%s): %s", self.serial, self.host, self.last_error)
            except Exception as err:  # noqa: BLE001 - keep the loop alive whatever happens
                self._end_row()  # unreachable is not "refused": the row of refusals starts again
                self.last_error = f"{type(err).__name__}: {err}"
                self.last_error_at = time.monotonic()
                _LOGGER.debug("%s (%s): %s", self.serial, self.host, err)
            finally:
                self._ws = None
                self._set_connected(False)
            if self._productive:
                backoff = RETRY_SECONDS  # eine angenommene Verbindung setzt die Wartezeit zurueck
            if self._stop.is_set():
                break
            wait = backoff
            if (self._busy_hits or self.busy) and time.monotonic() - self._busy_first < RETRY_BUSY_FOR_SECONDS:
                wait = min(wait, RETRY_BUSY_SECONDS)  # confirm it soon, and be back quickly after the restart
            try:
                await asyncio.wait_for(self._stop.wait(), wait)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, RETRY_MAX_SECONDS)

    async def _start_page(self) -> str:
        """What the device does with a request for its start page: "refused" (HTTP 429), "answered" (anything
        else), "silent" (took the connection, no answer) or "unreachable" (did not take it). Only asked after
        a WebSocket attempt of our own that got no answer (see the module docstring)."""
        timeout = aiohttp.ClientTimeout(total=START_PAGE_TIMEOUT, sock_connect=START_PAGE_TIMEOUT / 2)
        try:
            async with self._session.get(f"http://{self.host}/", allow_redirects=False, timeout=timeout) as resp:
                return "refused" if resp.status == HTTP_BUSY else "answered"
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientConnectorError, aiohttp.ConnectionTimeoutError):
            return "unreachable"
        except TimeoutError:
            return "silent"
        except Exception:  # noqa: BLE001 - broken answer, reset: it answered
            return "answered"

    async def _session_once(self) -> None:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                ws = await self._session.ws_connect(
                    _url(self.host), protocols=(pr.WS_SUBPROTOCOL,), autoping=True
                )
        except TimeoutError:
            raise _NoAnswer from None
        self._ws = ws
        self._note_busy(False)  # the device took the connection
        reader = asyncio.create_task(self._reader(ws))
        stopper = asyncio.create_task(self._stop.wait())
        try:
            self._set_connected(True)
            known = self.kind != pr.DEVICE_UNKNOWN  # unknown type: get/config only - nothing subscribed, no get/user
            await ws.send_bytes(pr.frame_get_config())
            if known:
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
                if not known:
                    if now - last_sub >= UNKNOWN_POLL_SECONDS:
                        await ws.send_bytes(pr.frame_get_config())  # its answer also shows the device is alive
                        last_sub = now
                    continue
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
        if self.kind == pr.DEVICE_UNKNOWN:
            self.last_data = time.monotonic()
            self.raw.note(frame)
        if info := pr.parse_config(frame):
            if info["serial"] != self.serial:
                _LOGGER.error(
                    "Device at %s reports serial %s, configured is %s - check the IP address",
                    self.host, info["serial"], self.serial,
                )
            if self._on_config:
                self._on_config(info)
            if self.kind == pr.DEVICE_UNKNOWN:
                self._on_data({})  # no values, but "Last report" should move
            return
        if self.kind == pr.DEVICE_UNKNOWN:
            # nothing of an unknown device type is decoded - its messages are only kept as they came
            self._on_data({})
            return
        if user := pr.parse_user(frame):
            self._on_data(user)
            return
        if self.kind and (data := pr.decode(self.kind, frame)):
            self.last_data = time.monotonic()
            self._on_data(data)

    @property
    def raw_frames(self) -> dict[str, dict]:
        return self.raw.kinds

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
