import os
import json
import logging

from state import CAPTURE_MODEL
from memory_client import client
from memory import invalidate_state_cache

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("capture")

CAPTURE_MODEL = os.getenv("CAPTURE_MODEL", "gpt-5.4-mini")

CAPTURE_PROMPT = """You extract durable facts about the user from a conversation turn.

Capture ONLY things that will still be true and useful in a future conversation:
- identity: stable facts about who they are (role, background, location)
- preference: how they like things done (style, tools, tastes)
- project: something ongoing they're working on
- decision: a specific choice they made, and why
- relationship: people or entities in their life

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

If a new fact DIRECTLY CONTRADICTS one of the known facts above — same subject,
different value — add "supersedes": "<the 8-char id in brackets>" to that unit.
Only for real contradictions, where both cannot be true at once. Do NOT use it
for facts that merely relate to, extend, or sit alongside an existing one.

Return JSON only, no other text:
{{"units": [{{"content": "...", "unit_type": "preference", "provenance": "stated", "summary": "short plain-language note on what changed", "branch": "main", "supersedes": "a1b2c3d4"}}]}}

Omit "supersedes" entirely when the fact is new rather than a replacement.
Return {{"units": []}} if nothing is worth remembering."""


def _known_facts_block(units: list[dict]) -> str:
    if not units:
        return "(none yet)"
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)


def extract_units(provider, user_message: str, assistant_message: str,
                  known: list[dict], branches: list[str]) -> list[dict]:
    prompt = CAPTURE_PROMPT.format(
        known=_known_facts_block(known),
        branches=", ".join(branches),
    )
    exchange = f"User: {user_message}\n\nAssistant: {assistant_message}"

    try:
        raw = "".join(provider.stream(
            [{"role": "system", "content": prompt}, {"role": "user", "content": exchange}],
            CAPTURE_MODEL,
        ))

        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        units = parsed.get("units", [])
        logger.info(f"capture proposed: exchange={exchange!r} units={units}")

        for u in units:
            if u.get("branch") not in branches:
                u["branch"] = "main"
        return units
    except Exception as e:
        logger.warning(f"extract_units failed to parse: {e!r}")
        return []


def commit_unit(unit: dict, source: str, branch: str = "main") -> bool:
    try:
        r = client.post(
            f"/remember",
            json={
                "content": unit["content"],
                "unit_type": unit["unit_type"],
                "provenance": unit["provenance"],
                "source": source,
                "summary": unit.get("summary", unit["content"]),
                "branch": branch,
            },
        )
        r.raise_for_status()
        invalidate_state_cache(branch)
        return True
    except Exception as e:
        logger.warning(f"commit_unit failed for {unit.get('content', '')!r}: {e!r}")
        return False

def supersede_unit(from_hash: str, unit: dict, source: str, branch: str = "main") -> bool:
    try:
        r = client.post(
            f"/supersede",
            json={
                "from": from_hash,
                "content": unit["content"],
                "unit_type": unit["unit_type"],
                "provenance": unit["provenance"],
                "source": source,
                "summary": unit.get("summary", unit["content"]),
                "branch": branch,
            },
        )
        r.raise_for_status()
        invalidate_state_cache(branch)
        return True
    except Exception as e:
        logger.warning(f"supersede_unit failed for {from_hash!r}: {e!r}")
        return False

def forget_unit(unit_hash: str, source: str, branch: str, summary: str) -> bool:
    """Soft-forget: drops the unit from HEAD, keeps it in history."""
    try:
        r = client.post(
            f"/forget",
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
        r = client.post(f"/purge", json={"hash": unit_hash})
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"purge_unit failed for {unit_hash!r}: {e!r}")
        return False