"""ReefClient reports a stuck web server (HTTP 429): only when its own connection attempts are refused for
the whole confirmation time, never from a single refusal, and without any extra request
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
SERIAL = "RFLK012304200017"
# the real values are five minutes and more - the same rules, faster
client.RETRY_SECONDS = 0.2
client.RETRY_MAX_SECONDS = 0.4
client.RETRY_BUSY_SECONDS = 0.3
client.BUSY_CONFIRM_SECONDS = 1.5

async def wait_for(cond, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()

async def main():
    # answer: status for the next connection attempts (None = take the connection); left: how many attempts
    # get that status (-1 = all); other: requests that are not the WebSocket
    state = {"answer": 429, "left": 1, "other": 0, "attempts": 0}
    async def index(request):
        state["other"] += 1
        return web.Response(text="ok")
    async def controler(request):
        state["attempts"] += 1
        if state["answer"] is not None and state["left"] != 0:
            if state["left"] > 0:
                state["left"] -= 1
            return web.Response(status=state["answer"], headers={"Retry-After": "5"})
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

        # 1 - one refused attempt, then the device takes the connection: not stuck
        assert await wait_for(lambda: c.connected, 3), "not connected"
        assert events == [] and not c.busy, events
        print("ok  client: a single refused connection attempt is not reported")

        # 2 - refused for a while, but shorter than the confirmation time (a second connection that is open
        #     for a moment, a connection the device has not let go of yet): not stuck
        state.update(answer=429, left=3)
        await c._ws.close()
        assert await wait_for(lambda: state["left"] == 0 and c.connected, 10), state
        assert events == [] and not c.busy, events
        print("ok  client: refusals shorter than the confirmation time are not reported")

        # 3 - every attempt refused: stuck, but only after the confirmation time
        state.update(answer=429, left=-1)
        await c._ws.close(); start = time.monotonic()
        assert await wait_for(lambda: events == [True], 10), events
        assert time.monotonic() - start >= client.BUSY_CONFIRM_SECONDS, time.monotonic() - start
        assert c.busy and not c.connected
        # 4 - the device restarted: the first connection that is taken ends it
        state.update(answer=None)
        assert await wait_for(lambda: events == [True, False] and c.connected, 10), events
        assert not c.busy
        print("ok  client: every attempt refused for the confirmation time -> busy, restart -> not busy")

        # 5 - another error than 429 (here 503) is not "refused", however long it lasts
        state.update(answer=503, left=-1)
        await c._ws.close()
        await asyncio.sleep(client.BUSY_CONFIRM_SECONDS * 2.5)
        assert events == [True, False] and not c.busy and not c.connected, events
        # ... and it breaks a row of refusals: 429, 503, 429 ... never adds up
        for answer in (429, 503) * 4:
            state.update(answer=answer, left=-1)
            await asyncio.sleep(client.BUSY_CONFIRM_SECONDS * 0.45)
        assert events == [True, False] and not c.busy, events
        print("ok  client: other errors are not reported and break a row of refusals")

        # 6 - the client never asks for anything but its WebSocket
        assert state["other"] == 0, state
        print("ok  client: no extra requests (%d connection attempts, 0 others)" % state["attempts"])
        await c.async_stop(); task.cancel()
    await runner.cleanup()

asyncio.run(main())
