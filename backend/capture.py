import os
import json
import logging
from datetime import datetime, timezone, timedelta

from state import CAPTURE_MODEL
from memory_client import client
from memory import invalidate_state_cache

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("capture")

DUPLICATE_SIMILARITY_THRESHOLD = 0.92

CAPTURE_MODEL = os.getenv("CAPTURE_MODEL", "gpt-5.6-luna")

ENTITY_TYPES = ["person", "project", "concept", "organization", "place", "animal", "other"]

CAPTURE_PROMPT = """You extract durable facts about the user from a conversation turn.

Capture ONLY things that will still be true and useful in a future conversation:
- identity: stable facts about who they are (role, background, location)
- preference: how they like things done (style, tools, tastes)
- project: something ongoing they're working on
- decision: a specific choice they made, and why
- relationship: people or entities in their life
- commitment: a real promise to do something later — made by the user
  ("I'll follow up with him next week") OR by the assistant on the user's
  behalf ("I'll look into that and get back to you"). Extract a concrete
  deadline if one is stated or clearly implied, resolving relative phrasing
  ("next week", "tomorrow") into a concrete ISO datetime using the current
  date you've already been given. If no deadline is stated or implied at
  all, omit "deadline" — do not invent one. If a message names MULTIPLE
  distinct actions as separate commitments (e.g. "I'll text Jamie about
  the venue and confirm the caterer by Thursday"), extract each action as
  its own separate commitment unit, even if they share one trailing
  deadline phrase — apply that shared deadline to EACH of them
  independently, don't fuse the actions into one combined commitment.
- correction: an EXPLICIT behavioral correction — the user telling the
  assistant to change how it behaves going forward, not just a passive
  preference. Signaled by phrasing like "no, always do X instead", "stop
  doing Y", "I already told you to always Z", "that's wrong, from now on
  do X". Capture the corrected rule itself, phrased as a clear, checkable
  instruction (e.g. "Always end responses with 'Anything else?'" not "the
  user wants a specific ending phrase"). Distinct from an ordinary
  preference: use "correction" only when the user is explicitly correcting
  a mistake or reasserting a rule that was violated or ignored, not for a
  first-time stated preference.
- entities: OPTIONAL. Name any distinct people, projects, or concepts
  this fact is clearly ABOUT — not every noun, only things worth
  tracking as a recurring subject across future conversations (a
  person's name, a named project, a specific ongoing concept). For
  each, give a "name", an "entity_type" (one of: {entity_types}), and
  a "relation" — a short verb phrase describing how the fact relates
  to it (e.g. "has_pet", "works_on", "decided"). Check the known
  entities list below first — if this is clearly the same
  person/project as an existing entry (allowing for nicknames or
  partial names — "Max" the dog, "the dog", "my dog" are the same
  entity), reuse that exact name so it resolves to the same record
  instead of creating a duplicate.

IMPORTANT: resolving an entity's canonical name (above) is separate
from writing the fact's "content". Keep "content" faithful to what was
actually said in THIS exchange — if the user said "the dog" or "him",
write the fact using that same wording, even if you've correctly
resolved which entity it refers to in "entities". Do NOT substitute a
resolved name into "content" when the exchange itself didn't use it —
that would state something as fact that wasn't actually said.

Do NOT capture:
- questions they asked, or the content of tasks they gave you
- topics merely discussed, rather than facts revealed about them
- anything already in the known facts list below — including when the
  assistant's own reply in this exchange restates a known fact back to the
  user. The assistant repeating something back is not new information about
  the user; only extract from what the user actually said or clearly implied.
- an inference you've already made before, even if you're re-deriving it
  independently this turn rather than recalling it — check whether a
  semantically equivalent fact already exists in the known list, not just
  whether the exact wording matches
- transient state ("I'm tired today")
- anything about the assistant itself — its name, capabilities, or how it
  described itself in this exchange. An exchange like "who are you?" / "I'm
  projectX" reveals nothing about the user and must not be captured, even
  phrased as if it were a fact ("the user was told the assistant is named
  X", "the user asked the assistant's identity") — that's still not
  information about the user.

For commitments specifically, also do NOT capture:
- hypotheticals ("I would follow up if he replies") — no real commitment
  has been made, only a condition described
- past-tense reflections ("I should have followed up last week") — this
  describes a missed opportunity, not a live, open commitment
- vague, non-actionable intentions ("I need to think about this someday",
  "I should really get better at this") — nothing concrete enough to
  track or resolve later

If the user EXPLICITLY asks you to remember something ("remember that...",
"please remember...", "keep in mind that..."), you MUST capture it as a
stated fact, even if it would otherwise seem borderline or task-like. An
explicit request to remember is an unconditional instruction, not a
judgment call.

Mark provenance as "stated" only if they said it outright. If you're reading
between the lines, mark it "inferred".

For each fact, also decide which branch it belongs on, from this list:
{branches}
Use "main" unless the fact is clearly and specifically about one of the other
listed domains. Never invent a branch name not in this list.

Known facts already stored:
{known}
Known entities already tracked:
{known_entities}

If a new fact DIRECTLY CONTRADICTS one of the known facts above — same subject,
different value — add "supersedes": "<the 8-char id in brackets>" to that unit.
Only for real contradictions, where both cannot be true at once. Do NOT use it
for facts that merely relate to, extend, or sit alongside an existing one.

Return JSON only, no other text:
{{"units": [{{"content": "...", "unit_type": "preference", "provenance": "stated", "summary": "short plain-language note on what changed", "branch": "main", "supersedes": "a1b2c3d4", "deadline": "2026-08-05T00:00:00Z", "entities": [{{"name": "Max", "entity_type": "person", "relation": "has_pet"}}]}}]}}

Omit "supersedes" entirely when the fact is new rather than a replacement.
Omit "deadline" entirely for anything that isn't a commitment, or a
commitment with no discernible deadline.
Omit "entities" entirely (or leave it an empty list) if nothing is worth
tracking as a recurring subject.
Return {{"units": []}} if nothing is worth remembering."""

VERIFY_PROMPT = """A fact-extraction pass proposed this candidate fact about
the user, from the exchange below:

User: {user_message}
Assistant: {assistant_message}

Candidate fact: "{content}"
Candidate unit_type: {unit_type}

If unit_type is "commitment": judge whether a real promise was actually
made in this exchange — by the user OR by the assistant on the user's
behalf — and whether it's concrete enough to track (not a hypothetical,
not a past-tense reflection, not a vague intention). A commitment the
ASSISTANT makes to the user ("I'll look into it and get back to you") IS
valid and durable — it's something owed to the user, not a stray fact
about the assistant's identity or capabilities. The assistant
acknowledging or restating the user's commitment back to them ("Got it",
"Got both", "Noted") does NOT make the commitment "already known" or
"not new information" — a commitment stated for the first time by the
user in THIS exchange is new and valid, even if the assistant's reply
simply confirms it received the message.

If unit_type is "correction": judge whether the user is genuinely
correcting or reasserting a behavioral rule, not just stating a one-off
preference for the first time. A real correction is valid and durable —
treat it the same as a commitment the assistant owes the user, not a
transient remark.

For every other unit_type: judge strictly whether this is genuinely new,
durable information ABOUT THE USER — not about the assistant, not a
restated question, not something the user already told the assistant
before, not a transient state. Facts about the assistant itself (its
name, who created or built it, its capabilities) are NOT information
about the user, even when phrased as if they were — "the user asked who
created the assistant" is still a fact about the assistant, not the user.

Return JSON only:
{{"valid": true}}
or
{{"valid": false, "reason": "one line on why this isn't valid"}}"""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["valid", "reason"],
    "additionalProperties": False,
}

CORRECTION_CHECK_PROMPT = """The user has these standing behavioral
corrections that MUST be followed in every reply:

{corrections}

Here is a reply the assistant just generated:

---
{reply}
---

Judge strictly: does this reply violate any of the corrections above? A
correction only counts as violated if the reply had a real opportunity to
follow it and didn't — e.g. a formatting rule that applies to any reply,
or an explicit rule this reply's content clearly triggers. Don't flag a
correction as violated if it genuinely doesn't apply to this specific
reply's content.

Return JSON only:
{{"compliant": true}}
or
{{"compliant": false, "violated": ["<correction text>"], "guidance": "one line telling the assistant precisely what to fix"}}"""

CORRECTION_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "compliant": {"type": "boolean"},
        "violated": {"type": "array", "items": {"type": "string"}},
        "guidance": {"type": ["string", "null"]},
    },
    "required": ["compliant", "violated", "guidance"],
    "additionalProperties": False,
}

CAPTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "unit_type": {"type": "string", "enum": ["identity", "preference", "project", "decision", "relationship", "commitment", "correction"]},
                    "provenance": {"type": "string", "enum": ["stated", "inferred"]},
                    "summary": {"type": "string"},
                    "branch": {"type": "string"},
                    "supersedes": {"type": ["string", "null"]},
                    "deadline": {"type": ["string", "null"]},
                    "entities": {
                         "type": "array",
                         "items": {
                             "type": "object",
                             "properties": {
                                "name": {"type": "string"},
                                "entity_type": {"type": "string", "enum": ["person", "project", "concept", "organization", "place", "animal", "other"]},
                                "relation": {"type": "string"},
                             },

                            "required": ["name", "entity_type", "relation"],
                             "additionalProperties": False,
                         },
                     },
                },
                "required": ["content", "unit_type", "provenance", "summary", "branch", "supersedes", "deadline", "entities"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["units"],
    "additionalProperties": False,
}

RESOLVE_PROMPT = """The user's message (and the assistant's reply) may
indicate that one or more of these currently OPEN commitments have now
been completed or are no longer relevant:

{open_commitments}

Exchange:
User: {user_message}
Assistant: {assistant_message}

For each commitment that this exchange genuinely resolves, decide its new
status:
- "done" — it was completed ("I sent it", "I followed up with him")
- "cancelled" — it's no longer going to happen / no longer relevant
  ("never mind, forget that", "that's not needed anymore")

Mentioning a NEW commitment involving the same person or entity does NOT
cancel or complete a DIFFERENT existing commitment about that same
person — two separate commitments about the same person can both stay
open at once. Only cancel or resolve a commitment if the message is
clearly about THAT SPECIFIC commitment's task, or explicitly says to
drop/cancel/never-mind it — not just because a new, unrelated commitment
involving the same person came up in the same message.

Be strict about matching the SPECIFIC subject — the same person, project,
or thing the commitment was actually about — not just a similar-sounding
action. "I emailed Sarah about the budget" does NOT resolve a commitment
about emailing someone else, even about a similar topic, and does NOT
resolve a commitment about a completely different action just because
both mention "email." Mentioning the SAME PERSON or entity is not enough
on its own — "I emailed the landlord about a leaky faucet" does NOT
resolve a commitment to email the landlord about a lease renewal; the
task/topic has to match too, not just who it involves. Only resolve a
commitment if the exchange clearly refers to the SAME specific subject
AND the SAME task the commitment names.

Only include a commitment here if the exchange ACTUALLY resolves it — do
not guess, and do not resolve something just because it's topically
related. If nothing in this exchange resolves any of the listed
commitments, return an empty list.

Only resolve a commitment if the exchange contains a genuine STATEMENT
that something was done or is no longer needed — never resolve just
because the user asked a question about their commitments, asked what's
open, or asked for a status update. Asking "what are my commitments" or
"is X still open" is a question, not a completion — do NOT resolve
anything based on a question alone, even if your own reply happens to
list or restate the commitment.

Return JSON only:
{{"resolutions": [{{"hash": "a1b2c3d4", "status": "done", "reason": "one line naming the specific match"}}]}}
or
{{"resolutions": []}}"""

RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "resolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hash": {"type": "string"},
                    "status": {"type": "string", "enum": ["done", "cancelled"]},
                    "reason": {"type": "string"},
                },
                "required": ["hash", "status", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["resolutions"],
    "additionalProperties": False,
}

def is_semantic_duplicate(u: dict, branch: str) -> bool:
    """Fuzzy backstop for capture's own judgment — catches rephrasings
    that slip past CAPTURE_PROMPT's semantic-dedup instruction (exact
    string match alone doesn't catch "prefers dark mode" vs. "likes the
    interface in dark mode"). Reuses the same dense retrieval pipeline
    already built for /retrieve — no new infrastructure, no LLM call.
    Fails open (not-a-duplicate) on any error: a missed duplicate is
    recoverable later, silently blocking a real new fact is not."""
    try:
        r = client.post(
            "/retrieve",
            json={
                "query": u["content"],
                "max_units": 1,
                "branch": branch,
                "boost_types": [u["unit_type"]],
            },
        )
        r.raise_for_status()
        results = r.json()
        if not results:
            return False
        top = results[0]
        return (
            top.get("unit_type") == u["unit_type"]
            and top.get("score", 0.0) >= DUPLICATE_SIMILARITY_THRESHOLD
        )
    except Exception as e:
        logger.warning(
            f"is_semantic_duplicate check failed for {u.get('content', '')!r}: "
            f"{e!r} — treating as not-duplicate (fail open)"
        )
        return False

def _known_facts_block(units: list[dict]) -> str:
    if not units:
        return "(none yet)"
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)

def _known_entities_block(entities: list[dict]) -> str:
    if not entities:
        return "(none yet)"
    lines = []
    for e in entities:
        aliases = f" (aka {', '.join(e['aliases'])})" if e.get("aliases") else ""
        lines.append(f"- {e['name']} [{e['entity_type']}]{aliases}")
    return "\n".join(lines)


def fetch_known_entities() -> list[dict]:
    """All entities tracked globally — deterministic list call, no LLM.
    Used both to build the known-entities prompt block and, indirectly,
    to let capture.py show the model what already exists so it reuses
    names instead of minting duplicates."""
    try:
        r = client.get("/entities")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_known_entities failed: {e!r}")
        return []

def _verify_unit(provider, user_message: str, assistant_message: str, unit: dict) -> bool:
    """Second, narrow pass: is this candidate genuinely about the user?
    Fails closed — any error here rejects the candidate rather than
    committing something unverified, since the whole point of this stage
    is trustworthiness, not maximizing recall."""
    prompt = VERIFY_PROMPT.format(
        user_message=user_message, assistant_message=assistant_message,
        content=unit["content"], unit_type=unit.get("unit_type", "unknown"),
    )
    try:
        if provider.supports_structured_output:
            result = provider.complete_json(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Verify."}],
                CAPTURE_MODEL, schema=VERIFY_SCHEMA, schema_name="capture_verify",
            )
            logger.info(f"capture verify (structured): content={unit['content']!r} result={result}")
            return bool(result.get("valid"))

        raw = "".join(provider.stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": "Verify."}],
            CAPTURE_MODEL,
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        logger.info(f"capture verify (unstructured): content={unit['content']!r} result={parsed}")
        return bool(parsed.get("valid"))
    except Exception as e:
        logger.warning(f"capture verify failed for {unit.get('content', '')!r}: {e!r} — rejecting (fail closed)")
        return False


def extract_units(provider, user_message: str, assistant_message: str,
                  known: list[dict], branches: list[str], known_entities: list[dict]) -> list[dict]:
    prompt = CAPTURE_PROMPT.format(
        known=_known_facts_block(known),
        branches=", ".join(branches),
        known_entities=_known_entities_block(known_entities),
        entity_types=", ".join(ENTITY_TYPES),
    )
    exchange = f"User: {user_message}\n\nAssistant: {assistant_message}"

    try:
        if provider.supports_structured_output:
            result = provider.complete_json(
                [{"role": "system", "content": prompt}, {"role": "user", "content": exchange}],
                CAPTURE_MODEL, schema=CAPTURE_SCHEMA, schema_name="capture_units",
            )
            units = result.get("units", [])
        else:
            raw = "".join(provider.stream(
                [{"role": "system", "content": prompt}, {"role": "user", "content": exchange}],
                CAPTURE_MODEL,
            ))
            parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            units = parsed.get("units", [])

        

        for u in units:
            if u.get("branch") not in branches:
                u["branch"] = "main"
            if u.get("supersedes") is None:
                u.pop("supersedes", None)
            if u.get("deadline") is None:
                u.pop("deadline", None)
            if u.get("unit_type") == "commitment":
                u["commitment_status"] = "open"

            if not u.get("entities"):
                u.pop("entities", None)

        logger.info(f"extract_units raw: {len(units)} candidate(s) — "
                    f"{[(u.get('unit_type'), u.get('content')) for u in units]}")
    except Exception as e:
        logger.warning(f"extract_units failed to parse: {e!r}")
        return []

    # Second pass: each candidate is independently verified before it's
    # returned at all — chat_engine.py's caller sees only what passed,
    # no change needed on that side.
    verified = []
    for u in units:
        if _verify_unit(provider, user_message, assistant_message, u):
            verified.append(u)
        else:
            logger.info(f"capture rejected at verify stage: {u['content']!r}")
    return verified


def find_open_commitments(branch: str) -> list[dict]:
    """Every currently-open commitment on a branch, regardless of
    deadline. Deterministic; no LLM call."""
    try:
        r = client.get("/commitments/open", params={"branch": branch})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"find_open_commitments failed for branch={branch!r}: {e!r}")
        return []

def find_due_commitments(branch: str, within_hours: int = 48) -> list[dict]:
    """Every currently-open commitment on a branch whose deadline falls
    within the next `within_hours` — the surfacing/reminder side of this
    feature, distinct from find_open_commitments (which ignores deadline
    entirely and is used only for resolution-matching). Deterministic;
    no LLM call."""
    within = (datetime.now(timezone.utc) + timedelta(hours=within_hours)).isoformat()
    try:
        r = client.get("/commitments/due", params={"branch": branch, "within": within})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"find_due_commitments failed for branch={branch!r}: {e!r}")
        return []

def _open_commitments_block(units: list[dict]) -> str:
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)


def detect_commitment_resolutions(provider, user_message: str, assistant_message: str,
                                   open_commitments: list[dict]) -> list[dict]:
    """Bounded judgment over a pre-narrowed candidate set — never scans
    the whole memory store, only whatever's already deterministically
    known to be open. Skips the LLM call entirely if there's nothing open
    to resolve, at zero cost. Returns [{"unit": <full open commitment
    dict>, "status": "done"|"cancelled"}]."""
    if not open_commitments:
        return []

    logger.info(f"resolve candidates ({len(open_commitments)}): "
                f"{[(u['hash'][:8], u['content']) for u in open_commitments]}")

    prompt = RESOLVE_PROMPT.format(
        open_commitments=_open_commitments_block(open_commitments),
        user_message=user_message, assistant_message=assistant_message,
    )

    try:
        if provider.supports_structured_output:
            result = provider.complete_json(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Resolve."}],
                CAPTURE_MODEL, schema=RESOLVE_SCHEMA, schema_name="commitment_resolve",
            )
        else:
            raw = "".join(provider.stream(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Resolve."}],
                CAPTURE_MODEL,
            ))
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())

        logger.info(f"commitment resolve: result={result}")
        resolutions = result.get("resolutions", [])
        for r in resolutions:
            logger.info(f"  resolution reasoning: hash={r.get('hash')} status={r.get('status')} reason={r.get('reason')!r}")
    except Exception as e:
        logger.warning(f"detect_commitment_resolutions failed: {e!r} — resolving nothing (fail closed)")
        return []

    out = []

    for r in resolutions:
        unit = next((u for u in open_commitments if u["hash"].startswith(r.get("hash", ""))), None)
        if unit:
            out.append({"unit": unit, "status": r["status"]})
    return out

def _commit_entities(from_hash: str, unit: dict) -> None:
    """For each entity a fact names, resolve-or-create the entity record,
    then write a unit->entity temporal edge with the stated relation.
    Never blocks or fails the parent commit — a missing entity link is a
    fluidity gap, not a data-integrity problem, so failures here are
    logged and swallowed rather than raised."""
    for ent in unit.get("entities", []):
        name = ent.get("name")
        entity_type = ent.get("entity_type")
        relation = ent.get("relation", "related_to")
        if not name or not entity_type:
            continue
        try:
            r = client.post(
                "/entity",
                json={"name": name, "entity_type": entity_type},
            )
            r.raise_for_status()
            entity_hash = r.json().get("hash")
            if not entity_hash:
                logger.warning(f"entity commit returned no hash for {name!r}")
                continue

            edge_r = client.post(
                "/edge",
                json={
                    "from": from_hash,
                    "to": entity_hash,
                    "relation": relation,
                    "reason": unit.get("summary", unit["content"]),
                },
            )
            edge_r.raise_for_status()
        except Exception as e:
            logger.warning(f"entity link failed {from_hash!r}->{name!r}: {e!r}") 

def commit_unit(unit: dict, source: str, branch: str = "main") -> bool:
    try:
        payload = {
            "content": unit["content"],
            "unit_type": unit["unit_type"],
            "provenance": unit["provenance"],
            "source": source,
            "summary": unit.get("summary", unit["content"]),
            "branch": branch,
        }
        if unit.get("deadline"):
            payload["deadline"] = unit["deadline"]
        if unit.get("commitment_status"):
            payload["commitment_status"] = unit["commitment_status"]

        r = client.post("/remember", json=payload)
        r.raise_for_status()
        invalidate_state_cache(branch)

        new_hash = r.json().get("hash")
        if new_hash:
            _commit_entities(new_hash, unit)
        elif unit.get("entities"):
            logger.warning("commit_unit: no hash in /remember response — skipping entity commit")

        return True
    except Exception as e:
        logger.warning(f"commit_unit failed for {unit.get('content', '')!r}: {e!r}")
        return False

def supersede_unit(from_hash: str, unit: dict, source: str, branch: str = "main") -> bool:
    try:
        payload = {
            "from": from_hash,
            "content": unit["content"],
            "unit_type": unit["unit_type"],
            "provenance": unit["provenance"],
            "source": source,
            "summary": unit.get("summary", unit["content"]),
            "branch": branch,
        }
        if unit.get("deadline"):
            payload["deadline"] = unit["deadline"]
        if unit.get("commitment_status"):
            payload["commitment_status"] = unit["commitment_status"]

        r = client.post("/supersede", json=payload)
        r.raise_for_status()
        invalidate_state_cache(branch)

        new_hash = r.json().get("hash")
        if new_hash:
            _commit_entities(new_hash, unit)
        elif unit.get("entities"):
            logger.warning("supersede_unit: no hash in /supersede response — skipping entity commit")

        return True
    except Exception as e:
        logger.warning(f"supersede_unit failed for {from_hash!r}: {e!r}")
        return False


def resolve_commitment(resolution: dict, source: str, branch: str) -> bool:
    """Marks an open commitment done/cancelled by superseding it with the
    same content under a new status — same versioning model every other
    update already uses; the old "open" version stays in history,
    genuinely resolved, not deleted."""
    unit = resolution["unit"]
    updated = {
        "content": unit["content"],
        "unit_type": "commitment",
        "provenance": unit.get("provenance", "stated"),
        "summary": f"Commitment marked {resolution['status']}: {unit['content']}",
        "deadline": unit.get("deadline"),
        "commitment_status": resolution["status"],
    }
    return supersede_unit(unit["hash"], updated, source, branch)


def forget_unit(unit_hash: str, source: str, branch: str, summary: str) -> bool:
    """Soft-forget: drops the unit from HEAD, keeps it in history."""
    try:
        r = client.post(
            "/forget",
            json={"hash": unit_hash, "source": source, "summary": summary, "branch": branch},
        )
        r.raise_for_status()
        invalidate_state_cache(branch)
        return True
    except Exception as e:
        logger.warning(f"forget_unit failed for {unit_hash!r}: {e!r}")
        return False


def purge_unit(unit_hash: str) -> bool:
    """Hard-delete: the unit's content is genuinely removed from disk.
    Callers must have already soft-forgotten the unit first."""
    try:
        r = client.post("/purge", json={"hash": unit_hash})
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"purge_unit failed for {unit_hash!r}: {e!r}")
        return False

CORRECTION_CHECK_PROMPT = """The user has these standing behavioral
corrections that MUST be followed in every reply:

{corrections}

Here is a reply the assistant just generated:

---
{reply}
---

Judge strictly: does this reply violate any of the corrections above? A
correction only counts as violated if the reply had a real opportunity to
follow it and didn't — e.g. a formatting rule that applies to any reply,
or an explicit rule this reply's content clearly triggers. Don't flag a
correction as violated if it genuinely doesn't apply to this specific
reply's content.

Return JSON only:
{{"compliant": true}}
or
{{"compliant": false, "violated": ["<correction text>"], "guidance": "one line telling the assistant precisely what to fix"}}"""

CORRECTION_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "compliant": {"type": "boolean"},
        "violated": {"type": "array", "items": {"type": "string"}},
        "guidance": {"type": ["string", "null"]},
    },
    "required": ["compliant", "violated", "guidance"],
    "additionalProperties": False,
}


def check_correction_compliance(provider, corrections: list[dict], reply: str) -> dict:
    """Bounded judgment over a small, pre-filtered set of active
    corrections (already fetched deterministically from `known` — no
    extra memory round-trip). Fails OPEN, deliberately — unlike forget/
    resolve, which fail closed. Holding a reply indefinitely on a
    classifier error is worse than rarely missing a real violation."""
    corrections_block = "\n".join(f"- {c['content']}" for c in corrections)
    prompt = CORRECTION_CHECK_PROMPT.format(corrections=corrections_block, reply=reply)

    try:
        if provider.supports_structured_output:
            result = provider.complete_json(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Check."}],
                CAPTURE_MODEL, schema=CORRECTION_CHECK_SCHEMA, schema_name="correction_check",
            )
        else:
            raw = "".join(provider.stream(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Check."}],
                CAPTURE_MODEL,
            ))
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        logger.info(f"correction check: result={result}")
        return result
    except Exception as e:
        logger.warning(f"check_correction_compliance failed: {e!r} — treating as compliant (fail open)")
        return {"compliant": True, "violated": [], "guidance": None}