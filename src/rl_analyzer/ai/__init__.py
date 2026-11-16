"""Provider-agnostic AI interfaces and implementations."""

from ..config import Config
from .anthropic import AnthropicProvider
from .base import AIError, AIProvider, JsonHTTPClient
from .gemini import GeminiProvider
from .mock import MockProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider


def create_provider(config: Config, *, http: JsonHTTPClient | None = None) -> AIProvider:
    """Construct the explicitly configured provider; never fall back to mock."""
    if config.ai_provider == "mock":
        return MockProvider()
    providers = {"ollama": OllamaProvider, "openai": OpenAIProvider,
                 "anthropic": AnthropicProvider, "gemini": GeminiProvider}
    provider = providers.get(config.ai_provider)
    if provider is None:
        raise AIError("Unknown AI provider")
    credentials = {"openai": config.openai_api_key, "anthropic": config.anthropic_api_key,
                   "gemini": config.gemini_api_key}
    if config.ai_provider in credentials and not credentials[config.ai_provider]:
        raise AIError(f"Missing {config.ai_provider.upper()}_API_KEY")
    return provider(config, http=http)


def provider_model(config: Config) -> str | None:
    """Return the configured model for persistence, or None for mock."""
    return {"ollama": config.ollama_model, "openai": config.openai_model,
            "anthropic": config.anthropic_model, "gemini": config.gemini_model}.get(config.ai_provider)
