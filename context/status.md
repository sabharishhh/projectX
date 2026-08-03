# loki — Project Status

*A personal, private AI assistant with versioned, auditable, git-like memory. Self-hosted, BYOK, free, not gatekept.*

---

## 1. What's Built

### 1.1 Memory Engine (Rust)
The core differentiator. Fully implemented and tested.

- **Memory units** — typed atomic facts (`identity`, `preference`, `project`, `decision`, `relationship`), each with content, provenance (`stated` vs `inferred`), timestamp, and source conversation.
- **Content-addressable storage** — git-object style, SHA-256 hashed, deduplicates naturally, plain files on disk.
- **Commits** — a set of unit changes (added/modified/superseded) with a plain-language semantic diff summary, chained via parent pointers into real history.
- **HEAD resolution** — replays commit history to produce the current live state; superseded units drop out of HEAD but stay readable in history (soft-forget).
- **Branches** — multiple isolated HEAD pointers (`refs/<branch>`) sharing one object store. Domain separation (work/personal) and hypothetical exploration, as specified. Branch names are validated/sanitized against path traversal.
- **Merge** — `preview` (diffs incoming vs. existing units) and `apply` (adopts clean units, resolves conflicts as `Modified` changes) as engine primitives. Semantic conflict detection layered on top in Python (an LLM compares two branches' facts for genuine contradictions, not just word overlap). Merge lands as a single commit, nothing is ever deleted.
- **Retrieval scoring** — real BM25 (not naive keyword overlap) with English stemming (`rust_stemmers`), a relevance floor (units must clear a minimum score, not just be "least irrelevant"), recency decay, type-priority boosting (e.g., a "what did I decide" query weights `decision` units higher), and an intent-match bypass so phrasing-based relevance (e.g. "what am I working on?") can rescue a unit even with zero literal word overlap.
- **HTTP service** (axum) exposing all of the above: `/remember`, `/supersede`, `/forget`, `/retrieve`, `/state`, `/history`, `/branches`, `/merge/preview`, `/merge/apply`, `/reset` (dev-only).
- **13 passing unit tests** covering dedup, commit chaining, state resolution, soft-forget, branch isolation, and branch name validation.

### 1.2 Chat System (Python/FastAPI + Svelte)
- SSE-streamed chat with a provider abstraction (`Provider` base class) — OpenAI wired and tested; Anthropic scaffolded but **untested** (see Deferred).
- SQLite-backed message persistence, single continuous conversation per browser (via a `localStorage`-persisted conversation ID), with a "+ new chat" action to start fresh.
- Typed SSE activity events (`memory_read`, `memory_write`, `conflict`, `skill`, `searching`, `search`, `search_failed`) rendered as an expandable strip under each assistant message, visually distinguished by kind (verdigris/dashed for memory, purple for skills, blue for search).
- Graceful degradation throughout — memory engine, search, or provider failures never crash a turn; the assistant just proceeds without that capability.

### 1.3 Memory Integration
- **Injection**: before each turn, memory is fetched (scored/budgeted via `/retrieve`) and woven into a system message. A small pinned set (identity/preference units) always loads regardless of query relevance.
- **Capture**: after each turn, an LLM call extracts durable facts from the exchange, deduplicating against everything already known, and per-fact assigning a branch (see 1.5).
- **Conflict resolution**: when a new fact contradicts an existing one, it's surfaced as a conversational choice (Replace it / Both are true / Ignore this) — never silently auto-resolved. Conflicts are held in an in-process pending store, keyed by ID.
- **Product-wide ledger**: append-only audit log (separate from the memory engine's own commit history) recording provider calls, memory commits, conflicts raised/resolved, skill invocations, search calls, merges, and conversation clears — with actor (user vs. system) attribution.

### 1.4 Deep Web Search
- **Discovery**: SearXNG (self-hosted, free, default) with BYOK Tavily/Exa as optional premium alternatives.
- **Extraction**: a three-tier fallback chain — Trafilatura → readability-lxml → Playwright (for JS-rendered or bot-defended pages) — each tier logging its own failures.
- **Distillation**: candidate pages are fetched and read in parallel, each summarized by a cheap LLM call focused on the specific query, before anything reaches the main context window (this is what keeps deep search from re-creating the token-burn problem it's meant to solve).
- **Decision gating**: a pre-turn classifier decides whether a message actually needs current web information, so ordinary questions never trigger a search.
- Full pipeline logging added (`extraction.py`, `search.py`) after a debugging session traced a search failure back through several real, independently-confirmed bugs (a Playwright `networkidle` timing issue, an HTTP/2 fingerprinting block) to its actual root cause (SearXNG's Docker container had stopped). The container now has `--restart unless-stopped` so this specific failure mode can't recur silently.

### 1.5 Skills
- TOML-based config files (`system_prompt`, `tools`, `boost_types`) — the schema is deliberately the future user-authoring slot, not exposed yet.
- Two starter skills: `writing`, `research`.
- A cheap LLM call selects at most one skill per turn (most turns select none).
- An active skill gates tool access (e.g., `writing` blocks web search even on a topic that sounds researchy) and biases retrieval scoring toward relevant unit types.

### 1.6 Branch Inference
- Fully automatic — no user-facing branch selector remains in the UI.
- Per-fact, not per-conversation: a single message can produce facts routed to different branches (e.g., "I told my manager I'm taking Friday off to see my mom" splits correctly).
- A domain classifier runs per-turn to decide which branches are relevant for *reading* (always `main`, plus a detected domain if the message is clearly work/personal).
- Capture separately decides, per extracted fact, which branch to *write* to, from a canonical list (`main`, `work`, `personal`, plus any custom branches already created) — never inventing new branch names.
- `known` (used for dedup/conflict-checking) deliberately spans *every* branch, while `injected` (what the model sees this turn) stays scoped to relevant branches — fixing a real double-commit bug found during testing.

### 1.7 UI
- Field-notebook aesthetic (graph paper, verdigris accents, JetBrains Mono for system/technical text, Instrument Sans for prose) — built for development legibility, not yet for the "personal assistant" feel the product ultimately wants (see Deferred/Improvements).
- Real markdown rendering (`marked`, GFM) — proper lists, numbered steps, headings, and boxed code blocks with a language label and working copy button. Previously a hand-rolled regex renderer that only understood fenced/inline code and bold.
- Aggregated memory panel (shows everything across all branches, no branch UI exposed) with a working show/hide toggle that actually resizes the layout.
- Componentized: `ActivityStrip`, `ConflictBlock`, `MemoryPanel` split out of the main `App.svelte`.

---

## 2. Deferred (Deliberately, With Reasoning)

| Item | Why deferred | Trigger to revisit |
|---|---|---|
| **Semantic embeddings for retrieval** | BM25+stemming solves everything actually tested so far; embeddings are a real future upgrade for true synonym/paraphrase matching ("database" ↔ "Postgres"), but adding them now means a new model, a schema change, and per-call latency/cost before there's evidence the heuristic is the bottleneck. | Real usage shows the assistant missing facts that share no words with a query but are obviously related. |
| **Self-writing, agent-executed skills** | A legitimate pattern (Voyager-style skill acquisition), but requires hardware-level sandboxing (microVM, e.g. Firecracker/gVisor) to run untrusted agent-written code safely — the industry-standard answer is a cloud sandbox service, which conflicts with the local-first/private positioning. Also directly reverses the "no unrestricted execution" principle deliberately set for the memory search tool. | A dedicated design pass on sandboxing strategy, likely far downstream. |
| **Anthropic provider — untested** | Code is written (system-prompt handling, message-list conversion) but never run — no API key available at the time. | Get a key, run the six-point test (ordinary message, memory recall, search-skill turn, capture call, provider switch back to OpenAI). Don't treat `PROVIDER=anthropic` as confirmed-working until then. |
| **Conversation list / multi-thread browsing** | "New chat" exists, but there's no way to browse back to a previous thread — each new chat is only reachable if you still have its ID. | Worth building once losing access to old threads becomes an actual annoyance in practice. |
| **Attachments (images, PDFs) as memory sources** | Storage layer is blob-capable by design, but extraction (vision/OCR) was explicitly out of scope for v1. | Real need for the assistant to read files, not just text. |
| **Query rewriting / hybrid dense+sparse retrieval / cross-encoder reranking** | Evaluated explicitly against this project's scale and found not worth it right now — each adds either a real model, training data, or an extra LLM call per turn, for gains that don't show up yet in a personal-scale memory store. | Same trigger as embeddings — evidence of retrieval genuinely failing. |
| **Rust port of the chat backend** | Not a performance decision (backend is I/O-bound). Real justification would be single-binary distribution for non-technical self-hosters. | Once the product is stable and distribution/onboarding friction becomes the actual bottleneck. |
| **Mobile / narrow-width UI check** | Explicitly deprioritized in favor of the bigger "personal" redesign — no point polishing a layout breakpoint before the whole visual language changes. | After the redesign, or if mobile use becomes a real near-term need. |

---

## 3. Known Gaps / Could Be Improved

- **The UI doesn't feel "personal" yet.** By design so far — it was built to be inspectable and testable (visible hashes, unit types, extraction methods, monospace everywhere), which is close to the opposite of warm/quiet/low-friction. This needs a real redesign pass once genuine usage reveals what actually matters, not a guess now. The tension to hold onto: the audit/transparency features are the actual differentiator, so the fix isn't hiding them — it's making them feel like insight offered to you rather than debug output.
- **Capture consistency varies.** The same underlying fact has been captured with meaningfully different specificity across runs (e.g., "has a mother they plan to see Friday when taking time off work" vs. just "has a mom"). Not a bug, just normal LLM variance — worth watching if it becomes a real quality issue.
- **A turn can now trigger up to ~4-5 LLM calls** (skill selection, domain classification, search decision, main response, capture — plus per-page distillation if search fires). The skill selector and search-decision classifier are doing similar "should I do X" work on the same message and are a natural candidate to merge into one routing call once the current split is validated as correct.
- **Silent failure was a recurring pattern** before this session's logging additions — `extraction.py` and `search.py` both had bare `except Exception: return None/[]` with no visibility, which is what turned a one-line container-restart fix into a multi-hour debugging chase. Worth auditing other modules (`branching.py`, `skills.py`, `capture.py`) for the same blind-spot pattern before they cause a similar hunt.
- **PENDING conflicts live in-process only** — a backend restart silently expires any unresolved conflict (handled gracefully in the UI now, but the state itself isn't durable). Worth moving to SQLite if this becomes a real annoyance.
- **No rate limiting or cost visibility** — nothing currently tracks or surfaces how many LLM calls a session is making, which matters for a BYOK product where the user is paying per call.
- **Ledger has no UI surface yet** — it's a real, working audit trail (`/api/ledger`), but only inspectable via curl right now. The spec calls for eventual "what has this app done" views.
- **HEAD retrieval doesn't cache** — `state_at`/`current_state` replay history from scratch on every call. Fine at current scale; the spec already flags caching as the fix once it matters.

---

## 4. What's Genuinely Solid

Worth naming plainly, since a status doc that's all gaps and deferrals undersells it: the core differentiator — versioned, branchable, auditable, user-controlled memory, with real conflict resolution and no silent overwrites — is fully built, tested, and working end to end, including the harder pieces (branch inference, merge, BM25 retrieval) that most comparable "AI memory" tools don't attempt. The deep search pipeline does genuine multi-source research with distillation, not snippet-pasting. Skills, memory, and search all compose correctly together (a skill can gate search, bias retrieval, and still respect memory injection in the same turn). That's a real, working product core — what remains is refinement, not foundational work.
