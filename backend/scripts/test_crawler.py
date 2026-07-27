# test_crawler.py
import time
import backend.extraction as extraction

extraction.start()

t0 = time.monotonic()
print(extraction.extract_page("https://example.com"))
print(f"first call: {time.monotonic()-t0:.2f}s\n")

t0 = time.monotonic()
print(extraction.extract_page("https://example.com"))
print(f"second call: {time.monotonic()-t0:.2f}s\n")
# second should be noticeably faster — no browser launch this time

# success path — example.com's real content is ~180 chars, plausibly under
# MIN_USEFUL_LENGTH=200, so neither call above actually proved extraction
# works under the shared instance. This does.
print(extraction.extract_page("https://en.wikipedia.org/wiki/Python_(programming_language)"))
print("^ should return method: 'crawl4ai' with real text\n")

# respawn — a routine page-level failure (bad URL, blocked port, 404) is
# handled internally by crawl4ai and correctly does NOT trigger respawn;
# only a genuine crawler-level failure should. Forcing a timeout is the
# deterministic way to trigger that path rather than relying on a flaky
# real-world failure.
original_timeout = extraction.CRAWL_TIMEOUT_SECONDS
extraction.CRAWL_TIMEOUT_SECONDS = 0.01
print(extraction.extract_page("https://example.com"))
print("^ should be {'text': None, 'method': 'failed'}, logs should show "
      "'crawl failed' -> 'respawning crawler after failure' -> 'crawler started'\n")

extraction.CRAWL_TIMEOUT_SECONDS = original_timeout
print(extraction.extract_page("https://example.com"))
print("^ the real test — confirms respawn actually worked and extraction recovered\n")

extraction.close()