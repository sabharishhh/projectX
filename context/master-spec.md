# loki — Master Spec

*Working name: loki. Final product name deferred.*

---

## 1. Product Overview

### 1.1 Problem Statement
- **Memory poisoning / staleness**: Existing AI memory (ChatGPT, Gemini, Claude) silently stores outdated or incorrect facts and quietly distorts future answers, with no visible audit trail for the user.
- **Trust / privacy**: Users don't know what's being stored about them, can't verify it, and often don't want a vendor holding a profile of their life at all.
- **Gatekeeping**: Core AI capabilities (memory, extended thinking, certain tools) are locked behind subscription tiers.
- **Session/token burn**: Forcing web search inside tools like Claude or ChatGPT eats disproportionate session/token budget, sometimes exhausting the user's usage window.
- **No ownership**: Memory lives in a vendor's opaque database — not inspectable, not portable, not truly the user's.

### 1.2 Target User
Privacy-conscious, tech-adjacent early adopters capable of self-hosting or comfortable with a slightly more technical setup (the r/selfhosted, r/LocalLLaMA, r/privacy audience) — not enterprises, not agent/developer-infra builders, not mainstream consumers at v1. Mainstream reach is a possible later expansion, not the initial bet.

### 1.3 Positioning
Not competing with mem0/Supermemory (developer memory APIs) or GCC/Contexa/Puppyone/Omnigraph (agent/coding-task memory infra) or native ChatGPT/Claude/Gemini memory (opaque, vendor-held, feature-gated). loki is the first **personal, individual-facing** AI assistant with memory that is versioned, auditable, and fully user-owned — delivered through natural conversation, not through git-style commands.

### 1.4 Core Differentiators
1. **Auditable, correctable memory presented as a UX benefit, not an architecture the user has to operate.** No commits/branches/merges exposed as vocabulary — just "remember this," "forget that," and "why do you think that about me."
2. **BYOK / model-agnostic.** Local model or the user's own API key to any provider — never the product paying for and metering inference.
3. **Free and not feature-gated.** No paywall on core capabilities.
4. **Built-in web search that doesn't burn the user's own AI session/token budget** (self-hosted SearXNG default).
5. **Small, extensible skill system**, starting minimal, designed to grow.

---

## 2. Tech Stack

### 2.1 Finalized (Phase 0)

| Layer | Choice | Why |
|---|---|---|
| Chat backend | Python / FastAPI | Fastest to iterate; best LLM SDK coverage across providers; easiest interop path into the Rust memory engine later (PyO3 or a thin service boundary) |
| Frontend | Svelte | Lighter and faster than React with strong DX; good fit for an open-source project's contributor experience |
| Chat history persistence | SQLite | Zero setup, file-based, portable, sufficient for single-user/early-stage |
| Streaming transport | SSE | Simplest one-directional token streaming; matches how LLM providers already stream |
| Memory engine | Rust | Genuine performance need — content-addressable hashing, diffing, embedding/similarity search are CPU-bound work, unlike the chat backend |
| Web search | SearXNG (self-hosted, default) + optional BYOK premium search APIs | Free, no per-query cost to the product, solves the token/session-burn pain directly |
| Skills | Config-file based (system prompt + allowed tools + retrieval scope) | Cheap to ship a few now, becomes the user-extensible slot later with no rearchitecture |
| Model access | BYOK — local model or user's own API key | Keeps "free" sustainable; product never carries inference cost |

### 2.2 Planned, Not Yet Built
- **Webhooks** — needed once the product supports bidirectional/event-driven behavior (e.g. live merge-conflict prompts, integrations). SSE is sufficient for Phase 0's one-way token streaming.

### 2.3 Deferred Decisions
- **Porting the chat backend to Rust.** Not a performance decision (the backend is I/O-bound, waiting on LLM APIs — Rust wouldn't meaningfully speed this up). The real justification would be single-binary distribution and one-codebase maintainability for self-hosted, non-technical users. Revisit once the product has real shape and usage signal — not before.
- **Image/PDF ingestion into the memory engine.** Storage layer is designed to support binary attachments (content-addressable blobs), but extraction (vision/OCR at capture time) is out of scope for the first build. See `memory-engine-spec.md §5`.

---

## 3. Product Principles (Do's and Don'ts)

### Do
- Auto-capture low-stakes facts silently, the way existing tools do — this is baseline, not differentiation.
- Surface a plain-language check-in when new information conflicts with an existing memory unit, before overwriting it.
- Expose memory control only through natural language: "remember X," "forget X," "why do you think that about me."
- Distinguish **soft-forget** (retired, recoverable, kept in history) from **hard-delete** (actually purged) as separate, explicit user actions.
- Keep git-style vocabulary (commit, branch, merge, HEAD) entirely out of the user-facing product — it's an implementation detail.
- Infer context separation (work vs. personal) automatically; never make the user manage "branches" by name.
- Store memory as plain, local, content-addressable files — the user should always be able to leave with their data intact.
- Log every state-changing action to the product-wide ledger (see `ledger-spec.md`).

### Don't
- Never silently overwrite a memory unit that contradicts an existing one — always check in on genuine conflicts.
- Never let an LLM auto-resolve a memory conflict without the user's explicit choice.
- Never gate core features (memory, search, model selection) behind a paywall.
- Never charge a platform fee on top of BYOK — the user's own provider costs are the only cost they bear.
- Never give the agent unrestricted shell/CLI execution — tool access to memory search must be a narrow, read-only, hard-scoped function, not a general command line (see `chat-system-spec.md §4`).
- Never treat a raw attachment (image, PDF) as a memory unit itself — it's a source, not a fact (see `memory-engine-spec.md §5`).
