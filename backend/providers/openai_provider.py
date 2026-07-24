from typing import Iterator
from openai import OpenAI
from .base import Provider

class OpenAIProvider(Provider):
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        stream = self.client.responses.create(
            model=model,
            input=messages,
            stream=True,
        )
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
            elif event.type == "response.completed":
                break