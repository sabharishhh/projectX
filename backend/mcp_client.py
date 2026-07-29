import asyncio
import concurrent.futures
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from background_loop import BackgroundEventLoop


class MCPClient:
    """stdio_client/ClientSession open anyio cancel scopes tied to the
    specific asyncio Task that entered them — exiting from a different
    Task raises RuntimeError. The original per-call pattern (each public
    method submitted as its own run_coroutine_threadsafe call) hit this on
    close(), since connect and close each ran as separate Tasks — a
    pre-existing bug, not something the shared-loop refactor introduced,
    just never exercised until close() was tested standalone. Fix: the
    whole session lifecycle (open, wait, close) runs inside ONE persistent
    task, started once and kept alive until close() signals it to exit."""

    def __init__(self, command: str, args: list[str]):
        self._bg = BackgroundEventLoop()
        self._session: ClientSession | None = None
        self._close_event: asyncio.Event | None = None
        self._ready: concurrent.futures.Future = concurrent.futures.Future()
        self._closed: concurrent.futures.Future = concurrent.futures.Future()

        self._bg.spawn(self._lifecycle(command, args))
        self._ready.result(timeout=30.0)  # blocks until connected, or re-raises a connect failure

    async def _lifecycle(self, command: str, args: list[str]):
        self._close_event = asyncio.Event()
        try:
            async with AsyncExitStack() as stack:
                params = StdioServerParameters(command=command, args=args)
                read, write = await stack.enter_async_context(stdio_client(params))
                self._session = await stack.enter_async_context(ClientSession(read, write))
                await self._session.initialize()
                self._ready.set_result(None)
                await self._close_event.wait()
        except Exception as e:
            if not self._ready.done():
                self._ready.set_exception(e)
        finally:
            if not self._closed.done():
                self._closed.set_result(None)

    def list_tools(self) -> list[dict]:
        async def _do():
            result = await self._session.list_tools()
            return [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                    for t in result.tools]
        return self._bg.run(_do())

    def call_tool(self, name: str, arguments: dict, timeout: float = 30.0) -> str:
        async def _do():
            result = await self._session.call_tool(name, arguments)
            return "\n".join(b.text for b in result.content if getattr(b, "text", None))
        return self._bg.run(_do(), timeout=timeout)

    def close(self):
        if self._close_event is None:
            return
        self._bg.call_soon(self._close_event.set)
        self._closed.result(timeout=10.0)
        self._bg.stop()