# loki — Self-Learning Roadmap

**Prerequisite:** finish the second memory subsystem (Phase 3 — research/planning/build
context store) before starting this list. Item 1 builds on the existing preference/fact
system, and Phase 3's data-shape decisions may affect how corrections get stored too.

---

## 1. Compiled Correction Enforcement — highest priority

**What:** when the user gives an explicit behavioral correction ("always do X", "never do
Y"), capture it as a distinct, checkable rule — not just a passive preference sentence
hoped to be remembered.

**Why:** today, corrections go into the same bucket as ordinary facts and only work if the
model happens to notice them in context. Published research (arXiv:2606.13174, Notre
Dame/IBM, verified real) found this leaves the majority of corrections silently ignored
later. Compiling them into an actual checked rule fixes this — not perfectly, but
substantially.

**Mechanism:**
- Extend `capture.py` with a parallel extraction path specifically for corrections,
  separate from general fact capture.
- Each correction becomes a rule + an applicability condition (when the rule applies).
- Before the agentic loop's final synthesis, run a lightweight check: does the output
  satisfy all applicable active rules? If not, force one more iteration with the
  violation stated explicitly — same pattern as the existing forced-synthesis-on-stall
  mechanism already in `agentic_search.py`.

---

## 2. Lightweight Procedural Learning

**What:** when a tool-use sequence shows a clear efficiency lesson (e.g. repeated failed
searches before finding the right approach), optionally save a durable "this worked
better" note.

**Mechanism:** widen `extract_units`' input to sometimes include a summary of the
agentic tool-call trace, not just the text exchange. Reuse an existing `unit_type`
(`project`/`preference`) rather than inventing a new one, unless a clear need for a
separate type shows up in practice.

**Explicitly not doing:** the full dual-agent "teacher" architecture some research
proposes for this. One added extraction path on the existing capture pipeline is enough
at this scale — no second agent watching and grading the first one.

---

## 3. Agent-Editable Adaptive Skill Layer — only once 1 and 2 are stable

**What:** let the agent adjust which tools a skill can access, based on learned patterns.

**Status:** deprioritized. Most of the value this would add is already covered by item 1;
the only genuinely unique piece is tool-access self-editing, which is a narrow need.
Revisit only if a concrete case comes up where compiled rules alone aren't enough.

**Non-negotiable design constraint if built:** never edit the user's hand-authored
`.toml` files directly. Each skill gets a separate, agent-only overlay file (e.g.
`sleuther.adaptive.toml`) merged in at load time on top of the base file — keeps manual
edits and agent-learned edits from ever colliding.

---

## Deferred — revisit only if circumstances change

- **Just-In-Time RL (logit modulation)** — blocked until local model support is solid;
  cloud provider APIs don't expose logits for direct manipulation.
- **Self-Contrast / parallel-stream reflection** — real technique, real cost (roughly 3x
  tokens per use). Worth an optional, explicit high-effort mode for specific hard
  queries later — never a default behavior.
- **Dynamic multi-agent topology** — not a fit until/unless Phase 3 project work grows
  into genuinely complex, multi-part collaborative tasks.

---

## Rejected outright — do not revisit without new evidence

All four items from the conflict-resolution-RL / adaptive-reranking / bandit-routing /
knowledge-graph-pruning proposal. Every one requires data volumes a single-user product
will never generate, and one assumes a knowledge graph that doesn't exist in this
architecture.
