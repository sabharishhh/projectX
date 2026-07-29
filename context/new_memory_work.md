Sequenced, not a wishlist — each one either closes a gap that's actively costing trust today, or builds toward the thing nobody else has. Given everything from tonight, here's the order I'd actually go in.

**Phase 1 — finish making memory trustworthy (mostly underway, close it out)**
1. Finish the redundant-storage work already in progress (branch-scoped caching, `retrieval_traces` pruning) — correctness-preserving, no shortcuts.
2. Pick up TRUSTMEM's actual lesson: add a lightweight verification pass before a capture write commits — not just "is this a duplicate," but "is this actually supported by what the user said," closing the loop on the same hallucinated-write risk that produced tonight's bugs.
3. Finish the structural cleanup already scoped (unify the three sync↔async patterns, dedupe the provider harness, centralize the memory-engine HTTP client). This isn't busywork — every real bug tonight traced back to exactly this kind of duplication.

**Phase 2 — the legibility/trust UX, your actual differentiator**
4. A real visual memory timeline/branch view — the human version of `memoir blame`/`checkout`. Nobody else has this because nobody else has a product layer at all.
5. Entity-linking on top of your existing BM25+dense+reranker retrieval — the one concrete technical upgrade the research actually validated (Mem0's biggest measured gains came from signal fusion, not any single clever idea).

**Phase 3 — the second subsystem: working context for active tasks**
6. Design the new store for research/planning/build context — the "Option C" from before. This is where the fact-vs-graph decision from earlier finally gets made for real, informed by what Zep/Mem0 do for relationships, but scoped to *your* actual use case (a project's evolving state), not a copy of either.
7. Wire it into the existing agentic tool system (`memory_search`'s sibling — a "project_search" or similar) so the model can draw on both atomic facts and working context in one coherent loop, the way `agentic_search.py` already unifies web/memory tools.

**Phase 4 — prove it, don't assume it**
8. Build your own small eval, even informal — a handful of real "does it remember correctly across sessions" and "does it stay useful across a multi-day project" test cases. You don't need LoCoMo-scale benchmarking, but you do need *some* structured way to know if a change actually helped, instead of finding out via another 2am bug hunt like tonight's.

Order matters here: 1-3 stop you from building the differentiator on a shaky foundation. 4-5 are the fastest real distance from competitors. 6-7 is the ambitious, genuinely novel piece — worth doing once the base is solid, not before. 8 is what turns "I think it's better" into "I know it's better."

Want to start back at the redundant-storage item where we left off, or pick a different starting point given this roadmap?

Good push to get specific — I was vague last time, and the specifics change the answer. Found exactly what "cryptographic integrity" means for Memoir: **SHA-256 hashing for all operations**, on top of a data structure called a **Prolly Tree** (a Merkle-search-tree — the same core idea Dolt, the "git for data" database, uses).

**First, the actual good news: you already have the crypto part.** Look at `store.rs`: `hash_bytes` computes SHA-256 over every object, and `path_for` derives the storage location *from* that hash. That's content-addressed storage — exactly what Memoir markets as "cryptographic integrity." You didn't miss this. No need to import anything here.

**But the comparison surfaces two real gaps — not the hashing itself, what's built on top of it.**

**Gap 1 — you hash, but never verify.** `get_object` reads bytes from a hash-derived path and deserializes them — it never re-hashes what it read and checks it still matches the filename. Content-addressing's entire value is that corruption becomes *detectable* — silent disk bit-rot, a partial write during a crash, manual tampering — the address itself is a checksum. Right now you're paying the cost of hashing without collecting the actual benefit. Cheap, high-value fix:

```rust
pub fn get_object<T: DeserializeOwned>(&self, hash: &str) -> Result<T, StoreError> {
    let bytes = fs::read(self.path_for(hash))?;
    let actual = hash_bytes(&bytes);
    if actual != hash {
        return Err(StoreError::Corrupted(hash.to_string(), actual));
        // needs a new StoreError::Corrupted(String, String) variant
    }
    Ok(serde_json::from_slice(&bytes)?)
}
```

**Gap 2 — this is the real one, and it's the actual point of a Prolly tree.** The Prolly tree gives Memoir `O(log n)` lookups by making the tree itself content-addressed and structurally shared — most of an old version's tree nodes survive unchanged into a new version, so reading current state doesn't mean replaying everything that ever happened.

Your `state_at()` doesn't have this property. It replays the **entire commit history from the beginning**, every single call, applying every `Added`/`Modified`/`Superseded` change in order, just to answer "what's true right now." Fine at tonight's scale — dozens of commits. But it's `O(total history ever written)`, not `O(current state size)`, and it only gets slower, forever, for a system whose entire purpose is accumulating personal history over months or years. This is the concrete, structural version of the "redundant fetching" problem we were about to fix in Python — same disease, showing up one layer lower, in Rust.

**What to actually do about it — not a blind port.** A real Prolly tree is serious infrastructure (Dolt's implementation is a meaningful engineering effort by itself) — building one for a single-user, self-hosted personal memory store is very likely over-engineering relative to your actual scale. The right-sized version of the same *principle* (don't replay from genesis every time) is **periodic state checkpointing**: every N commits, snapshot the resolved state alongside the commit itself. `state_at()` then only needs to find the nearest checkpoint at or before the requested commit and replay forward from there, not from the start of time. Same core idea Prolly trees solve structurally, achieved with a much smaller, correctness-preserving addition — a new `checkpoints` table/dir in the store, written opportunistically on `commit()`, read first by `state_at()` before falling back to full replay if none exists yet.

**Net answer to "should we change the memory engine":** not a rewrite, and not a copy of their data structure — two targeted additions that close a real, honestly-identified gap each: verify-on-read (small, do it now, no design decision needed) and checkpointed state resolution (bigger, but scoped correctly for what you're actually building, not what a distributed structured-data company is building).

Want the verify-on-read fix now — it's small and unambiguous — and the checkpointing design talked through separately, given it touches `commit()`, `state_at()`, and the storage layout all at once?

Fair pushback — "why can't we" deserves a real answer, not just "it's overkill," and I don't want to assert the difficulty from memory when I can actually check whether the hard part is already solved by someone else.Good challenge — and the search actually changes my answer. I assumed "hand-build a Prolly tree" last time; that's not the real choice on the table.

**The crate already exists — and it's built by the same person who built Memoir.** `zhangfengcdt/prollytree` is a real, published Rust crate (`prollytree = "0.3.1"` on crates.io): a probabilistic B-tree with Merkle properties, `O(log n)` operations, multiple storage backends including **git-backed persistence**, and it explicitly lists **"AI Agent Memory: purpose-built for LLM applications and agent systems"** as a target use case. Same author as Memoir, so this is almost certainly the literal engine underneath it, not a separate reimplementation. So "why can't we" — you genuinely could. This is dependency adoption, not inventing a data structure from scratch, which is a meaningfully smaller ask than I gave you credit for.

**What that actually changes:** the honest cost isn't "write a Prolly tree," it's "evaluate whether an early, purpose-built crate is solid enough to put your entire storage layer on top of, and do the real integration work of remapping your commit/branch/object model onto its API." Worth being precise about what "integration" means here — this isn't calling a new function alongside what exists, it's rearchitecting `store.rs`'s storage layer around a different underlying structure. Two things temper how eagerly I'd jump at it:

1. **It's young — `0.3.1`.** Not necessarily a problem, but worth knowing before betting your whole storage layer on it: a separate, independent investigation into this exact space (Waku's sync research) noted as recently as last year that no mature general-purpose Prolly tree implementation existed yet. This crate may well have filled that gap since — but "may well have" is a claim to verify by actually reading the source and trying it, not something to take on faith from a crates.io description.

2. **A chunk of its feature surface is probably dead weight for you.** Distributed sync and three-way merge across peers is the other half of what Prolly trees are *for* — that's real infrastructure for multi-node/collaborative systems. You're single-user, self-hosted, one machine. The `O(log n)` lookup property is genuinely relevant to your problem; the distributed-sync machinery mostly isn't, at least not yet.

**So: not "can't," genuinely "should evaluate deliberately before committing."** This deserves its own scoped spike — pull the crate, prototype `MemoryUnit` storage on top of it against your actual object/commit/branch shape, see if the API fits cleanly or fights you — rather than folding into tonight's checkpoint-fix scope. Swapping a storage engine underneath live personal data is exactly the kind of change that earns the "flag it, don't proceed silently, maybe a branch" treatment your own workflow already calls for on anything large or destabilizing.

Want that spike scoped out as its own next step, separate from the smaller verify-on-read fix and the checkpoint approach — which stay worth doing either way, since they're valid regardless of which storage engine ends up underneath them?