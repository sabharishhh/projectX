import json
import logging
from typing import Iterator

import httpx
from openai import OpenAI
from .base import Provider
from ._harness import run_worker, with_retry

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 90.0
MAX_ATTEMPTS = 2


class OpenAIProvider(Provider):
    supports_tools = True
    supports_structured_output = True

    def __init__(self, api_key: str):
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        # Bounded pool, not the httpx default (100/20) — a pile-up of
        # slow/stuck calls should hit a clear connection-limit error
        # instead of silently growing the pool indefinitely across a
        # long-running session.
        http_client = httpx.Client(
            transport=transport, timeout=60.0,
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=10),
        )
        self.client = OpenAI(api_key=api_key, http_client=http_client, max_retries=1)

    def _worker(self, messages, model, reasoning_effort, out):
        try:
            stream = self.client.responses.create(
                model=model, input=messages, stream=True,
                reasoning={"effort": reasoning_effort},
            )
            for event in stream:
                if event.type == "response.output_text.delta":
                    out.put(("chunk", event.delta))
                elif event.type == "response.completed":
                    usage = getattr(event.response, "usage", None)
                    if usage:
                        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
                        logger.info(f"prompt cache: {cached}/{usage.input_tokens} input tokens cached "
                                    f"(model={model})")
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _do_stream(self, messages: list[dict], model: str, reasoning_effort: str,
                    deadline_seconds: float | None = None) -> Iterator[str]:
        attempt = lambda: run_worker(
            lambda out: self._worker(messages, model, reasoning_effort, out),
            deadline_seconds or HARD_DEADLINE_SECONDS, "provider call",
        )
        yield from with_retry(attempt, MAX_ATTEMPTS, f"call (model={model}, effort={reasoning_effort}, {len(messages)} msgs)")

    def _json_worker(self, messages, model, schema, schema_name, reasoning_effort, out):
        try:
            response = self.client.responses.create(
                model=model, input=messages,
                reasoning={"effort": reasoning_effort},
                text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
            )
            usage = getattr(response, "usage", None)
            if usage:
                cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
                logger.info(f"prompt cache: {cached}/{usage.input_tokens} input tokens cached "
                            f"(model={model}, json call)")
            out.put(("chunk", response.output_text))
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _do_complete_json(self, messages: list[dict], model: str, schema: dict, schema_name: str,
                           reasoning_effort: str, deadline_seconds: float | None = None) -> dict:
        # Previously a bare, unprotected call — no deadline, no retry, no
        # attempt logging, unlike every other call type in this file. That
        # silence is exactly why a stuck search_decision call never showed
        # up in logs during the classify stall — this closes that gap by
        # routing through the same run_worker/with_retry path _do_stream
        # already uses, just yielding one JSON chunk instead of many text
        # ones. deadline_seconds lets callers (classify-tier calls) opt
        # into a shorter timeout than the 90s default meant for full replies.
        attempt = lambda: run_worker(
            lambda out: self._json_worker(messages, model, schema, schema_name, reasoning_effort, out),
            deadline_seconds or HARD_DEADLINE_SECONDS, "json call",
        )
        chunks = list(with_retry(attempt, MAX_ATTEMPTS, f"json call (model={model}, effort={reasoning_effort})"))
        return json.loads("".join(chunks))

    def _worker_tools(self, messages, model, tools, reasoning_effort, out):
        try:
            stream = self.client.responses.create(
                model=model, input=messages, tools=tools, stream=True,
                reasoning={"effort": reasoning_effort},
            )
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
                    usage = getattr(event.response, "usage", None)
                    if usage:
                        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0)
                        logger.info(f"prompt cache: {cached}/{usage.input_tokens} input tokens cached "
                                    f"(model={model})")
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _do_stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str) -> Iterator[dict]:
        attempt = lambda: run_worker(
            lambda out: self._worker_tools(messages, model, tools, reasoning_effort, out),
            HARD_DEADLINE_SECONDS, "tool call",
        )
        yield from with_retry(attempt, MAX_ATTEMPTS, f"tool call (model={model}, effort={reasoning_effort}, {len(messages)} msgs, {len(tools)} tools)")