"""One shared pattern for bridging sync code to a background asyncio event
loop — own the loop, run it on a daemon thread, submit work via
run_coroutine_threadsafe. mcp_client.py and extraction.py both need exactly
this (a stdio subprocess session, a browser instance) and previously
hand-rolled it identically in two places. Deliberately NOT used by the
provider files — those wrap synchronous SDK/httpx calls with no async work
to bridge to; forcing them onto this pattern would add an event loop to
run a blocking call inside, solving a problem that doesn't exist there."""

import asyncio
import threading


class BackgroundEventLoop:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def run(self, coro, timeout: float | None = None):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except TimeoutError:
            fut.cancel()
            raise

    def call_soon(self, callback):
        self._loop.call_soon_threadsafe(callback)

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)

    def spawn(self, coro):
        """Schedules coro to run on the background loop without waiting for
        it to complete — for long-running work that outlives the calling
        thread's immediate need (a session kept open until closed later)."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)