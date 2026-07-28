import logging
import queue
import threading
import time
from typing import Iterator

from openai import OpenAI
from .base import Provider

logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 180.0


class LocalProvider(Provider):
    """Talks to any locally-running, OpenAI-compatible chat server — Ollama,
    LM Studio, vLLM, text-generation-webui, etc. — via the standard
    /v1/chat/completions interface. No API key required; nothing leaves
    the machine."""

    def __init__(self, base_url: str):
        self.client = OpenAI(api_key="local", base_url=base_url, timeout=HARD_DEADLINE_SECONDS)

    def _run(self, messages: list[dict], model: str, out: queue.Queue):
        try:
            stream = self.client.chat.completions.create(model=model, messages=messages, stream=True)
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    out.put(("chunk", delta))
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _do_stream(self, messages: list[dict], model: str, reasoning_effort: str) -> Iterator[str]:
        # reasoning_effort accepted for interface compatibility, currently
        # unused — the standard /v1/chat/completions shape most local
        # servers expose has no equivalent parameter.
        logger.info(f"local call started (model={model}, {len(messages)} msgs)")
        q: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run, args=(messages, model, q), daemon=True)
        t.start()

        deadline = time.monotonic() + HARD_DEADLINE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"local provider call exceeded {HARD_DEADLINE_SECONDS}s hard deadline")
            try:
                kind, payload = q.get(timeout=remaining)
            except queue.Empty:
                continue
            if kind == "chunk":
                yield payload
            elif kind == "done":
                logger.info("local call completed")
                return
            elif kind == "error":
                logger.warning(f"local call failed: {payload!r}")
                raise payload