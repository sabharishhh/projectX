import logging
import queue
import threading
import time
from typing import Iterator

import httpx
from openai import OpenAI
from .base import Provider

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 90.0
MAX_ATTEMPTS = 2


class OpenAIProvider(Provider):
    def __init__(self, api_key: str):
        # Force IPv4: diagnostics showed rapid bursts of connections stall
        # intermittently, but the same burst over IPv4-only never did. This
        # is a well-known class of issue on networks with a broken/slow
        # IPv6 path — macOS tries IPv6 first and only falls back to IPv4
        # after it stalls, which matches the symptom exactly.
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport, timeout=60.0)
        self.client = OpenAI(api_key=api_key, http_client=http_client, max_retries=1)

    def _run(self, messages: list[dict], model: str, out: queue.Queue):
        try:
            stream = self.client.responses.create(model=model, input=messages, stream=True)
            for event in stream:
                if event.type == "response.output_text.delta":
                    out.put(("chunk", event.delta))
                elif event.type == "response.completed":
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _attempt(self, messages: list[dict], model: str):
        q: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run, args=(messages, model, q), daemon=True)
        t.start()

        deadline = time.monotonic() + HARD_DEADLINE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"provider call exceeded {HARD_DEADLINE_SECONDS}s hard deadline")
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

    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"call started (model={model}, {len(messages)} msgs, attempt {attempt}/{MAX_ATTEMPTS})")
            yielded_anything = False
            try:
                for chunk in self._attempt(messages, model):
                    yielded_anything = True
                    yield chunk
                logger.info("call completed")
                return
            except Exception as e:
                logger.warning(f"attempt {attempt} failed: {e!r}")
                if yielded_anything or attempt == MAX_ATTEMPTS:
                    raise
                logger.info("retrying after transient failure...")