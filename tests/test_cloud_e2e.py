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
    print("cloud e2e passed")

asyncio.run(main())
