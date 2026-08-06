import logging
import threading

from crawl4ai import AsyncWebCrawler

from background_loop import BackgroundEventLoop

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("extraction")

MIN_USEFUL_LENGTH = 200
CRAWL_TIMEOUT_SECONDS = 20.0

# Status codes and error-message substrings that indicate an anti-bot
# block specifically, distinguished from an ordinary failure (timeout,
# DNS, dead link) — verified against crawl4ai's actual CrawlResult schema
# (status_code, error_message fields), not guessed. This distinction
# matters because a paid-fallback hook should only fire on confirmed
# blocks, not on every failure — paying for a fallback on a genuinely
# dead URL would be wasted cost that also masks the real problem.
BLOCK_STATUS_CODES = {403, 429, 503}
BLOCK_MESSAGE_MARKERS = ("cloudflare", "captcha", "anti-bot", "access denied", "blocked")

# Pluggable fallback slot — None by default (no fallback configured).
# Wire in a paid unlocking service (e.g. ScraperAPI, Bright Data Web
# Unlocker) here later if block frequency in your own logs justifies the
# cost: FALLBACK_FETCHER = lambda url: my_provider_fetch(url). Deliberately
# not hardcoded to any specific vendor — that's a cost/vendor decision to
# make with evidence (how often blocks actually happen), not something to
# bake in speculatively.
FALLBACK_FETCHER = None


def _is_block(result) -> bool:
    status = getattr(result, "status_code", None)
    if status in BLOCK_STATUS_CODES:
        return True
    msg = (getattr(result, "error_message", None) or "").lower()
    return any(marker in msg for marker in BLOCK_MESSAGE_MARKERS)


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
                    pass
            self.start()

    def crawl(self, url: str) -> tuple[str | None, bool]:
        """Returns (text, was_blocked). was_blocked is only meaningful
        when text is None — distinguishes a confirmed anti-bot block from
        any other failure mode (timeout, dead link, crawler crash)."""
        if self._crawler is None:
            with self._lock:
                if self._crawler is None:
                    self.start()
        try:
            async def _do():
                result = await self._crawler.arun(url=url)
                if result.success and result.markdown:
                    text = result.markdown.fit_markdown or result.markdown.raw_markdown
                    return text, False
                return None, _is_block(result)
            return self._bg.run(_do(), timeout=CRAWL_TIMEOUT_SECONDS)
        except Exception as e:
            logger.warning(f"crawl failed for {url}: {e!r}")
            self._respawn()
            return None, False


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
    """Returns {url, text, method}. text is None if extraction failed.
    method distinguishes 'crawl4ai' (success), 'fallback' (block detected,
    FALLBACK_FETCHER recovered it), 'blocked' (block detected, no fallback
    configured or fallback also failed), and 'failed' (any other failure).
    This is a superset of the old contract — old callers checking only
    `text`/truthiness see no change; new callers can branch on `method`
    if they want to distinguish "permanently dead" from "blocked, might
    work via a different route"."""
    text, was_blocked = _get_manager().crawl(url)

    if text and len(text) >= MIN_USEFUL_LENGTH:
        return {"url": url, "text": text, "method": "crawl4ai"}

    if was_blocked:
        logger.warning(f"extraction blocked (anti-bot) for {url}")
        if FALLBACK_FETCHER is not None:
            try:
                fallback_text = FALLBACK_FETCHER(url)
                if fallback_text and len(fallback_text) >= MIN_USEFUL_LENGTH:
                    return {"url": url, "text": fallback_text, "method": "fallback"}
            except Exception as e:
                logger.warning(f"fallback fetcher also failed for {url}: {e!r}")
        return {"url": url, "text": None, "method": "blocked"}

    logger.warning(f"extraction failed or too short for {url}")
    return {"url": url, "text": None, "method": "failed"}