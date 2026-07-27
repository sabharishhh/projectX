import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import extraction
import search as discovery

import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("research")


from state import CAPTURE_MODEL as DISTILL_MODEL
READ_TOP_N = 3  # how many discovered pages actually get fetched + read

SEARCH_DECISION_PROMPT = """Does answering this message require current information
from the web — recent events, today's facts, specific current data, or anything
that changes over time?

Answer with JSON only:
{"search": true, "query": "concise search query"}
or
{"search": false}

Do NOT search for: general knowledge, definitions, coding help, writing tasks,
math, opinions, or anything about the user themselves."""

DISTILL_PROMPT = """The user asked: "{query}"

Full text of a web page found while researching this:
---
{page_text}
---

In 2-4 sentences, extract only what's relevant to the query. If nothing on
this page is relevant, respond exactly: "Nothing relevant found on this page."
Do not add information that isn't in the text above."""


def _call(provider, system: str, user: str) -> str:
    return "".join(provider.stream(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        DISTILL_MODEL,
    ))


def should_search(provider, message: str) -> str | None:
    try:
        raw = _call(provider, SEARCH_DECISION_PROMPT, message)
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return parsed.get("query") if parsed.get("search") else None
    except Exception as e:
        logger.warning(f"should_search failed to parse: {e!r}")
        return None


def _read_and_distill(provider, query: str, result: dict) -> dict | None:
    page = extraction.extract_page(result["url"])
    logger.info(f"extraction result for {result['url']}: method={page['method']}")
    if not page["text"]:
        return None

    text = page["text"][:6000]
    try:
        summary = _call(provider, DISTILL_PROMPT.format(query=query, page_text=text), "Summarize.")
    except Exception as e:
        logger.warning(f"distill failed for {result['url']}: {e!r}")
        return None

    if "nothing relevant" in summary.lower():
        return None

    return {
        "title": result.get("title", result["url"]),
        "url": result["url"],
        "summary": summary.strip(),
        "extraction_method": page["method"],
    }


def research(provider, query: str, discover_limit: int = 5, read_top: int = READ_TOP_N) -> list[dict]:
    """Discover candidates, then read + distill the top few in parallel."""
    candidates = discovery.discover(query, limit=discover_limit)
    if not candidates:
        return []

    to_read = candidates[:read_top]
    distilled = []
    with ThreadPoolExecutor(max_workers=read_top) as pool:
        futures = [pool.submit(_read_and_distill, provider, query, r) for r in to_read]
        for f in as_completed(futures):
            result = f.result()
            if result:
                distilled.append(result)
    return distilled


def format_for_context(query: str, distilled: list[dict]) -> str:
    if not distilled:
        return ""
    lines = [
        f'Web research on "{query}":',
        "Cite these sources inline using [1], [2], etc. when you use information "
        "from them. Only cite a source for a claim it actually supports.",
        "",
    ]
    for i, d in enumerate(distilled, 1):
        lines.append(f"[{i}] {d['title']} ({d['url']})\n{d['summary']}")
    return "\n".join(lines)