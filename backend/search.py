import os
import httpx

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "searxng")  # searxng | tavily
TAVILY_KEY = os.getenv("TAVILY_API_KEY")

SEARCH_DECISION_PROMPT = """Does answering this message require current information
from the web — recent events, today's facts, specific current data, or anything
that changes over time?

Answer with JSON only:
{"search": true, "query": "concise search query"}
or
{"search": false}

Do NOT search for: general knowledge, definitions, coding help, writing tasks,
math, opinions, or anything about the user themselves."""


def should_search(provider, message: str) -> str | None:
    """Returns a search query, or None if no search needed."""
    import json
    try:
        raw = "".join(provider.stream(
            [
                {"role": "system", "content": SEARCH_DECISION_PROMPT},
                {"role": "user", "content": message},
            ],
            os.getenv("CAPTURE_MODEL", "gpt-5.4-mini"),
        ))
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return parsed.get("query") if parsed.get("search") else None
    except Exception:
        return None

def _searxng(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        f"{SEARXNG_URL}/search",
        params={"q": query, "format": "json"},
        timeout=10.0,
    )
    r.raise_for_status()
    results = r.json().get("results", [])[:limit]
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
        for x in results
    ]


def _tavily(query: str, limit: int) -> list[dict]:
    """BYOK premium option — user's own key, their own cost."""
    r = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": TAVILY_KEY, "query": query, "max_results": limit},
        timeout=10.0,
    )
    r.raise_for_status()
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
        for x in r.json().get("results", [])
    ]


def search(query: str, limit: int = 5) -> list[dict]:
    """Returns [] on any failure — search is additive, never fatal to a turn."""
    try:
        if SEARCH_PROVIDER == "tavily" and TAVILY_KEY:
            return _tavily(query, limit)
        return _searxng(query, limit)
    except Exception:
        return []


def format_for_context(query: str, results: list[dict]) -> str:
    if not results:
        return ""
    lines = [f"Web search results for \"{query}\":"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)