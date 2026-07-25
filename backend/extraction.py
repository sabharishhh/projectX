import logging
import re

import httpx

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("extraction")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MIN_USEFUL_LENGTH = 200


def fetch_html(url: str, timeout: float = 8.0) -> str | None:
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": BROWSER_UA})
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"fetch_html failed for {url}: {e!r}")
        return None


def _via_trafilatura(html: str) -> str | None:
    try:
        import trafilatura
        return trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception as e:
        logger.warning(f"trafilatura failed: {e!r}")
        return None


def _via_readability(html: str) -> str | None:
    try:
        from readability import Document
        summary_html = Document(html).summary()
        text = re.sub("<[^<]+?>", " ", summary_html)
        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        logger.warning(f"readability failed: {e!r}")
        return None


def _via_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--disable-http2"])
            page = browser.new_page(user_agent=BROWSER_UA)
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()
        return _via_trafilatura(html) if html else None
    except Exception as e:
        logger.warning(f"playwright failed for {url}: {e!r}")
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
        logger.info(f"content extraction too short/empty for {url}, trying playwright")

    text = _via_playwright(url)
    if text and len(text) >= MIN_USEFUL_LENGTH:
        return {"url": url, "text": text, "method": "playwright"}

    logger.warning(f"all extraction tiers failed for {url}")
    return {"url": url, "text": None, "method": "failed"}