"""Local MCP server exposing web_search and web_fetch. Launched as a
subprocess over stdio by mcp_client.py — not a standalone network service."""

from mcp.server.fastmcp import FastMCP

import search as discovery
import extraction

mcp = FastMCP("projectx-web")
MAX_FETCH_CHARS = 8000  # keep one fetch from blowing the context budget


@mcp.tool()
def web_search(query: str, limit: int = 5) -> str:
    """Search the web and return candidate results (title, url, snippet)."""
    results = discovery.discover(query, limit=limit)
    if not results:
        return "No results."
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r['snippet']}" for r in results)


@mcp.tool()
def web_fetch(url: str) -> str:
    """Fetch a specific URL and return its main text content."""
    page = extraction.extract_page(url)
    if not page["text"]:
        return f"Could not extract content from {url}."
    return page["text"][:MAX_FETCH_CHARS]


if __name__ == "__main__":
    mcp.run(transport="stdio")