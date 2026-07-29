"""Agentic tool loop: gives the model direct access to whichever of
web_search / web_fetch / memory_search are relevant this turn, via the
local MCP server, called iteratively — instead of a fixed pipeline. Only
runs when the active provider supports tool calling.

Each round runs in two phases: (1) collect every tool call the model wants
to make this round and classify repeats sequentially — cheap, no I/O, and
catches duplicates issued within the SAME round, not just against earlier
ones, by claiming a cache slot before dispatching; (2) only the genuinely
new calls' actual network/MCP round-trips run concurrently in a thread
pool. Nothing shared (citation numbers, the repeat caches) is touched
inside the worker threads — that all happens afterward, sequentially, in
the model's original call order, so results stay deterministic regardless
of which call finishes first.

Redundancy tracking: repeat searches (same query, normalized) and repeat
fetches (same URL) are intercepted before going out — the cached result is
handed back instead of paying for another round-trip. If every tool call
in a round turns out to be a repeat, that's treated as a stall (the model
has run out of new ground to cover) and synthesis is forced immediately,
rather than only at MAX_TOOL_ITERATIONS. The iteration cap remains as a
backstop for the case where every round keeps finding genuinely new (but
ultimately unhelpful) things to try.

Citation numbering: both web_search and web_fetch results are numbered/
citable, sharing one numbering space keyed by URL — a result that's
searched and later fetched keeps its original number, doesn't get a second
one. web_fetch grounds a claim more solidly (full page vs. a snippet); the
model is told to prefer it for load-bearing claims but may cite a search
snippet directly when it's sufficient. memory_search results are never
citation-numbered — they're not web sources."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from mcp_client import MCPClient
from mcp_server import NOT_EXTRACTED_PREFIX

logger = logging.getLogger("agentic_search")
MAX_TOOL_ITERATIONS = 5
_client: MCPClient | None = None

CITATION_INSTRUCTION = (
    "You have web_search, web_fetch, and memory_search tools (only the ones "
    "relevant to this turn may actually be available). Both web_search and "
    "web_fetch results are numbered [1], [2], etc. as you use them — cite "
    "inline using that number when you rely on information from it. Prefer "
    "fetching a page with web_fetch when a claim needs solid grounding, but "
    "a web_search snippet may be cited directly when it's sufficient on its "
    "own — phrase claims sourced only from a snippet a little more "
    "cautiously than ones confirmed by a fetched page. Only cite a source "
    "for a claim it actually supports. Cite each specific claim with the "
    "specific source(s) that support it — don't pile multiple citation "
    "numbers onto one broad or summary sentence; if you're making several "
    "distinct points, split them into separate sentences each with its own "
    "precise citation. memory_search results are the user's own saved "
    "facts, not web sources — don't cite them with [n]. Before searching "
    "again, check whether your new query meaningfully differs from ones "
    "you've already tried — repeating a search wastes a turn and will be "
    "flagged back to you instead of actually re-run."
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


def _normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def _repeat_cache_and_key(event: dict, tried_queries: dict, tried_urls: dict):
    if event["name"] == "web_search":
        return tried_queries, _normalize_query(event["input"].get("query", ""))
    if event["name"] == "web_fetch":
        return tried_urls, event["input"].get("url", "")
    return None, None


def _call_tool_raw(client: MCPClient, event: dict) -> str:
    """Worker-thread body — only the actual network/MCP round-trip.
    Deliberately touches no shared state (sources, the repeat caches) —
    those are only ever mutated back on the main thread, sequentially,
    after every worker in this round has returned."""
    try:
        return client.call_tool(event["name"], event["input"])
    except Exception as e:
        logger.warning(f"tool call {event['name']} failed: {e!r}")
        return f"Tool call failed: {e!r}"


def _process_search_results(raw: str, sources: dict[str, int]) -> tuple[str, list[dict]]:
    """Parses the JSON web_search now returns, assigns each result a
    citation number (same numbering space web_fetch uses, keyed by URL —
    a result later fetched reuses its number rather than getting a second
    one), and rebuilds a numbered, readable block to feed back to the
    model. Falls back to the raw text unchanged if parsing fails, rather
    than breaking the turn over a malformed tool result."""
    try:
        results = json.loads(raw)
    except Exception as e:
        logger.warning(f"web_search result wasn't valid JSON, passing through raw: {e!r}")
        return raw, []
    if not results:
        return "No results.", []

    lines, events = [], []
    for r in results:
        url = r.get("url", "")
        n = sources.setdefault(url, len(sources) + 1)
        title, snippet = r.get("title", ""), r.get("snippet", "")
        lines.append(f"[{n}] {title}\n{url}\n{snippet}")
        preview = f"{title} — {snippet}"[:200].strip()
        events.append({"kind": "source", "citation": n, "url": url, "preview": preview})
    return "\n\n".join(lines), events


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
    tried_queries: dict[str, str] = {}  # normalized web_search query -> result
    tried_urls: dict[str, str] = {}     # web_fetch url -> result

    for _ in range(MAX_TOOL_ITERATIONS):
        pending_calls = []
        for event in provider.stream_with_tools(messages, model, tools, reasoning_effort=reasoning_effort):
            if event["type"] == "text":
                yield {"type": "text", "value": event["text"]}
            elif event["type"] == "tool_call":
                pending_calls.append(event)

        if not pending_calls:
            return  # model gave a real final answer — done, no synthesis needed

        # Phase 1 — classify repeats sequentially, before anything runs
        # concurrently. Claiming the cache slot for a genuinely-new call
        # immediately (before its real result comes back) is what catches
        # a duplicate issued later in this SAME round, not just against
        # earlier ones — if this ran concurrently, two identical calls in
        # one round would both see an empty cache and both go out for real.
        to_run = []
        outcomes: dict[str, tuple[str, str | None]] = {}
        for event in pending_calls:
            cache, key = _repeat_cache_and_key(event, tried_queries, tried_urls)
            if key is not None and key in cache:
                outcomes[event["call_id"]] = ("repeat", cache[key])
            else:
                if key is not None:
                    cache[key] = None  # claim the slot
                to_run.append((event, cache, key))
                outcomes[event["call_id"]] = ("new", None)

        # Phase 2 — the actual network/MCP I/O, the expensive part, runs
        # concurrently. Nothing shared is touched inside the workers.
        if to_run:
            with ThreadPoolExecutor(max_workers=len(to_run)) as pool:
                futures = {pool.submit(_call_tool_raw, client, event): (event, cache, key)
                           for event, cache, key in to_run}
                for future in futures:
                    event, cache, key = futures[future]
                    raw_result = future.result()
                    if key is not None:
                        cache[key] = raw_result
                    outcomes[event["call_id"]] = ("new", raw_result)

        made_new_progress = bool(to_run)

        # Walk pending_calls in the model's original order — not
        # completion order — so citation numbers, activity events, and
        # message ordering stay deterministic regardless of which worker
        # finished first.
        for event in pending_calls:
            status, raw_result = outcomes[event["call_id"]]
            label = _step_label(event["name"], event["input"])
            if status == "repeat":
                label += " (already tried)"
            yield {"type": "activity", "event": {"kind": "tool_step", "label": label}}

            if status == "repeat":
                kind = "search" if event["name"] == "web_search" else "fetch"
                result = (
                    f"You already tried this exact {kind} and got:\n{raw_result}\n\n"
                    "This is a repeat — try something genuinely different, or answer with what you have."
                )
            else:
                result = raw_result
                if event["name"] == "web_search":
                    result, search_events = _process_search_results(result, sources)
                    for ev in search_events:
                        yield {"type": "activity", "event": ev}
                elif event["name"] == "web_fetch" and not result.startswith(NOT_EXTRACTED_PREFIX):
                    url = event["input"].get("url", "")
                    n = sources.setdefault(url, len(sources) + 1)
                    result = f"[{n}] {url}\n{result}"
                    preview = result[:200].strip()
                    yield {"type": "activity", "event": {"kind": "source", "citation": n, "url": url, "preview": preview}}

            messages.append({"type": "function_call", "call_id": event["call_id"],
                              "name": event["name"], "arguments": json.dumps(event["input"])})
            messages.append({"type": "function_call_output", "call_id": event["call_id"], "output": result})

        if not made_new_progress:
            logger.info("agentic_search stalled — every tool call this round was a repeat, forcing synthesis early")
            break
    else:
        logger.warning(f"agentic_search hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS} without a final answer — forcing synthesis")

    messages.append({
        "role": "system",
        "content": "You've used all available search attempts, or repeated ones "
                    "already tried. Answer now using only what you've already "
                    "gathered, even if incomplete. Say what's uncertain or "
                    "missing rather than continuing to search.",
    })
    for event in provider.stream_with_tools(messages, model, tools=[], reasoning_effort=reasoning_effort):
        if event["type"] == "text":
            yield {"type": "text", "value": event["text"]}