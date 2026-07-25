import os

import httpx

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "searxng")  # searxng | tavily | exa
TAVILY_KEY = os.getenv("TAVILY_API_KEY")
EXA_KEY = os.getenv("EXA_API_KEY")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _searxng(query: str, limit: int) -> list[dict]:
    r = httpx.get(
        f"{SEARXNG_URL}/search",
        params={"q": query, "format": "json"},
        headers={"User-Agent": BROWSER_UA},
        timeout=10.0,
    )
    r.raise_for_status()
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
        for x in r.json().get("results", [])[:limit]
    ]


def _tavily(query: str, limit: int) -> list[dict]:
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


def _exa(query: str, limit: int) -> list[dict]:
    r = httpx.post(
        "https://api.exa.ai/search",
        json={"query": query, "numResults": limit, "type": "neural"},
        headers={"x-api-key": EXA_KEY},
        timeout=10.0,
    )
    r.raise_for_status()
    return [
        {"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("text", "") or ""}
        for x in r.json().get("results", [])
    ]


def discover(query: str, limit: int = 5) -> list[dict]:
    """Find candidate URLs. Returns [] on any failure — never fatal to a turn."""
    try:
        if SEARCH_PROVIDER == "tavily" and TAVILY_KEY:
            return _tavily(query, limit)
        if SEARCH_PROVIDER == "exa" and EXA_KEY:
            return _exa(query, limit)
        return _searxng(query, limit)
    except Exception:
        return []