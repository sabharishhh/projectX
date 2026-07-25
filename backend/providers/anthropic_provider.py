from typing import Iterator
from anthropic import Anthropic
from .base import Provider

class AnthropicProvider(Provider):
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key, timeout=60.0)

    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        # Anthropic takes system prompts as a separate parameter, not a
        # message in the list — and there can be more than one system
        # message by the time skills/search have both appended context,
        # so join all of them rather than assuming just the first.
        system = "".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]

        with self.client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system or None,
            messages=turns,
        ) as stream:
            for text in stream.text_stream:
                yield text