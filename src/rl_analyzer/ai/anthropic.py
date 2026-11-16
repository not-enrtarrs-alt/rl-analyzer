"""Anthropic messages provider."""

from ..config import Config
from .base import AIError, AIProvider, JsonHTTPClient


class AnthropicProvider(AIProvider):
    """Generate text with Anthropic's messages API."""

    def __init__(self, config: Config, *, http: JsonHTTPClient | None = None) -> None:
        self._config = config
        self._http = http if http is not None else JsonHTTPClient(timeout=config.request_timeout_seconds)

    def generate(self, system: str, user: str) -> str:
        config = self._config
        data = self._http.post(f"{config.anthropic_base_url.rstrip('/')}/messages", headers={
            "x-api-key": config.anthropic_api_key, "anthropic-version": "2023-06-01",
        }, body={
            "model": config.anthropic_model, "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": config.ai_temperature, "max_tokens": config.ai_max_output_tokens,
        })
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise AIError("Anthropic returned no text")
        parts = [block["text"] for block in blocks if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)]
        content = "\n".join(parts)
        if not content.strip():
            raise AIError("Anthropic returned no text")
        return content
