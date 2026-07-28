import logging
import queue
import threading
import time
from typing import Iterator
import json
import httpx
from openai import OpenAI
from .base import Provider

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("provider")

HARD_DEADLINE_SECONDS = 90.0
MAX_ATTEMPTS = 2


class OpenAIProvider(Provider):
    supports_tools = True
    supports_structured_output = True

    def __init__(self, api_key: str):
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        http_client = httpx.Client(transport=transport, timeout=60.0)
        self.client = OpenAI(api_key=api_key, http_client=http_client, max_retries=1)

    def _run(self, messages: list[dict], model: str, reasoning_effort: str, out: queue.Queue):
        try:
            stream = self.client.responses.create(
                model=model,
                input=messages,
                stream=True,
                reasoning={"effort": reasoning_effort},
            )
            for event in stream:
                if event.type == "response.output_text.delta":
                    out.put(("chunk", event.delta))
                elif event.type == "response.completed":
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _attempt(self, messages: list[dict], model: str, reasoning_effort: str):
        q: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run, args=(messages, model, reasoning_effort, q), daemon=True)
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

    def _do_stream(self, messages: list[dict], model: str, reasoning_effort: str) -> Iterator[str]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"call started (model={model}, effort={reasoning_effort}, {len(messages)} msgs, attempt {attempt}/{MAX_ATTEMPTS})")
            yielded_anything = False
            try:
                for chunk in self._attempt(messages, model, reasoning_effort):
                    yielded_anything = True
                    yield chunk
                logger.info("call completed")
                return
            except Exception as e:
                logger.warning(f"attempt {attempt} failed: {e!r}")
                if yielded_anything or attempt == MAX_ATTEMPTS:
                    raise
                logger.info("retrying after transient failure...")

    def _do_complete_json(self, messages: list[dict], model: str, schema: dict, schema_name: str) -> dict:
        response = self.client.responses.create(
            model=model,
            input=messages,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        return json.loads(response.output_text)

    def _run_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str, out: queue.Queue):
        try:
            stream = self.client.responses.create(
                model=model,
                input=messages,
                tools=tools,
                stream=True,
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
                    out.put(("chunk", {
                        "type": "tool_call", "call_id": call["call_id"],
                        "name": call["name"], "input": json.loads(call["args"] or "{}"),
                    }))
                elif event.type == "response.completed":
                    break
            out.put(("done", None))
        except Exception as e:
            out.put(("error", e))

    def _attempt_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str):
        q: queue.Queue = queue.Queue()
        t = threading.Thread(target=self._run_tools, args=(messages, model, tools, reasoning_effort, q), daemon=True)
        t.start()

        deadline = time.monotonic() + HARD_DEADLINE_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"tool call exceeded {HARD_DEADLINE_SECONDS}s hard deadline")
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

    def _do_stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str) -> Iterator[dict]:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(f"tool call started (model={model}, effort={reasoning_effort}, {len(messages)} msgs, {len(tools)} tools, attempt {attempt}/{MAX_ATTEMPTS})")
            yielded_anything = False
            try:
                for event in self._attempt_tools(messages, model, tools, reasoning_effort):
                    yielded_anything = True
                    yield event
                logger.info("tool call completed")
                return
            except Exception as e:
                logger.warning(f"tool call attempt {attempt} failed: {e!r}")
                if yielded_anything or attempt == MAX_ATTEMPTS:
                    raise
                logger.info("retrying after transient failure...")