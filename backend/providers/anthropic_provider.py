import json
import logging
from typing import Iterator

import httpx
from anthropic import Anthropic
from .base import Provider
from ._harness import run_worker, with_retry

logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 90.0
MAX_ATTEMPTS = 2


class AnthropicProvider(Provider):
    supports_tools = False

    def __init__(self, api_key: str):
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport, timeout=60.0)
        self.client = Anthropic(api_key=api_key, http_client=http_client, max_retries=1)

    def _worker(self, messages, model, out):
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

    def _do_stream(self, messages: list[dict], model: str, reasoning_effort: str) -> Iterator[str]:
        # reasoning_effort accepted for interface compatibility, currently
        # unused — Anthropic's equivalent (extended thinking / `thinking`
        # budget) is a different shape entirely; separate scope.
        attempt = lambda: run_worker(
            lambda out: self._worker(messages, model, out),
            HARD_DEADLINE_SECONDS, "provider call",
        )
        yield from with_retry(attempt, MAX_ATTEMPTS, f"call (model={model}, {len(messages)} msgs)")

    def _worker_tools(self, messages, model, tools, out):
        # UNVERIFIED — assumes Anthropic's responses.create surface emits
        # the same function-call event names as OpenAI's. supports_tools
        # stays False until this is smoke-tested; dormant code, not
        # currently reachable via stream_with_tools().
        try:
            stream = self.client.responses.create(model=model, input=messages, tools=tools, stream=True)
            pending: dict[str, dict] = {}
            for event in stream:
                if event.type == "response.output_text.delta":
                    out.put(("chunk", {"type": "text", "text": event.delta}))
                elif event.type == "response.output_item.added" and event.item.type == "function_call":
                    pending[event.item.id] = {"call_id": event.item.call_id, "name": event.item.name, "args": ""}
                elif event.type == "response.function_call_arguments.delta":
                    pending[event.item_id]["args"] += event.delta
                elif event.type == "response.output_item.done" and event.item.type == "function_call":
                    call = pending.pop(event.item.id)
                    out.put(("chunk", {"type": "tool_call", "call_id": call["call_id"],
                                        "name": call["name"], "input": json.loads(call["args"] or "{}")}))
                elif event.type == "response.completed":
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _do_stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str) -> Iterator[dict]:
        attempt = lambda: run_worker(
            lambda out: self._worker_tools(messages, model, tools, out),
            HARD_DEADLINE_SECONDS, "tool call",
        )
        yield from with_retry(attempt, MAX_ATTEMPTS, f"tool call (model={model}, {len(messages)} msgs, {len(tools)} tools)")