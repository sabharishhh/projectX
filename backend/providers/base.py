from abc import ABC, abstractmethod
from typing import Iterator

class Provider(ABC):
    """A provider takes conversation messages and yields plain text chunks."""

    supports_tools: bool = False

    @abstractmethod
    def stream(self, messages: list[dict], model: str, reasoning_effort: str = "none") -> Iterator[str]:
        ...

    def stream_with_tools(self, messages: list[dict], model: str, tools: list[dict], reasoning_effort: str = "none") -> Iterator[dict]:
        """Only implemented by providers with real tool-calling support.
        Yields {"type": "text", "text": ...} or
        {"type": "tool_call", "call_id", "name", "input": dict}."""
        raise NotImplementedError(f"{type(self).__name__} has no tool-calling support")