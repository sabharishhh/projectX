# loki — Product Document

*A personal AI assistant whose memory is versioned, auditable, correctable, and
fully owned by the user. Self-hosted, BYOK, free, not feature-gated.*

Working name: **loki**. Final product name deferred.
This document describes the product **as actually built** as of commit `d2e4b7e`
(branch `commitments`, v0.21.0+). Where the code and the specs disagree, the code
wins and the divergence is noted.

---

## 1. The Product

### 1.1 One-sentence version

A chat assistant that remembers you the way a careful person would — it tells you
what it learned, asks before overwriting something it already believed, lets you
take a fact back, and keeps a full history you can inspect or walk away with.

### 1.2 The problems it exists to solve

| Problem | How loki answers it |
|---|---|
| **Memory poisoning / staleness.** ChatGPT/Claude/Gemini silently store outdated or wrong facts and quietly distort later answers, with no audit trail. | Every fact is a versioned unit. Contradictions are surfaced as a conversational choice, never auto-resolved. Nothing is overwritten — old versions are superseded and stay readable. |
| **Trust / privacy.** Users can't see what's stored, can't verify it, and often don't want a vendor holding a profile of their life. | The store is plain, local, content-addressable files. A live Memory panel shows everything known plus the full commit timeline. |
| **Gatekeeping.** Memory, extended thinking, and tools sit behind subscription tiers. | Nothing is gated. No paywall on any core capability. |
| **Session/token burn.** Forcing web search inside a hosted assistant eats the user's usage window. | Self-hosted SearXNG by default; search results are distilled before reaching the main context window. The product never pays for or meters inference. |
| **No ownership.** Memory lives in a vendor's opaque database. | Git-object-style local store. The user can inspect, back up, or export it independently of the app. |

### 1.3 Target user

Privacy-conscious, tech-adjacent early adopters comfortable self-hosting — the
r/selfhosted, r/LocalLLaMA, r/privacy audience. **Not** enterprises, **not**
agent/developer-infra builders, **not** mainstream consumers at v1.

### 1.4 Positioning

Not competing with developer memory APIs (mem0, Supermemory), agent/coding-task
memory infra (GCC/Contexa, Puppyone, Omnigraph), or native vendor memory
(opaque, vendor-held, feature-gated). loki is the first **personal,
individual-facing** assistant with memory that is versioned, auditable, and
user-owned — delivered through **natural conversation**, not git commands.

### 1.5 The four differentiators

1. **Auditable, correctable memory as a UX benefit, not an architecture the user
   operates.** No commit/branch/merge vocabulary in the product — just "remember
   this," "forget that," "what did I used to think."
2. **BYOK / model-agnostic.** Local model or the user's own API key.
3. **Free and not feature-gated.**
4. **Built-in web search that doesn't burn the user's own token budget.**

Plus a small, extensible skill system designed to grow.

### 1.6 Product principles

**Do:** auto-capture low-stakes facts silently; surface plain-language check-ins
on genuine conflicts; expose memory control only through natural language;
distinguish soft-forget (recoverable) from hard-delete (purged) as separate
explicit actions; infer work/personal separation automatically; store memory as
plain local files; log every state-changing action to the ledger.

**Don't:** silently overwrite a contradicted fact; let an LLM auto-resolve a
conflict; gate core features; charge on top of BYOK; give the agent unrestricted
shell execution; treat a raw attachment as a memory unit (it's a source, not a
fact).

---

## 2. Architecture

Four processes, all local:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Svelte 5 frontend          :5173    vite dev server                 │
│  chat · activity strip · memory panel (Current + Timeline graph)     │
└────────────┬──────────────────────────────────┬──────────────────────┘
             │ SSE + REST                       │ direct reads
             │                                  │ (/branches /state
             ▼                                  │  /history /reset)
┌──────────────────────────────────────────┐    │
│  Python FastAPI backend      :8000       │    │
│  turn orchestration · LLM providers ·    │    │
│  capture · forget · commitments ·        │    │
│  skills · ledger · SQLite                │    │
└──────┬──────────────────┬────────────────┘    │
       │ httpx (pooled)   │ stdio MCP           │
       ▼                  ▼                     ▼
┌──────────────────────┐  ┌───────────────────────────────┐
│ Rust memory engine   │  │ MCP server (subprocess)       │
│ :8100 (axum)         │  │ web_search · web_fetch ·      │
│ store · commits ·    │  │ memory_search                 │
│ branches · dense +   │  └──────┬────────────────┬───────┘
│ BM25 + rerank        │         │                │
│ (bge-base-en,        │         ▼                ▼
│  bge-reranker-v2-m3, │   SearXNG :8888    crawl4ai/Chromium
│  tantivy, candle)    │   (Docker)         (shared instance)
└──────────────────────┘
```

### 2.1 Why each choice

| Layer | Choice | Rationale |
|---|---|---|
| Chat backend | Python / FastAPI | Fastest iteration; best multi-provider LLM SDK coverage |
| Frontend | Svelte 5 (runes) | Lighter/faster than React, good contributor DX |
| Chat persistence | SQLite (`backend/loki.db`) | Zero setup, file-based, portable, single-user |
| Streaming | SSE | Simplest one-directional token streaming |
| Memory engine | Rust | Genuine CPU-bound work — hashing, diffing, embedding, reranking |
| Embeddings/rerank | `candle` (in-process, CPU) | No Python ML runtime, no external inference service |
| BM25 | `tantivy`, per-branch persisted index | Exact/rare-term matching, incrementally updated |
| Web search | SearXNG self-hosted; BYOK Tavily/Exa optional | Free, no per-query cost |
| Skills | TOML config files | Cheap now, user-extensible slot later, no rearchitecture |
| Tool transport | MCP over stdio | Reserves the same slot for future sandboxed tools |

### 2.2 Size

| Component | Lines |
|---|---|
| Rust memory engine (`memory-engine/src/`) | ~1,830 |
| Python backend (`backend/`, incl. eval) | ~3,860 |
| Svelte frontend (`frontend/src/`) | ~2,230 |
| **Total** | **~7,900** |

75 commits, versioned v0.1 → v0.21.0. Nine feature branches
(`main`, `commitments`, `memory-engine`, `retrieval-v2`, `skills`, `time_travel`,
`async-work`, `frontend-redesign`, `ui-polish`).

### 2.3 Deferred architectural decisions

- **Rust port of the chat backend.** Not a performance question (it's I/O-bound).
  The real justification would be single-binary distribution for non-technical
  self-hosters. Revisit when distribution friction is the actual bottleneck.
- **Prolly-tree storage** (`prollytree` crate — same author as competitor
  Memoir). Assessed as a genuine option, but a storage swap under live data
  warrants its own spike. Checkpointing was chosen as the right-sized version of
  the same principle (don't replay from genesis).
- **Attachments (image/PDF) as memory sources.** Storage layer is blob-capable
  by design; vision/OCR extraction is out of scope for v1.

---

## 3. The Memory Model

This is the core of the product. All git vocabulary here is **internal** — never
surfaced as vocabulary to the user.

### 3.1 Memory Unit — the atomic fact

`memory-engine/src/unit.rs`

```rust
struct MemoryUnit {
    content: String,
    unit_type: UnitType,
    provenance: Provenance,     // stated | inferred
    source: String,             // conversation id that produced it
    created_at: DateTime<Utc>,
    deadline: Option<DateTime<Utc>>,          // commitment-only
    commitment_status: Option<CommitmentStatus>, // commitment-only
}
```

Six types:

| Type | Meaning |
|---|---|
| `identity` | Stable facts — role, background, location |
| `preference` | How they like things done — style, tools, tastes |
| `project` | Something ongoing — status, decisions, open questions |
| `decision` | A specific choice and its reasoning, timestamped |
| `relationship` | People/entities in their life |
| `commitment` | A real promise to do something later, with lifecycle |

**Provenance** splits `stated` (said outright) from `inferred` (read between the
lines). Inferred units are labelled `(uncertain)` in the injected context block
and rendered with a muted border in the UI.

**Commitment lifecycle** (`Open` → `Done` | `Cancelled`) rides along as two
optional fields on `MemoryUnit` rather than a separate struct — so the existing
store/commit/retrieval machinery needs no new code path for it.

### 3.2 Commit — a set of unit changes

`memory-engine/src/commit.rs`

A commit is **not** a snapshot. It records:

- `parent: Option<String>` — chains into real history
- `changes: Vec<UnitChange>` — `Added{hash}` | `Modified{from,to}` | `Superseded{hash}`
- `source` — the triggering conversation
- `summary` — **a plain-language semantic diff**, e.g. *"career goal changed from
  'stay in current role' to 'exploring founder path'"*

That plain-language summary is the primary UX differentiator over file/line
diffing systems. It's written for a human to read, and it's what the Timeline
view renders.

`Superseded` is soft-forget: retired from HEAD, kept in history, recoverable.
`Modified` keeps both versions — `from` stays readable, just no longer current.

### 3.3 Branch — an isolated context line

A branch is one HEAD pointer file at `refs/<branch>`, all sharing one object
store. Two intended uses:

1. **Domain separation** — `work` vs `personal`, so context doesn't bleed.
2. **Hypothetical exploration** — a line of thinking developed without
   contaminating main. **Not built.**

Branches are **inferred and managed by the system**, never created or named by
the user. Names are validated against path traversal (`valid_branch_name`:
alphanumeric + `-` + `_`, ≤64 chars).

**Important implementation nuance:** branches turned out to be a *write*-routing
mechanism, not a read-scoping one. Reads scan **every** branch every turn
(`_fetch_known`, `_fetch_relevant` in `chat_engine.py`) — relevance scoring, not
folder-style filtering, decides what gets used. This was a deliberate fix: domain
classification guessing wrong used to make whole categories of real memory
invisible for a turn.

### 3.4 Storage layout

```
memory-engine/memory-store/
├── objects/<first-2-hex>/<rest-of-hash>       # SHA-256 content-addressed JSON
│                        /<rest-of-hash>.emb   # cached 768-dim f32 embedding
├── refs/<branch>                              # HEAD pointer per branch
├── checkpoints/<commit-hash>                  # resolved live-hash list
└── bm25/<branch>/                             # tantivy index per branch
```

Content-addressable and git-object style: identical content hashes to one object,
so dedup is structural. **Verify-on-read** (`get_object`) re-hashes bytes read
from a hash-addressed path and rejects a mismatch — content-addressing without
verification is a guarantee in name only; this catches disk corruption, partial
writes from a crash, and tampering.

**Checkpointing** bounds state resolution. `state_at()` walks back toward genesis
but stops at the first checkpoint it finds; `commit()` opportunistically writes a
fresh checkpoint every `CHECKPOINT_INTERVAL = 20` commits. Without it,
`state_at()` replays the *entire* history on every call — cost growing without
bound as a personal store does exactly what it's meant to do: accumulate years of
history.

### 3.5 HEAD resolution

`state_at(commit)` walks parent pointers backward (stopping at a checkpoint),
then replays forward applying each change: `Added` appends, `Modified` removes
`from` and appends `to`, `Superseded` removes. The result is always current
state — never a stale superseded version, even if that version would score well
semantically.

`state_at_time(branch, target)` is the time-travel primitive: walk back from HEAD
to the latest commit at or before `target`, then delegate to `state_at`. It
returns the **actual commit timestamp used** alongside the state, because
`target` snaps to the nearest real commit — a caller asking "as of March 15"
needs to know the answer is really "as of the last change before that date," not
be handed false precision.

---

## 4. Retrieval — Three Signals + a Floor

`memory-engine/src/retrieval.rs`, `bm25.rs`, `embedding.rs`, `reranker.rs`,
orchestrated in `main.rs::retrieve`.

The pipeline for one `/retrieve` call:

```
current_state(branch)
   │
   ├─ partition ──► identity + preference  ──► PINNED, always injected,
   │                                            sentinel score 1000.0, no scoring
   └─ everything else
        │
        ├─ dense:  cosine(query_emb, cached unit_emb)     bge-base-en-v1.5, CLS pool, L2-norm
        ├─ bm25:   tantivy per-branch index               normalized against this set's own max
        │
        ├─ blend:  relevance = max(dense,0) + bm25_norm*0.5          ← additive, not multiplicative
        │          score     = (relevance + recency*0.2)
        │                      * type_priority * skill_boost
        │            recency  = exp(-days/30)
        │            priority = 1.3 decision if query mentions "decide/decision"
        │                       1.3 project  if "working on"/"project"
        │                       1.1 preference
        │            boost    = 1.4 if unit_type in the active skill's boost_types
        │
        ├─ take top DENSE_POOL_K = 50
        ├─ cross-encoder rerank: bge-reranker-v2-m3, joint (query,doc) attention,
        │                        sigmoid to [0,1], per-pair (not batched)
        ├─ filter MIN_RERANK_SCORE = 0.1
        └─ take (max_units - pinned_count)
```

**Design notes worth keeping:**

- **Dense and BM25 combine additively, before the multipliers.** Either signal
  alone should be enough to surface a unit. A fact BM25 matches exactly but dense
  ranks poorly (an exact name phrased very differently from the query) must not
  be suppressed because one signal missed it.
- **BM25 is normalized against the result set's own max** before blending. Raw
  BM25 is unbounded and on a totally different scale from cosine (0–1); blending
  it unnormalized would let it either dominate or vanish depending on the query.
- **The relevance floor matters more than it sounds.** Without it, a query with
  nothing relevant still fills every context slot with noise. With it, an
  irrelevant query returns *only* pinned facts.
- **`Retrievable` trait** generalizes dense ranking away from `MemoryUnit`, so
  conversation turns or documents can plug into the same scoring later without
  duplicating it. Type priority/recency/boost stay `MemoryUnit`-specific.
- **Embeddings are computed once at write time** (`/remember`, `/supersede`) and
  cached as `.emb` sidecar files — content is immutable once hashed, so they
  never need recomputing. A missing embedding degrades to BM25 rather than
  panicking.
- **BGE asymmetry is respected:** queries get the instruction prefix
  (`"Represent this sentence for searching relevant passages: "`), stored
  documents don't. Mixing this up silently degrades relevance.
- **Models warm up at boot** in `main()` before the listener binds, so the first
  real query doesn't pay cold-load cost.

**Tuning honesty:** `MIN_RERANK_SCORE = 0.1`, the `0.5` BM25 weight, the `0.2`
recency weight, and the 30-day decay constant are **unvalidated starting
guesses**. Observed so far: relevant facts score 0.15–0.59 post-rerank, clearly
irrelevant ones 0.0001–0.03.

### 4.1 Retrieval history

Worth recording because each step was a real bug fix, not a refactor:

1. Naive keyword overlap → **false matches on common words** ("the" matched
   unrelated facts).
2. → BM25 + English stemming. IDF downweights common words with no hand-
   maintained stopword list.
3. **The BM25 fix broke a working case:** "what am I working on?" stopped finding
   a project fact with zero shared words. Fixed by letting intent-type matching
   count as its own path past the relevance floor.
4. → Dense (bge-base-en) + cross-encoder rerank; BM25 dropped after a confirmed
   stopword-collision bug ranked an unrelated fact #1.
5. **Dense candidate pool was collapsed to output width** (16). Fixed: dense
   surfaces top-50, reranker cuts to the requested count.
6. → BM25 reintroduced as a *third, complementary* signal for exact/rare terms,
   not the sole mechanism. Verified directly: an invented compound term
   (`Nightjar-Vorlax-9`) scores 0.996 post-rerank where dense-only ranking would
   likely have missed the reranker's cutoff entirely.
7. **Cross-branch merging was alphabetical concatenation with a hard cap of 12** —
   a relevant fact on a later branch could be silently excluded by an earlier
   branch filling the cap. Fixed to merge-and-sort by actual score.

---

## 5. The Turn Lifecycle

`backend/chat_engine.py::stream_chat` — a generator yielding SSE frames. This is
the single most important control-flow path in the product.

```
load history, save user message
   │
   ├─ _classify(message)                    ← 2 LLM calls, CONCURRENT
   │    skill selection  ‖  search decision   (independent; neither reads the other)
   │    search_decision discarded if the resolved skill disallows web_search
   │    either failing degrades to "no skill, no search" — never crashes the turn
   │
   ├─ allowed_branches = {main} ∪ CANONICAL_DOMAINS ∪ existing branches
   ├─ detect_time_travel_query(message)     ← trigger-word prefilter, then 1 LLM call
   ├─ _fetch_known(branches)                ← concurrent /state per branch, cached 10s
   ├─ detect_forget_request(...)            ← 3 stages: pattern → regex search → confirm
   ├─ _fetch_due_commitments(branches)      ← concurrent, deterministic, no LLM
   │
   ├─ IF time-travel:  injected = historical state (REPLACES normal injection)
   │  ELSE:            injected = _fetch_relevant(...)  ← concurrent /retrieve per branch,
   │                                                       merged and sorted by score, top 12
   ├─ save_retrieval_trace(...)             ← debug introspection, bounded to last 20
   │
   ├─ _build_conversation(...)
   │    [system: identity + judgment guidance + forget capability + skill prompt + known facts]
   │    [system: rolling summary, if any]
   │    [system: forget context, if any]
   │    [system: due commitments, if any]
   │    + last 12 messages + this message
   │
   ├─ yield activity: skill / time_travel | memory_read / commitments_due
   │
   ├─ _generate_reply(...)                  ← THE MAIN LLM CALL
   │    agentic_search.run() if provider supports tools AND any tool applies
   │    else plain provider.stream()
   │    on error: yield error, ABORT ENTIRE TURN (no capture, no persist, no "done")
   │
   ├─ _process_capture(...)                 ← 1 extract call + 1 verify call PER candidate
   │    skipped entirely if this was a forget-matched turn
   │    verbatim duplicate → duplicate_skipped
   │    contradiction      → PENDING conflict, yields conflict card
   │    otherwise          → commit, yields memory_write card
   │
   ├─ _process_forgets(...)                 ← PENDING_FORGETS, yields forget_request card
   │    skips anything capture already surfaced as a conflict (no double-prompting)
   │
   ├─ _process_commitment_resolutions(...)  ← deterministic candidates + 1 bounded LLM judgment
   │                                          skips the LLM call entirely if nothing is open
   ├─ persist message + activity, write chat log
   ├─ yield "done"
   └─ summarization on a daemon thread      ← deferred PAST "done"
```

### 5.1 Ordering decisions that are load-bearing

- **Forget detection runs *before* capture.** Capture can't honor its own "don't
  create a unit describing a forget request" rule if it runs first without
  knowing the message is one. Skipping capture entirely on a forget-matched turn
  is the deterministic fix; relying on the model to self-censor was not.
- **An error in reply generation aborts the whole turn.** Not just the reply —
  capture, conflicts, forgets, persistence, and `"done"` are all skipped. This is
  covered by a dedicated eval case using monkeypatching, not hope.
- **Only summarization is deferred past `"done"`.** It has no live activity card,
  so nothing visible depends on it finishing before the stream closes.
  Capture/conflict/forget were evaluated for the same treatment and deliberately
  **not** deferred — they have live cards, so deferring would mean reload-only
  visibility: a real UX regression, not just a perf tradeoff.
- **Concurrent fetches are reassembled in `allowed_branches` order, not
  completion order.** When the same hash appears on multiple branches, `seen`
  lets only the first through — and "first" must mean deterministic branch order,
  or which branch a duplicate is credited to would vary between runs.
- **`known` spans every branch; `injected` is scored.** These are two different
  jobs that once shared one variable — which caused a real double-commit bug (a
  fact already on `work` was invisible during a dedup check, so it committed
  twice).

### 5.2 LLM call budget per turn

| Call | When |
|---|---|
| Skill selection | every turn (concurrent with next) |
| Search decision | every turn (concurrent with previous) |
| Time-travel detection | only if a trigger word is present |
| Forget pattern generation | only if a trigger word is present |
| Forget confirmation | only if the regex search found candidates |
| **Main reply** | every turn (1–6 rounds if agentic) |
| Capture extraction | every turn except forget-matched |
| Capture verification | **once per candidate fact** |
| Commitment resolution | only if something is open |
| Summarization | only when ≥6 messages have aged past the window |
| Page distillation | per page, if search fired |

Roughly **3 calls on a quiet turn**, and comfortably **10+** on a turn that
searches, captures three facts, and resolves a commitment. The skill selector and
search-decision classifier do similar "should I do X" work on the same message
and are the natural candidate to merge into one routing call.

Cost control: only the main reply uses `MAIN_REASONING_EFFORT`; every background
call stays at the cheap `"none"` default and uses `CAPTURE_MODEL`.

---

## 6. Feature Subsystems

### 6.1 Capture — silent fact extraction

`backend/capture.py`

Two-stage, and the second stage is the point:

1. **`extract_units`** — one structured-output call producing candidate facts,
   each with content, type, provenance, summary, target branch, optional
   `supersedes` (8-char hash of a contradicted known fact), optional `deadline`.
2. **`_verify_unit`** — a **second, narrow call per candidate**: "is this
   genuinely new, durable information *about the user*?" **Fails closed** — any
   error rejects the candidate rather than committing something unverified.

The verify pass is structural, not enumerative. It closes the whole
"assistant-self-identity" family ("who created you?" being captured as a fact
about the user) without needing a new exclusion bullet for each phrasing.
Tested against 10 cases: 6 of 7 negatives were caught by extraction itself, 1
required the verify stage — confirming it's a necessary backstop, not redundant.

The capture prompt carries hard-won specifics:
- **Explicit "remember that X" is an unconditional instruction**, not a judgment
  call, even if the content seems borderline or task-like.
- **Multiple distinct actions with one trailing deadline split into separate
  commitments**, each inheriting that deadline — "I'll text Jamie about the venue
  and confirm the caterer by Thursday" is two commitments, not one fused blob.
- **Excluded:** questions asked, topics merely discussed, transient state,
  anything about the assistant, hypotheticals ("I would follow up if…"),
  past-tense reflections ("I should have…"), vague intentions, and inferences
  already made before (checked semantically, not by exact wording).

### 6.2 Conflict resolution — never silent

When a candidate carries `supersedes` matching a known fact, no write happens.
Instead it lands in the in-process `PENDING` dict and surfaces as a
`ConflictBlock` card:

> **This changes something I already knew**
> ~~was: prefers short answers~~
> now: prefers detailed answers
> [ Replace it ] [ Both are true ] [ Ignore this ]

`POST /api/memory/resolve` maps these to `supersede` / `commit` / no-op, logs to
the ledger with `actor="user"`, and patches the stored message's activity so a
reload shows the resolution instead of re-prompting.

The supersede lands on **the target's own branch**, not the incoming fact's.

The spec calls for a fourth option ("defer, leave flagged open"); three are
built. `PENDING` is in-process only — a backend restart expires unresolved
conflicts, handled gracefully in the UI ("This one expired when the backend
restarted. Tell me again and I'll store it.") but not durable.

### 6.3 Forgetting — three stages, deterministic in the middle

`backend/forgetting.py`

1. **Trigger-word prefilter** — `forget`, `remove`, `delete`, `erase`,
   `unremember`, `no longer`, `drop`, … Cheap; most turns never pay for a call.
2. **Pattern generation** (LLM) — writes a *regex* for what the user seems to
   want forgotten, reasoning about words that would appear in matching facts, not
   just the literal words used. Returns `confident: false` rather than guessing.
3. **Deterministic execution** — the regex runs in Rust via `/search` against
   live HEAD state. **Grounded in real matches, not model recall.**
4. **Confirmation** (LLM) — narrows the actual matches down to real intent. Fails
   closed: if confirmation breaks, show nothing rather than everything.

Then a `ForgetBlock` card offers three genuinely different actions:

| Choice | Effect |
|---|---|
| **Forget it** | Soft-forget — `Superseded` commit. Drops from HEAD, stays in history, recoverable. |
| **Delete permanently** | Soft-forget **then** `purge_object` — the object file is genuinely removed from disk. |
| **Keep it** | No-op, logged. |

Per `ledger-spec §4`, a hard-delete still leaves a ledger entry recording *that*
it happened — `"permanently deleted a personal-branch fact"` — without retaining
the content.

Two real bugs fixed here, both found by live testing:
- `FORGET_TRIGGER_WORDS` used multi-word phrases (`"drop memory"`) that failed on
  any natural phrasing with a word between them. Fixed to single-word stems.
- On a no-match turn, the model would falsely promise a confirmation prompt that
  never rendered. Fixed with an explicit negative-case system message
  (`_build_forget_context`'s second branch).

### 6.4 Commitments — memory that follows through

The newest subsystem, and the one that moves memory from recall toward action.

- **Capture** extracts a commitment with a resolved concrete deadline (relative
  phrasing like "next week" resolved against injected current time).
- **Surfacing** — `find_due_commitments(branch, within_hours=48)` is a purely
  deterministic Rust filter. Due items are injected as a system-stated fact the
  model may weave in naturally: *"If one is naturally relevant to this exchange,
  you may mention it — don't force it into an unrelated conversation, and don't
  recite the whole list mechanically."*
- **Resolution** — deterministic candidate gathering (every open commitment,
  deadline irrelevant) followed by **one bounded LLM judgment** over that
  pre-narrowed set. Skips the call entirely at zero cost when nothing is open.
  Mirrors the forget pipeline's pattern-then-confirm shape exactly.
- **Marking done** supersedes the unit with the same content under a new status —
  the same versioning model everything else uses. The `open` version stays in
  history.

The resolution prompt is unusually specific because stress-testing kept breaking
it. Three failure modes are now explicitly guarded and eval-covered:

- Same entity, **different task** must not resolve. *"I emailed the landlord
  about a leaky faucet"* does **not** resolve *"email the landlord about the
  lease renewal."*
- A **new** commitment about the same person must not cancel an unrelated older
  one.
- Similar-sounding action, different subject must not match.

### 6.5 Time travel — a separate, explicit mode

`backend/time_travel.py`

Deliberately separate from normal injection per spec §6.6: when it fires,
historical state **replaces** the normal injected block rather than blending with
it, so stale context can never leak into an ordinary answer.

Trigger-word prefilter (`used to`, `back then`, `as of`, `what did I think`, …),
then one classification call resolving relative phrasing to a concrete ISO
datetime. Two guards:

- Retrospective intent with no anchor ("what did I used to think") must still
  resolve a best-effort target (~6 months back). **Never** return
  `time_travel: true` with a null target.
- Present-tense intent must not misfire — *"what's my job"* wants the current
  answer even though the answer references the past.

The UI shows `Looking back to <date>` where the date is the **earliest actually
resolved commit timestamp** across branches, not the requested target.

### 6.6 Merge — engine primitives, no product surface

`memory-engine/src/main.rs` (`/merge/preview`, `/merge/apply`) +
`backend/merge.py`.

`preview` diffs live-on-source against live-on-target. Semantic conflict
detection is layered in Python — an LLM compares two branches' facts for genuine
contradictions, not word overlap. `apply` lands as a **single commit**; adopted
units become `Added`, resolved conflicts become `Modified`. Nothing is deleted.

**This is the largest gap against spec.** The spec calls for silent auto-merge on
clean additions as ordinary background behavior. In reality merge only ever runs
when `/api/merge/preview` and `/api/merge/apply` are called manually — there is
no UI, no automatic reconciliation, and branches accumulate indefinitely.

### 6.7 Skills

`backend/skills.py` + `backend/skills/*.toml`

A skill is a config file: `name`, `description`, `system_prompt`, `tools`,
`boost_types`. Loaded at import; a malformed file is skipped, not fatal. One
cheap LLM call selects at most one skill per turn (most turns select none).

Two shipped:

| Skill | Tools | Boosts | Purpose |
|---|---|---|---|
| `writing` | *(none — blocks web search entirely)* | `preference`, `identity` | Drafting/editing prose. Draft first, discussion after. Preserve the author's phrasing where it works. |
| `sleuth` | `web_search`, `web_fetch`, `memory_search` | `project`, `decision` | Research, fact-finding, precise recall. Accuracy over completeness; cite what supports what; say when sources disagree. |

An active skill does three things at once: injects its system prompt, **gates
tool access** (`writing` blocks search even on a researchy-sounding topic), and
**biases retrieval scoring** toward relevant unit types (×1.4). All three compose
correctly with memory injection in the same turn.

The TOML schema is deliberately the future user-authoring slot; v1 just doesn't
expose the authoring UI.

> **Note:** the specs and status docs refer to a `research` skill. The actual file
> is `sleuth.toml`. Also, `backend/skills/wafinder_skill.md` is an unrelated
> Claude Code skill sitting in this directory — the loader only globs `*.toml`,
> so it's inert, but it doesn't belong here.

### 6.8 Web search — the agentic loop

`backend/agentic_search.py`, `mcp_server.py`, `mcp_client.py`, `search.py`,
`extraction.py`

All search converges on one agentic path. The older fixed
discover→distill pipeline (`fixed_search.py`) was retired outright once
redundancy tracking made the cheap/capable routing split unnecessary.

**Discovery:** SearXNG (default, free, self-hosted) with BYOK Tavily/Exa as
optional premium alternatives. Returns `[]` on any failure — never fatal.

**Extraction:** crawl4ai behind a `_CrawlerManager` singleton — one
`AsyncWebCrawler`, one background event loop, shared across every call. This
replaced a per-call Chromium cold start (~0.5–1s each), which mattered
increasingly once one turn could fetch up to 5 pages. Failures are split by kind:
a routine page-level failure (404, bad URL) is handled internally by crawl4ai and
does **not** respawn; only a genuine crawler-level failure (timeout, exception)
triggers `_respawn()`.

**The loop** (`MAX_TOOL_ITERATIONS = 5`), two phases per round:

1. **Sequential repeat classification** — cheap, no I/O. A genuinely-new call
   *claims its cache slot immediately, before its result comes back*. This is
   what catches a duplicate issued later in the **same** round — run
   concurrently, two identical calls would both see an empty cache and both go
   out for real.
2. **Concurrent I/O** — only genuinely-new calls dispatch via a thread pool.
   Workers touch **no** shared state.

Results are then walked in the model's **original call order**, not completion
order, so citation numbers and activity events stay deterministic.

**Stall detection:** if every call in a round is a repeat, the model has run out
of new ground — synthesis is forced immediately rather than burning to the
iteration cap. The cap remains as a backstop for the case where every round finds
genuinely new but unhelpful things to try.

**Citations:** one numbering space keyed by URL, shared by `web_search` and
`web_fetch` — a result that's searched and later fetched keeps its original
number. The citation-discipline instruction is specific: cite each claim with the
sources that support *it*, don't pile numbers onto a broad summary sentence,
phrase snippet-only claims more cautiously than fetched-page ones, and never
`[n]`-cite a `memory_search` result (it's the user's own memory, not a web
source).

### 6.9 The agent-facing memory tool

`memory_search(pattern, branch)` via MCP → Rust `/search` → `search_state()`:
regex match over **live HEAD state only**. Read-only, hard-scoped to the memory
directory, no write or execute capability. Superseded/forgotten units are
deliberately excluded — same privacy boundary as everything else the agent reads.

This constraint exists specifically to stop memory content (user-authored text
fed back to the model) from becoming a prompt-injection vector into arbitrary
command execution. **Never** general shell access.

Bundling three tools into one MCP server is a deployment choice, not a loosening
of any individual tool's constraints. Going through MCP rather than a bespoke
interface reserves the same slot for a future sandboxed runtime tool without
rearchitecture — just another MCP server.

### 6.10 The ledger — product-wide audit trail

`backend/ledger.py`. Distinct from the memory engine's commit history: the engine
tracks memory *state*; the ledger tracks *everything worth auditing*.

Schema: `event_type`, `description`, `source` (conversation), `actor`
(`user` | `system`), `created_at`. **Append-only** — never updated, never deleted
from. That's what makes it trustworthy.

Event types actually logged: `provider_call`, `memory_commit`, `conflict_raised`,
`conflict_resolved`, `forget_requested`, `memory_forgotten`, `memory_purged`,
`forget_cancelled`, `commitment_resolved`, `skill_invoked`, `search_call`,
`merge_preview`, `merge_applied`, `conversation_cleared`, `classify_failed`.

Real, working, and exposed at `GET /api/ledger` — but **no UI surface**. It's
curl-inspectable only. The spec calls for eventual "what has this app done"
views.

### 6.11 Conversation windowing

`backend/summarization.py`. Sending unbounded history every turn was replaced by
a 12-message visible window plus a rolling summary. `maybe_update_summary` folds
in messages that have aged past the window, but only once ≥6 have accumulated
(`TRIGGER_BUFFER`) — so it's a cheap no-op with no LLM call most turns. On
failure it keeps the old summary rather than losing it.

### 6.12 Caching and pruning

- **`fetch_state` cache** — 10s TTL per branch, plus explicit invalidation on all
  four real write paths (`commit`, `supersede`, `forget`, `merge.apply`).
  `merge.preview` deliberately does **not** invalidate — it's read-only.
- **`fetch_state_at_time` is deliberately not cached** — a rare explicit-intent
  mode, not a hot path.
- **`retrieval_traces` pruning** — bounded `DELETE … NOT IN (… LIMIT 20)` on
  write. Pure debug data, nothing depends on old rows, and this needed no new
  scheduler infrastructure.
- **One pooled memory-engine client** (`memory_client.py`) replaced 5 independent
  `httpx` call sites with 3 inconsistent timeouts (20s/10s/5s), unified to 20s —
  matching what two call sites had already independently settled on to tolerate
  a cold engine load.

---

## 7. Provider Abstraction (BYOK)

`backend/providers/`

```
Provider (ABC)
├── stream()             → _do_stream()             ← every provider
├── stream_with_tools()  → _do_stream_with_tools()  ← gated on supports_tools
└── complete_json()      → _do_complete_json()      ← gated on supports_structured_output
```

The public methods are thin concrete wrappers that inject current-time context
via `_with_time()` before delegating. **This is the one place time-awareness
lives** — every call through this class, present and future, gets it
automatically, rather than six-plus call sites each remembering to add it. That
change directly fixed a real ambiguity bug: a "last weekend" query previously
took 4–8 search rounds to disambiguate; post-fix, 2.

Callers must check `provider.supports_structured_output`, **not**
`hasattr(provider, "complete_json")` — the method now exists on every provider,
it just raises when unsupported. (An earlier version required `complete_json` on
all providers while only OpenAI implemented it, which would have crashed the
others at instantiation.)

| Provider | Tools | Structured output | Status |
|---|---|---|---|
| `OpenAIProvider` | ✅ | ✅ | **Working, tested live.** `responses.create` streaming. |
| `AnthropicProvider` | ❌ gated off | ❌ | **Broken.** Calls `client.responses.create` — that's OpenAI's API shape, not Anthropic's Messages API. Dormant under `PROVIDER=openai`. |
| `LocalProvider` | ❌ | ❌ | **Built, never verified against a real server.** Any OpenAI-compatible `/v1/chat/completions` endpoint — Ollama, LM Studio, vLLM. Fails fast at startup with a clear message if unreachable. |

**Shared harness** (`_harness.py`): `run_worker` runs the blocking SDK call on a
background thread and reads a queue against a hard 90s wall-clock deadline
enforced by our own code — so even an unforeseeable hang can't wait forever.
`with_retry` retries once, but **only if nothing has been yielded yet** — once
partial output has streamed to the user, retrying would duplicate or garble it,
so a later failure always raises.

`LocalProvider` deliberately keeps single-attempt behavior (180s deadline, no
retry). The refactor deduplicated existing behavior; adding retry to a provider
that never had it would be a real decision, not a cleanup side effect.

**All provider HTTP is forced to IPv4** (`local_address="0.0.0.0"`). This was the
resolution to a genuinely hard bug — see §11.

---

## 8. Frontend

Svelte 5 (runes: `$state`, `$derived`, `$props`, `$effect`), Vite, no framework
beyond that.

### 8.1 Layout

Three-column CSS grid: `ConversationSidebar` (220px, collapsible) | chat |
`MemoryPanel` (drag-resizable 260–640px, width persisted to `localStorage`).
Both side panels slide on the x-axis with `cubicOut`.

### 8.2 Chat

- **Composer** is a CodeMirror 6 editor with markdown syntax highlighting, live
  spellcheck/autocorrect, custom highlighting (list marks rendered as accent
  dots, code fences hidden), and `Enter` to send / `Shift+Enter` for newline via
  a `Prec.highest` keymap.
- **Rendering** is `marked` with GFM: proper lists, tables, headings, blockquotes,
  and `highlight.js` code blocks with a language label and working copy button.
- **Citations** are a custom `marked` inline extension: `[1]` becomes a
  superscript link with a hover preview card, safely tokenized so it doesn't
  break bold/italic parsing.
- Typing indicator while `processing`; `latestText` tracks the CodeMirror doc so
  Enter-to-send and button-send agree.

### 8.3 The activity strip — "show your work"

Typed SSE events render as expandable cards under each assistant message, colour-
coded by kind: verdigris for memory, blue for search, amber for attention, grey
for skills.

| Event kind | Rendering |
|---|---|
| `memory_read` | "Recalled N facts" → expandable unit list |
| `memory_write` | "Remembered N things" → expandable unit list |
| `time_travel` | "Looking back to \<date\>" → historical units |
| `commitments_due` | "N commitments coming due" |
| `conflict` | `ConflictBlock` — three-way choice |
| `forget_request` | `ForgetBlock` — soft / hard / keep |
| `commitment_resolved` | "Done: \<content\>" |
| `tool_step` | Grouped into one collapsible "Searching…" block with sub-steps |
| `source` | Hidden from the strip; feeds citation previews |
| `duplicate_skipped` | Logged, not surfaced |
| `search_failed` | Amber warning line |

Transient states (`skill`, `searching`) are **actively scrubbed** the moment
concrete text or a real result arrives. Without that, the "Searching…" placeholder
sat on screen forever next to its own result.

### 8.4 The Memory panel

Two views.

**Current** — every live fact across all branches, deduped by hash, grouped by
type in `identity → preference → project → decision → relationship → commitment`
order. Inferred facts get a muted left border. Commitments show `due <date>`
instead of a hash. Resolved commitments are filtered out. No branch UI is exposed
anywhere.

**Timeline** — a hand-rolled SVG-less commit graph. One column per branch, nodes
by time, palette-cycled colours, circles for facts and **diamonds for
commitments**. Hover shows `Remembered/Changed/Forgot — <plain-language summary>`;
click opens a detail card with branch, timestamp, per-change list, and source.

Tooltip edge-collision is resolved by **measuring the node against the actual
scroll container at hover time**, not a static x-vs-width check — whether a node
is "near an edge" depends on current scroll offset, which a CSS-only rule can't
know.

The panel is honest about its own limits, in the UI itself:

> *"Each column is a branch, arranged by time. Branches don't currently record
> where they forked from — this shows parallel history, not merges between them."*

**This view is a deliberate, considered deviation from `master-spec §3`** ("keep
git-style vocabulary out of the user-facing product"). It's framed in plain
language, but it is structurally closer to exposing the commit graph than the
spec anticipated. Judged worth it: legible, auditable memory *is* the
differentiator the spec's own §1.4.1 names as the goal — expressed as UI rather
than vocabulary.

### 8.5 Design system

`lib/styles/tokens.css` — a two-layer token system: a raw palette
(`--ink-900`, `--verdigris`, `--amber`, `--azure`, `--danger`) that components
never read directly, and semantic tokens (`--surface-page`, `--text-primary`,
`--accent-memory`, `--border-hairline`) that they do.

Field-notebook aesthetic: graph-paper background, verdigris accents, JetBrains
Mono for technical/system text, Instrument Sans for prose. Full dark mode via
`[data-mode='dark']`; three alternate themes (`slate`, `warm`, `mono`) defined in
`themes.css`.

Motion is centralized in `lib/motion.js` with `reveal` and `arrive` transitions,
and every duration passes through `dur()`, which returns 0 under
`prefers-reduced-motion` — enforced in both JS and CSS.

---

## 9. API Surface

### 9.1 Rust memory engine — `127.0.0.1:8100`

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/branches` | Every branch with ≥1 commit |
| GET | `/state?branch=` | Live HEAD units |
| POST | `/remember` | New unit + embedding + `Added` commit |
| POST | `/supersede` | New unit + embedding + `Modified` commit |
| POST | `/forget` | `Superseded` commit (soft-forget) |
| POST | `/retrieve` | Scored retrieval — pinned + dense + BM25 + rerank |
| GET | `/search?pattern=&branch=` | Regex match over live state |
| GET | `/history?branch=` | Full commit chain with per-change unit types |
| POST | `/state-at-time` | Historical state + actual resolved timestamp |
| GET | `/commitments/open?branch=` | All open commitments |
| GET | `/commitments/due?branch=&within=` | Open commitments due by a time |
| GET | `/merge/preview?from=&into=` | Incoming vs. existing diff |
| POST | `/merge/apply` | Merge as one commit |
| POST | `/purge` | Hard-delete an object from disk |
| POST | `/reset` | **Dev only** — wipes every branch |

Permissive CORS (the frontend reads `/branches`, `/state`, `/history`, `/reset`
directly).

### 9.2 Python backend — `127.0.0.1:8000`

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| POST | `/api/chat` | **The turn.** SSE stream. |
| GET | `/api/messages/{id}` | Load a conversation |
| DELETE | `/api/messages/{id}` | Clear a conversation |
| GET | `/api/conversations` | Conversation list with labels |
| GET | `/api/ledger?limit=` | Audit trail (no UI yet) |
| GET | `/api/retrieval-trace/{id}` | Per-branch scores and merge decisions |
| POST | `/api/memory/resolve` | Conflict → update / keep_both / keep_old |
| POST | `/api/memory/forget` | Forget → soft / hard / cancel |
| GET | `/api/merge/preview` | Preview + semantic conflict detection |
| POST | `/api/merge/apply` | Apply a merge |

CORS is restricted to `http://localhost:5173`.

### 9.3 SSE frame types

`{"type": "text", "value": "…"}` · `{"type": "activity", "event": {…}}` ·
`{"type": "error", "message": "…"}` · `{"type": "done"}`

`"done"` is always last on a successful turn. On an error, `"error"` is last and
**no** `"done"` follows — the eval suite asserts exactly this.

---

## 10. Configuration & Running

### 10.1 Environment (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDER` | `openai` | `openai` \| `anthropic` \| `local` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | BYOK |
| `MODEL` | per-provider | Main chat model. **Required** for `local`. |
| `CAPTURE_MODEL` | `gpt-5.4-mini` | Cheap background calls |
| `REASONING_EFFORT` | `low` | Main reply only |
| `LOCAL_BASE_URL` | `http://localhost:11434/v1` | Ollama/LM Studio/vLLM |
| `MEMORY_URL` | `http://127.0.0.1:8100` | Rust engine |
| `MEMORY_ROOT` | `./memory-store` | Store location (Rust) |
| `SEARXNG_URL` | `http://localhost:8888` | Self-hosted search |
| `SEARCH_PROVIDER` | `searxng` | `searxng` \| `tavily` \| `exa` |
| `TAVILY_API_KEY` / `EXA_API_KEY` | — | Optional BYOK premium search |
| `CHAT_LOG_DIR` | `logs/chats` | Per-conversation markdown logs |

### 10.2 Running

```bash
# memory engine (downloads bge-base-en + bge-reranker-v2-m3 on first run)
cd memory-engine && cargo run

# backend
cd backend && uv run uvicorn main:app --reload

# frontend
cd frontend && npm run dev

# search
docker start searxng
docker update --restart unless-stopped searxng   # so it can't silently die again

# one-time
playwright install chromium
```

Boot order matters loosely: the backend fires a warmup `/retrieve` at import and
starts the crawler; the engine warms both models before binding its listener.

---

## 11. Engineering History — Problems Actually Hit

Recorded because the causes were non-obvious and the fixes are load-bearing.

### 11.1 One slow chat turn froze the entire server

`/api/chat` was declared `async def` while every call inside it (httpx memory
fetches, capture, provider streaming) was **synchronous and never awaited**.
FastAPI runs `async def` routes directly on the shared event loop, so a blocking
sync call inside one never yields — it stalled the *whole server*, including
unrelated requests like `/health`, for the full duration of the turn.

Found by the integration suite: isolated tests passed, but the full suite reliably
hung on `ReadTimeout` once enough sequential turns had run. Confirmed directly —
`curl /health` during an in-flight turn took seconds instead of ~5ms.

**Fix: `async def chat(...)` → `def chat(...)`.** A plain FastAPI route runs in a
background thread pool. Full-suite runtime dropped from ~450s to ~90s, 0 timeouts
across three consecutive runs.

### 11.2 Intermittent stalls that worsened over time, then "fixed themselves"

Several plausible explanations were chased in turn — a stuck connection, LLM
timeouts set too low, too many sequential calls per turn — each real to some
degree, none explaining the full pattern: fine for a while, then hanging,
sometimes recovering only after a full restart.

**Actual root cause:** an intermittent stall on the machine's **IPv6 network
path** (likely worsened by the private DNS resolver in use), which only reliably
surfaced under a rapid burst of outbound calls — exactly what a test suite
produces in seconds and one-message-at-a-time typing almost never does.

Fixed in three layers:
1. Force IPv4 (`httpx.HTTPTransport(local_address="0.0.0.0")`) — verified with a
   30-call burst test that failed reliably before and passed cleanly twice after.
2. A hard 90s wall-clock deadline enforced by our own code around every provider
   call, running the actual call on a background thread.
3. One automatic retry for a clean pre-stream failure.

### 11.3 Search silently stopped working

The SearXNG Docker container had simply stopped. Every downstream failure was
swallowed by bare `except: return None/[]` with no logging, so nothing showed
*why*. Hours went to red herrings (bot-blocking, timing) before the trivial cause
surfaced. Two genuine bugs were found *along the way* and are still fixed:

- The Playwright fallback waited for `networkidle` — which modern
  ad/tracker-heavy sites rarely reach — so it usually just timed out. Switched to
  `domcontentloaded` + a short fixed pause.
- One site returned `net::ERR_HTTP2_PROTOCOL_ERROR`, a bot-detection signature at
  the protocol level. Disabling HTTP/2 on browser launch routed around it.

**Fix:** restarted the container with `--restart unless-stopped`, and added real
logging at every failure point in extraction and search.

### 11.4 A route vanished during a refactor

`main.py` had grown to ~500 lines doing five jobs. Splitting it into `db.py`,
`models.py`, `chat_engine.py`, and one router per concern accidentally dropped
`/api/ledger` from every new file. The test suite caught it immediately as a
clean 404.

### 11.5 The pattern worth naming

A large share of these share one root cause: **a failure happening silently**,
with no log line, turning a five-minute fix into a multi-hour investigation.
Every fix from then on included adding real logging at the point of failure — not
just solving the immediate bug, but making the *next* one fast to diagnose.

The codebase now reflects this: `fetch_state`, `fetch_relevant`, `commit_unit`,
`supersede_unit`, `forget_unit`, `purge_unit`, `discover`, `extract_page`,
`extract_units`, `_verify_unit`, `detect_commitment_resolutions`,
`detect_time_travel_query`, `should_search`, and `log_turn` all log their
failures and degrade rather than raise. A memory, search, or capture failure
never crashes a turn — the assistant just proceeds without that capability.

---

## 12. Testing

### 12.1 Rust unit tests — 13, `memory-engine/src/lib.rs`

Dedup to one object, distinct content → distinct hash, commit chaining, HEAD-is-
none-before-first-commit, state reflects modifications not stale versions,
superseded units drop from state but stay readable, branch isolation, branch
listing, purge genuinely removes from disk, embedder output shape + L2
normalization, reranker ordering, unsafe branch name rejection.

`cargo test`

### 12.2 Python eval suite — 37 cases, `backend/eval/`

A lightweight `@case(id, category, description)` registry. A case returns
`True`/`False` or `(passed, detail)`; an exception is a fail with traceback
captured, **never a crash of the suite**. Output is a per-category scorecard and
an exit code.

```bash
uv run python3 -m eval.run_evals              # all
uv run python3 -m eval.run_evals commitments  # one category
```

| Category | Cases | What it guards |
|---|---|---|
| `capture` | 14 | Assistant-identity rejection (7 separate phrasings, kept granular so a scorecard shows exactly which wording regresses), hypothetical/past-tense commitment rejection, explicit-remember capture, multi-commitment split, legitimate captures |
| `forgetting` | 8 | Broad pattern catches the cluster, excludes unrelated, trap-fact scoping (excluded from broad query but reachable when targeted), trigger-word stems, never-stated → no match |
| `time_travel` | 5 | Vague-date fallback resolves, surfaces the **old** fact, present-tense doesn't misfire, no-history is graceful |
| `commitments` | 3 | Same entity/different task must not resolve, genuine resolution still matches, new commitment about same person doesn't cancel an older one |
| `retrieval` | 3 | Invented exact term surfaces via BM25, outranks topically-similar distractors, dense path still works on paraphrases |
| `chat_engine` | 2 | Ordinary turn completes cleanly with `done` last; **a reply error aborts the entire turn** (verified by monkeypatching, not by hoping an API call fails) |
| `infra` | 2 | Cache invalidates on commit; a write to one branch doesn't leak into another |

Two design choices worth noting: eval cases use `uuid4`-suffixed branch names for
isolation, and the retrieval cases deliberately use an **invented compound term**
because dense embeddings carry ~no signal for a made-up word — if it still ranks
top-2, BM25 is provably doing the work.

### 12.3 What isn't covered

No load/concurrency testing since the async fix. No frontend tests. Merge has no
eval coverage. `LocalProvider` and `AnthropicProvider` have no coverage because
neither has ever run.

---

## 13. Current State

### 13.1 What's genuinely solid

Worth stating plainly so the gap list below doesn't read as the whole picture.

The core differentiator is **fully built and working end to end**: versioned,
branchable, auditable, user-owned memory with real conflict resolution and no
silent overwrites — including the harder pieces most comparable "AI memory" tools
don't attempt (branch inference, merge primitives, three-signal hybrid retrieval,
commitment lifecycle, time travel).

It's also been **hardened**, not merely completed: verify-on-read, checkpointed
state resolution, a second verification pass on capture, and fail-closed
behavior on every judgment call. The search pipeline does genuine multi-source
research with distillation and citation discipline, not snippet-pasting. Skills,
memory, and search compose correctly in the same turn. There is a real eval suite
so future changes can be measured rather than guessed at.

What remains is refinement and reach — not foundational work.

### 13.2 Open gaps

**High — a stated differentiator isn't backed by working code**

| Gap | Detail |
|---|---|
| **Merge never happens automatically** | Spec calls for silent auto-merge on clean additions. Primitives exist; nothing calls them outside manual endpoints. Branches accumulate with zero reconciliation. **The single largest structural gap.** |
| **Merge conflict UI** | `find_conflicts` genuinely computes semantic conflicts; nothing surfaces them for the spec'd four-way resolution. *(The one gap consciously deferred as a decision rather than overlooked.)* |
| **Anthropic provider is broken** | Calls `client.responses.create` — OpenAI's shape, not Anthropic's Messages API. `supports_tools = False` is a deliberate gate. Rewrite needed, not a smoke test. |
| **Local model support unverified** | Fully built, never run against a real server. "Local model" is named as a core differentiator repeatedly. |
| **Hypothetical-exploration branches** | Spec's second branch use case has no mechanism at all. |

**Medium**

| Gap | Detail |
|---|---|
| **"Why do you think that about me?"** | Named in `master-spec §1.4.1`. No feature looks up which commit/conversation produced a fact and surfaces it. The model may improvise something plausible; there's no designed capability. All the data exists (`source`, `/history`). |
| **Ledger has no UI** | Real, working, curl-only. |
| **Provider switching needs an env change + restart** | So the ledger's "provider/model switches" event type has nothing to log. |
| **Inferred units aren't numerically downweighted** | Spec says lower weight *in scoring*. Reality: a cosmetic `(uncertain)` label applied after retrieval. |
| **`PENDING` / `PENDING_FORGETS` are in-process** | A restart expires unresolved conflicts and forget requests. Handled gracefully in the UI; not durable. |
| **No rate limiting or cost visibility** | Nothing tracks or surfaces LLM calls per session — which matters a lot for a BYOK product where the user pays per call, especially given §5.2's budget. |
| **Attachments** | Blob-capable storage by design; no vision/OCR ingestion. |

**Low / deliberate**

- **The UI doesn't feel "personal" yet.** By design so far — built to be
  inspectable and testable (visible hashes, unit types, monospace everywhere),
  which is close to the opposite of warm and low-friction. The tension to hold:
  the audit/transparency features *are* the differentiator, so the fix isn't
  hiding them — it's making them feel like insight offered to you rather than
  debug output. Needs a real pass informed by genuine usage, not a guess now.
- **Capture consistency varies.** The same fact has been captured at meaningfully
  different specificity across runs ("has a mother they plan to see Friday when
  taking time off work" vs. just "has a mom"). Normal LLM variance; worth
  watching.
- **Mobile / narrow-width unchecked** — deprioritized pending the bigger visual
  redesign.
- **Retrieval constants are unvalidated guesses** (§4).
- **Two commit-adjacent gaps:** the BM25 index keeps a stale entry for a
  superseded unit's old hash (accepted, same gap as `purge_object`), and the
  Timeline graph can't show fork points because branches don't record where they
  diverged (surfaced honestly in the UI).

### 13.3 Concrete bugs found while writing this document

Not in any existing status doc. Verified against the code.

1. **`MAIN_REASONING_EFFORT` is inert.** `.env:17` sets
   `MAIN_REASONING_EFFORT=medium`, but `state.py:13` reads
   `os.getenv("REASONING_EFFORT", "low")`. The name doesn't match, so the setting
   is silently ignored and effort is always `low`. One-line fix either side.
2. **`CAPTURE_MODEL` is shadowed, breaking local mode.** `capture.py:6` imports
   the local-mode-aware value from `state.py`, then `capture.py:13` immediately
   overwrites it with `os.getenv("CAPTURE_MODEL", "gpt-5.4-mini")`. `state.py`
   goes to real trouble to avoid falling back to a cloud model name that won't
   exist on a local server — and this line undoes it. Delete line 13.
3. **`merge.py:find_conflicts` hardcodes `"gpt-5.4-mini"`** instead of using
   `CAPTURE_MODEL`, so it breaks under any non-OpenAI provider.
4. **`forgetting._generate_pattern` calls `provider.complete_json` without
   checking `supports_structured_output`.** It raises, gets caught, returns
   `None` — so forgetting silently fails entirely on any provider without
   structured output. Every other call site checks first.
5. **`branching.py` is dead code with a real bug.** `infer_domain` is never
   called and would crash if it were — it passes `(CAPTURE_MODEL, messages)` to
   `provider.stream(messages, model)`, arguments reversed. Only
   `CANONICAL_DOMAINS` is actually imported. Delete `DOMAIN_PROMPT` and
   `infer_domain`.
6. **`pyproject.toml` still declares `trafilatura` and `readability-lxml`** —
   both removed from the code when extraction moved to crawl4ai.
7. **`frontend/package.json` is missing four direct dependencies** that
   `App.svelte` imports: `@codemirror/state`, `@codemirror/language`,
   `@lezer/highlight`, and `svelte/easing`'s peer set. They resolve transitively
   today; a fresh install could break.
8. **`main.py` uses the deprecated `@app.on_event("shutdown")`** rather than a
   `lifespan` handler. Cosmetic, known.
9. **`backend/skills/wafinder_skill.md`** is an unrelated Claude Code skill file
   sitting in the product's skills directory. Inert (the loader globs `*.toml`)
   but misplaced.

---

## 14. Roadmap

### 14.1 Phase status

| Phase | Goal | Status |
|---|---|---|
| **1** | Trustworthy foundation — verification, dedup, structural cleanup | ✅ Closed |
| **2** | Legibility/trust UX — timeline view, hybrid retrieval | ✅ Closed |
| **3** | **The memory-to-action bridge** | Not started — design first |
| **4** | Structured eval | ✅ Built (37 cases); expand coverage |

### 14.2 Phase 3 — reframed

Originally scoped as "a second memory subsystem for research/planning/build
context." **Deliberately reframed** as memory built to *drive real action*:

- **Follow-through, not just recall.** The commitment subsystem is the first step
  of this; it currently surfaces and resolves but doesn't *act*.
- **Protocol-native dispatch** — SMTP/CalDAV. Explicitly **not** screen
  automation and **not** per-app connector sprawl.
- **The confirm-before-act trust pattern extended** from memory conflicts into
  real-world dispatch. This is the natural generalization of what
  `ConflictBlock` and `ForgetBlock` already establish, and it's the mechanism
  that makes an acting assistant trustworthy rather than alarming.

A **graph + Personalized-PageRank retrieval layer** (HippoRAG/Zep-style) is a
legitimate design candidate *for* this phase — it's the more rigorous version of
the "atomic facts can't capture connected information" problem that motivates
Phase 3 at all. It is **not** currently in any spec; an exhaustive search
confirmed the only mention anywhere is in the context of *rejecting* an RL
proposal that assumed a knowledge graph existed. Worth deciding formally rather
than half-remembering it as "in the spec somewhere."

### 14.3 Self-learning roadmap

**Prerequisite: finish Phase 3 first** — item 1 builds on the existing
preference/fact system, and Phase 3's data-shape decisions affect how corrections
get stored.

1. **Compiled correction enforcement — highest priority.** When the user gives an
   explicit behavioral correction ("always do X", "never do Y"), capture it as a
   distinct, *checkable rule* — not a passive preference sentence hoped to be
   noticed in context. Published research (Notre Dame/IBM) found the passive
   approach leaves the majority of corrections silently ignored later. Mechanism:
   a parallel extraction path in `capture.py`; each correction becomes a rule + an
   applicability condition; before final synthesis, a lightweight check asks
   whether the output satisfies all applicable active rules, forcing one more
   iteration with the violation stated — the same pattern as the existing
   forced-synthesis-on-stall in `agentic_search.py`.
2. **Lightweight procedural learning.** When a tool-use sequence shows a clear
   efficiency lesson, optionally save a "this worked better" note by widening
   `extract_units`' input to sometimes include the agentic trace. Reuse an
   existing `unit_type` rather than inventing one. **Explicitly not** building the
   dual-agent "teacher" architecture some research proposes — one added
   extraction path is enough at this scale.
3. **Agent-editable adaptive skill layer** — deprioritized; mostly covered by
   item 1. Non-negotiable constraint if ever built: never edit the user's
   hand-authored `.toml`; use a separate agent-only overlay file merged at load
   time.

**Deferred:** Just-In-Time RL / logit modulation (blocked until local models are
solid — cloud APIs don't expose logits); Self-Contrast parallel-stream reflection
(real technique, ~3× tokens — worth an optional explicit high-effort mode, never
a default); dynamic multi-agent topology.

**Rejected outright, don't revisit without new evidence:** conflict-resolution
RL, adaptive reranking, bandit routing, knowledge-graph pruning. Each requires
data volumes a single-user product will never generate, and one assumes a
knowledge graph this architecture doesn't have.

### 14.4 Suggested near-term ordering

1. The nine concrete bugs in §13.3 — mostly one-liners, several silently
   disabling real features.
2. Automatic merge — the biggest gap between "branches exist" and "branches
   behave like the mental model."
3. Rewrite `AnthropicProvider` against the real Messages API; verify
   `LocalProvider` against Ollama. Both are claimed differentiators.
4. "Why do you think that about me" — all the data already exists; this is a
   retrieval + presentation feature, and it's a named differentiator.
5. Ledger UI, and cost/call visibility alongside it.
6. Persist `PENDING`/`PENDING_FORGETS` to SQLite.
7. Merge the skill selector and search-decision classifier into one routing call.
8. Tune the retrieval constants against real usage.
9. The "personal" visual redesign — after real usage reveals what matters.
