"""The one gate every turn passes through: does this message need a web
search, and if so, does it need one lookup or several? Used regardless of
which skill (if any) is active, and regardless of which search path
(fixed_search.py or agentic_search.py) ends up handling it."""

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

If search is needed, also judge how complex the lookup is:
- "simple": one clear fact, likely answered directly by a top search result
  (e.g. "what's the weather in X", "what's the latest version of Y").
- "iterative": genuine ambiguity to resolve (e.g. vague dates like "last
  weekend"), multiple entities to compare, or an answer that needs
  cross-referencing more than one source to trust.

Answer with JSON only:
{"search": true, "query": "concise search query", "complexity": "simple"}
or
{"search": true, "query": "concise search query", "complexity": "iterative"}
or
{"search": false, "query": null, "complexity": null}

Do NOT search for: general knowledge, definitions, coding help, writing tasks,
math, opinions, or anything about the user themselves — unless the user
explicitly asked you to search/look it up online, per the rule above."""

SEARCH_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "search": {"type": "boolean"},
        "query": {"type": ["string", "null"]},
        "complexity": {"type": ["string", "null"], "enum": ["simple", "iterative", None]},
    },
    "required": ["search", "query", "complexity"],
    "additionalProperties": False,
}


def _call(provider, system: str, user: str) -> str:
    return "".join(provider.stream(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        DECISION_MODEL,
    ))


def should_search(provider, message: str) -> dict | None:
    """Returns {"query": str, "complexity": "simple"|"iterative"} or None."""
    if hasattr(provider, "complete_json"):
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
            return {"query": result["query"], "complexity": result.get("complexity") or "simple"}
        except Exception as e:
            logger.warning(f"should_search (structured) failed: {e!r}")
            return None

    try:
        raw = _call(provider, SEARCH_DECISION_PROMPT, message)
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        logger.info(f"should_search (unstructured): message={message!r} raw={raw!r} parsed={parsed}")
        if not parsed.get("search"):
            return None
        return {"query": parsed["query"], "complexity": parsed.get("complexity") or "simple"}
    except Exception as e:
        logger.warning(f"should_search (unstructured) failed: {e!r}")
        return None