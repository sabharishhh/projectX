## v0.8.1 — MCP web_search/web_fetch tools, agentic research loop, crawl4ai extraction

### New
- **`mcp_server.py`** — local stdio MCP server exposing `web_search` (wraps `search.discover`) and `web_fetch` (wraps `extraction.extract_page`, capped at 8000 chars).
- **`mcp_client.py`** — sync wrapper around the MCP client, running its own background asyncio loop thread so callers don't touch async directly (mirrors the existing thread+queue pattern used for provider streaming).
- **`agentic_search.py`** — iterative tool-calling loop (max 5 rounds) that lets the model call `web_search`/`web_fetch` directly via the MCP client, instead of one fixed discover→distill pass.

### Changed
- **`extraction.py`** — rewritten on crawl4ai, replacing the Trafilatura → readability-lxml → Playwright fallback chain. Same `extract_page(url) -> {url, text, method}` contract, so `research.py` needed no changes.
- **`providers/base.py`** — added `supports_tools` flag and `stream_with_tools()` (default `NotImplementedError`); `reasoning_effort` param added to both abstract signatures.
- **`providers/openai_provider.py`** — added `stream_with_tools()`, using the same `responses.create` event-streaming pattern as the existing `stream()`. `supports_tools = True`.
- **`providers/anthropic_provider.py`** — same addition, `reasoning_effort` accepted but unused (no `thinking`-budget wiring yet — separate scope). **Tool-call event names (`response.output_item.added`, `response.function_call_arguments.delta`, etc.) are unverified against a live key — smoke-test before relying on it.**
- **`providers/local_provider.py`** — no changes needed; already correctly ignores `reasoning_effort` and has no `stream_with_tools`, so local models fall through to the fixed pipeline as intended.
- **`chat_engine.py`** — added a gated branch: `research`-skill turns on a tool-capable provider use `agentic_search.run()`; everything else (other skills, no skill, local models) keeps the original fixed search pipeline unchanged.
- **`skills/research.toml`** — added `web_fetch` to the allowed tools list.
- **`pyproject.toml`** — removed `trafilatura`, `readability-lxml`; added `crawl4ai`, `mcp`. `playwright` retained (crawl4ai dependency) — run `playwright install chromium` once.

### Design notes
- Web search/fetch now goes through MCP rather than a bespoke tool interface — reserves the same slot for a future sandboxed runtime tool (clone repo, grep, etc.) without rearchitecture: just another MCP server.
- Agentic mode is strictly opt-in (research skill + tool-capable provider only); the token/session-burn-avoidant fixed pipeline stays the default everywhere else.

### Known gaps / follow-ups
- Anthropic tool-call event names unverified (see above).
- `extraction.py` launches a fresh crawl4ai browser instance per call inside `research.py`'s thread pool — works, but a shared `AsyncWebCrawler` instance would be faster.
- Runtime/sandbox tool (E2B/Microsandbox-class) intentionally not built — documented as a future MCP server attachment point only.