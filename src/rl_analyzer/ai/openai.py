"""OpenAI chat completions provider."""

from ..config import Config
from .base import AIError, AIProvider, JsonHTTPClient


class OpenAIProvider(AIProvider):
    """Generate text with the configured OpenAI-compatible chat endpoint."""

    def __init__(self, config: Config, *, http: JsonHTTPClient | None = None) -> None:
        self._config = config
        self._http = http if http is not None else JsonHTTPClient(timeout=config.request_timeout_seconds)

    def generate(self, system: str, user: str) -> str:
        config = self._config
        data = self._http.post(f"{config.openai_base_url.rstrip('/')}/chat/completions", headers={
            "Authorization": f"Bearer {config.openai_api_key}"
        }, body={
            "model": config.openai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": config.ai_temperature, "max_tokens": config.ai_max_output_tokens,
        })
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIError("OpenAI returned no text") from None
        if not isinstance(content, str) or not content.strip():
            raise AIError("OpenAI returned no text")
        return content
