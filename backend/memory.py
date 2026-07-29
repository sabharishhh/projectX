import os
import logging
import httpx

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("memory")

MEMORY_URL = os.getenv("MEMORY_URL", "http://127.0.0.1:8100")
REQUEST_TIMEOUT = 20.0

IDENTITY = (
    "You are projectX, a personal AI assistant. Sabharish is your creator. You were born on 24 July 2026."
    "If asked who you are, you're projectX."
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

FORGET_CAPABILITY = (
    "You do have the ability to forget or delete stored memory, mediated "
    "through a confirmation prompt the user sees in the interface — never "
    "claim you're unable to forget or delete something."
)

def fetch_state(branch: str = "main") -> list[dict]:
    try:
        r = httpx.get(f"{MEMORY_URL}/state", params={"branch": branch}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_state failed for branch={branch!r}: {e!r}")
        return []

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

def fetch_branches() -> list[str]:
    try:
        r = httpx.get(f"{MEMORY_URL}/branches", timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"fetch_branches failed: {e!r}")
        return []

def build_system_message(units: list[dict], skill_prompt: str | None = None) -> dict:
    parts = [IDENTITY, JUDGMENT_GUIDANCE, FORGET_CAPABILITY]

    if skill_prompt:
        parts.append(skill_prompt)

    if units:
        lines = []
        for u in units:
            prefix = "(uncertain) " if u["provenance"] == "inferred" else ""
            lines.append(f"- [{u['unit_type']}] {prefix}{u['content']}")
        parts.append(
            "What you know about this user, from previous conversations:\n"
            + "\n".join(lines)
            + "\n\nUse this naturally. Don't recite it back or mention that you "
            "have stored memory unless asked."
        )

    return {"role": "system", "content": "\n\n".join(parts)}