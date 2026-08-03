# loki — Ledger Spec

The ledger is a **product-wide audit trail**, not a memory-engine-only feature. It's distinct from the memory engine's own commit history (`memory-engine-spec.md §2`), which tracks memory *state* changes specifically — the ledger tracks *everything worth auditing* across the product.

---

## 1. Purpose

Reinforces the core positioning ("not a black box, you own this") beyond memory alone. Anything that changes state or could later raise a "why did it do that" question should be reconstructable from the ledger.

## 2. Scope — Event Types

- **Memory events**: commits, merges, soft-forgets, hard-deletes (cross-referenced with the memory engine's own history, not a duplicate of it — the ledger records *that* an event happened and its context; the memory engine's commit log holds the detailed content diff).
- **Conversation events**: session start/end, provider/model used.
- **Skill invocations**: which skill was triggered, on what input, by what conversation.
- **Search calls**: query issued, provider used (SearXNG vs. BYOK premium), whether results were incorporated.
- **Provider/model switches**: when and to what the user changed their model selection.
- **Any other state-changing action** deemed worth auditing as the product grows (extensible — this list is not exhaustive by design).

## 3. Entry Schema

Each ledger entry records:
- **What** — event type and a short description
- **When** — timestamp
- **Source** — which conversation/session triggered it
- **Actor** — user-initiated vs. system-inferred (mirrors the `stated` vs. `inferred` provenance distinction in the memory engine)

## 4. Immutability

- Ledger entries are append-only. Nothing is edited or removed after the fact — this is what makes it trustworthy as an audit trail.
- A hard-delete of a memory unit (`memory-engine-spec.md §5`) still leaves a ledger entry recording *that* a hard-delete occurred, without retaining the deleted content itself — the fact of the action is preserved even when the data is not.

## 5. Relationship to the Memory Engine's Commit History

- **Memory commit history**: internal to the memory engine, holds the actual semantic diffs and content, used for retrieval, rollback, and time-travel queries.
- **Ledger**: product-wide, lighter-weight, event-level record used for overall auditability and (later) surfaces like "what has this app done" views — not a retrieval or rollback mechanism itself.
