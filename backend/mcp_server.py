"""Local MCP server exposing loki's agent-facing tools — web_search,
web_fetch, memory_search, and github_search. One process, one tool
surface, launched as a subprocess over stdio by mcp_client.py. Each tool
stays narrow and single-purpose on its own terms (read-only where
relevant, hard-scoped) — bundling them into one server is a deployment/
organizational choice, not a loosening of any individual tool's
constraints."""

import json
import httpx
import extraction
import search as discovery
from memory_client import client
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("loki-tools")
MAX_FETCH_CHARS = 8000

NOT_EXTRACTED_PREFIX = "Could not extract content from"
GITHUB_API = "https://api.github.com"


@mcp.tool()
def web_search(query: str, limit: int = 5) -> str:
    """Search the web and return candidate results as a JSON list of
    {title, url, snippet} objects. Returned as structured JSON, not
    preformatted text, so the calling agent can cite each individual
    result by URL — see agentic_search.py's citation handling. A snippet
    alone is thinner grounding than a fetched page; prefer web_fetch when
    a claim needs solid support, but a snippet may be cited directly when
    it's sufficient on its own."""
    results = discovery.discover(query, limit=limit)
    return json.dumps(results)


@mcp.tool()
def github_search(query: str, kind: str = "repositories", limit: int = 5) -> str:
    """Search GitHub for repositories, code, or issues via the official
    GitHub Search API — no scraping, no auth required for reasonable use
    (60 req/hr unauthenticated; set GITHUB_TOKEN in .env for higher
    limits). kind: 'repositories', 'code', or 'issues'. Returns the same
    JSON shape as web_search ({title, url, snippet}) so results are
    citable the same way."""
    import os
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.get(
            f"{GITHUB_API}/search/{kind}",
            params={"q": query, "per_page": limit},
            headers=headers, timeout=15.0,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        results = []
        for i in items:
            title = i.get("full_name") or i.get("name") or i.get("title") or ""
            url = i.get("html_url", "")
            snippet = (i.get("description") or "").strip()
            if not snippet and i.get("text_matches"):
                snippet = i["text_matches"][0].get("fragment", "")[:200]
            results.append({"title": title, "url": url, "snippet": snippet[:200]})
        return json.dumps(results)
    except Exception as e:
        return f"GitHub search failed: {e!r}"


@mcp.tool()
def memory_search(pattern: str, branch: str = "main") -> str:
    """Search the user's saved memory for an exact word/phrase (regex
    pattern) — for precise recall ("what exactly did I say about X"), not
    the general semantic recall already injected into context. Read-only,
    scoped to currently-active memory in one branch. Does not search
    forgotten/superseded facts."""
    try:
        r = client.get(f"/search", params={"pattern": pattern, "branch": branch})
        r.raise_for_status()
        results = r.json()
    except Exception as e:
        return f"Memory search failed: {e!r}"

    if not results:
        return "No matches."
    return "\n\n".join(f"[{u['hash'][:8]}] {u['content']} ({u['unit_type']})" for u in results)


@mcp.tool()
def web_fetch(url: str) -> str:
    """Fetch a specific URL and return its main text content. Only call this
    on a URL you intend to actually use/cite."""
    page = extraction.extract_page(url)
    if not page["text"]:
        return f"{NOT_EXTRACTED_PREFIX} {url}."
    return page["text"][:MAX_FETCH_CHARS]

@mcp.tool()
def list_open_commitments() -> str:
    """Returns every currently open commitment across all branches,
    regardless of due date — the deterministic, complete answer for
    requests like 'what are all my commitments' or 'close all open
    commitments'. Unlike memory_search, this needs no guessed keywords
    and cannot miss an item due to word choice — it's a direct read of
    the authoritative open-commitment list, the same source
    _build_commitment_context's due-soon slice is drawn from, just
    without the 48-hour window restricting it."""
    from capture import find_open_commitments
    from branching import CANONICAL_DOMAINS
    branches = sorted({"main", *CANONICAL_DOMAINS})
    all_open = []
    for b in branches:
        all_open.extend({**u, "branch": b} for u in find_open_commitments(b))
    if not all_open:
        return "No open commitments."
    return "\n".join(f"[{u['hash'][:8]}] {u['content']}" + (f" (due {u['deadline']})" if u.get("deadline") else "")
                      for u in all_open)

if __name__ == "__main__":
    mcp.run(transport="stdio")

@mcp.tool()
def conversation_history_search(query: str, conversation_id: str, all_conversations: bool = False, limit: int = 6) -> str:
    """Search raw message history for something that may have fallen out
    of the visible context window. Keyword/BM25 search, not semantic —
    works best with distinct words from the original message, not a
    paraphrase. all_conversations=False (default) searches only the
    current conversation; True searches every past conversation — only
    useful if the question clearly can't be about the current
    conversation alone. conversation_id is injected by the caller, not
    supplied by the model — it identifies which conversation is 'current'."""
    import db
    conv_id = None if all_conversations else conversation_id
    hits = db.search_messages(query, conversation_id=conv_id, limit=limit)
    if not hits:
        return "No matches found in conversation history."
    return "\n\n".join(f"({h['role']}, {h['created_at']}): {h['content'][:300]}" for h in hits)