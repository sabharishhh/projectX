import logging
from typing import Iterator

from openai import OpenAI
from .base import Provider
from ._harness import run_worker

logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 180.0


class LocalProvider(Provider):
    """Talks to any locally-running, OpenAI-compatible chat server — Ollama,
    LM Studio, vLLM, text-generation-webui, etc. — via the standard
    /v1/chat/completions interface. No API key required; nothing leaves
    the machine."""

    def __init__(self, base_url: str):
        self.client = OpenAI(api_key="local", base_url=base_url, timeout=HARD_DEADLINE_SECONDS)

    def _worker(self, messages, model, out):
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
        #
        # Deliberately NOT using with_retry — local's current behavior is a
        # single attempt, no retry. This refactor dedupes identical code,
        # it doesn't add new retry behavior to a provider that never had
        # it — that'd be a real decision to make explicitly, not a side
        # effect of cleanup.
        logger.info(f"local call started (model={model}, {len(messages)} msgs)")
        try:
            yield from run_worker(
                lambda out: self._worker(messages, model, out),
                HARD_DEADLINE_SECONDS, "local provider call",
            )
            logger.info("local call completed")
        except Exception as e:
            logger.warning(f"local call failed: {e!r}")
            raise