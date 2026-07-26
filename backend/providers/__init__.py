import os
import httpx
from .base import Provider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .local_provider import LocalProvider

REGISTRY = {
    "openai": (OpenAIProvider, "OPENAI_API_KEY", "gpt-5.4-mini"),
    "anthropic": (AnthropicProvider, "ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
}


def get_provider() -> tuple[Provider, str]:
    name = os.getenv("PROVIDER", "openai")

    if name == "local":
        base_url = os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1")
        model = os.getenv("MODEL")
        if not model:
            raise ValueError(
                "PROVIDER=local requires MODEL to be set to a model you've already "
                "pulled locally (e.g. MODEL=llama3.1 for Ollama). There's no safe "
                "universal default, since it depends entirely on what you have."
            )
        # fail fast, at startup, with a clear message — rather than a
        # confusing connection error deep inside the first chat turn
        try:
            httpx.get(f"{base_url}/models", timeout=3.0)
        except Exception:
            raise ValueError(
                f"Could not reach a local model server at {base_url}. "
                f"Is it running? (e.g. `ollama serve`)"
            )
        return LocalProvider(base_url), model

    if name not in REGISTRY:
        raise ValueError(f"Unknown provider: {name}")

    cls, key_env, default_model = REGISTRY[name]
    api_key = os.getenv(key_env)
    if not api_key:
        raise ValueError(f"{key_env} not set")

    model = os.getenv("MODEL", default_model)
    return cls(api_key), model