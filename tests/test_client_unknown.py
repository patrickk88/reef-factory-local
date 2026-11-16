"""A device of an unknown type (valid serial, no known prefix) is only ever asked for its config: nothing is
subscribed, get/user is not sent, the connection stays up without data, and what the device sends is kept
for the diagnostics - without the content of messages that may carry account or Wi-Fi data
(needs aiohttp; runs in the HA python)."""
import asyncio, importlib.util, pathlib, sys, time, types
import aiohttp
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "reef_factory_local"
pkg = types.ModuleType("reef_factory_local"); pkg.__path__ = [str(ROOT)]; sys.modules["reef_factory_local"] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f"reef_factory_local.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod
pr = load("protocol"); client = load("client")
SERIAL = "RFKH012345678901"
pr.register_device_type(SERIAL, pr.DEVICE_UNKNOWN)
# the real values are 30 and 60 seconds - the same rules, faster
client.UNKNOWN_POLL_SECONDS = 1
pr.WATCHDOG_SECONDS = 3

async def wait_for(cond, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()

async def main():
    got = []       # (topic, subtopic) of everything the client sent
    async def controler(request):
        ws = web.WebSocketResponse(protocols=(pr.WS_SUBPROTOCOL,)); await ws.prepare(request)
        async for msg in ws:
            frame = pr.parse_frame(msg.data)
            got.append((frame.topic, frame.subtopic))
            if (frame.topic, frame.subtopic) == ("get", "config"):
                await ws.send_bytes(pr.build_frame("refresh", "config", SERIAL.encode() + b"\x00\x03\x001.2.3" + bytes(8), SERIAL))
                if got.count(("get", "config")) == 1:   # what such a device may send by itself
                    await ws.send_bytes(pr.build_frame("khRefresh", "all", bytes(range(40)), SERIAL))
                    await ws.send_bytes(pr.build_frame("status", "user", b"someone@example.org\x00\x01\x03\x02", SERIAL))
                    await ws.send_bytes(pr.build_frame("khWifi", "list", b"MyNetwork\x00", SERIAL))
                    await ws.send_bytes(pr.build_frame("khReport", "mail", b"x@y.z", SERIAL))
        return ws
    app = web.Application(); app.router.add_get(pr.WS_PATH, controler)
    runner = web.AppRunner(app); await runner.setup(); site = web.TCPSite(runner, "127.0.0.1", 18081); await site.start()
    data, config, conn = [], [], []
    async with aiohttp.ClientSession() as session:
        c = client.ReefClient(session, "127.0.0.1:18081", SERIAL, on_data=data.append,
                              on_connection=conn.append, on_config=config.append)
        assert c.kind == pr.DEVICE_UNKNOWN
        task = asyncio.create_task(c.run())
        assert await wait_for(lambda: c.connected and config, 3), "not connected"
        assert config[0]["serial"] == SERIAL and config[0]["firmware"] == "1.2.3", config
        # longer than the watchdog time: the answers to get/config keep the connection up
        await asyncio.sleep(pr.WATCHDOG_SECONDS * 2 + 0.5)
        assert c.connected and conn == [True], conn
        assert set(got) == {("get", "config")} and len(got) >= 4, got      # nothing else was ever sent
        assert data and not any(data), data                               # "something came", but no values are made up
        print("ok  unknown: only get/config is sent (%d times), connection stays up, no values" % len(got))

        raw = c.raw_frames
        assert raw["refresh/config"]["count"] >= 4 and raw["refresh/config"]["hex"].startswith(SERIAL.encode().hex())
        assert raw["khRefresh/all"] == {"count": 1, "length": 41, "hex": bytes(range(40)).hex() + "00"}, raw["khRefresh/all"]  # with the frame's closing NUL
        for private in ("status/user", "khWifi/list", "khReport/mail"):   # account name, Wi-Fi, an e-mail address
            assert raw[private]["count"] == 1 and raw[private]["hex"] is None, (private, raw[private])
        print("ok  unknown: messages kept for the diagnostics, account/Wi-Fi content left out")
        await c.async_stop(); task.cancel()
    await runner.cleanup()

asyncio.run(main())
