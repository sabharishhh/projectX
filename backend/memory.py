import os
import time
import httpx
import logging

from memory_client import client

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("memory")

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")
REQUEST_TIMEOUT = 20.0

IDENTITY = (
    "You are loki — a personal AI assistant with a name that's an invitation, not "
    "a warning. You carry a bit of your namesake's wit: clever, quietly theatrical, "
    "quick with a dry aside or an unexpected turn of phrase. A little mischief in "
    "how you say things is welcome — a silver tongue, not a straight face.\n\n"
    "But the trickery is all in the delivery, never in the substance. You are "
    "unfailingly honest and direct about anything that actually matters — facts, "
    "memory, commitments, what you can and can't do. No games with the truth, only "
    "with the phrasing of it. If asked who you are, you're loki — say so plainly, "
    "with a flourish if the moment earns it, not a monologue every time.\n\n"
    "Keep the wit light-touch, not constant — one well-placed clever line lands "
    "harder than personality crammed into every sentence. Match the user's own "
    "register: brief and practical gets brief and practical with just a glint of "
    "character; save the fuller flourish for moments that actually invite it."
)

JUDGMENT_GUIDANCE = (
    "For messages where the user shares something about themselves — an "
    "experience, opinion, memory, or fact about their life — respond to the "
    "content directly, in plain conversational prose. Do not rewrite, "
    "correct, or offer alternate phrasings of what they said, and do not "
    "ask what 'version' or tone they want. A well-formed sentence is not a "
    "draft.\n\n"
    "Only edit, correct, or offer phrasing alternatives when the message "
    "itself asks for writing help — requesting a rewrite, wording "
    "assistance, or explicit feedback on a draft."
)

CONSISTENCY_GUIDANCE = (
    "The facts and commitments listed above reflect the CURRENT state of "
    "memory, freshly fetched this turn. If anything you said earlier in "
    "this conversation conflicts with what's listed now — because the "
    "user edited, deleted, or resolved something since then — treat the "
    "current list as correct and your earlier statement as outdated. "
    "Don't insist on your own prior turn over what's actually true now."
)

FORGET_CAPABILITY = (
    "You do have the ability to forget or delete stored memory, mediated "
    "through a confirmation prompt the user sees in the interface — never "
    "claim you're unable to forget or delete something.\n\n"
    "The same applies to commitment resolution: closing, cancelling, or "
    "marking a commitment done is mediated through a confirmation card "
    "that appears AFTER your reply, requiring the user's explicit click "
    "to actually take effect — even if the user just confirmed it "
    "verbally ('yes, close it'). You cannot see whether that card will "
    "appear or what it will say while writing this reply, so never state "
    "a commitment as already closed, resolved, or changed — phrase it as "
    "proposed, not done. Say something like 'I've proposed marking that "
    "closed — confirm below,' never 'Closed' or 'Done.'"
)

_state_cache: dict[str, tuple[list[dict], float]] = {}
CACHE_TTL_SECONDS = 10.0

def fetch_state(branch: str = "main") -> list[dict]:
    cached = _state_cache.get(branch)
    if cached and (time.monotonic() - cached[1]) < CACHE_TTL_SECONDS:
        return list(cached[0])
    try:
        r = client.get("/state", params={"branch": branch})
        r.raise_for_status()
        units = r.json()
        _state_cache[branch] = (units, time.monotonic())
        return list(units)
    except Exception as e:
        logger.warning(f"fetch_state failed for branch={branch!r}: {e!r}")
        return []

def fetch_state_at_time(branch: str, target_iso: str) -> dict:
    """Returns {"resolved_at": iso_or_None, "units": [...]}. Deliberately
    NOT cached, unlike fetch_state — this is a rare, explicit-intent mode,
    not a hot path."""
    try:
        r = client.post("/state-at-time", json={"branch": branch, "target": target_iso})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_state_at_time failed for branch={branch!r} target={target_iso!r}: {e!r}")
        return {"resolved_at": None, "units": []}

def fetch_relevant(query: str, branch: str = "main", max_units: int = 12, boost_types: list[str] | None = None) -> list[dict]:
    try:
        r = httpx.post(
            f"{MEMORY_URL}/retrieve",
            json={"query": query, "max_units": max_units, "branch": branch, "boost_types": boost_types or []},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_relevant failed for branch={branch!r}: {e!r}")
        return []

def invalidate_state_cache(branch: str) -> None:
    """Call after any write that changes a branch's live state — commit,
    supersede, or forget. fetch_state() re-fetches fresh on next call for
    that branch only; other branches are untouched."""
    _state_cache.pop(branch, None)

def fetch_branches() -> list[str]:
    try:
        r = httpx.get(f"{MEMORY_URL}/branches", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_branches failed: {e!r}")
        return []

def build_system_message(units: list[dict], skill_prompt: str | None = None,
                          include_identity: bool = True) -> list[dict]:
    """Returns TWO messages instead of one joined string — the static
    identity/guidance/skill block first, the per-turn recalled-facts block
    second. Splitting these is what actually makes the static block a
    stable, cacheable prefix: joining them into one string (the previous
    shape) meant the 'static' block was never byte-identical turn to turn,
    since the facts appended at the end changed the whole string's bytes
    every single time, defeating caching regardless of _with_time's fix."""
    parts = [IDENTITY, JUDGMENT_GUIDANCE, FORGET_CAPABILITY, CONSISTENCY_GUIDANCE] if include_identity \
        else [JUDGMENT_GUIDANCE, FORGET_CAPABILITY, CONSISTENCY_GUIDANCE]
    if skill_prompt:
        parts.append(skill_prompt)

    messages = [{"role": "system", "content": "\n\n".join(parts)}]

    if units:
        lines = []
        for u in units:
            prefix = "(uncertain) " if u["provenance"] == "inferred" else ""
            lines.append(f"- [{u['unit_type']}] {prefix}{u['content']}")
        messages.append({
            "role": "system",
            "content": ("What you know about this user, from previous conversations:\n"
                        + "\n".join(lines)
                        + "\n\nUse this naturally. Don't recite it back or mention that you "
                        "have stored memory unless asked."),
        })

    return messages

