# projectX — Session Architecture Outbound

Covers everything built this session at the architecture/systems level — concurrency,
storage, redundancy, time complexity, retrieval, structural cleanup — mapped against
`master-spec.md`, `memory-engine-spec.md`, `chat-system-spec.md`, `ledger-spec.md`, and
`spec-compliance-audit.md`. Deliberate deviations from those specs are noted as such,
not treated as defects. Closes with the graph/PPR check requested, and the forward plan
for Phase 3/4 and the 10x roadmap.

---

## 1. Concurrency

| Change | Where | What it replaced |
|---|---|---|
| Skill-selection + search-decision run concurrently | `chat_engine.py` | Two independent LLM classifications of the same message, previously sequential — neither's output feeds the other |
| Per-branch memory state fetch (`known`) runs concurrently | `chat_engine.py` | Sequential `for b in allowed_branches: fetch_state(b)` loop |
| Per-branch relevance fetch (`injected`) runs concurrently | `chat_engine.py` | Same sequential pattern; results reassembled in `allowed_branches` order (not completion order) to keep dedup attribution deterministic across runs |
| Tool calls within one agentic round run concurrently | `agentic_search.py` | Sequential tool-by-tool execution inside the loop. Two-phase design: repeat-detection classified sequentially first (cheap, no I/O — also catches same-round duplicates), then only genuinely-new calls dispatch via a thread pool; results reassembled in the model's original call order |
| Capture/conflict/forget/summarization deferred past `"done"` (summarization only) | `chat_engine.py` | Summarization ran inline, blocking the SSE stream close. Now fires on a daemon thread after `"done"` — no live activity card exists for it, so nothing visible depends on ordering. Capture/conflict/forget were evaluated for the same treatment and deliberately **not** deferred — those have live activity cards; deferring them would mean reload-only visibility, a real UX regression, not just a perf tradeoff |

**Structural unification:** the three independent hand-rolled "background asyncio event loop on a thread" implementations (`providers/*.py`, `mcp_client.py`, `extraction.py`) were consolidated into one shared `background_loop.py` helper, used by `mcp_client.py` and `extraction.py`. Provider files were deliberately left on their own `threading.Thread` + `queue.Queue` pattern — they wrap synchronous SDK calls with no async work to bridge to; forcing them onto the shared helper would add an event loop to run a blocking call inside it. This consolidation surfaced and fixed a real pre-existing bug: `MCPClient.close()` was exiting an anyio cancel scope from a different asyncio Task than opened it, latent since the file was first written, only triggered once `close()` was actually exercised standalone.

---

## 2. Storage & Retrieval (memory-engine, Rust)

| Change | Mechanism | Complexity impact |
|---|---|---|
| Checkpointed state resolution | `state_at()` now stops at the nearest saved checkpoint instead of always replaying from genesis; a checkpoint is written every `CHECKPOINT_INTERVAL` (20) commits if none exists in range | State resolution's worst case is now bounded by the checkpoint interval, not total history length. Without this, cost grows without bound as a personal store does what it's meant to do — accumulate history over months/years |
| Verify-on-read | `get_object()` re-hashes bytes read from a hash-addressed path and rejects a mismatch | Closes a real gap: content-addressing without verification is a guarantee in name only. Catches disk corruption, partial writes from a crash, or tampering that previously would silently deserialize |
| Per-branch persisted BM25 index (tantivy) | New `bm25.rs`; one index per branch, incrementally updated inside `commit()`, not rebuilt from scratch per query | Adds exact/rare-term matching (names, invented terms) as a third retrieval signal alongside dense similarity — verified directly: an invented compound term ("Nightjar-Vorlax-9") scored 0.996 post-rerank where dense-only ranking would likely have missed it before the reranker's top-50 cutoff ever saw it |
| `fetch_state` result caching (Python side) | `memory.py`, TTL + explicit invalidation on all four real write paths (`commit`, `supersede`, `forget`, `merge.apply`) | Removes redundant full-store fetches on every turn when nothing changed. `merge.preview` deliberately does **not** invalidate — it's read-only |
| `retrieval_traces` table pruning | `db.py`, bounded `DELETE ... NOT IN (... LIMIT 20)` on write | Was unbounded growth, pure debug data with no functional dependency on old rows |
| Centralized memory-engine HTTP client | New `memory_client.py`; replaces 5 independent `httpx` call sites (`memory.py`, `capture.py`, `merge.py`, `mcp_server.py`) with one pooled client | Real connection reuse instead of a fresh connection per call; unified the three previously-inconsistent timeout values (20s/10s/5s) to one 20s default, matching the value two of the five call sites had already independently settled on for the same reason (tolerating a cold engine load) |

**Evaluated, deliberately not built:** a Prolly-tree-backed storage layer (`prollytree` crate — confirmed to exist, built by the same author as a comparable competitor product, Memoir). Assessed as a real, lower-friction option than initially estimated, but a genuine architecture swap under live data, warranting its own dedicated evaluation spike rather than a same-session addition. Checkpointing was chosen as the right-sized version of the same underlying principle (avoid full-history replay) for this product's actual scale.

---

## 3. Redundancy Removed

- `capture.py`'s CAPTURE_PROMPT scope, twice: once for assistant-self-identity ("who are you" / "who created you" family) being miscaptured as a user fact, and again structurally via the new verification pass (§5).
- Duplicate-content commits (`chat_engine.py`'s verbatim-equality check against `known`, holding across the whole session).
- `fixed_search.py` — the entire non-agentic search pipeline retired outright once `agentic_search.py`'s redundancy tracking made the cheap/capable routing split unnecessary; every search now converges on one path.
- Provider harness duplication — `_run`/`_attempt`/retry/deadline logic was ~90% identical between `OpenAIProvider` and `AnthropicProvider`; extracted into `providers/_harness.py` (`run_worker`, `with_retry`), used by all three providers. `LocalProvider` deliberately kept its original single-attempt (no retry) behavior — the refactor deduplicated existing behavior, it didn't add new retry semantics to a provider that never had them.

---

## 4. Correctness Fixes Found Via Testing (not perf/structure, but load-bearing)

- **Forget-pipeline trigger words** — two separate root causes, both found via live testing: (1) `FORGET_TRIGGER_WORDS` used exact multi-word phrases (`"drop memory"`) that failed on any natural phrasing with a word in between; fixed to single-word stems. (2) `mentions_forgetting()`'s absence in the forget-context branch caused the model to falsely promise a confirmation prompt that would never render on a no-match turn; fixed with an explicit negative-case system message.
- **Capture verification pass** — a genuine TRUSTMEM-motivated fix, not a prompt patch: `extract_units` now runs a second, narrow verification call per candidate fact ("is this genuinely about the user, not the assistant, not already known") before returning anything to the caller. Structural, not enumerative — closes the "who created you" family and any future phrasing in the same category without needing a new exclusion bullet each time. Tested against 10 cases (7 assistant-self-identity variants, 3 legitimate captures) — all passed; 6 of 7 negative cases were caught by extraction itself, 1 required the verify stage, confirming the second pass is a necessary backstop, not redundant with stage one.
- **Citation numbering gap** — `web_search` results were previously uncitable (only `web_fetch` was numbered); fixed by having `web_search` return structured JSON instead of preformatted text, enabling per-result numbering in the same citation space as fetched pages.
- **Universal time-injection** — `Provider.stream()`/`stream_with_tools()`/`complete_json()` now inject current datetime via a shared `_with_time()` wrapper in `base.py`, reaching every call site automatically rather than requiring each of six-plus call sites to remember it individually. Verified to directly fix a real ambiguity bug (a "last weekend" query previously took 4-8 search rounds to disambiguate; post-fix, 2 rounds).

---

## 5. Mapping Against the Specs

### 5.1 Gaps from `spec-compliance-audit.md` closed this session

| Gap (audit §) | Status now |
|---|---|
| No natural-language "remember X" / "forget X" commands (§1.1) | **Closed.** Full three-stage forget pipeline (pattern generation → deterministic search → confirmation), wired into `chat_engine.py`'s activity/PENDING_FORGETS flow |
| Memory Search Tool, agent-facing (§1.1) | **Closed.** `memory_search` MCP tool, exact/regex recall, read-only, scoped to current branch state |
| No caching on HEAD retrieval (§2, known gap) | **Closed**, via checkpointing (§2 above) — not literal caching as originally implied, but the same complexity problem the gap named |
| "Semantic similarity" was BM25-only, not true semantic (§1.3) | **Superseded twice over.** First replaced with dense (bge-base-en) + cross-encoder rerank; this session added BM25 back as a *third*, complementary signal (exact/rare-term matching) rather than the sole mechanism — the current pipeline is dense + BM25 + rerank, closer to the spec's actual intent than either prior state |

### 5.2 Gaps from the audit still open, unchanged this session

- Local model support — built, still not verified against a real local server.
- Anthropic provider — still untested against a real key; `supports_tools = False` remains a deliberate gate, not a bug.
- Hard-delete — **partially closed**: `purge_object` exists and is wired to a real `/purge` endpoint, tested live tonight (confirmed genuinely removed from disk, not just soft-forgotten). The audit's "no object file is ever actually deleted" claim is now out of date.
- "Why do you think that about me" — no dedicated handling.
- Provider switching still requires env-var change + restart, not live in-app.
- Merge conflict resolution UI — still the only spec gap that was consciously deferred as a decision, not overlooked; unchanged.
- Hypothetical-exploration branches — unbuilt.
- Time-travel queries — unbuilt.
- Retrieval doesn't numerically downweight inferred units in scoring (cosmetic "(uncertain)" label only) — unchanged.
- Ledger UI — still curl-inspectable only.
- `PENDING`/`PENDING_FORGETS` — still in-process only, lost on backend restart before resolution.

### 5.3 Deliberate deviations from spec introduced this session (not defects)

- **`master-spec.md §3 Do`** ("keep git-style vocabulary out of the user-facing product") — the new Memory panel Timeline view surfaces commit-level history (branch, timestamp, change kind) directly to the user, framed in plain language ("Remembered"/"Changed"/"Forgot") rather than git terms, but it is structurally closer to exposing the commit graph than the spec's original "just remember/forget, no visible mechanism" framing anticipated. Judged a deliberate, considered exception — this is the actual differentiator (legible, auditable memory) the spec's own §1.4.1 names as a goal, expressed as UI rather than vocabulary.
- **`memory-engine-spec.md §7`** (content-addressable storage) — now additionally includes a persisted BM25 index per branch and a checkpoint layer, both new on-disk structures the spec didn't originally describe. Consistent with the spec's storage philosophy (plain, local, inspectable files), not a violation of it.

---

## 6. Graph / PPR Check

Searched exhaustively (`grep` across every file in the project knowledge base, plus targeted searches for HippoRAG, GraphRAG, PageRank, and PPR specifically): **no reference to a graph-based or PageRank-based retrieval architecture exists anywhere in the actual spec documents.** The only "knowledge graph" mention in the entire project is tonight's own `self-learning-roadmap.md`, in the context of explicitly rejecting an RL proposal that assumed one existed.

Most likely origin: this came up during tonight's competitive research discussion (Zep's temporal knowledge graph, or general awareness of graph+PPR techniques like HippoRAG for multi-hop retrieval) — a real, substantive idea from that conversation, but never actually written into a spec file as a planned item. Worth deciding now whether it should be formally added as a Phase 3 candidate or left as a rejected/deferred idea, rather than continuing to half-remember it as "in the spec somewhere."

If evaluated on its merits: a graph+PPR layer is the more rigorous version of exactly the "atomic facts can't capture connected information" problem identified earlier this session (the reason Phase 3 exists at all). It's a legitimate candidate *for* Phase 3's design, not a separate missed item — see §8.

---

## 7. What's Genuinely Solid (carried forward from the audit, still true)

Unchanged from `spec-compliance-audit.md §3`, and reinforced, not undermined, by this session's work: the core differentiator — versioned, branchable, auditable, user-owned memory with real conflict resolution — remains fully built and now additionally hardened (verify-on-read, checkpointing, hybrid retrieval, capture verification) rather than just functionally complete. This was refinement and trust-hardening on a solid foundation, not foundational rework.

---

## 8. Remaining Work

### 8.1 On the road to 10x (from tonight's roadmap discussion)
- **Phase 1 (trustworthy foundation)** — effectively closed. Capture verification pass, the one open item, is now built and tested (§4).
- **Phase 2 (legibility/trust UX)** — closed. Timeline/branch graph view and BM25 hybrid retrieval both built and verified.
- **Phase 3 (second memory subsystem)** — not started. Now reframed, per tonight's closing discussion, as memory built to *drive real action* (protocol-level dispatch — SMTP/CalDAV, not screen control), not narrowly "research/planning storage." Graph+PPR-style retrieval (§6) is a legitimate design candidate for this phase, not a separate missed item.
- **Phase 4 (structured eval)** — not started. No repeatable way yet to know if a future change helped or quietly hurt, beyond manual spot-testing.

### 8.2 Smaller, real, not yet actioned
- `writing` skill's `memory_search` access — still an open, undecided question.
- `main.py`'s deprecated `@app.on_event("shutdown")` — cosmetic, low priority.
- Query decomposition and result re-ranking — real, smaller-scope items, tactical rather than 10x-critical.
- Local + Anthropic provider verification — both still genuinely untested, not just deprioritized.

### 8.3 Explicit direction for next session (Phase 3)
Design, not build, first. Per tonight's closing discussion: the felt 10x is memory that *drives* action (follow-through, not just recall), protocol-native dispatch (SMTP/CalDAV — no screen automation, no per-app connector sprawl), and the existing confirm-before-act trust pattern extended from memory conflicts into real-world dispatch. This reframes Phase 3's scope from "a subsystem for research notes" to "the memory-to-action bridge" — worth designing deliberately with this frame in hand, not the narrower one Phase 3 started with.
