import os
import json
import logging

import httpx
from state import CAPTURE_MODEL

logger = logging.getLogger("forgetting")

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")

FORGET_TRIGGER_WORDS = (
    "forget", "remove", "delete", "erase", "unremember",
    "stop remembering", "don't remember", "no longer", "drop memory", "drop memories"
)

FORGET_PATTERN_PROMPT = """The user's message may be asking to forget one or
more previously stored facts. If so, write a regex pattern that would match
the relevant fact(s) by content — think about what words would appear in
matching facts, not just the literal words in the user's message (e.g. for
"forget stuff about movies", the pattern should catch actor/director names,
"film", "movie", etc., not just the literal word "movies").

If this message isn't actually a forget request, or you can't confidently
write a pattern for it, say so — don't guess a pattern that might over-match.

Return JSON only:
{"pattern": "movie|film|director|actor names...", "confident": true}
or
{"pattern": null, "confident": false}"""

FORGET_PATTERN_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": ["string", "null"]},
        "confident": {"type": "boolean"},
    },
    "required": ["pattern", "confident"],
    "additionalProperties": False,
}

FORGET_CONFIRM_PROMPT = """The user said: "{message}"

A pattern search found these stored facts that might be relevant:
{candidates}

Which of these, if any, does the user actually want forgotten? Be strict —
a fact only sharing a keyword with the search pattern isn't automatically
what they meant. Only include facts that genuinely match their intent.

Return JSON only:
{{"confirmed": ["a1b2c3d4", "e5f6g7h8"]}}
or
{{"confirmed": []}}"""

FORGET_CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["confirmed"],
    "additionalProperties": False,
}


def _generate_pattern(provider, message: str) -> dict | None:
    try:
        result = provider.complete_json(
            [{"role": "system", "content": FORGET_PATTERN_PROMPT}, {"role": "user", "content": message}],
            CAPTURE_MODEL, schema=FORGET_PATTERN_SCHEMA, schema_name="forget_pattern",
        )
        logger.info(f"forget pattern: message={message!r} result={result}")
        return result
    except Exception as e:
        logger.warning(f"forget pattern generation failed: {e!r}")
        return None


def _search_memory(pattern: str, branch: str) -> list[dict]:
    """Same /search endpoint memory_search already uses — deterministic
    regex match in Rust, not LLM judgment."""
    try:
        r = httpx.get(f"{MEMORY_URL}/search", params={"pattern": pattern, "branch": branch}, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"forget pattern search failed on branch={branch!r}: {e!r}")
        return []


def _confirm_candidates(provider, message: str, candidates: list[dict], pattern: str) -> list[dict]:
    if not candidates:
        return []
    listing = "\n".join(f"- [{c['hash'][:8]}] {c['content']}" for c in candidates)
    try:
        result = provider.complete_json(
            [{"role": "system", "content": FORGET_CONFIRM_PROMPT.format(message=message, candidates=listing)},
             {"role": "user", "content": message}],
            CAPTURE_MODEL, schema=FORGET_CONFIRM_SCHEMA, schema_name="forget_confirm",
        )
        logger.info(f"forget confirm: result={result}")
        confirmed_hashes = set(result.get("confirmed", []))
        return [
            {"unit": c, "reason": f"matched pattern: {pattern}"}
            for c in candidates if c["hash"][:8] in confirmed_hashes
        ]
    except Exception as e:
        logger.warning(f"forget confirmation failed: {e!r}")
        return []  # fail closed — if confirmation breaks, show nothing rather than everything


def detect_forget_request(provider, message: str, known: list[dict], branches: list[str] = ("main",)) -> list[dict]:
    """Three deterministic-in-the-middle stages: (1) model writes a search
    pattern for what it thinks the user wants forgotten, (2) code executes
    that pattern as a real regex match via the memory engine — grounded,
    not model recall, (3) model confirms only among the actual matches
    found, narrowing a broad/over-matching pattern down to real intent.
    Returns [] at any stage that doesn't confidently produce something —
    never guesses."""
    if not known:
        return []
    if not any(w in message.lower() for w in FORGET_TRIGGER_WORDS):
        return []

    pattern_result = _generate_pattern(provider, message)
    if not pattern_result or not pattern_result.get("confident") or not pattern_result.get("pattern"):
        return []
    pattern = pattern_result["pattern"]

    hits = []
    for b in branches:
        hits.extend({**h, "branch": b} for h in _search_memory(pattern, b))
    if not hits:
        return []

    return _confirm_candidates(provider, message, hits, pattern)

def mentions_forgetting(message: str) -> bool:
    return any(w in message.lower() for w in FORGET_TRIGGER_WORDS)