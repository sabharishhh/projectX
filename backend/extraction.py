import re

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MIN_USEFUL_LENGTH = 200  # below this, treat extraction as failed, try the next tier


def fetch_html(url: str, timeout: float = 8.0) -> str | None:
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": BROWSER_UA})
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _via_trafilatura(html: str) -> str | None:
    try:
        import trafilatura
        return trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception:
        return None


def _via_readability(html: str) -> str | None:
    try:
        from readability import Document
        summary_html = Document(html).summary()
        text = re.sub("<[^<]+?>", " ", summary_html)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return None


def _via_playwright(url: str) -> str | None:
    """Last resort for JS-rendered pages. No-ops silently if playwright
    isn't installed — this tier is optional, not required."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            html = browser.new_page().goto(url, timeout=15000, wait_until="networkidle") and browser.contexts[0].pages[0].content()
            browser.close()
        return _via_trafilatura(html) if html else None
    except Exception:
        return None


def extract_page(url: str) -> dict:
    """Returns {url, text, method}. text is None if every tier failed."""
    html = fetch_html(url)
    if html:
        text = _via_trafilatura(html)
        if text and len(text) >= MIN_USEFUL_LENGTH:
            return {"url": url, "text": text, "method": "trafilatura"}

        text = _via_readability(html)
        if text and len(text) >= MIN_USEFUL_LENGTH:
            return {"url": url, "text": text, "method": "readability"}

    text = _via_playwright(url)
    if text and len(text) >= MIN_USEFUL_LENGTH:
        return {"url": url, "text": text, "method": "playwright"}

    return {"url": url, "text": None, "method": "failed"}