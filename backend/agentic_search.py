"""Agentic tool loop: gives the model direct access to whichever of
web_search / web_fetch / memory_search are relevant this turn, via the
local MCP server, called iteratively — instead of a fixed pipeline. Only
runs when the active provider supports tool calling.

Citation numbering: only web_fetch results are numbered/citable — a
web_search snippet alone is too thin to ground a claim in, so the model is
told to fetch before citing. memory_search results are never citation-
numbered — they're not web sources. Numbers are assigned in first-fetched
order and reused if the same URL is fetched twice in one turn."""

import json
import logging

from mcp_client import MCPClient
from mcp_server import NOT_EXTRACTED_PREFIX

logger = logging.getLogger("agentic_search")
MAX_TOOL_ITERATIONS = 5
_client: MCPClient | None = None

CITATION_INSTRUCTION = (
    "You have web_search, web_fetch, and memory_search tools (only the ones "
    "relevant to this turn may actually be available). web_search returns "
    "title/url/snippet only — too thin to cite directly. Fetch a page with "
    "web_fetch before citing anything from it. Once fetched, each source is "
    "numbered [1], [2], etc. (shown with its content) — cite inline using "
    "that number when you use information from it. Only cite a source for a "
    "claim it actually supports. memory_search results are the user's own "
    "saved facts, not web sources — don't cite them with [n]."
)


def _get_client() -> MCPClient:
    global _client
    if _client is None:
        _client = MCPClient("python", ["mcp_server.py"])
    return _client


def _to_responses_tools(mcp_tools: list[dict], allowed: set[str] | None) -> list[dict]:
    tools = mcp_tools if allowed is None else [t for t in mcp_tools if t["name"] in allowed]
    return [{"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["input_schema"]} for t in tools]


def _step_label(name: str, tool_input: dict) -> str:
    if name == "web_search":
        return f"Searching: {tool_input.get('query', '')}"
    if name == "web_fetch":
        return f"Reading: {tool_input.get('url', '')}"
    if name == "memory_search":
        return f"Searching memory: {tool_input.get('pattern', '')}"
    return f"{name}({tool_input})"


def run(provider, model: str, conversation: list[dict], reasoning_effort: str = "none",
        allowed_tools: set[str] | None = None):
    """Yields the same {"type": "text"/"activity"} shapes chat_engine already
    streams. allowed_tools restricts which of the MCP server's tools are
    actually offered this turn — None means all (backward-compatible
    default); chat_engine.py assembles the real per-turn set."""
    client = _get_client()
    tools = _to_responses_tools(client.list_tools(), allowed_tools)
    messages = list(conversation) + [{"role": "system", "content": CITATION_INSTRUCTION}]
    sources: dict[str, int] = {}

    for _ in range(MAX_TOOL_ITERATIONS):
        made_call = False
        for event in provider.stream_with_tools(messages, model, tools, reasoning_effort=reasoning_effort):
            if event["type"] == "text":
                yield {"type": "text", "value": event["text"]}
            elif event["type"] == "tool_call":
                made_call = True
                yield {"type": "activity", "event": {"kind": "tool_step", "label": _step_label(event["name"], event["input"])}}

                fetch_ok = False
                try:
                    result = client.call_tool(event["name"], event["input"])
                    fetch_ok = event["name"] == "web_fetch" and not result.startswith(NOT_EXTRACTED_PREFIX)
                except Exception as e:
                    result = f"Tool call failed: {e!r}"
                    logger.warning(f"tool call {event['name']} failed: {e!r}")

                if fetch_ok:
                    url = event["input"].get("url", "")
                    n = sources.setdefault(url, len(sources) + 1)
                    result = f"[{n}] {url}\n{result}"
                    preview = result[:200].strip()
                    yield {"type": "activity", "event": {"kind": "source", "citation": n, "url": url, "preview": preview}}

                messages.append({"type": "function_call", "call_id": event["call_id"],
                                  "name": event["name"], "arguments": json.dumps(event["input"])})
                messages.append({"type": "function_call_output", "call_id": event["call_id"], "output": result})
        if not made_call:
            return

    logger.warning(f"agentic_search hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS} without a final answer — forcing synthesis")
    messages.append({
        "role": "system",
        "content": "You've used all available search attempts. Answer now using "
                    "only what you've already gathered, even if incomplete. Say "
                    "what's uncertain or missing rather than continuing to search.",
    })
    for event in provider.stream_with_tools(messages, model, tools=[], reasoning_effort=reasoning_effort):
        if event["type"] == "text":
            yield {"type": "text", "value": event["text"]}