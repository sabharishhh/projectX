import logging
from typing import Iterator
from openai import OpenAI
from .base import Provider

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("provider")

class OpenAIProvider(Provider):
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, timeout=60.0, max_retries=2)

    def stream(self, messages: list[dict], model: str) -> Iterator[str]:
        logger.info(f"call started (model={model}, {len(messages)} msgs)")
        try:
            stream = self.client.responses.create(model=model, input=messages, stream=True)
            for event in stream:
                if event.type == "response.output_text.delta":
                    yield event.delta
                elif event.type == "response.completed":
                    break
            logger.info("call completed")
        except Exception as e:
            logger.warning(f"call failed: {e!r}")
            raise