"""End-to-end test of the cloud replacement without Home Assistant (needs aiohttp + cryptography).

A simulated Smart feeder connects to the server (local mode) and, in a second
round, to a server in passthrough mode whose "real cloud" is another local
server. Frames are the ones captured on 03.11.2026.
"""
import asyncio, importlib.util, json, os, pathlib, sys, tempfile, time

import aiohttp

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "reef_factory_local"
def load(name):
    spec = importlib.util.spec_from_file_location(f"reef_factory_local.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod
import types
pkg = types.ModuleType("reef_factory_local"); pkg.__path__ = [str(ROOT)]; sys.modules["reef_factory_local"] = pkg
pr = load("protocol"); cloud = load("cloud")

SERIAL = "RFSF012309180013"
REPORT = {"mode": "period", "periods": [{"time": 660, "rotations": 1, "days": 127}], "sequence": {"frequency": 360, "rotations": 2},
          "nextFeeding": {"date": "2026-11-03", "time": "20:00", "doseValue": 100},
          "container": {"value": 5000, "size": 0, "reminderDays": 0, "singleDose": 100, "daysToEnd": 24},
          "history": [], "dailyDose": 0, "ledStatus": "enabled", "feedingButton": "enabled"}


async def fake_feeder(port, tls, received, send_queue):
    """Behaves like the device: login, then answers sfGet/all and every sfSet with sfReport/all."""
    async with aiohttp.ClientSession() as s:
        url = f"{'wss' if tls else 'ws'}://127.0.0.1:{port}/hardware32"
        async with s.ws_connect(url, ssl=False if tls else None, autoping=False) as ws:
            await ws.send_bytes(pr.build_frame("geConnect", "login", json.dumps({"key": "k", "token": "t", "email": "e", "version": "1.1.6"}).encode(), SERIAL))
            state = dict(REPORT)
            async def sender():
                while True:
                    f = await send_queue.get()
                    if f is None: return
                    await ws.send_bytes(f)
            st = asyncio.create_task(sender())
            try:
                async with asyncio.timeout(8):
                    async for msg in ws:
                        if msg.type is aiohttp.WSMsgType.BINARY:
                            fr = pr.parse_frame(msg.data); received.append(fr)
                            if fr.topic.endswith("Get") or fr.topic == "sfSet" or fr.topic == "sfExecute":
                                if fr.topic == "sfSet" and fr.subtopic == "mode":
                                    state["mode"] = pr.parse_json(fr)["mode"]
                                await ws.send_bytes(pr.build_frame("sfReport", "all", json.dumps(state).encode(), SERIAL, fr.joinid))
                        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                            break
            except TimeoutError:
                pass
            finally:
                st.cancel()


async def main():
    tmp = tempfile.mkdtemp()
    new = []
    # --- round 1: local mode
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_LOCAL, on_new_device=new.append, ports=(14442, 14444))
    await srv.async_start(); assert not srv.listen_errors, srv.listen_errors
    assert os.path.exists(srv.cert_path) and oct(os.stat(srv.key_path).st_mode)[-3:] == "600"
    received, q = [], asyncio.Queue()
    task = asyncio.create_task(fake_feeder(14444, True, received, q))
    await asyncio.sleep(2.5)
    dev = srv.devices[SERIAL]
    assert new and new[0] is dev and dev.kind == pr.DEVICE_FEEDER and dev.mode == cloud.MODE_LOCAL
    topics = [(f.topic, f.subtopic) for f in received]
    assert topics[:4] == [("geReport", "login"), ("geSet", "time"), ("sfConnect", "join"), ("sfGet", "all")], topics
    assert dev.data["container_g"] == 50.0 and dev.data["mode"] == "schedule" and dev.firmware == "1.1.6"
    # command from HA -> device answers -> state updated
    await dev.async_send(pr.frame_sf_set_mode(SERIAL, "interval", dev.join_id))
    await asyncio.sleep(0.5)
    assert dev.data["mode"] == "interval", dev.data["mode"]
    await q.put(None); task.cancel()
    await srv.async_stop()
    print("ok  local mode: login, time, subscribe, get, command round trip")

    # --- round 2: passthrough to a fake "real cloud" (= another local server)
    real = cloud.ReefCloudServer(tmp, mode=cloud.MODE_LOCAL, ports=(15442, 15444))
    await real.async_start(); assert not real.listen_errors
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_PASSTHROUGH, upstream_ips=["127.0.0.1"], on_new_device=new.append, ports=(16442, 16444))
    srv.upstream_ports = (15442, 15444); srv.upstream_verify = False
    await srv.async_start(); assert not srv.listen_errors
    received, q = [], asyncio.Queue()
    task = asyncio.create_task(fake_feeder(16444, True, received, q))
    await asyncio.sleep(3)
    dev = srv.devices[SERIAL]
    assert dev.mode == cloud.MODE_PASSTHROUGH and dev.cloud_connected, (dev.mode, dev.cloud_connected)
    topics = [(f.topic, f.subtopic) for f in received]
    assert ("geReport", "login") in topics and ("sfGet", "all") in topics, topics
    assert dev.data.get("container_g") == 50.0, dev.data
    assert real.devices[SERIAL].data.get("container_g") == 50.0  # the "cloud" saw the report too
    await q.put(None); task.cancel()
    await srv.async_stop(); await real.async_stop()
    print("ok  passthrough: forwarded both ways, state learned on both sides")

    # --- round 3: passthrough with unreachable cloud -> served locally
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_PASSTHROUGH, upstream_ips=["127.0.0.1"], ports=(17442, 17444))
    srv.upstream_ports = (1, 1); srv.upstream_verify = False
    await srv.async_start()
    received, q = [], asyncio.Queue()
    task = asyncio.create_task(fake_feeder(17444, True, received, q))
    await asyncio.sleep(3)
    dev = srv.devices[SERIAL]
    assert dev.mode == cloud.MODE_LOCAL and not dev.cloud_connected and dev.data.get("container_g") == 50.0
    await q.put(None); task.cancel(); await srv.async_stop()
    print("ok  passthrough fallback: cloud unreachable -> local answers")

    # --- round 4: the cloud comes back -> the device is reconnected and passed through (2026-11-11)
    real = cloud.ReefCloudServer(tmp, mode=cloud.MODE_LOCAL, ports=(18442, 18444))
    await real.async_start(); assert not real.listen_errors
    retry = cloud.UPSTREAM_RETRY_SECONDS; cloud.UPSTREAM_RETRY_SECONDS = 0.5
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_PASSTHROUGH, upstream_ips=["127.0.0.1"], ports=(19442, 19444))
    srv.upstream_ports = (1, 1); srv.upstream_verify = False
    await srv.async_start()
    received, q = [], asyncio.Queue()

    async def device_that_reconnects():  # like the firmware after a TCP reset
        while True:
            try:
                await fake_feeder(19444, True, received, q)
            except (aiohttp.ClientError, OSError):
                pass
            await asyncio.sleep(0.3)
    task = asyncio.create_task(device_that_reconnects())
    await asyncio.sleep(2)
    dev = srv.devices[SERIAL]
    assert dev.mode == cloud.MODE_LOCAL and not dev.cloud_connected and SERIAL not in real.devices
    first = dev._ws
    srv.upstream_ports = (18442, 18444)  # the cloud is back
    await asyncio.sleep(4)
    assert dev._ws is not None and dev._ws is not first, "device was not reconnected"
    assert dev.mode == cloud.MODE_PASSTHROUGH and dev.cloud_connected and dev.connected, (dev.mode, dev.cloud_connected)
    assert real.devices[SERIAL].data.get("container_g") == 50.0
    assert srv._upstream_hosts == {pr.CLOUD_HOST: ["127.0.0.1"]}
    task.cancel(); cloud.UPSTREAM_RETRY_SECONDS = retry
    await srv.async_stop(); await real.async_stop()
    print("ok  passthrough recovery: cloud back -> device reconnected through the real cloud")

    # --- round 5: stopping must not hang on a connection that never sent a frame (2026-11-11)
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_LOCAL, ports=(20442, 20444))
    await srv.async_start()
    received, q = [], asyncio.Queue()
    task = asyncio.create_task(fake_feeder(20444, True, received, q))
    silent = aiohttp.ClientSession()
    quiet_ws = await silent.ws_connect("ws://127.0.0.1:20442/hardware32", autoping=False)  # connects, says nothing
    await asyncio.sleep(1.5)
    assert SERIAL in srv.devices and len(srv._transports) == 2, len(srv._transports)
    t0 = time.monotonic()
    async with asyncio.timeout(6):
        await srv.async_stop()
    assert time.monotonic() - t0 < 5 and not srv._transports and not srv._runners
    task.cancel(); await quiet_ws.close(); await silent.close()
    print("ok  stop: all connections reset, listeners closed in %.1f s" % (time.monotonic() - t0))

    # --- round 6: a live device session is never handed to another source address (HACS review 2026-11-12)
    srv = cloud.ReefCloudServer(tmp, mode=cloud.MODE_LOCAL, ports=(21442, 21444))
    await srv.async_start()
    received, q = [], asyncio.Queue()
    task = asyncio.create_task(fake_feeder(21444, True, received, q))
    await asyncio.sleep(1.5)
    dev = srv.devices[SERIAL]
    first_ws = dev._ws
    assert dev.connected and dev.peer == "127.0.0.1" and dev.firmware == "1.1.6", (dev.peer, dev.firmware)
    opened = []

    async def claim(local):
        """Someone else logs in with the feeder's serial number; True if the server answered the login."""
        session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(local_addr=(local, 0)))
        opened.append(session)
        ws = await session.ws_connect("ws://127.0.0.1:21442/hardware", autoping=False)
        await ws.send_bytes(pr.build_frame("geConnect", "login", json.dumps(
            {"key": "x", "token": "x", "email": "x", "version": "9.9.9"}).encode(), SERIAL))
        try:
            msg = await ws.receive(timeout=2)
        except (asyncio.TimeoutError, TimeoutError):
            return False
        return msg.type is aiohttp.WSMsgType.BINARY

    assert await claim("127.0.0.2") is False                       # other address while the feeder is alive
    assert dev._ws is first_ws and dev.peer == "127.0.0.1" and dev.firmware == "1.1.6", (dev.peer, dev.firmware)
    await dev.async_send(pr.frame_sf_set_mode(SERIAL, "interval", dev.join_id))   # commands still reach the feeder
    await asyncio.sleep(0.5)
    assert dev.data["mode"] == "interval" and any(f.topic == "sfSet" for f in received), dev.data["mode"]
    assert await claim("127.0.0.1") is True                        # same address: the device reconnecting
    assert dev._ws is not first_ws and dev.peer == "127.0.0.1"
    dev.last_seen -= cloud.SESSION_LIVE_SECONDS + 1                # the old connection went silent ...
    assert await claim("127.0.0.2") is True                        # ... so a device with a new address gets in
    assert dev.peer == "127.0.0.2"
    await q.put(None); task.cancel()
    await srv.async_stop()
    for session in opened:
        await session.close()
    print("ok  takeover: live session kept against another address, same address and silent session accepted")
    print("cloud e2e passed")

def test_lan_addresses():
    class IP:  # ifaddr.IP lookalike
        def __init__(self, ip): self.ip = ip
    class Adapter:
        def __init__(self, *ips): self.ips = [IP(i) for i in ips]
    got = cloud.lan_ipv4_addresses([Adapter("127.0.0.1", ("::1", 0, 0)), Adapter("192.168.177.50"),
                                    Adapter("100.113.127.4"), Adapter("169.254.1.2"), Adapter("10.42.1.1")])
    assert got == ["10.42.1.1", "192.168.177.50"], got
    print("ok  lan addresses (no loopback, link-local, Tailscale)")


async def test_relay_fallback():
    """Port taken on one address (like Tailscale Funnel on 443, 07.11.2026): the app relay binds the LAN address."""
    holder = socket.socket(); holder.bind(("127.0.0.1", 0)); holder.listen(); port = holder.getsockname()[1]
    ports, lan = cloud.APP_PORTS, cloud.lan_ipv4_addresses
    cloud.APP_PORTS = (port,)
    cloud.lan_ipv4_addresses = lambda adapters=None: ["127.0.0.2"]
    srv = cloud.ReefCloudServer.__new__(cloud.ReefCloudServer); srv._raw_servers = []
    try:
        await srv._start_app_relays()
        bound = [sock.getsockname() for server in srv._raw_servers for sock in server.sockets]
        assert bound == [("127.0.0.2", port)], bound
    finally:
        for server in srv._raw_servers:
            server.close()
        holder.close(); cloud.APP_PORTS, cloud.lan_ipv4_addresses = ports, lan
    print("ok  app relay falls back to the LAN address when the port is taken elsewhere")


import socket
test_lan_addresses()
asyncio.run(test_relay_fallback())
asyncio.run(main())
