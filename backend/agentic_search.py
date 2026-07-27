"""Agentic web tool loop: gives the model direct access to web_search and
web_fetch via the local MCP server, called iteratively — instead of
research.py's fixed discover-then-distill pipeline. Only runs when the
active provider supports tool calling; everything else keeps using the
fixed pipeline."""

import json
import logging

from mcp_client import MCPClient

logger = logging.getLogger("agentic_search")
MAX_TOOL_ITERATIONS = 5
_client: MCPClient | None = None


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
    streams, so it drops into the existing SSE loop unchanged."""
    client = _get_client()
    tools = _to_responses_tools(client.list_tools())
    messages = list(conversation)

    for _ in range(MAX_TOOL_ITERATIONS):
        made_call = False
        for event in provider.stream_with_tools(messages, model, tools, reasoning_effort=reasoning_effort):
            if event["type"] == "text":
                yield {"type": "text", "value": event["text"]}
            elif event["type"] == "tool_call":
                made_call = True
                args = ", ".join(f"{k}={v!r}" for k, v in event["input"].items())
                yield {"type": "activity", "event": {"kind": "search", "label": f"{event['name']}({args})"}}
                try:
                    result = client.call_tool(event["name"], event["input"])
                except Exception as e:
                    result = f"Tool call failed: {e!r}"
                    logger.warning(f"tool call {event['name']} failed: {e!r}")
                messages.append({"type": "function_call", "call_id": event["call_id"],
                                  "name": event["name"], "arguments": json.dumps(event["input"])})
                messages.append({"type": "function_call_output", "call_id": event["call_id"], "output": result})
        if not made_call:
            break