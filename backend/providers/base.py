from abc import ABC, abstractmethod
from typing import Iterator

class Provider(ABC):
    """A provider takes conversation messages and yields plain text chunks,
    or returns a single JSON object matching a provided schema."""

    @abstractmethod
    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        ...

    @abstractmethod
    def complete_json(self, messages: list[dict], model: str, schema: dict, schema_name: str) -> dict:
        ...