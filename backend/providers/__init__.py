import os
from .base import Provider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider

REGISTRY = {
    "openai": (OpenAIProvider, "OPENAI_API_KEY", "gpt-5.4-mini"),
    "anthropic": (AnthropicProvider, "ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
}

def get_provider() -> tuple[Provider, str]:
    name = os.getenv("PROVIDER", "openai")
    if name not in REGISTRY:
        raise ValueError(f"Unknown provider: {name}")

    cls, key_env, default_model = REGISTRY[name]
    api_key = os.getenv(key_env)
    if not api_key:
        raise ValueError(f"{key_env} not set")

    model = os.getenv("MODEL", default_model)
    return cls(api_key), model