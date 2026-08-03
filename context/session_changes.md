# loki — session changes

## Retrieval engine (Rust, `memory-engine`)
- Replaced BM25+dense hybrid with **dense (bge-base-en) + cross-encoder rerank (bge-reranker-v2-m3)** — BM25 dropped after a confirmed stopword-collision bug (a "the" match ranked an unrelated fact #1)
- Fixed dense candidate pool: was collapsed to the same width as final output (16); now dense surfaces top-50 by rank, reranker cuts to the caller's requested count
- Added a **relevance floor on rerank score** — previously a query with nothing relevant would still fill every context slot with low-scoring noise; now returns only pinned facts if nothing else qualifies
- Generalized `retrieval::score()` behind a `Retrievable` trait — no longer hardcoded to `MemoryUnit`, so future sources (conversation turns, documents) can plug in without duplicating the scoring pipeline
- `/retrieve` now returns per-unit relevance scores, not just units — enables real cross-branch ranking instead of branch-order concatenation

## Session layer (Python backend)
- **Windowed conversation history + rolling summary** — replaces sending the full, unbounded conversation every turn
- **Judgment-layer system prompt** — fixes the model treating personal disclosure as a draft to edit/rewrite
- **`reasoning.effort` split** — main chat reply uses `low` (env-configurable via `REASONING_EFFORT`), background calls (capture, forget-detection, skill-select, search-decision) stay at the cheap `none` default
- **Retrieval trace tooling** (`/api/retrieval-trace/{conversation_id}`) — surfaces per-branch scores and merge decisions for debugging recall issues from real data instead of screenshots

## Bug fixes
- Silent timeout swallowing in `memory.py`/`capture.py` — a cold engine load (~15–20s) was timing out at 2–3s and returning `[]` indistinguishably from "no relevant facts," causing real recall failures. Timeouts raised to 20s, failures now logged
- Cross-branch retrieval was concatenating each branch's results in alphabetical order and hard-capping at 12 — a relevant fact from a later branch could be silently excluded by an earlier branch filling the cap. Fixed to merge-and-sort by actual score
- `research.py` had the same silent-failure pattern (`should_search`, `_read_and_distill`) — now logged
- Fixed a broken ABC contract: `base.py` required `complete_json` on all providers, but only `OpenAIProvider` implemented it — would have crashed `AnthropicProvider`/`LocalProvider` on instantiation

## Known, not yet fixed
- `AnthropicProvider` calls `client.responses.create(...)` — that's OpenAI's API shape, not Anthropic's actual Messages API. Dormant under `PROVIDER=openai`, broken if switched
- Reranker warmup at Python startup only fires if the store already has non-pinned units — a fresh/reset store still cold-loads on first real query. Rust-side unconditional warmup proposed, not yet applied
- Dead code: `DOMAIN_PROMPT`/`infer_domain` in `branching.py` (unused, and would crash if called — backwards argument order), duplicate `DISTILL_PROMPT` definition
- `MIN_DENSE_SCORE`, `MIN_RERANK_SCORE`, recency weighting — all unvalidated starting guesses, not tuned against real usage