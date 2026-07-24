from abc import ABC, abstractmethod
from typing import Iterator

class Provider(ABC):
    """A provider takes conversation messages and yields plain text chunks."""

    @abstractmethod
    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        ...