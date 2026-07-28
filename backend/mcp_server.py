"""Local MCP server exposing projectX's agent-facing tools — web_search,
web_fetch, and memory_search. One process, one tool surface, launched as a
subprocess over stdio by mcp_client.py. Each tool stays narrow and
single-purpose on its own terms (read-only where relevant, hard-scoped) —
bundling them into one server is a deployment/organizational choice, not a
loosening of any individual tool's constraints."""

import os
import httpx
from mcp.server.fastmcp import FastMCP

import search as discovery
import extraction

mcp = FastMCP("projectx-tools")
MAX_FETCH_CHARS = 8000
MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")

NOT_EXTRACTED_PREFIX = "Could not extract content from"


@mcp.tool()
def web_search(query: str, limit: int = 5) -> str:
    """Search the web and return candidate results (title, url, snippet).
    Snippets are too short to cite directly — use web_fetch on a result
    before citing it."""
    results = discovery.discover(query, limit=limit)
    if not results:
        return "No results."
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r['snippet']}" for r in results)


@mcp.tool()
def memory_search(pattern: str, branch: str = "main") -> str:
    """Search the user's saved memory for an exact word/phrase (regex
    pattern) — for precise recall ("what exactly did I say about X"), not
    the general semantic recall already injected into context. Read-only,
    scoped to currently-active memory in one branch. Does not search
    forgotten/superseded facts."""
    try:
        r = httpx.get(f"{MEMORY_URL}/search", params={"pattern": pattern, "branch": branch}, timeout=10.0)
        r.raise_for_status()
        results = r.json()
    except Exception as e:
        return f"Memory search failed: {e!r}"

    if not results:
        return "No matches."
    return "\n\n".join(f"[{u['hash'][:8]}] {u['content']} ({u['unit_type']})" for u in results)

if __name__ == "__main__":
    mcp.run(transport="stdio")