import asyncio
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, command: str, args: list[str]):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._run(self._connect(command, args))

    async def _connect(self, command: str, args: list[str]):
        params = StdioServerParameters(command=command, args=args)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def list_tools(self) -> list[dict]:
        async def _do():
            result = await self._session.list_tools()
            return [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                    for t in result.tools]
        return self._run(_do())

    def call_tool(self, name: str, arguments: dict) -> str:
        async def _do():
            result = await self._session.call_tool(name, arguments)
            return "\n".join(b.text for b in result.content if getattr(b, "text", None))
        return self._run(_do())

    def close(self):
        self._run(self._stack.aclose())
        self._loop.call_soon_threadsafe(self._loop.stop)