"""Cloud replacement: a local stand-in for api.reeffactory.com.

Reef Factory devices without a local port (Smart feeder; very likely Base pump
and Dosing pump) only talk to the cloud. They do not check the server
certificate, so once ``api.reeffactory.com`` resolves to the Home Assistant
host (DNS rewrite in the router / AdGuard / Pi-hole), this server can serve
them: TLS on 444 (ESP32 devices, path /hardware32) and plain text on 442
(ESP8266 devices, path /hardware, subprotocol "reeffactory").

Two modes per connection:
- passthrough: everything is forwarded to the real cloud (resolved through a
  public DNS server, because the local one points to us) and read along, so the
  official app keeps working while the cloud exists;
- local: Home Assistant answers the login itself, sets the clock and
  subscribes to the device. This is the automatic fallback when the real cloud
  cannot be reached.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import datetime
import ipaddress
import json
import logging
import os
import socket
import struct
import time

import aiohttp
from aiohttp import web
from aiohttp.abc import AbstractResolver

from . import protocol as pr

_LOGGER = logging.getLogger(__name__)

PUBLIC_DNS = ("1.1.1.1", "9.9.9.9", "8.8.8.8")
RESOLVE_TTL = 600
UPSTREAM_TIMEOUT = 8
STOP_TIMEOUT = 10  # per listener when stopping; open connections are reset first
UPSTREAM_RETRY_SECONDS = 120  # served locally because the real cloud was away: look again this often
LOCAL_POLL_SECONDS = 300
NO_DEVICE_HINT_SECONDS = 600
APP_PORTS = (80, 443, 445, 446)  # app: REST/devices 443, ERP 445, social 446 (from the web client config)
MODE_PASSTHROUGH = "passthrough"
_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale and other overlay networks
MODE_LOCAL = "local"


# --- small DNS client (UDP, A records) so we can find the real cloud ----------

async def resolve_public(name: str, servers=PUBLIC_DNS, timeout: float = 3) -> list[str]:
    """Resolve an A record via a public resolver, bypassing the local (rewritten) DNS."""
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.strip(".").split(".")) + b"\x00"
    query = struct.pack(">HHHHHH", 0x5252, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)
    loop = asyncio.get_running_loop()
    for server in servers:
        fut: asyncio.Future = loop.create_future()

        class _P(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                if not fut.done():
                    fut.set_result(data)

            def error_received(self, exc):
                if not fut.done():
                    fut.set_exception(exc)

        try:
            transport, _ = await loop.create_datagram_endpoint(_P, remote_addr=(server, 53))
        except OSError:
            continue
        try:
            transport.sendto(query)
            data = await asyncio.wait_for(fut, timeout)
        except (asyncio.TimeoutError, OSError):
            continue
        finally:
            transport.close()
        ips = _parse_a_records(data)
        if ips:
            return ips
    return []


def _parse_a_records(data: bytes) -> list[str]:
    try:
        qd, an = struct.unpack(">HH", data[4:8])
        pos = 12
        for _ in range(qd):
            while data[pos] != 0:
                pos += 1 + data[pos]
            pos += 5
        ips = []
        for _ in range(an):
            if data[pos] & 0xC0 == 0xC0:
                pos += 2
            else:
                while data[pos] != 0:
                    pos += 1 + data[pos]
                pos += 1
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
            pos += 10
            if rtype == 1 and rdlen == 4:
                ips.append(".".join(str(b) for b in data[pos:pos + 4]))
            pos += rdlen
        return ips
    except (IndexError, struct.error):
        return []


class _StaticResolver(AbstractResolver):
    def __init__(self, hosts: dict[str, list[str]]) -> None:
        self._hosts = hosts

    async def resolve(self, host, port=0, family=socket.AF_INET):
        ips = self._hosts.get(host)
        if not ips:
            raise OSError(f"no address for {host}")
        return [{"hostname": host, "host": ip, "port": port, "family": socket.AF_INET,
                 "proto": 0, "flags": socket.AI_NUMERICHOST} for ip in ips]

    async def close(self) -> None:
        return None


# --- certificate -----------------------------------------------------------------

def ensure_certificate(cert_path: str, key_path: str) -> None:
    """Create a self-signed certificate for the cloud host name once (devices do not check it)."""
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, pr.CLOUD_HOST)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(pr.CLOUD_HOST)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as f:
        os.chmod(key_path, 0o600) if os.path.exists(key_path) else None
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    os.chmod(key_path, 0o600)
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


# --- one connected device --------------------------------------------------------

_SECRET_KEYS = {"key", "token", "email", "password", "pass", "ssid", "psk"}


def _redact(obj):
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in _SECRET_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def frame_dump(frame: pr.Frame, limit: int = 4000) -> str:
    """Payload of a cloud frame for the debug log - JSON with login secrets masked, else hex.

    Enable debug logging for ``custom_components.reef_factory_local`` and click through the
    device pages in the Reef Factory app to capture the protocol of a device the integration
    does not decode yet; paste the lines into an issue.
    """
    blob = frame.blob.rstrip(b"\x00")  # the devices terminate JSON with NUL
    try:
        obj = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return blob[:limit // 2].hex()
    text = json.dumps(_redact(obj), ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...(%d B)" % len(text)


def reset_transport(transport) -> None:
    """Drop a device connection with a TCP reset instead of a WebSocket close handshake.

    Reef Factory firmware (esp_websocket_client, ESP-IDF 4.4) never reconnects after a
    server-initiated close frame - the device stays offline until it is power cycled.
    After a plain TCP reset it reconnects on its own within about 10-20 seconds, so this is
    the only safe way to let a device go (Home Assistant stop, reload, upstream loss).
    """
    if transport is None or transport.is_closing():
        return
    try:
        sock = transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except (OSError, AttributeError):
        pass
    transport.abort()


class CloudDevice:
    """State of one device connected to the cloud replacement."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.kind = pr.device_type(serial)
        self.firmware: str | None = None
        self.mode: str | None = None          # passthrough / local
        self.cloud_connected = False          # upstream (real cloud) reachable for this connection
        self.connected = False
        self.last_seen = 0.0
        self.last_data = 0.0
        self.data: dict = {}
        self.join_id = pr.cloud_join_id()
        self._ws: web.WebSocketResponse | None = None
        self._transport = None
        self.listeners: list[Callable[[CloudDevice], None]] = []

    def notify(self) -> None:
        for cb in list(self.listeners):
            cb(self)

    async def async_send(self, frame: bytes) -> None:
        ws = self._ws
        if ws is None or ws.closed:
            raise ConnectionError(f"{self.serial} not connected")
        await ws.send_bytes(frame)

    async def async_refresh(self) -> None:
        """Ask the device for its full state (sfGet/all etc.)."""
        if self.kind in pr.CLOUD_ONLY:
            await self.async_send(pr.frame_cloud_subscribe(self.serial, self.join_id))
            await self.async_send(pr.frame_cloud_get_all(self.serial, self.join_id))
            await self.async_send(pr.frame_cloud_get_wifi(self.serial, self.join_id))


def lan_ipv4_addresses(adapters=None) -> list[str]:
    """IPv4 addresses of this host for the app relay: no loopback, link-local or 100.64.0.0/10 (Tailscale).
    ``adapters`` as returned by ifaddr.get_adapters() (ifaddr ships with Home Assistant)."""
    if adapters is None:
        try:
            import ifaddr  # noqa: PLC0415
        except ImportError:
            return []
        adapters = ifaddr.get_adapters()
    out = set()
    for adapter in adapters:
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):  # IPv6 entries are tuples
                continue
            try:
                addr = ipaddress.ip_address(ip.ip)
            except ValueError:
                continue
            if addr.is_loopback or addr.is_link_local or addr in _CGNAT:
                continue
            out.add(ip.ip)
    return sorted(out, key=ipaddress.ip_address)


class ReefCloudServer:
    """Listens on 442 (plain) and 444 (TLS) and serves every device that connects."""

    def __init__(self, hass_config_dir: str, mode: str = MODE_PASSTHROUGH,
                 upstream_ips: list[str] | None = None,
                 on_new_device: Callable[[CloudDevice], None] | None = None,
                 ports: tuple[int, int] = (pr.CLOUD_PORT_PLAIN, pr.CLOUD_PORT_TLS)) -> None:
        self.mode = mode
        self.upstream_ips = list(upstream_ips or [])
        self._resolved: tuple[float, list[str]] = (0.0, [])
        self.devices: dict[str, CloudDevice] = {}
        self._on_new_device = on_new_device
        self._ports = ports
        self._runners: list[web.AppRunner] = []
        self._hint_task: asyncio.Task | None = None
        self._raw_servers: list[asyncio.base_events.Server] = []
        self.app_passthrough = True
        self._dir = os.path.join(hass_config_dir, ".storage", "reef_factory_local")
        self.cert_path = os.path.join(self._dir, "cloud-cert.pem")
        self.key_path = os.path.join(self._dir, "cloud-key.pem")
        self._session: aiohttp.ClientSession | None = None
        self._upstream_hosts: dict[str, list[str]] = {}  # read by the session's resolver on every connect
        self._transports: set = set()  # every open connection (devices, also before their first frame, and the app)
        self.listen_errors: dict[int, str] = {}
        # where the real cloud listens; only tests change these
        self.upstream_ports = (pr.CLOUD_PORT_PLAIN, pr.CLOUD_PORT_TLS)
        self.upstream_verify = True

    # -- lifecycle -------------------------------------------------------------
    async def async_start(self) -> None:
        import ssl
        loop = asyncio.get_running_loop()

        def _prepare() -> ssl.SSLContext:
            ensure_certificate(self.cert_path, self.key_path)
            c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            c.minimum_version = ssl.TLSVersion.TLSv1_2
            c.load_cert_chain(self.cert_path, self.key_path)
            try:
                c.set_ciphers("DEFAULT:@SECLEVEL=1")  # old mbedTLS builds on the devices
            except ssl.SSLError:
                pass
            return c

        ctx = await loop.run_in_executor(None, _prepare)
        for port, ssl_ctx in ((self._ports[0], None), (self._ports[1], ctx)):
            app = web.Application()
            app.router.add_route("GET", "/{tail:.*}", self._handle)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            try:
                await web.TCPSite(runner, "0.0.0.0", port, ssl_context=ssl_ctx, reuse_address=True).start()
            except OSError as err:
                self.listen_errors[port] = str(err)
                _LOGGER.error("Cloud replacement cannot listen on port %s: %s", port, err)
                await runner.cleanup()
                continue
            self._runners.append(runner)
            _LOGGER.info("Cloud replacement listening on port %s (%s)", port, "TLS" if ssl_ctx else "plain")
        if self.listen_errors:
            _LOGGER.error("Cloud replacement: Home Assistant must be allowed to open ports 442 and 444 "
                          "(fine on Home Assistant OS and Docker with host networking; otherwise run as root or "
                          "grant CAP_NET_BIND_SERVICE).")
        if self.mode == MODE_PASSTHROUGH and self.app_passthrough:
            await self._start_app_relays()
        self._hint_task = asyncio.get_running_loop().create_task(self._hint_if_nothing_connects())

    async def _hint_if_nothing_connects(self) -> None:
        await asyncio.sleep(NO_DEVICE_HINT_SECONDS)
        if not self.devices and not self.listen_errors:
            _LOGGER.warning("Cloud replacement: no Reef Factory device has connected in %d minutes. Check that "
                            "'%s' resolves to this host inside your network (DNS rewrite in AdGuard/Pi-hole/router), "
                            "that your router allows private addresses for that name (FRITZ!Box: DNS rebind protection "
                            "exception) and that the devices were restarted after the DNS change.",
                            NO_DEVICE_HINT_SECONDS // 60, pr.CLOUD_HOST)

    async def _start_app_relays(self) -> None:
        """Ports 80/443: the official app also talks to api.reeffactory.com. Those connections are
        passed through untouched (end-to-end TLS with the real cloud) so the app keeps working at home.

        If a port is taken on one address only (e.g. Tailscale Funnel/Serve listens on 443 of the
        tailnet address), binding 0.0.0.0 fails - then the relay listens on the LAN addresses instead."""
        for port in APP_PORTS:
            handler = lambda r, w, p=port: self._relay_raw(r, w, p)  # noqa: E731
            try:
                self._raw_servers.append(await asyncio.start_server(handler, "0.0.0.0", port, reuse_address=True))
                _LOGGER.info("Cloud replacement passing port %s through to the real cloud", port)
                continue
            except OSError as err:
                wildcard_error = err
            bound = []
            for address in lan_ipv4_addresses():
                try:
                    self._raw_servers.append(await asyncio.start_server(handler, address, port, reuse_address=True))
                    bound.append(address)
                except OSError:
                    continue
            if bound:
                _LOGGER.warning("Cloud replacement: port %s is in use on another address (%s) - passing it through "
                                "on %s only", port, wildcard_error, ", ".join(bound))
            else:
                _LOGGER.warning("Cloud replacement: port %s not available for the app passthrough (%s) - the "
                                "official app will only work outside your network", port, wildcard_error)

    async def _relay_raw(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, port: int) -> None:
        peer = writer.get_extra_info("peername")
        try:
            ips = await self._upstream_ips()
            if not ips:
                raise ConnectionError("cloud address unknown")
            async with asyncio.timeout(UPSTREAM_TIMEOUT):
                ur, uw = await asyncio.open_connection(ips[0], port)
        except (OSError, ConnectionError, asyncio.TimeoutError) as err:
            _LOGGER.debug("cloud: app passthrough %s:%s failed: %s", peer, port, err)
            writer.close()
            return

        async def pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await src.read(65536)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except (OSError, asyncio.CancelledError):
                pass
            finally:
                if not dst.is_closing():
                    dst.close()

        both = (writer.transport, uw.transport)
        self._transports.update(both)
        try:
            await asyncio.gather(pump(reader, uw), pump(ur, writer))
        finally:
            self._transports.difference_update(both)

    async def async_stop(self) -> None:
        if self._hint_task:
            self._hint_task.cancel()
        for server in self._raw_servers:
            server.close()
        self._raw_servers = []
        for dev in list(self.devices.values()):
            # never a close frame (see reset_transport) - the device reconnects after ~10 s,
            # by then the server is gone (HA stop) or back (reload)
            reset_transport(dev._transport)
            dev._ws = None
            dev._transport = None
            dev.connected = False
            dev.cloud_connected = False
        # also the connections no device is known for (nothing sent yet, replaced by a newer one) and the app's:
        # an open connection keeps the listener from closing - seen 2026-11-11, a reload hung in "unloading"
        for transport in list(self._transports):
            reset_transport(transport)
        self._transports.clear()
        for runner in self._runners:
            try:
                async with asyncio.timeout(STOP_TIMEOUT):
                    await runner.cleanup()
            except asyncio.TimeoutError:
                _LOGGER.warning("Cloud replacement: a listener did not close within %s s - going on", STOP_TIMEOUT)
        self._runners = []
        if self._session is not None:
            await self._session.close()
            self._session = None

    # -- upstream ------------------------------------------------------------------
    async def _upstream_ips(self) -> list[str]:
        if self.upstream_ips:
            return self.upstream_ips
        stamp, ips = self._resolved
        if ips and time.monotonic() - stamp < RESOLVE_TTL:
            return ips
        ips = await resolve_public(pr.CLOUD_HOST)
        if ips:
            self._resolved = (time.monotonic(), ips)
        return ips

    async def _connect_upstream(self, port: int, path: str, protocols: tuple[str, ...]):
        ips = await self._upstream_ips()
        if not ips:
            raise ConnectionError("cloud address unknown")
        # the cloud sits behind a load balancer whose addresses change: always hand the session the current ones
        self._upstream_hosts[pr.CLOUD_HOST] = ips
        if self._session is None:
            self._session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(
                resolver=_StaticResolver(self._upstream_hosts), use_dns_cache=False))
        tls = port == self._ports[1]
        url = f"{'wss' if tls else 'ws'}://{pr.CLOUD_HOST}:{self.upstream_ports[1] if tls else self.upstream_ports[0]}{path}"
        kwargs = {} if self.upstream_verify else {"ssl": False}
        try:
            async with asyncio.timeout(UPSTREAM_TIMEOUT):
                return await self._session.ws_connect(url, protocols=protocols, autoping=True, heartbeat=None,
                                                      headers={"User-Agent": "reef_factory_local"}, **kwargs)
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            self._resolved = (0.0, [])  # look the address up again next time
            raise

    async def _retry_upstream(self, device: CloudDevice, ws: web.WebSocketResponse, port: int, path: str,
                              protocols: tuple[str, ...]) -> None:
        """The device is served locally because the real cloud did not answer when it connected. Look again
        every UPSTREAM_RETRY_SECONDS; once the cloud answers, drop the device's connection with a TCP reset -
        it reconnects within seconds and logs in to the real cloud through the passthrough (seen 2026-11-11:
        after a short cloud outage the devices stayed "local" and the app showed them offline for hours)."""
        while True:
            await asyncio.sleep(UPSTREAM_RETRY_SECONDS)
            if ws.closed or device._ws is not ws:
                return
            try:
                probe = await self._connect_upstream(port, path, protocols)
            except (aiohttp.ClientError, ConnectionError, OSError, asyncio.TimeoutError):
                continue
            await probe.close()
            if ws.closed or device._ws is not ws:
                return
            _LOGGER.info("cloud: real cloud reachable again - reconnecting %s", device.serial)
            reset_transport(device._transport)
            return

    # -- connection handler ----------------------------------------------------------
    async def _handle(self, request: web.Request) -> web.StreamResponse:
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return web.Response(status=426, text="Upgrade Required")
        offered = tuple(p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip())
        ws = web.WebSocketResponse(protocols=offered or (), autoping=False, max_msg_size=1 << 20)
        await ws.prepare(request)
        transport = request.transport
        self._transports.add(transport)
        peer = request.remote
        port = request.transport.get_extra_info("sockname")[1] if request.transport else 0
        _LOGGER.debug("cloud: connection from %s on port %s path %s", peer, port, request.path)
        device: CloudDevice | None = None
        upstream = None
        local_task: asyncio.Task | None = None
        retry_task: asyncio.Task | None = None
        try:
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.PING:
                    await ws.pong(msg.data)
                    if device:
                        device.last_seen = time.monotonic()
                    if upstream is not None and not upstream.closed:
                        await upstream.ping(msg.data)
                    continue
                if msg.type is aiohttp.WSMsgType.PONG:
                    continue
                if msg.type not in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                    break
                raw = msg.data if isinstance(msg.data, bytes) else msg.data.encode()
                frame = pr.parse_frame(raw)
                if device is None:
                    if frame is None or not frame.serial:
                        _LOGGER.debug("cloud: first frame from %s not parseable", peer)
                        break
                    device = self._device(frame.serial, ws, request.transport)
                    device.mode = MODE_LOCAL
                    if self.mode == MODE_PASSTHROUGH:
                        try:
                            upstream = await self._connect_upstream(port, request.path, offered)
                            device.mode = MODE_PASSTHROUGH
                            device.cloud_connected = True
                            asyncio.get_running_loop().create_task(self._pump_upstream(device, upstream, ws))
                        except (aiohttp.ClientError, ConnectionError, OSError, asyncio.TimeoutError) as err:
                            _LOGGER.warning("cloud: real cloud unreachable for %s (%s) - serving locally, looking again "
                                            "every %s s", device.serial, err or type(err).__name__, UPSTREAM_RETRY_SECONDS)
                            upstream = None
                            retry_task = asyncio.get_running_loop().create_task(
                                self._retry_upstream(device, ws, port, request.path, offered))
                    device.notify()
                device.last_seen = time.monotonic()
                self._learn(device, frame, raw)
                if upstream is not None and not upstream.closed:
                    await upstream.send_bytes(raw)
                elif frame is not None and frame.topic == "geConnect" and frame.subtopic == "login":
                    await ws.send_bytes(pr.frame_login_ok(device.serial))
                    await ws.send_bytes(pr.frame_cloud_time(device.serial, datetime.datetime.now()))
                if frame is not None and frame.topic == "geConnect" and local_task is None:
                    # our own subscription, in both modes (the real cloud only subscribes while the app is open)
                    local_task = asyncio.get_running_loop().create_task(self._poll(device))
        finally:
            self._transports.discard(transport)
            if local_task:
                local_task.cancel()
            if retry_task:
                retry_task.cancel()
            if upstream is not None and not upstream.closed:
                await upstream.close()
            if device is not None and device._ws is ws:
                device.connected = False
                device.cloud_connected = False
                device._ws = None
                device._transport = None
                device.notify()
            _LOGGER.debug("cloud: %s disconnected", device.serial if device else peer)
        return ws

    def _device(self, serial: str, ws: web.WebSocketResponse, transport=None) -> CloudDevice:
        device = self.devices.get(serial)
        new = device is None
        if new:
            device = CloudDevice(serial)
            self.devices[serial] = device
        device._ws = ws
        device._transport = transport
        device.connected = True
        device.last_seen = time.monotonic()
        if new and self._on_new_device:
            self._on_new_device(device)
        return device

    def _learn(self, device: CloudDevice, frame: pr.Frame | None, raw: bytes) -> None:
        if frame is None:
            return
        if (info := pr.parse_login(frame)):
            device.firmware = info.get("firmware") or device.firmware
            return
        if device.kind is None:
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug("cloud: unknown device %s -> cloud %s/%s %s", device.serial, frame.topic, frame.subtopic, frame_dump(frame))
            return
        data = pr.decode(device.kind, frame)
        if data:
            device.data = {**device.data, **data}
            device.last_data = time.monotonic()
            device.notify()
        elif _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("cloud: %s -> cloud %s/%s %s", device.serial, frame.topic, frame.subtopic, frame_dump(frame))

    async def _pump_upstream(self, device: CloudDevice, upstream, ws: web.WebSocketResponse) -> None:
        """Forward frames from the real cloud to the device (and learn from them)."""
        try:
            async for msg in upstream:
                if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                    raw = msg.data if isinstance(msg.data, bytes) else msg.data.encode()
                    if ws.closed:
                        break
                    await ws.send_bytes(raw)
                    frame = pr.parse_frame(raw)
                    if frame and _LOGGER.isEnabledFor(logging.DEBUG):
                        _LOGGER.debug("cloud -> %s %s/%s %s", device.serial, frame.topic, frame.subtopic, frame_dump(frame))
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break
        except (aiohttp.ClientError, ConnectionResetError):
            pass
        finally:
            device.cloud_connected = False
            device.notify()
            if not ws.closed and device._ws is ws:
                # reset, never a close frame: the device reconnects in ~10 s and is served
                # locally if the real cloud stays away
                reset_transport(device._transport)

    async def _poll(self, device: CloudDevice) -> None:
        await asyncio.sleep(1.0)
        while True:
            try:
                await device.async_refresh()
            except ConnectionError:
                return
            await asyncio.sleep(LOCAL_POLL_SECONDS)
