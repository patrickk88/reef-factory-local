"""ReefClient reports a stuck web server (HTTP 429) and its end (needs aiohttp; runs in the HA python)."""
import asyncio, importlib.util, pathlib, sys, types
import aiohttp
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "reef_factory_local"
pkg = types.ModuleType("reef_factory_local"); pkg.__path__ = [str(ROOT)]; sys.modules["reef_factory_local"] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f"reef_factory_local.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod); return mod
pr = load("protocol"); client = load("client")
SERIAL = "RFLK012304200017"

async def main():
    state = {"stuck": True}
    async def index(request):
        return web.Response(status=429, headers={"Retry-After": "5"}) if state["stuck"] else web.Response(text="ok")
    async def controler(request):
        if state["stuck"]:
            return web.Response(status=429, headers={"Retry-After": "5"})
        ws = web.WebSocketResponse(protocols=(pr.WS_SUBPROTOCOL,)); await ws.prepare(request)
        async for _ in ws:
            pass
        return ws
    app = web.Application(); app.router.add_get("/", index); app.router.add_get(pr.WS_PATH, controler)
    runner = web.AppRunner(app); await runner.setup(); site = web.TCPSite(runner, "127.0.0.1", 18080); await site.start()
    events = []
    async with aiohttp.ClientSession() as session:
        c = client.ReefClient(session, "127.0.0.1:18080", SERIAL, on_data=lambda d: None,
                              on_connection=lambda v: None, on_busy=events.append)
        task = asyncio.create_task(c.run())
        await asyncio.sleep(1.0)
        assert events == [True] and c.busy, events          # handshake answered with 429
        state["stuck"] = False                              # device restarted
        for _ in range(30):
            await asyncio.sleep(0.5)
            if events[-1] is False:
                break
        assert events == [True, False] and not c.busy and c.connected, events
        state["stuck"] = True                               # stuck again while connected: the periodic check sees it
        client.BUSY_CHECK_SECONDS = 0.5
        await asyncio.sleep(2.5)
        assert events[-1] is True and c.connected, events   # the open connection keeps working
        await c.async_stop(); task.cancel()
    await runner.cleanup()
    print("ok  client: 429 on connect -> busy, restart -> not busy, 429 while connected -> busy again")

asyncio.run(main())
