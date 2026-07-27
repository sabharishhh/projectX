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

## v0.8.2 — shared crawl4ai instance, respawn on failure

### Changed
- **`extraction.py`** — rewritten around a `_CrawlerManager` singleton: one `AsyncWebCrawler` instance and one background event-loop thread, shared across every `extract_page()` call, replacing the previous per-call browser launch. Same `extract_page(url) -> {url, text, method}` contract — `research.py` needed no changes.
  - Explicit `start()`/`close()` lifecycle, not just `async with`.
  - Failures are split by kind: a routine page-level failure (bad URL, 404, blocked port) is handled internally by crawl4ai and does **not** trigger a respawn — only a genuine crawler-level failure (timeout, raised exception) does, via `_respawn()`.
- **`main.py`** — wired `extraction.start()` at boot and `extraction.close()` on shutdown (`@app.on_event("shutdown")` — the older FastAPI API, kept deliberately rather than restructuring the file around `lifespan` for this change).

### Why
- Every parallel `extract_page()` call in `research.py`'s `ThreadPoolExecutor` was previously paying a full Chromium cold-start (~0.5–1s) on top of actual page-load time. On the modest self-hosted hardware this product targets, three concurrent browser launches is real memory pressure, not just latency.
- The agentic loop from v0.8.1 makes this worse if left unfixed — a single `research`-skill turn can call `web_fetch` multiple times in sequence (up to `MAX_TOOL_ITERATIONS=5`), each paying that cold-start cost.

### Tested
- **Singleton reuse** — one `"crawler started"` log line total; second call to the same URL measurably faster than the first (no relaunch).
- **Success path** — confirmed against a real content-bearing page (Wikipedia); returns `method: "crawl4ai"` with real extracted text. (`example.com` alone was insufficient to confirm this — its content is under `MIN_USEFUL_LENGTH=200`, so it always returns `failed` regardless of whether extraction is actually working.)
- **Respawn** — forced via an artificially low `CRAWL_TIMEOUT_SECONDS`, not a real network failure (deterministic, avoids flakiness). Confirmed full sequence: `"crawl failed"` → `"respawning crawler after failure"` → fresh `"crawler started"`.
- **Recovery** — confirmed a call immediately after respawn succeeds again.
- **SearXNG** — unaffected by any of this; discovery is plain HTTP via `search.py`, a separate pipeline stage from extraction. No changes, no re-test needed.

### Also verified this round (from v0.8.1, previously outstanding)
- **OpenAI tool-calling** — confirmed live: `stream_with_tools()` correctly emits a `tool_call` event for `web_search` against the real API.
- **Anthropic tool-calling** — **deliberately left unverified.** `AnthropicProvider.supports_tools = True` is live in the code, so `research`-skill turns on `PROVIDER=anthropic` will hit the untested `_run_tools()` event-handling path in practice, not just in theory. Known and accepted, not an oversight — flagged in code comments and here so it can't quietly get lost.

### Open items
- Anthropic tool-call event names — verify with `PROVIDER=anthropic uv run python3 test_tool_call.py` whenever convenient.
- Runtime/sandbox tool — still just a documented future MCP-server attachment point, not built.