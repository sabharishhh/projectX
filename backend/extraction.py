import logging
import threading

from crawl4ai import AsyncWebCrawler

from background_loop import BackgroundEventLoop

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("extraction")

MIN_USEFUL_LENGTH = 200
CRAWL_TIMEOUT_SECONDS = 20.0


class _CrawlerManager:
    """One AsyncWebCrawler, one background event loop, shared across every
    extract_page() call — replaces the previous per-call browser launch.
    A wedged/crashed browser is detected via per-call timeout and replaced,
    instead of silently taking down every subsequent extraction."""

    def __init__(self):
        self._bg = BackgroundEventLoop()
        self._crawler: AsyncWebCrawler | None = None
        self._lock = threading.Lock()

    def start(self):
        async def _do():
            crawler = AsyncWebCrawler()
            await crawler.start()
            return crawler
        self._crawler = self._bg.run(_do())
        logger.info("crawler started")

    def close(self):
        if self._crawler is None:
            return
        try:
            self._bg.run(self._crawler.close(), timeout=10.0)
        except Exception as e:
            logger.warning(f"crawler close failed: {e!r}")
        self._crawler = None
        self._bg.stop()

    def _respawn(self):
        with self._lock:
            logger.warning("respawning crawler after failure")
            old, self._crawler = self._crawler, None
            if old is not None:
                try:
                    self._bg.run(old.close(), timeout=5.0)
                except Exception:
                    pass  # already dead — that's why we're here
            self.start()

    def crawl(self, url: str) -> str | None:
        if self._crawler is None:
            with self._lock:
                if self._crawler is None:
                    self.start()
        try:
            async def _do():
                result = await self._crawler.arun(url=url)
                if result.success and result.markdown:
                    return result.markdown.fit_markdown or result.markdown.raw_markdown
                return None
            return self._bg.run(_do(), timeout=CRAWL_TIMEOUT_SECONDS)
        except Exception as e:
            logger.warning(f"crawl failed for {url}: {e!r}")
            self._respawn()
            return None


_manager: _CrawlerManager | None = None


def _get_manager() -> _CrawlerManager:
    global _manager
    if _manager is None:
        _manager = _CrawlerManager()
    return _manager


def start():
    """Call once at app startup."""
    _get_manager().start()


def close():
    """Call once at app shutdown."""
    if _manager is not None:
        _manager.close()


def extract_page(url: str) -> dict:
    """Returns {url, text, method}. text is None if extraction failed. Same
    contract as before — research.py needs no changes."""
    text = _get_manager().crawl(url)
    if text and len(text) >= MIN_USEFUL_LENGTH:
        return {"url": url, "text": text, "method": "crawl4ai"}
    logger.warning(f"extraction failed or too short for {url}")
    return {"url": url, "text": None, "method": "failed"}