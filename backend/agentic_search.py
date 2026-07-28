"""Agentic web tool loop: gives the model direct access to web_search and
web_fetch via the local MCP server, called iteratively — instead of
research.py's fixed discover-then-distill pipeline. Only runs when the
active provider supports tool calling; everything else keeps using the
fixed pipeline.

Citation numbering: only web_fetch results are numbered/citable — a
web_search snippet alone is too thin to ground a claim in, so the model is
told to fetch before citing. Numbers are assigned in first-fetched order and
reused if the same URL is fetched twice in one turn."""

import json
import logging

from mcp_client import MCPClient
from mcp_server import NOT_EXTRACTED_PREFIX

logger = logging.getLogger("agentic_search")
MAX_TOOL_ITERATIONS = 7
_client: MCPClient | None = None

CITATION_INSTRUCTION = (
    "You have web_search and web_fetch tools. web_search returns title/url/"
    "snippet only — too thin to cite directly. Fetch a page with web_fetch "
    "before citing anything from it. Once fetched, each source is numbered "
    "[1], [2], etc. (shown with its content) — cite inline using that number "
    "when you use information from it. Only cite a source for a claim it "
    "actually supports."
)


def _get_client() -> MCPClient:
    global _client
    if _client is None:
        _client = MCPClient("python", ["mcp_server.py"])
    return _client


def _to_responses_tools(mcp_tools: list[dict]) -> list[dict]:
    return [{"type": "function", "name": t["name"], "description": t["description"],
             "parameters": t["input_schema"]} for t in mcp_tools]


def run(provider, model: str, conversation: list[dict], reasoning_effort: str = "none"):
    """Yields the same {"type": "text"/"activity"} shapes chat_engine already
    streams. If the model is still calling tools when MAX_TOOL_ITERATIONS
    runs out, forces one final tools-disabled pass so the turn always ends
    with a real answer instead of silently returning nothing — previously,
    exhausting the loop mid-research (every round making a tool call, none
    left over to just answer) produced an empty response with no error."""
    client = _get_client()
    tools = _to_responses_tools(client.list_tools())
    messages = list(conversation) + [{"role": "system", "content": CITATION_INSTRUCTION}]
    sources: dict[str, int] = {}

    for _ in range(MAX_TOOL_ITERATIONS):
        made_call = False
        for event in provider.stream_with_tools(messages, model, tools, reasoning_effort=reasoning_effort):
            if event["type"] == "text":
                yield {"type": "text", "value": event["text"]}
            elif event["type"] == "tool_call":
                made_call = True
                if event["name"] == "web_search":
                    step_label = f"Searching: {event['input'].get('query', '')}"
                else:
                    step_label = f"Reading: {event['input'].get('url', '')}"
                yield {"type": "activity", "event": {"kind": "tool_step", "label": step_label}}

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
            return  # model produced a real final answer on its own — done

    # Ran out of iterations while the model was still trying to call tools.
    # Force one last pass with no tools available, so it's structurally
    # unable to keep researching and has to answer with what it's gathered.
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