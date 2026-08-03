# loki — Chat System Spec

Covers the conversational agent's capabilities layer: skills, web search, model provider abstraction, memory search tool, and session/streaming behavior. Distinct from `tech-stack.md` (names the tools) and `memory-engine-spec.md` (memory system internals).

---

## 1. Skills

- A skill = a config file: system prompt + allowed tools + optional retrieval scope.
- Starter set: **writing**, **research**. Kept minimal at v1.
- Schema designed from the start to be the future user-extensible slot — no rearchitecture needed to let users define their own skills later; v1 just doesn't expose the authoring UI yet.

## 2. Web Search

- **Default**: self-hosted SearXNG instance. Free, aggregates multiple search engines, no per-query cost to the product — directly solves the token/session-burn pain of forcing search inside Claude/Gemini/ChatGPT.
- **Optional BYOK premium search**: user can plug in their own key for higher-quality results (e.g. Tavily/Brave/Exa-class providers) at their own cost.
- Search results are woven into context as retrieved evidence for the current turn — not stored as memory units themselves (same provenance-vs-fact distinction as attachments in the memory engine spec).

## 3. Model Provider Abstraction (BYOK)

- User selects: local model, or their own API key to a cloud provider (Claude, GPT, Gemini, etc.).
- Product never holds or pays for inference on the user's behalf.
- Abstraction layer should support adding new providers without touching core chat logic.

## 4. Memory Search Tool (agent-facing)

- The agent gets a **narrow, read-only search tool** over the memory store — functionally grep/ripgrep-style exact and pattern matching over the plain-text memory files — exposed as a scoped function call, **not general shell/CLI access**.
- Purpose: complements semantic HEAD retrieval (`memory-engine-spec.md §6`) with precise recall — "what exactly did I say about X," or locating a specific past commit for time-travel queries.
- **Hard constraints**: read-only, hard-scoped to the memory directory, no write or execute capability beyond search. This exists specifically to prevent memory content (user-authored text fed back to the model) from becoming a prompt-injection vector into arbitrary command execution.

## 5. Streaming / Session Behavior

- **Phase 0**: SSE for one-directional token streaming from the model provider to the client.
- **Planned**: webhooks, once the product needs event-driven/bidirectional behavior (e.g. live merge-conflict prompts surfaced outside an active request, integrations).
