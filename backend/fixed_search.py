"""One-shot fixed search pipeline: discover candidates, read the top few,
summarize each independently. No model judgment mid-loop — the alternative
to agentic_search.py's iterative model-driven loop. Used when the query is
judged "simple" (search_decision.py) or when the provider can't do tool
calling at all."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import extraction
import search as discovery

import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("fixed_search")

from state import CAPTURE_MODEL as DISTILL_MODEL
READ_TOP_N = 3  # how many discovered pages actually get fetched + read

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

    # Dedupe by URL before citation numbers get assigned in
    # format_for_context — as_completed() returns in completion order, not
    # discovery order, and a URL appearing twice (same page surfaced under
    # two distinct discover() results) would otherwise get two different
    # [n] numbers instead of one reused number, the same guard
    # agentic_search.py's citation sources dict already provides.
    seen_urls = set()
    deduped = []
    for d in distilled:
        if d["url"] not in seen_urls:
            seen_urls.add(d["url"])
            deduped.append(d)
    return deduped


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