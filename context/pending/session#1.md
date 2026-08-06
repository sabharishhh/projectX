**1. Reconcile `capture.py`** *(blocking — do first)*
Two sessions edited it independently the same day: this session's commitment status-aware duplicate filter vs. the entity-graph session's `known_entities`/`_commit_entities` additions. Diff both versions, merge into one file, re-run `eval_fixes.py` to confirm both feature sets still work together.

**2. Reply sufficiency check**
New verify pass at the `_generate_reply`/`_generate_reply_gated` layer — applies to both the agentic (tool-using) and plain-stream paths, not just search. Fresh-context call, same buffer-check-regenerate shape as `check_correction_compliance`: given the question + gathered context, does the drafted reply actually answer it? Three outcomes: sufficient → release as-is; insufficient but answerable-with-caveat → regenerate with explicit uncertainty stated; insufficient and genuinely blocked → route to step 3.

**3. Ask-vs-report decision**
Sub-branch inside step 2's "insufficient" outcome. When the gap is something only the user can supply (missing preference, ambiguous scope), ask a clarifying question instead of guessing or hedging. When it's something the system could look for but hasn't yet (older context, a source not checked), route to step 5's search instead of asking. Needs its own small classification inside the sufficiency check's output schema — `{sufficient, reason, action: "answer" | "clarify" | "search_more"}`.

**4. Reasoning-event narration**
New SSE activity kind, `"reasoning"` — structurally separate from `tool_step` (action labels) and text (final answer), matching the AG-UI standard. One instruction added telling the model to narrate real judgment calls briefly (switching sources, narrowing a query, the sufficiency check's own verdict) — not every step. Frontend: new `ActivityStrip` kind with quieter styling (dimmer/italic, no citation badge), same extension pattern as `commitments_due` earlier.

**5. Cross-chat / long-conversation search**
Hybrid retrieval over raw message history, reusing the Rust engine's existing dense+rerank pipeline (bge-base-en + cross-encoder) rather than building a second vector store, plus SQLite FTS5 for exact/keyword recall. Exposed as a new typed MCP tool, `conversation_history_search`, same shape as `web_search`/`memory_search`. Fires only when step 2/3 flags that current injected context is insufficient and the gap is retrievable — not on every turn.

**6. Multimodal support** *(separate project, after all of the above)*
File upload + storage, extraction per type (PDF/DOCX/OCR/Excel), message shape changes from plain string to content-block arrays across `_build_conversation`/`to_provider_messages`/every provider method, DB schema changes for attachments, and a decision on where extracted content lands (context injection vs. memory unit vs. `read_file` tool result).