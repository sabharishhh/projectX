# loki — Memory Engine Spec

Language: Rust. Storage: local, plain-file, content-addressable. All git-style vocabulary here (commit, branch, merge, HEAD) is internal — never exposed to the user directly (see `master-spec.md §3`).

---

## 1. Memory Unit — the core object

Atomic, typed fact. Types:
- `identity` — stable facts (role, background)
- `preference` — style, tools, tastes
- `project` — state of something ongoing (status, decisions made, open questions)
- `decision` — a specific choice and its reasoning, timestamped
- `relationship` — context about people/entities the user references

Each unit stores: content, type, timestamp, source (which conversation produced it), provenance (`stated` vs. `inferred` — inferred units are weighted lower in retrieval and surfaced as "I think you meant..." rather than treated as settled fact).

## 2. Commit

A commit is a set of unit changes, not a snapshot of everything. It references:
- which units were added / modified / superseded
- the triggering conversation
- a **semantic diff summary in plain language** — not a line diff. e.g. *"career goal changed from 'stay in current role' to 'exploring founder path' — Mar 2026."*

This plain-language diff is the primary UX differentiator versus file/line-diffing systems (e.g. GCC/Contexa) — it's written for a human to read, not a machine to parse.

## 3. Branch

An isolated context line. Two uses:
1. **Domain separation** — work vs. personal, so memory doesn't bleed between contexts by default.
2. **Hypothetical exploration** — a line of thinking ("what if I pivoted careers") developed without contaminating main context, later merged in or discarded.

Branches are **inferred and managed by the system**, never created or named by the user explicitly.

## 4. Merge

- **Auto-merge silently** when no real collision exists (pure additions on either side).
- **Surface only true collisions** — same unit changed on both sides since divergence — conversationally, in plain language, with a small bounded set of resolutions:
  - Keep main's version
  - Keep branch's version
  - Keep both, reworded as coexisting (common for personal facts — two things can both be true)
  - Defer — leave flagged as open
- Resolve unit-by-unit; batch/auto-fold the non-conflicting rest.
- Nothing is deleted on merge, only superseded — the losing version stays in history.
- The resolution itself becomes its own commit.
- **An LLM may draft the plain-language summary of a conflict, but never silently picks the winner.**

## 5. Attachments (images, PDFs, other files)

- **Scope for v1: text-only memory units.** Attachment ingestion is deferred, not architected out.
- Storage layer is content-addressable and blob-capable by design (same as git handles binary files), so attachments can be added later without a storage rearchitecture.
- **Model: attachments are provenance, not memory units themselves.** A photo of a receipt is not a memory — it's a source a memory unit gets extracted from (e.g. "renewed X subscription, $Y — Mar 2026"). The original file is stored and linked as evidence, retrievable to verify what the system actually saw.
- Future work: a vision/OCR extraction step at capture time, using whichever BYOK model the user has connected. Out of scope for the first build.

## 6. HEAD Retrieval — what gets injected into a conversation

1. **Scope by branch first** — only the active branch's units are candidates (structural fix for memory bleed).
2. **Small pinned set always loads** — stable identity/preference units, no scoring needed.
3. **Everything else is scored**, combining: semantic similarity to the current message, recency, and type priority (e.g. `decision` units weighted higher for "what did I decide" queries; `preference` units weighted higher for writing requests). Top-scoring units load up to a fixed token budget — never an unbounded dump.
4. **Always resolves to HEAD** — the current value of a unit, never a stale superseded version, even if the old version scores well semantically.
5. **Cache the per-branch current-state view**, invalidate only on new commits — avoids rescanning history every turn.
6. **Time-travel queries are a separate, explicit mode** ("what did I think about this in March") — query a specific past commit, kept deliberately separate from default injection so stale context never leaks into normal answers.
7. **Show your work** — a visible "here's what was pulled into context this turn" view in the UI, reinforcing the ownership/non-black-box positioning.

## 7. Storage

Content-addressable, git-object style: each memory unit hashed and stored once; commits reference trees of unit hashes. Deduplicates naturally. The whole store is a local, git-compatible repo of plain files — the user can inspect or export it directly, independent of the app.
