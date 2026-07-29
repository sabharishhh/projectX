"""One shared HTTP client to the memory engine, reused across every module
that talks to it — memory.py, capture.py, merge.py, mcp_server.py.
Previously each opened its own httpx connection per call with 3 different
timeout values (20s/10s/5s); a shared, connection-pooled client is both
faster (no new connection per request) and consistent. 20s everywhere,
including merge — matches the value memory.py/capture.py already agreed on
for the same reason: the memory engine can be genuinely slow to respond on
a cold/paged-out load, and that's just as true for a merge as anything
else, not a case for cutting it short."""

import httpx

MEMORY_URL = "http://127.0.0.1:8100"
REQUEST_TIMEOUT = 20.0

client = httpx.Client(base_url=MEMORY_URL, timeout=REQUEST_TIMEOUT)