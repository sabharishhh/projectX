import asyncio
import logging

from crawl4ai import AsyncWebCrawler

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("extraction")

MIN_USEFUL_LENGTH = 200


async def _crawl(url: str) -> str | None:
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
        if result.success and result.markdown:
            return result.markdown.fit_markdown or result.markdown.raw_markdown
    return None


def extract_page(url: str) -> dict:
    """Returns {url, text, method}. text is None if extraction failed."""
    try:
        text = asyncio.run(_crawl(url))
    except Exception as e:
        logger.warning(f"crawl4ai failed for {url}: {e!r}")
        text = None

    if text and len(text) >= MIN_USEFUL_LENGTH:
        return {"url": url, "text": text, "method": "crawl4ai"}

    logger.warning(f"extraction failed or too short for {url}")
    return {"url": url, "text": None, "method": "failed"}