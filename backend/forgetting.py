import os
import json
from state import CAPTURE_MODEL

FORGET_TRIGGER_WORDS = (
    "forget", "remove", "delete", "erase", "unremember",
    "stop remembering", "don't remember", "no longer",
)

FORGET_DECISION_PROMPT = """Does this message ask the assistant to forget, stop
remembering, or remove something specific it was told before?

Known facts:
{known}

Only match if the request is genuinely about forgetting something already known —
not a new fact, not a question, not ordinary conversation. Require a clear,
specific match to one or more known facts. If you're not confident which fact
they mean, don't guess — leave it out.

Return JSON only:
{{"forget": [{{"hash": "a1b2c3d4", "reason": "one line on why this matches"}}]}}
or
{{"forget": []}}"""


def _known_facts_block(units: list[dict]) -> str:
    if not units:
        return "(none yet)"
    return "\n".join(f"- [{u['hash'][:8]}] {u['content']}" for u in units)


def detect_forget_request(provider, message: str, known: list[dict]) -> list[dict]:
    """Returns candidate facts the user may want forgotten. Empty list if
    nothing confidently matches — never guesses. Nothing is deleted here;
    this only detects intent."""
    if not known:
        return []
    # cheap pre-filter, no LLM call — the vast majority of turns have
    # nothing to do with forgetting anything, and this avoids paying for
    # a judgment call on every single message just to rule that out
    if not any(w in message.lower() for w in FORGET_TRIGGER_WORDS):
        return []
    try:
        raw = "".join(provider.stream(
            [
                {"role": "system", "content": FORGET_DECISION_PROMPT.format(known=_known_facts_block(known))},
                {"role": "user", "content": message},
            ],
            CAPTURE_MODEL,
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        matches = []
        for m in parsed.get("forget", []):
            target = next((k for k in known if k["hash"].startswith(m.get("hash", ""))), None)
            if target:
                matches.append({"unit": target, "reason": m.get("reason", "")})
        return matches
    except Exception:
        return []