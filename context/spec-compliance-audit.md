# projectX — Spec Compliance Audit

Cross-checks the actual implementation against `master-spec.md`, `memory-engine-spec.md`, `chat-system-spec.md`, and `ledger-spec.md`, line by line. Companion to `projectX-status.md` (which covers build progress in general); this document is specifically about where the implementation matches, deviates from, or falls short of what the specs call for.

**Headline finding:** the core architecture — memory units, commits, HEAD resolution, branch isolation, content-addressable storage, skills, search — is solid and largely spec-compliant. But several things the specs describe as *core, load-bearing behavior* were never actually wired up, most notably: memory never merges automatically, and the natural-language "remember X" / "forget X" commands don't exist despite being named as *the* way memory control should work.

---

## 1. Gaps — Not Previously Documented

These were not mentioned in `projectX-status.md` or flagged as deliberate deferrals at any point in the build. Found only by re-reading the specs against the actual code.

### 1.1 High priority — core differentiators affected

| Gap | Spec reference | What's actually true |
|---|---|---|
| **No natural-language "remember X" / "forget X" commands** | `master-spec.md §1.4.1`, `§3 Do` | Auto-capture works silently. There is no command parsing that recognizes an explicit user request to forget something and calls the engine's `/forget` endpoint. That endpoint exists and was tested via curl, but nothing in the Python layer ever calls it — it's dead code from the product's point of view. |
| **Merge never happens automatically** *(resolved — see note)* | `memory-engine-spec.md §4` | `merge_preview`/`merge_apply` are still only invoked manually via their dedicated endpoints. However, tracing why this gap mattered surfaced the real underlying problem: reads were being scoped to a single guessed domain per turn (`read_branches = ["main"] if domain == "main" else ["main", domain]`), which silently hid whole categories of real, stored memory whenever the classifier guessed wrong or a question spanned domains — a user has no way to "remember" which branch something was said under, so this was a genuine recall failure, not a UX inconvenience. Auto-merging work/personal into `main` would have "fixed" this by destroying the domain-separation feature entirely — the wrong tool. **Actual fix:** reads now always scan every branch (`known`/`injected` both iterate `allowed_branches` unconditionally); domain classification remains write-side only, routing new facts to `main`/`work`/`personal` but no longer gating what can be read back. This resolves the practical symptom the spec's auto-merge requirement was aimed at. True automatic merge — reconciling a genuinely temporary branch (e.g. hypothetical-exploration, see below) back into its origin — remains unbuilt, but is now understood to be a narrower, separate concern from the recall-gap this entry originally described. |
| **No local model support** | `master-spec.md §1.4.2`, `chat-system-spec.md §3` | BYOK exists for cloud providers only (OpenAI tested, Anthropic scaffolded/untested). "Local model" is named as a core differentiator repeatedly in the specs; no Ollama/llama.cpp or equivalent path was ever built. |
| **Memory Search Tool (agent-facing) was never built** | `chat-system-spec.md §4` | The specifically-designed narrow, read-only, grep-style tool for precise agent recall ("what exactly did I say about X") doesn't exist. The BM25 `/retrieve` endpoint is HEAD retrieval — a different capability from what §4 describes. |
| **Hard-delete doesn't exist** | `master-spec.md §3 Do` | Soft-forget's underlying mechanism exists in the engine (unreachable from the product per above). True, irreversible purge was never implemented — no object file is ever actually deleted from disk. |

### 1.2 Medium priority

| Gap | Spec reference | What's actually true |
|---|---|---|
| **"Why do you think that about me" has no dedicated handling** | `master-spec.md §1.4.1` | No feature looks up which commit/conversation produced a given fact and surfaces it on request. The model might improvise a reasonable-sounding answer using injected context, but there's no designed capability behind it. |
| **Provider switching requires an env-var change + restart** | `chat-system-spec.md §3`, `ledger-spec.md §2` | Not live, in-app switching as implied by spec. Consequently the ledger's "provider/model switches" event type has nothing to log — no switching UI exists to trigger it. |
| **Merge conflict resolution has zero UI** | `memory-engine-spec.md §4` | `find_conflicts` genuinely computes semantic conflicts between branches, but nothing surfaces them to a user for the spec'd 4-way resolution (keep main / keep branch / keep both / defer). *(This one was at least consciously deferred as a decision mid-session — the only gap in this document that was.)* |
| **Hypothetical-exploration branches don't exist** | `memory-engine-spec.md §3` | Branch inference only implements domain separation (work/personal). The spec's second branch use case — a line of exploratory thinking, later merged or discarded — has no mechanism at all. |
| **Time-travel queries don't exist** | `memory-engine-spec.md §6.6` | "What did I think about this in March" has no API or UI path anywhere in the product. |
| **Retrieval doesn't numerically downweight inferred units** | `memory-engine-spec.md §1` | Spec says inferred units should be weighted lower *in retrieval scoring*. What's actually built only labels them "(uncertain)" in the injected text after they've already been retrieved — a cosmetic distinction, not a scoring one. |

### 1.3 Low priority / deliberate, reasoned substitution

| Gap | Spec reference | What's actually true |
|---|---|---|
| **"Semantic similarity" is BM25 lexical matching, not semantic** | `memory-engine-spec.md §6.3` | A deliberate, well-reasoned interim substitution made and documented at the time (embeddings deferred pending evidence of the heuristic actually failing) — but worth naming plainly as a literal deviation from the spec's wording, not just an implementation detail. |
| **Merge's 4-way choice set isn't fully matched** | `memory-engine-spec.md §4` | The single-branch supersede-conflict flow (`ConflictBlock`) offers 3 choices (Replace / Both are true / Ignore) rather than the spec's 4 (keep main / keep branch / keep both / defer) — missing an explicit "defer, leave flagged open" option. |

---

## 1.4 Found and resolved during integration testing (not a spec gap — an implementation bug)

| Issue | Where | Resolution |
|---|---|---|
| **Chat route blocked the entire event loop under load** | `backend/main.py`, `/api/chat` | Not called for by any spec, but worth recording: the route was declared `async def` while every call inside it (`httpx` sync client for memory fetches, capture, provider streaming) was synchronous and never `await`ed. FastAPI runs `async def` routes directly on the single shared event loop, so a blocking synchronous call inside one didn't yield — it stalled the *entire server*, including unrelated requests like `/health`, for the full duration of that chat turn. Found via the integration test suite (`test_projectx.py`): isolated test functions passed, but the full suite reliably hung on `ReadTimeout` once enough sequential turns had run. Confirmed by a direct check (`curl /health` during an in-flight chat turn took multiple seconds instead of ~5ms). **Fix: `async def chat(...)` → `def chat(...)`.** A plain (non-async) FastAPI route runs in a background thread pool instead of the event loop, so concurrent requests no longer block each other. Verified: full suite runtime dropped from ~450s to ~90s after the fix, with 0 timeouts across three consecutive full runs. |

---

## 2. Gaps — Already Known and Documented

Confirmed still accurate; no new information here, listed for completeness against this audit's scope:

- No caching on HEAD retrieval (`state_at`/`current_state` replay from scratch every call).
- Anthropic provider untested (code written, never run against a real key).
- No attachment/image/PDF ingestion (explicitly out of scope for v1 per spec itself).
- Ledger has no UI surface (real, working, curl-inspectable only).
- No rate limiting or per-session cost visibility.
- `PENDING` conflicts are in-process only — lost on backend restart.

---

## 3. Compliant / Solid Against Spec

Worth naming plainly so the gaps above don't read as the whole picture:

- **Memory unit model** — types, provenance, timestamps, source — matches `memory-engine-spec.md §1` exactly.
- **Commits** — semantic diff summaries in plain language, parent-chained history — matches `§2`.
- **Branch isolation (domain separation half)** — matches `§3.1`; branches are inferred, never user-named, per the spec's hard requirement.
- **Content-addressable storage** — git-object style, deduplicating, local plain files — matches `§7`.
- **HEAD resolution correctness** — always resolves current state, never a stale superseded version — matches `§6.4`, verified under test.
- **Pinned-set + scored retrieval + fixed budget** — matches `§6.2–6.3` in structure (see §1.3 above for the "semantic" caveat).
- **"Show your work" activity UI** — matches `§6.7` directly.
- **Skills** — config-file schema, minimal starter set, extensible without rearchitecture — matches `chat-system-spec.md §1` closely.
- **Web search** — SearXNG default, BYOK premium optional, results woven in per-turn without becoming memory units — matches `§2` exactly.
- **Provider abstraction structure** — adding a provider doesn't touch core chat logic — matches `§3`'s architectural requirement, independent of the local-model gap above.
- **SSE streaming** — matches `§5` for Phase 0.
- **Git vocabulary kept out of the user-facing product** — matches `master-spec.md §3` after the branch-UI removal.
- **Never silently overwrite a contradicted fact / never let an LLM auto-resolve** — both `Don'ts` upheld and tested.
- **Ledger schema and immutability** — What/When/Source/Actor, append-only, no update/delete ever issued — matches `ledger-spec.md §3–4` exactly.

---

## 4. Built Beyond Spec

Not gaps — extensions the specs don't call for but that were built anyway, generally in response to real usage or explicit direction mid-session:

- **Deep search pipeline** (discovery → extraction → distillation, three-tier extraction fallback) — considerably more than `chat-system-spec.md §2`'s plain "results woven into context."
- **Conversation sidebar / multi-thread history** — not addressed anywhere in the specs; a straightforward usage-driven addition.
- **BM25 + stemming** as the interim relevance engine — a considered design response to a real bug, going beyond what any spec asked for in terms of rigor.

---

## 5. Suggested Priority If Addressing These

Not a commitment, just an ordering suggestion based on how central each gap is to the product's stated differentiators:

1. **Automatic merge** — currently the biggest gap between "branches exist" and "branches actually behave like the spec's mental model."
2. **Remember/forget commands** — named explicitly as *the* memory-control UX in the master spec; currently just missing.
3. **Local model support** — a repeated, explicit differentiator claim that isn't backed by any code yet.
4. Everything else in §1.2/1.3, roughly in the order listed.
