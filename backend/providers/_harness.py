"""Shared harness for bridging a provider SDK's blocking call into this
codebase's generator-based streaming interface. Every provider does the
same two things: run the SDK call on a background thread and read results
off a queue against a hard deadline (run_worker), and for OpenAI/Anthropic,
retry once if nothing was yielded before the failure (with_retry). The
actual SDK call and its event-parsing stays provider-specific — that's
real business logic, not duplication — only this bridging mechanism was
identical across files."""

import logging
import queue
import threading
import time
from typing import Callable, Iterator

logger = logging.getLogger("provider")


def run_worker(worker: Callable[[queue.Queue], None], deadline_seconds: float, timeout_label: str) -> Iterator:
    """Runs worker(out_queue) on a background thread, yields whatever it
    puts as ("chunk", payload), returns on ("done", None), raises on
    ("error", exc) or on exceeding deadline_seconds with nothing received."""
    q: queue.Queue = queue.Queue()
    t = threading.Thread(target=worker, args=(q,), daemon=True)
    t.start()

    deadline = time.monotonic() + deadline_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{timeout_label} exceeded {deadline_seconds}s hard deadline")
        try:
            kind, payload = q.get(timeout=remaining)
        except queue.Empty:
            continue
        if kind == "chunk":
            yield payload
        elif kind == "done":
            return
        elif kind == "error":
            raise payload


def with_retry(attempt: Callable[[], Iterator], max_attempts: int, log_label: str) -> Iterator:
    """Calls attempt() (a zero-arg callable returning a fresh iterator each
    time) up to max_attempts times. Only retries a failure if NOTHING was
    yielded yet on this attempt — once partial output has streamed to the
    user, retrying would duplicate or garble it, so a failure past that
    point always raises instead."""
    for attempt_num in range(1, max_attempts + 1):
        logger.info(f"{log_label} started (attempt {attempt_num}/{max_attempts})")
        yielded_anything = False
        try:
            for item in attempt():
                yielded_anything = True
                yield item
            logger.info(f"{log_label} completed")
            return
        except Exception as e:
            logger.warning(f"{log_label} attempt {attempt_num} failed: {e!r}")
            if yielded_anything or attempt_num == max_attempts:
                raise
            logger.info("retrying after transient failure...")