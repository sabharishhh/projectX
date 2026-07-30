"""Detects explicit time-travel queries — "what did I think about X in
March", "what did I believe before I changed my mind" — and resolves the
target date. Deliberately separate from normal memory injection (per
memory-engine-spec.md §6.6): when this fires, historical state REPLACES
the normal injected block for that turn rather than blending with it, so
stale/superseded context never leaks into an ordinary answer."""

import json
import logging
from datetime import datetime

from state import CAPTURE_MODEL as DECISION_MODEL

logger = logging.getLogger("time_travel")

TRIGGER_WORDS = (
    "used to", "back then", "at the time", "as of", "before i", "before you",
    "what did i think", "what did i believe", "what did i know",
    "previously thought", "previously believed", "in the past", "back in",
)

TIME_TRAVEL_PROMPT = """The user's message may be asking what was true in
their stored memory at some point in the PAST — not what's true now.

Current date/time: {now}

If this is genuinely a time-travel query (asking about a past state, not
just recalling an old fact that's still true), extract the target
date/time they mean, resolving relative phrasing ("last March", "back
when I started this job") into a concrete ISO datetime using the current
date above.

If retrospective intent is clear but no specific date is stated (e.g.
"what did I used to think" with no anchor), you MUST still resolve a
best-effort target rather than leaving it unresolved — default to some
months before the current date (e.g. 6 months back) as a reasonable
"the past, generally" anchor. NEVER return time_travel: true with a null
target — if you cannot commit to any target at all, return time_travel:
false instead.

Only fire on genuine retrospective intent — "what's my job" is NOT
time-travel even if the answer happens to reference the past; it wants
the CURRENT answer. Time-travel is specifically "as it was then," usually
signaled by "used to," "back then," "before I changed my mind," "as of
[date]."

Return JSON only:
{{"time_travel": true, "target": "2026-03-01T00:00:00Z"}}
or
{{"time_travel": false, "target": null}}"""

TIME_TRAVEL_SCHEMA = {
    "type": "object",
    "properties": {
        "time_travel": {"type": "boolean"},
        "target": {"type": ["string", "null"]},
    },
    "required": ["time_travel", "target"],
    "additionalProperties": False,
}


def mentions_time_travel(message: str) -> bool:
    return any(w in message.lower() for w in TRIGGER_WORDS)


def detect_time_travel_query(provider, message: str) -> str | None:
    """Returns an ISO datetime string if this is a genuine time-travel
    query, else None. Cheap trigger-word prefilter first — most turns
    never pay for the classification call."""
    if not mentions_time_travel(message):
        return None

    now = datetime.now().astimezone().isoformat()
    prompt = TIME_TRAVEL_PROMPT.format(now=now)

    try:
        if provider.supports_structured_output:
            result = provider.complete_json(
                [{"role": "system", "content": prompt}, {"role": "user", "content": message}],
                DECISION_MODEL, schema=TIME_TRAVEL_SCHEMA, schema_name="time_travel",
            )
            logger.info(f"time_travel (structured): message={message!r} result={result}")
        else:
            raw = "".join(provider.stream(
                [{"role": "system", "content": prompt}, {"role": "user", "content": message}],
                DECISION_MODEL,
            ))
            result = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            logger.info(f"time_travel (unstructured): message={message!r} result={result}")

        if not result.get("time_travel"):
            return None
        if not result.get("target"):
            logger.warning(f"time_travel=true but target unresolved for {message!r} — treating as non-match")
            return None
        return result["target"]
    except Exception as e:
        logger.warning(f"detect_time_travel_query failed: {e!r}")
        return None