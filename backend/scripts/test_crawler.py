# test_crawler.py
import time
import extraction

extraction.start()

t0 = time.monotonic()
print(extraction.extract_page("https://en.wikipedia.org/wiki/Python_(programming_language)"))
print(f"first call: {time.monotonic()-t0:.2f}s\n")

t0 = time.monotonic()
print(extraction.extract_page("https://en.wikipedia.org/wiki/Python_(programming_language)"))
print(f"second call: {time.monotonic()-t0:.2f}s\n")
# second should be noticeably faster — no browser launch this time

original_timeout = extraction.CRAWL_TIMEOUT_SECONDS
extraction.CRAWL_TIMEOUT_SECONDS = 0.01
print(extraction.extract_page("https://en.wikipedia.org/wiki/Python_(programming_language)"))
print("^ should be {'text': None, 'method': 'failed'}, logs should show "
      "'crawl failed' -> 'respawning crawler after failure' -> 'crawler started'\n")

extraction.CRAWL_TIMEOUT_SECONDS = original_timeout
print(extraction.extract_page("https://en.wikipedia.org/wiki/Python_(programming_language)"))
print("^ confirms respawn actually worked and extraction recovered\n")

extraction.close()