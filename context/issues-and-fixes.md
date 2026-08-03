# loki — Issues Faced and How We Solved Them

A plain-language log of the real problems hit during this build, what actually caused each one, and what fixed it. Written so a future reader (including future us) can understand what happened without re-living the debugging.

---

## 1. Git / Tooling

### Merge blocked by build artifacts
**What happened:** Merging one branch into another failed because Rust's `target/` folder (compiled build output) was untracked on `main` but the incoming branch treated it as tracked, so git refused to overwrite it.
**Fix:** Deleted the local `target/` folder (it's regenerable — `cargo build` recreates it) and re-ran the merge.

### Broken `.gitignore` pattern
**What happened:** The ignore rule was written as `target/target/` instead of `target/`, so it literally meant "ignore a folder named target *inside* a folder named target" — the real `target/` directory was never actually being ignored, which is what caused the merge issue above in the first place.
**Fix:** Corrected the pattern to `target/`, then untracked anything that had slipped in under the broken rule (`git rm -r --cached`).

---

## 2. Memory Retrieval (Rust engine)

### Recent-but-irrelevant facts sneaking into context
**What happened:** A memory unit could qualify for injection into a conversation just by being *recent*, even if it had nothing to do with the current question — there was no minimum relevance requirement.
**Fix:** Added a relevance floor: a unit must clear a minimum score before recency is even considered.

### Common words causing false matches
**What happened:** Naive keyword-overlap scoring treated words like "the" as meaningful matches, since it just counted shared words above a certain length — a query containing "the" could accidentally match unrelated stored facts.
**Fix:** Replaced naive keyword overlap with **BM25**, the standard lexical ranking algorithm — its **IDF (inverse document frequency)** term automatically downweights words that appear in most stored facts (like "the") without needing a hand-maintained stopword list. Also added **English stemming** (`rust_stemmers`) so "decide," "decides," and "deciding" match each other.

### The BM25 fix accidentally broke a working case
**What happened:** After adding the relevance floor, a query like "what am I working on?" stopped finding a project fact that used completely different wording — zero shared words, so it scored near-zero and got filtered out before a separate "intent match" boost (which rewards facts of the right *type* for the question) ever got a chance to rescue it.
**Fix:** Let intent-type matching count as its own path past the relevance floor, so a unit can qualify either through real word overlap *or* through matching the kind of thing being asked about.

---

## 3. Branch Routing (work / personal / main)

### A fact got remembered twice
**What happened:** When answering a general question like "what do you know about me?", the app only checked memory for duplicates within the one branch it guessed was relevant. A fact already stored on the `work` branch wasn't visible during that check, so the same fact got committed a second time.
**Fix:** The **dedup check** (what counts as "already known") now scans every branch, while the **injected context** (what's actually shown to the model this turn) stays narrowly scoped for relevance — two different jobs that had been sharing one variable.

### Domain classification silently hid real memories
**What happened:** Every message was first classified as "work," "personal," or "main," and only that one category (plus "main") got read. If the guess was wrong, or the question didn't clearly belong anywhere, whole categories of real, stored memory were invisible for that turn — not because they didn't exist, but because the app never looked.
**Fix:** Reads now always scan **every branch**, every turn. Domain classification still decides where a *new* fact gets filed away, but it no longer gates what can be read back. Relevance scoring (not a folder-style filter) decides what's worth using.

### A casual fact ("I have a dog") didn't route to "personal"
**What happened:** The domain-classification prompt used "main" as a vague default, so borderline-but-clearly-personal facts sometimes landed in the general bucket instead.
**Fix:** Rewrote the prompt to give concrete examples of each domain and redefine "main" narrowly (only context-free facts true regardless of situation), instead of treating it as a fallback for uncertainty.

---

## 4. Search Pipeline

### Search silently stopped working
**What happened:** The self-hosted search service (SearXNG, running in Docker) had simply stopped, and every failure downstream was swallowed by bare `except: return None/[]` blocks with no logging — so nothing showed *why* search wasn't returning results. Hours were spent chasing red herrings (bot-blocking, timing issues) before the real, simple cause was found.
**Fix:** Restarted the container and set its restart policy to `unless-stopped` so it survives reboots automatically. Just as importantly, added real logging to every failure point in the extraction and search code, so the next failure is visible immediately instead of requiring a multi-hour investigation.

### A real extraction bug, found along the way
**What happened:** The headless-browser fallback tier (Playwright, used for JavaScript-heavy pages) waited for `networkidle` — "the network goes fully quiet" — which modern ad/tracker-heavy sites rarely ever do, so it usually just timed out.
**Fix:** Switched to waiting for `domcontentloaded` plus a short fixed pause, which is far more reliable.

### One site actively blocked the browser
**What happened:** A specific site returned `net::ERR_HTTP2_PROTOCOL_ERROR` — a signature of bot-detection rejecting the connection at the protocol level.
**Fix:** Disabled HTTP/2 on the headless browser launch, which routed around that specific fingerprint check.

### The "Searching…" indicator never went away
**What happened:** Each new activity event (search results, in this case) was added to the list shown in the UI, but the earlier "Searching…" note was never removed once it was superseded — so both sat on screen forever.
**Fix:** When a real search result (or failure) event arrives, the UI now removes the matching "Searching…" placeholder first.

---

## 5. Backend Concurrency & Networking

### One slow chat turn could freeze the entire server
**What happened:** The chat endpoint was declared `async def`, but every call inside it (memory fetches, the AI provider call, fact extraction) used a **synchronous** HTTP client with no `await`. In FastAPI, an `async def` route runs directly on the shared event loop — a blocking synchronous call inside it doesn't yield control, so it stalled the *entire server*, including unrelated requests like a basic health check, for the full length of that one chat turn.
**Fix:** Changed the route from `async def` to a plain `def`. FastAPI automatically runs non-async routes in a background thread pool, so requests stop blocking each other. Confirmed by timing a health check during an in-flight chat turn (seconds before the fix, milliseconds after) and by the full test suite's total runtime dropping roughly fivefold.

### Intermittent stalls that got worse over time, then seemed to "fix themselves" on restart
**What happened:** Several different explanations were chased in turn — a stuck network connection, LLM client timeouts set too low, too many sequential AI calls per turn — each real to some degree, but none fully explained the pattern: everything working fine for a while, then hanging, sometimes recovering after a full backend restart.
**Root cause, eventually confirmed:** An intermittent stall on the machine's IPv6 network path (likely worsened by the private DNS resolver in use), which only reliably showed up under a rapid burst of outbound network calls — the kind a test suite produces in seconds, but ordinary one-message-at-a-time typing almost never does.
**Fix, in three layers:**
1. **Forced all AI provider connections to use IPv4 only** (`httpx.HTTPTransport(local_address="0.0.0.0")`), sidestepping the unreliable IPv6 path entirely — verified with a 30-call burst test that failed reliably before this change and passed cleanly, twice in a row, after it.
2. **Added a hard wall-clock deadline** (90 seconds) enforced by our own code around every AI call, running the actual call on a background thread — so even if something hangs in a way our code can't predict, it can never wait forever.
3. **Added one automatic retry** for a clean failure before any output has started streaming, since a transient network stall is often gone moments later.

### A route disappeared after a code reorganization
**What happened:** `main.py` had grown to nearly 500 lines doing five different jobs (app setup, database access, request schemas, and all the actual chat logic in one function). It was split into separate files by responsibility (`db.py`, `models.py`, `chat_engine.py`, and one router file per concern). In the process, the `/api/ledger` endpoint was accidentally left out of every new file.
**Fix:** Added the missing route to the conversations router. The test suite caught this immediately as a clean 404, rather than it going unnoticed.

---

## 6. Frontend

### A memory-write confirmation had no visible box around it
**What happened:** After a UI redesign, the reusable "collapsible" component (used to show expandable activity like "Remembered 1 thing") had no CSS rule at all for its own container — no border, background, or padding — so it rendered as plain, unstyled text instead of a visually distinct block.
**Fix:** Added the missing container styling, tinted from the same accent-color value already being passed into the component, so it automatically matches the right color for each activity type.

### The same fix over-applied to a place it shouldn't have
**What happened:** The container styling above was shared by every use of the component, including the memory side panel, where it wasn't wanted — the panel's fact groups (like "identity") suddenly all had boxes and borders too.
**Fix:** Added an opt-out flag (`boxed`) to the component, defaulting to on for chat activity and explicitly turned off for the memory panel's groupings.

---

## Pattern worth naming

A large share of these issues share one root cause: a failure happening silently, with no log line or visible error, which turned a five-minute fix into a multi-hour investigation. Every time this was found, the fix included adding real logging at the point of failure — not just solving the immediate bug, but making the *next* similar bug fast to diagnose instead of another blind hunt.
