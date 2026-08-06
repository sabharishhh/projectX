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

import re
import json
import logging
from pipeline import Stage, Pipeline

from mcp_client import MCPClient
from mcp_server import NOT_EXTRACTED_PREFIX

logger = logging.getLogger("agentic_search")
MAX_TOOL_ITERATIONS = 5
_client: MCPClient | None = None

CITATION_INSTRUCTION = (
    "You have web_search, web_fetch, github_search, and memory_search tools "
    "(only the ones relevant to this turn may actually be available). "
    "web_search, github_search, and web_fetch results are numbered [1], [2], "
    "etc. as you use them — cite inline using that exact bracket-number "
    "format, and nothing else. Never write the word 'cite' or any other citation marker "
    "text in your reply — the ONLY valid citation format is a plain number "
    "in square brackets. Prefer fetching a page with web_fetch when a claim "
    "needs solid grounding, but a web_search snippet may be cited directly "
    "when it's sufficient on its own — phrase claims sourced only from a "
    "snippet a little more cautiously than ones confirmed by a fetched page. "
    "Only cite a source for a claim it actually supports. Cite each specific "
    "claim with the specific source(s) that support it — don't pile multiple "
    "citation numbers onto one broad or summary sentence; if you're making "
    "several distinct points, split them into separate sentences each with "
    "its own precise citation. memory_search results are the user's own "
    "saved facts, not web sources — don't cite them with [n]. Before "
    "searching again, check whether your new query meaningfully differs "
    "from ones you've already tried — repeating a search wastes a turn and "
    "will be flagged back to you instead of actually re-run.\n\n"
    "When you make a real judgment call while working — rejecting a source "
    "as unreliable or off-topic, narrowing or pivoting a search query "
    "because the first attempt wasn't productive, choosing one source over "
    "another when they conflict — briefly say why, on its own line, wrapped "
    "exactly like this: [[reasoning: your one-sentence rationale]]. Use this "
    "only for real decisions worth explaining, not for every step — most "
    "tool calls need no explanation at all. Never use this marker in your "
    "final answer to the user, only while working."
)

_REASONING_MARKER = re.compile(r'\[\[reasoning:\s*(.*?)\s*\]\]', re.DOTALL)

def _split_reasoning(text: str) -> tuple[str, list[str]]:
    """Pulls [[reasoning: ...]] markers out of a round's buffered text —
    each becomes its own narration, and the marker itself is removed from
    what actually reaches the user as answer prose. This is the general
    narration mechanism: unlike the sufficiency-check's own reasoning
    events (which fire from a separate fixed check), this lets the model
    flag ANY real judgment call it makes mid-loop — source rejection,
    query pivots, conflicting-source calls — in its own words, not a
    fixed set of triggers."""
    notes = _REASONING_MARKER.findall(text)
    remaining = _REASONING_MARKER.sub('', text)
    remaining = re.sub(r'\n{3,}', '\n\n', remaining).strip()
    return remaining, notes

def _get_client() -> MCPClient:
    global _client
    if _client is None:
        _client = MCPClient("python", ["mcp_server.py"])
    return _client

_MD_IMAGE = re.compile(r'!\[.*?\]\(.*?\)')
_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')

def _strip_markdown_noise(text: str) -> str:
    """Scraped pages routinely open with nav/skip-links or logo markup
    ('[](url)[Site Name]') before any real content — raw markdown taken
    straight from a fetched page's first N characters spends the preview
    window on that boilerplate instead of actual content. Strips image
    and link syntax (keeping a link's visible text, dropping the URL and
    dropping empty-text links entirely), then collapses whitespace —
    applied BEFORE truncation, not after, so the visible window is spent
    on real text."""
    text = _MD_IMAGE.sub('', text)
    text = _MD_LINK.sub(lambda m: m.group(1), text)
    return re.sub(r'\s+', ' ', text).strip()

def _to_responses_tools(mcp_tools: list[dict], allowed: set[str] | None) -> list[dict]:
    tools = mcp_tools if allowed is None else [t for t in mcp_tools if t["name"] in allowed]
    out = []
    for t in tools:
        schema = t["input_schema"]
        # conversation_history_search's conversation_id is injected by
        # run() at dispatch time, never supplied by the model — hiding it
        # from the schema the model sees keeps that guarantee real rather
        # than just documented in a docstring the model could ignore.
        if t["name"] == "conversation_history_search" and "properties" in schema:
            schema = {**schema, "properties": {k: v for k, v in schema["properties"].items() if k != "conversation_id"},
                      "required": [r for r in schema.get("required", []) if r != "conversation_id"]}
        out.append({"type": "function", "name": t["name"], "description": t["description"], "parameters": schema})
    return out


def _step_label(name: str, tool_input: dict) -> str:
    if name == "web_search":
        return f"Searching: {tool_input.get('query', '')}"
    if name == "github_search":
        return f"Searching GitHub: {tool_input.get('query', '')}"
    if name == "web_fetch":
        return f"Reading: {tool_input.get('url', '')}"
    if name == "memory_search":
        return f"Searching memory: {tool_input.get('pattern', '')}"
    return f"{name}({tool_input})"


def _normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def _repeat_cache_and_key(event: dict, tried_queries: dict, tried_urls: dict, tried_github: dict):
    if event["name"] == "web_search":
        return tried_queries, _normalize_query(event["input"].get("query", ""))
    if event["name"] == "github_search":
        return tried_github, _normalize_query(event["input"].get("query", ""))
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
        allowed_tools: set[str] | None = None, disconnected=None, conversation_id: str | None = None):
    client = _get_client()
    tools = _to_responses_tools(client.list_tools(), allowed_tools)
    messages = list(conversation) + [{"role": "system", "content": CITATION_INSTRUCTION}]
    sources: dict[str, int] = {}
    tried_queries: dict[str, str] = {}
    tried_urls: dict[str, str] = {}
    tried_github: dict[str, str] = {}

    for _ in range(MAX_TOOL_ITERATIONS):
        if disconnected is not None and disconnected.is_set():
            logger.info("agentic_search: disconnected — stopping before next round, not issuing further tool calls")
            return

        pending_calls = []
        round_text = []
        for event in provider.stream_with_tools(messages, model, tools, reasoning_effort=reasoning_effort):
            if event["type"] == "text":
                round_text.append(event["text"])
            elif event["type"] == "tool_call":
                pending_calls.append(event)

        buffered_text = "".join(round_text)
        if buffered_text:
            clean_text, reasoning_notes = _split_reasoning(buffered_text)
            for note in reasoning_notes:
                yield {"type": "activity", "event": {"kind": "reasoning", "label": note}}
            if clean_text:
                yield {"type": "text", "value": clean_text}

        if not pending_calls:
            return

        if disconnected is not None and disconnected.is_set():
            logger.info("agentic_search: disconnected after this round's model turn — dropping pending tool calls, not dispatching")
            return

        # Phase 1 — classify repeats sequentially, before anything runs
        # concurrently. Claiming the cache slot for a genuinely-new call
        # immediately (before its real result comes back) is what catches
        # a duplicate issued later in this SAME round, not just against
        # earlier ones — if this ran concurrently, two identical calls in
        # one round would both see an empty cache and both go out for real.
        to_run = []
        outcomes: dict[str, tuple[str, str | None]] = {}
        for event in pending_calls:
            cache, key = _repeat_cache_and_key(event, tried_queries, tried_urls, tried_github)
            if event["name"] == "conversation_history_search":
                event = {**event, "input": {**event["input"], "conversation_id": conversation_id}}
            if key is not None and key in cache:
                outcomes[event["call_id"]] = ("repeat", cache[key])
            else:
                if key is not None:
                    cache[key] = None
                to_run.append((event, cache, key))
                outcomes[event["call_id"]] = ("new", None)

        # Phase 2 — the actual network/MCP I/O, the expensive part, runs
        # concurrently. Nothing shared is touched inside the workers.
        if to_run:
            tool_stages = [
                Stage(name=f"tool_{i}", deps=[], on_fail="open",
                      fn=(lambda ctx, event=event: _call_tool_raw(client, event)))
                for i, (event, cache, key) in enumerate(to_run)
            ]
            tool_context = Pipeline(tool_stages).run({})
            for i, (event, cache, key) in enumerate(to_run):
                raw_result = tool_context[f"tool_{i}"]
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
                if event["name"] in ("web_search", "github_search"):
                    result, search_events = _process_search_results(result, sources)
                    for ev in search_events:
                        yield {"type": "activity", "event": ev}
                elif event["name"] == "web_fetch" and not result.startswith(NOT_EXTRACTED_PREFIX):
                    url = event["input"].get("url", "")
                    n = sources.setdefault(url, len(sources) + 1)
                    cleaned = _strip_markdown_noise(result[:800])
                    preview = cleaned[:200].strip()
                    result = f"[{n}] {url}\n{result}"
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