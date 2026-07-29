"""The one gate every turn passes through: does this message need a web
search at all? Used regardless of which skill (if any) is active. All
searches now route through agentic_search.py — there's no separate fixed
pipeline to route between, so this no longer classifies query complexity,
only whether a search is needed and what to search for."""

import json
import logging

from state import CAPTURE_MODEL as DECISION_MODEL

logger = logging.getLogger("search_decision")

SEARCH_DECISION_PROMPT = """Does this message need a real web search to answer well?
Say yes if either is true:
- Answering accurately requires current information — recent events, today's
  facts, specific current data, or anything that changes over time and your
  own knowledge could be outdated or wrong.
- The user is explicitly asking you to search, look up, find, or check
  something online, regardless of whether the topic itself seems time-sensitive.
  Trust the user's actual request even if the topic itself seems like something
  you'd already know.

Answer with JSON only:
{"search": true, "query": "concise search query"}
or
{"search": false, "query": null}

Do NOT search for: general knowledge, definitions, coding help, writing tasks,
math, opinions, or anything about the user themselves — unless the user
explicitly asked you to search/look it up online, per the rule above."""

SEARCH_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "search": {"type": "boolean"},
        "query": {"type": ["string", "null"]},
    },
    "required": ["search", "query"],
    "additionalProperties": False,
}


def _call(provider, system: str, user: str) -> str:
    return "".join(provider.stream(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        DECISION_MODEL,
    ))


def should_search(provider, message: str) -> dict | None:
    """Returns {"query": str} or None."""
    if provider.supports_structured_output:
        try:
            result = provider.complete_json(
                [{"role": "system", "content": SEARCH_DECISION_PROMPT},
                 {"role": "user", "content": message}],
                DECISION_MODEL,
                schema=SEARCH_DECISION_SCHEMA,
                schema_name="search_decision",
            )
            logger.info(f"should_search (structured): message={message!r} result={result}")
            if not result.get("search"):
                return None
            return {"query": result["query"]}
        except Exception as e:
            logger.warning(f"should_search (structured) failed: {e!r}")
            return None

    try:
        raw = _call(provider, SEARCH_DECISION_PROMPT, message)
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        logger.info(f"should_search (unstructured): message={message!r} raw={raw!r} parsed={parsed}")
        if not parsed.get("search"):
            return None
        return {"query": parsed["query"]}
    except Exception as e:
        logger.warning(f"should_search (unstructured) failed: {e!r}")
        return None