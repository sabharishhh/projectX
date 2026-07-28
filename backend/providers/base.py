from abc import ABC, abstractmethod
from typing import Iterator

from time_context import current_time_context


class Provider(ABC):
    """A provider takes conversation messages and yields plain text chunks.

    stream()/stream_with_tools()/complete_json() are the public entry points
    every call site uses — each is a thin concrete wrapper that injects
    current-time context into `messages` before delegating to the matching
    _do_* method subclasses implement. This is the one place time-awareness
    lives: every call through this class, present and future, gets it
    automatically — no call site has to remember to add it itself.
    """

    supports_tools: bool = False
    supports_structured_output: bool = False

    def stream(self, messages: list[dict], model: str, reasoning_effort: str = "none") -> Iterator[str]:
        return self._do_stream(self._with_time(messages), model, reasoning_effort)

    @abstractmethod
    def _do_stream(self, messages: list[dict], model: str, reasoning_effort: str) -> Iterator[str]:
        ...

    def stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str = "none") -> Iterator[dict]:
        """Only implemented by providers with real tool-calling support.
        Yields {"type": "text", "text": ...} or
        {"type": "tool_call", "call_id", "name", "input": dict}."""
        if not self.supports_tools:
            raise NotImplementedError(f"{type(self).__name__} has no tool-calling support")
        return self._do_stream_with_tools(self._with_time(messages), model, tools, reasoning_effort)

    def _do_stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str) -> Iterator[dict]:
        raise NotImplementedError(f"{type(self).__name__} has no tool-calling support")

    def complete_json(self, messages: list[dict], model: str, schema: dict, schema_name: str) -> dict:
        """Only implemented by providers with real structured-output
        support. Callers MUST check `provider.supports_structured_output`,
        NOT hasattr(provider, "complete_json") — this method now exists on
        every provider, it just raises when unsupported."""
        if not self.supports_structured_output:
            raise NotImplementedError(f"{type(self).__name__} has no structured-output support")
        return self._do_complete_json(self._with_time(messages), model, schema, schema_name)

    def _do_complete_json(self, messages: list[dict], model: str, schema: dict, schema_name: str) -> dict:
        raise NotImplementedError(f"{type(self).__name__} has no structured-output support")

    @staticmethod
    def _with_time(messages: list[dict]) -> list[dict]:
        return [{"role": "system", "content": current_time_context()}] + messages